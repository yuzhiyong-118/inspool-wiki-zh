"""离线 PDF 候选采集（公共契约 v1.0），不执行 OCR 或模型调用。

可选依赖：pypdf；在所用 Python 环境执行 ``python -m pip install pypdf``。
导入本模块不要求安装依赖；capabilities() 可先查询，实际解析缺依赖时抛
UnsupportedPdfError，不能把环境错误伪装为有效包。原件保留全部字节。

本版未核验阅读顺序、表格和版面，任何成功抽取均为 partial，需人工校验。
页级图形检测只是保守提示，不证明无图或无表。下游必须保留 input_type=pdf
与 used_ocr=False，继续执行既有 PDF/多模态暂停策略。
"""
from datetime import datetime, timezone
from importlib import import_module
from io import BytesIO
import json
from pathlib import Path

from tools.wiki_runtime.contracts import (
    ContractError, bytes_digest, digest, resolve_path, validate, validate_path,
)
from .adapters import _outside_business


_ORIGINAL = 'originals/source.pdf'
_EXTRACTED = 'extracted/content.md'
_CONFIG = {'offline': True, 'strict': True, 'ocr': False,
           'layout_verified': False, 'extraction': 'plain-page-text-v1'}
_VISUAL_OPERATORS = {b'Do', b'INLINE IMAGE', b'sh', b'S', b's', b'f', b'F',
                     b'f*', b'B', b'B*', b'b', b'b*'}


class UnsupportedPdfError(RuntimeError):
    """PDF 解析环境不支持；调用者应报告 unsupported 并停止对应步骤。"""

    status = 'unsupported'


def _load_pypdf():
    try:
        return import_module('pypdf')
    except ImportError as exc:
        raise UnsupportedPdfError(
            'unsupported: PDF 解析缺少可用 pypdf；请在当前 Python 环境安装 pypdf'
        ) from exc


def capabilities(adapter_id='pdf'):
    """查询可选环境，不联网、不安装依赖、不创建文件。"""
    if adapter_id != 'pdf':
        raise ValueError(f'不支持的 PDF 适配器: {adapter_id}')
    try:
        library = _load_pypdf()
        available, reason = True, ''
        parser_version = 'pypdf-' + library.__version__
    except UnsupportedPdfError as exc:
        available, reason, parser_version = False, str(exc), ''
    return {'adapter_id': 'pdf', 'version': '1.0', 'input_type': 'pdf',
            'offline': True, 'used_ocr': False, 'used_model': False,
            'available': available, 'status': 'available' if available else 'unsupported',
            'reason': reason, 'parser_version': parser_version,
            'layout_verified': False, 'requires_multimodal_review': True}


def _parser(library):
    return {'adapter_id': 'pdf', 'adapter_version': '1.0',
            'parser_version': 'pypdf-' + library.__version__,
            'config_digest': digest(_CONFIG), 'used_ocr': False, 'used_model': False}


def _analyse(data, library):
    errors, missing, locators, parts = [], [], [], []
    meta = {'title': '', 'author': '', 'published_at': ''}
    total, extracted_pages = 0, 0
    evidence = ['保留 PDF 原始字节；离线逐页抽取；未使用 OCR 或模型',
                '原始类型为 pdf，必须继续执行 PDF/多模态暂停审查',
                '文字抽取不证明阅读顺序、表格或版面正确；图形检测不证明视觉信息完整']
    try:
        reader = library.PdfReader(BytesIO(data), strict=True)
        if reader.is_encrypted:
            errors.append('encrypted_pdf')
        else:
            total = len(reader.pages)
            if total == 0:
                errors.append('zero_pages')
            try:
                metadata = reader.metadata
                if metadata:
                    meta['title'] = str(metadata.title or '')
                    meta['author'] = str(metadata.author or '')
                # CreationDate/ModDate are not a verified publication date.
            except Exception as exc:
                if isinstance(exc, (MemoryError, RecursionError)):
                    raise
                missing.append('metadata_unreadable')
            if total:
                missing.append('reading_order_and_layout_unverified')
            for number, page in enumerate(reader.pages, 1):
                locators.append({'block_id': f'p{number}', 'artifact_path': _ORIGINAL,
                                 'location': f'page:{number}'})
                text = ''
                try:
                    text = page.extract_text() or ''
                except Exception as exc:
                    if isinstance(exc, (MemoryError, RecursionError)):
                        raise
                    errors.append(f'page:{number}:extraction_failed')
                if text.strip():
                    extracted_pages += 1
                    if '\ufffd' in text or any(ord(c) < 32 and c not in '\n\r\t' for c in text):
                        missing.append(f'page:{number}:suspect_text_encoding')
                else:
                    missing.append(f'page:{number}:no_text_ocr_or_manual_review_required')
                try:
                    content = page.get_contents()
                    if (content is not None and any(op in _VISUAL_OPERATORS for _, op in content.operations)
                            or page.get('/Annots')):
                        missing.append(f'page:{number}:visual_content_unprocessed')
                except Exception as exc:
                    if isinstance(exc, (MemoryError, RecursionError)):
                        raise
                    missing.append(f'page:{number}:visual_inspection_failed')
                # A section exists even for blank pages, keeping numbering stable.
                parts.append(f'## 第 {number} 页\n\n' + text + '\n')
            evidence.append(f'页数 {total}；包含非空抽取文字的页数 {extracted_pages}；定位覆盖 {len(locators)} 页')
    except Exception as exc:
        if isinstance(exc, (MemoryError, RecursionError)):
            raise
        errors.append('invalid_pdf')
        evidence.append('PDF 严格解析失败：' + type(exc).__name__)
    extracted = '\n'.join(parts)
    quality = {'status': 'failed' if errors else 'partial', 'errors': errors,
               'missing': missing, 'evidence': evidence,
               'statistics': {'blocks': len(locators), 'characters': len(extracted),
                              'pages_total': total, 'pages_extracted': extracted_pages}}
    return extracted, meta, locators, quality


