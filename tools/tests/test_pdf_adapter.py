"""PDF 适配器离线回归；所有 PDF 在临时库内以最小 PDF 对象生成。"""
import copy
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools.wiki_runtime.capture.pdf import (
    UnsupportedPdfError, capabilities, capture_pdf, validate_pdf_package,
)
from tools.wiki_runtime.contracts import ContractError, bytes_digest, validate

try:
    import pypdf
    from pypdf.generic import (
        DecodedStreamObject, DictionaryObject, NameObject, NumberObject,
    )
except ImportError:
    pypdf = None


def make_pdf(kinds=('text',), *, password=None):
    """测试数据，无生产/出版输出；text、blank、vector、image 均可混合。"""
    writer = pypdf.PdfWriter()
    writer.add_metadata({'/Title': 'PDF fixture', '/Author': 'Fixture author',
                         '/CreationDate': 'D:20261026000000Z'})
    for index, kind in enumerate(kinds, 1):
        page = writer.add_blank_page(width=300, height=300)
        resources = DictionaryObject()
        commands = b''
        if kind in ('text', 'vector'):
            font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                                     NameObject('/Subtype'): NameObject('/Type1'),
                                     NameObject('/BaseFont'): NameObject('/Helvetica')})
            resources[NameObject('/Font')] = DictionaryObject({NameObject('/F1'): font})
            commands = f'BT /F1 12 Tf 20 250 Td (Page {index} body text.) Tj ET'.encode()
        if kind == 'vector':
            commands += b' 10 10 100 100 re S'
        if kind == 'image':
            image = DecodedStreamObject()
            image.set_data(b'\xff\x00\x00')
            image.update({NameObject('/Type'): NameObject('/XObject'),
                          NameObject('/Subtype'): NameObject('/Image'),
                          NameObject('/Width'): NumberObject(1),
                          NameObject('/Height'): NumberObject(1),
                          NameObject('/ColorSpace'): NameObject('/DeviceRGB'),
                          NameObject('/BitsPerComponent'): NumberObject(8)})
            resources[NameObject('/XObject')] = DictionaryObject({
                NameObject('/Im1'): writer._add_object(image)})
            commands = b'q 100 0 0 100 20 20 cm /Im1 Do Q'
        page[NameObject('/Resources')] = resources
        stream = DecodedStreamObject()
        stream.set_data(commands)
        page[NameObject('/Contents')] = writer._add_object(stream)
    if password is not None:
        writer.encrypt(password)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