def capture_pdf(input_path, candidate_root, package_path, *, vault_root, adapter_id=None,
                origin=None, source_id=None, attachments=None):
    """与 capture 同形，返回 (source_package dict, package_root Path)。

    PDF 内嵌视觉内容仅保留在原件中，不把未解析图表冒充已捕获附件。
    非空 attachments 不支持；加密、损坏保留 failed 包，空白/扫描件为 partial。
    输入文件 IO、路径、依赖错误抛异常，不创建成功清单。
    """
    if adapter_id not in (None, 'pdf'):
        raise ValueError(f'不支持的 PDF 适配器: {adapter_id}')
    if attachments:
        raise ValueError('PDF 首版不支持外部附件映射；内嵌资源保留在 PDF 原件中')
    input_path, vault_root = Path(input_path), Path(vault_root).resolve()
    candidate_root = Path(candidate_root).resolve()
    _outside_business(candidate_root, vault_root)
    validate_path(package_path)
    library = _load_pypdf()
    data = input_path.read_bytes()
    candidate_root.mkdir(parents=True, exist_ok=True)
    root = resolve_path(candidate_root, package_path)
    _outside_business(root, vault_root)
    if root.exists():
        raise FileExistsError(root)
    extracted, meta, locators, quality = _analyse(data, library)
    original = {'path': _ORIGINAL, 'sha256': bytes_digest(data), 'media_type': 'application/pdf'}
    extracted_bytes = extracted.encode('utf-8', errors='strict')
    origin = origin or input_path.resolve().as_uri()
    package = {'contract_version': '1.0', 'package_version': '1.0',
               'source_id': source_id or 'source-' + digest({'origin': origin}),
               'source_revision': digest([{'path': _ORIGINAL, 'sha256': original['sha256']}]),
               'input_type': 'pdf',
               'source': dict(meta, origin=origin,
                              acquired_at=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                              unavailable_fields=[key for key, value in meta.items() if not value]),
               'originals': [original],
               'extracted': {'path': _EXTRACTED, 'sha256': bytes_digest(extracted_bytes),
                             'media_type': 'text/markdown'},
               'attachments': [], 'locators': locators, 'parser': _parser(library), 'quality': quality}
    validate('source_package', package)
    root.mkdir(parents=True, exist_ok=False)
    for relative, payload in ((_ORIGINAL, data), (_EXTRACTED, extracted_bytes)):
        target = resolve_path(root, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(payload)
    validate_pdf_package(package, root)
    with (root / 'source-package.json').open('x', encoding='utf-8') as stream:
        json.dump(package, stream, ensure_ascii=False, indent=2)
    return package, root


def validate_pdf_package(package, package_root):
    """检查真实字节并重算全部抽取/质量/定位；不授予任何门禁批准。"""
    validate('source_package', package)
    if package['input_type'] != 'pdf' or package['parser']['adapter_id'] != 'pdf':
        raise ContractError('PDF 适配器与原始类型不符')
    library = _load_pypdf()
    if package['parser'] != _parser(library):
        raise ContractError('PDF 解析器版本、配置或 OCR/模型标记不符，需重新解析')
    if (len(package['originals']) != 1 or package['attachments']
            or package['originals'][0]['path'] != _ORIGINAL
            or package['originals'][0]['media_type'] != 'application/pdf'
            or package['extracted']['path'] != _EXTRACTED
            or package['extracted']['media_type'] != 'text/markdown'):
        raise ContractError('PDF 原件或抽取清单不符')
    root = Path(package_root).resolve()
    data = resolve_path(root, _ORIGINAL).read_bytes()
    extracted_bytes = resolve_path(root, _EXTRACTED).read_bytes()
    for record, payload in ((package['originals'][0], data), (package['extracted'], extracted_bytes)):
        if bytes_digest(payload) != record['sha256']:
            raise ContractError(f'文件哈希不一致: {record["path"]}')
    revision = digest([{'path': _ORIGINAL, 'sha256': bytes_digest(data)}])
    if revision != package['source_revision']:
        raise ContractError('source_revision 与 PDF 原件不符')
    try:
        extracted = extracted_bytes.decode('utf-8', errors='strict')
    except UnicodeDecodeError as exc:
        raise ContractError('PDF 抽取不是严格 UTF-8') from exc
    expected, meta, locators, quality = _analyse(data, library)
    if extracted != expected or package['locators'] != locators or package['quality'] != quality:
        raise ContractError('PDF 抽取、逐页定位或质量声明与原件复算不符')
    if (any(package['source'][key] != value for key, value in meta.items())
            or package['source']['unavailable_fields'] != [key for key, value in meta.items() if not value]):
        raise ContractError('PDF 来源元数据与原件复算不符')
    return package