class EnvironmentTests(unittest.TestCase):
    def test_missing_dependency_is_explicit_and_creates_no_package(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / 'source.pdf'
            source.write_bytes(b'%PDF-test')
            with patch('tools.wiki_runtime.capture.pdf.import_module', side_effect=ModuleNotFoundError('pypdf')):
                capability = capabilities()
                self.assertFalse(capability['available'])
                self.assertEqual(capability['status'], 'unsupported')
                self.assertTrue(capability['requires_multimodal_review'])
                with self.assertRaises(UnsupportedPdfError) as raised:
                    capture_pdf(source, base / 'candidates', 'p', vault_root=base / 'vault')
                self.assertEqual(raised.exception.status, 'unsupported')
                self.assertIn('pypdf', str(raised.exception))
            self.assertFalse((base / 'candidates').exists())

    def test_import_without_pypdf_or_side_effects(self):
        repo = Path(__file__).resolve().parents[2]
        code = (f'import sys; sys.path.insert(0, {str(repo)!r}); '
                'sys.modules["pypdf"] = None; '
                'from tools.wiki_runtime.capture.pdf import capabilities; '
                'assert capabilities()["status"] == "unsupported"')
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-B', '-c', code], cwd=directory, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(list(Path(directory).iterdir()), [])


@unittest.skipIf(pypdf is None, '可选 pypdf 未安装；环境缺依赖测试仍执行')
class PdfAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.vault = self.base / 'vault'
        self.vault.mkdir()
        self.candidates = self.base / 'candidates'
        self.source = self.base / 'source.pdf'

    def capture(self, data=None, **kwargs):
        self.source.write_bytes(make_pdf() if data is None else data)
        return capture_pdf(self.source, kwargs.pop('candidate_root', self.candidates),
                           kwargs.pop('package_path', 'p1'), vault_root=self.vault, **kwargs)

    def test_text_original_pages_metadata_and_policy_preserved(self):
        original = make_pdf(('text', 'text'))
        package, root = self.capture(original)
        self.assertEqual(validate('source_package', package), package)
        self.assertEqual(validate_pdf_package(package, root), package)
        self.assertEqual(json.loads((root / 'source-package.json').read_text(encoding='utf-8')), package)
        self.assertEqual((root / 'originals/source.pdf').read_bytes(), original)
        self.assertEqual(package['originals'][0]['sha256'], bytes_digest(original))
        self.assertEqual(package['quality']['status'], 'partial')
        self.assertIn('reading_order_and_layout_unverified', package['quality']['missing'])
        self.assertEqual(package['quality']['statistics']['pages_total'], 2)
        self.assertEqual(package['quality']['statistics']['pages_extracted'], 2)
        self.assertEqual([x['location'] for x in package['locators']], ['page:1', 'page:2'])
        text = (root / package['extracted']['path']).read_text(encoding='utf-8')
        self.assertLess(text.index('Page 1 body'), text.index('Page 2 body'))
        self.assertIn('第 2 页', text)
        self.assertEqual(package['input_type'], 'pdf')
        self.assertFalse(package['parser']['used_ocr'])
        self.assertFalse(package['parser']['used_model'])
        self.assertEqual(package['source']['title'], 'PDF fixture')
        self.assertEqual(package['source']['author'], 'Fixture author')
        self.assertEqual(package['source']['published_at'], '')
        self.assertIn('published_at', package['source']['unavailable_fields'])

    def test_blank_and_mixed_pages_have_stable_locators_and_coverage(self):
        package, _ = self.capture(make_pdf(('text', 'blank', 'text')))
        self.assertEqual(package['quality']['statistics']['pages_total'], 3)
        self.assertEqual(package['quality']['statistics']['pages_extracted'], 2)
        self.assertEqual(len(package['locators']), 3)
        self.assertIn('page:2:no_text_ocr_or_manual_review_required', package['quality']['missing'])
        blank, _ = self.capture(make_pdf(('blank',)), package_path='blank')
        self.assertEqual(blank['quality']['status'], 'partial')
        self.assertEqual(blank['quality']['statistics']['pages_extracted'], 0)

    def test_image_only_scan_and_vector_chart_report_unprocessed_visuals(self):
        for kind in ('image', 'vector'):
            with self.subTest(kind=kind):
                package, root = self.capture(make_pdf((kind,)), package_path=kind)
                self.assertEqual(package['quality']['status'], 'partial')
                self.assertIn('page:1:visual_content_unprocessed', package['quality']['missing'])
                self.assertEqual(package['attachments'], [])
                self.assertEqual(validate_pdf_package(package, root), package)
                if kind == 'image':
                    self.assertEqual(package['quality']['statistics']['pages_extracted'], 0)
                    self.assertIn('page:1:no_text_ocr_or_manual_review_required', package['quality']['missing'])

    def test_corrupt_encrypted_zero_pages_and_truncated_are_never_complete(self):
        for name, data, expected in (
            ('corrupt', b'%PDF-1.4\ncorrupt', 'invalid_pdf'),
            ('encrypted', make_pdf(password='secret'), 'encrypted_pdf'),
            ('empty_password', make_pdf(password=''), 'encrypted_pdf'),
            ('zero', make_pdf(()), 'zero_pages'),
            ('truncated', make_pdf()[:150], 'invalid_pdf'),
        ):
            with self.subTest(name=name):
                package, root = self.capture(data, package_path=name)
                self.assertEqual(package['quality']['status'], 'failed')
                self.assertIn(expected, package['quality']['errors'])
                self.assertEqual((root / 'originals/source.pdf').read_bytes(), data)
                self.assertEqual(validate_pdf_package(package, root), package)

    def test_page_extract_failure_is_reported(self):
        with patch('pypdf._page.PageObject.extract_text', side_effect=ValueError('bad text')):
            package, _ = self.capture()
        self.assertEqual(package['quality']['status'], 'failed')
        self.assertIn('page:1:extraction_failed', package['quality']['errors'])

    def test_suspect_encoding_is_reported(self):
        with patch('pypdf._page.PageObject.extract_text', return_value='text \ufffd\x00'):
            package, _ = self.capture()
        self.assertIn('page:1:suspect_text_encoding', package['quality']['missing'])

    def test_forged_complete_quality_pages_locators_and_flags_rejected(self):
        package, root = self.capture(make_pdf(('image',)))
        mutations = [
            lambda p: p['quality'].update(status='complete', missing=[], errors=[]),
            lambda p: p['quality']['statistics'].update(pages_total=99),
            lambda p: p['quality']['statistics'].update(pages_extracted=1),
            lambda p: p.update(locators=[]),
            lambda p: p['locators'][0].update(location='page:999'),
            lambda p: p['locators'][0].update(artifact_path='extracted/content.md'),
            lambda p: p.update(input_type='markdown'),
            lambda p: p['parser'].update(used_ocr=True),
            lambda p: p['parser'].update(used_model=True),
            lambda p: p['parser'].update(adapter_id='markdown'),
            lambda p: p['parser'].update(config_digest='0' * 64),
            lambda p: p.update(source_revision='0' * 64),
            lambda p: p['source'].update(title='invented'),
        ]
        for index, mutation in enumerate(mutations):
            with self.subTest(mutation=index):
                forged = copy.deepcopy(package)
                mutation(forged)
                with self.assertRaises(ContractError):
                    validate_pdf_package(forged, root)

    def test_forged_text_even_with_matching_hash_is_rejected(self):
        package, root = self.capture()
        path = root / package['extracted']['path']
        path.write_bytes(b'forged content')
        package['extracted']['sha256'] = bytes_digest(path.read_bytes())
        with self.assertRaises(ContractError):
            validate_pdf_package(package, root)

    def test_original_byte_tamper_is_rejected(self):
        package, root = self.capture()
        (root / package['originals'][0]['path']).write_bytes(make_pdf(('blank',)))
        with self.assertRaises(ContractError):
            validate_pdf_package(package, root)

    def test_invalid_utf8_hash_tamper_and_unsafe_record_paths(self):
        package, root = self.capture()
        for path in ('../secret.pdf', 'C:/outside.pdf'):
            forged = copy.deepcopy(package)
            forged['originals'][0]['path'] = path
            with self.assertRaises(ContractError):
                validate_pdf_package(forged, root)
        extracted = root / package['extracted']['path']
        extracted.write_bytes(b'\xff')
        with self.assertRaises(ContractError):
            validate_pdf_package(package, root)
        package['extracted']['sha256'] = bytes_digest(b'\xff')
        with self.assertRaises(ContractError):
            validate_pdf_package(package, root)

    def test_identity_and_revisions(self):
        first, _ = self.capture(origin='user:pdf')
        same, _ = self.capture(package_path='same', origin='user:pdf')
        changed, _ = self.capture(make_pdf(('text', 'text')), package_path='changed', origin='user:pdf')
        self.assertEqual(first['source_id'], changed['source_id'])
        self.assertEqual(first['source_revision'], same['source_revision'])
        self.assertNotEqual(first['source_revision'], changed['source_revision'])

    def test_paths_reject_business_areas_traversal_and_overwrite(self):
        for path in ('../escape', '/absolute', 'C:/outside', 'a/../b', 'a\\b'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.capture(package_path=path)
        for area in ('raw', 'wiki', 'tools', '.git', ''):
            with self.subTest(area=area), self.assertRaises(ValueError):
                self.capture(candidate_root=self.vault / area)
        self.capture()
        with self.assertRaises(FileExistsError):
            self.capture()
        package, _ = self.capture(candidate_root=self.vault / '.wiki-runtime/candidates')
        self.assertEqual(package['input_type'], 'pdf')
        self.assertFalse((self.vault / 'raw').exists())

    def test_output_symlink_escape_rejected(self):
        self.candidates.mkdir()
        outside = self.base / 'outside'
        outside.mkdir()
        try:
            (self.candidates / 'link').symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            if os.name != 'nt':
                self.skipTest(str(exc))
            result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(self.candidates / 'link'), str(outside)],
                                    capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode:
                self.skipTest('当前 Windows 未允许创建 symlink/junction')
        with self.assertRaises(ValueError):
            self.capture(package_path='link/p')
        self.assertEqual(list(outside.iterdir()), [])

    def test_unsupported_options_and_input_io_fail_before_writing(self):
        with self.assertRaises(ValueError):
            self.capture(adapter_id='markdown')
        with self.assertRaises(ValueError):
            self.capture(attachments={'x': 'y'})
        with self.assertRaises(ValueError):
            capabilities('other')
        with self.assertRaises(FileNotFoundError):
            capture_pdf(self.base / 'missing.pdf', self.candidates, 'missing', vault_root=self.vault)
        self.assertFalse(self.candidates.exists())
        self.assertTrue(capabilities()['available'])

    def test_interruption_has_no_success_manifest(self):
        with patch('tools.wiki_runtime.capture.pdf.validate_pdf_package', side_effect=RuntimeError('interrupt')):
            with self.assertRaises(RuntimeError):
                self.capture()
        self.assertFalse((self.candidates / 'p1/source-package.json').exists())
        self.assertTrue((self.candidates / 'p1/originals/source.pdf').is_file())

    def test_validation_missing_dependency_stops(self):
        package, root = self.capture()
        with patch('tools.wiki_runtime.capture.pdf.import_module', side_effect=ImportError('unavailable')):
            with self.assertRaises(UnsupportedPdfError):
                validate_pdf_package(package, root)


if __name__ == '__main__':
    unittest.main()
