"""安装预检应在索引开始前发现缓存硬链接。"""
import os
from pathlib import Path
import tempfile
import unittest

from tools.learning_book.local_install import (verify_author_install, verify_extension_install,
    verify_materialized_dependencies)
from tools.learning_book.contracts import DeliveryError, read_json, sha256


class InstallTests(unittest.TestCase):
    def test_cache_hardlink_rejected_and_copy_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);site=root/'site';site.mkdir()
            cache=root/'cache.txt';cache.write_text('unchanged data')
            linked=site/'dependency.dat';os.link(cache,linked)
            with self.assertRaises(DeliveryError) as error:
                verify_materialized_dependencies(site)
            self.assertEqual(error.exception.code,'install_links')
            content=linked.read_bytes();linked.unlink();linked.write_bytes(content)
            self.assertEqual(verify_materialized_dependencies(site),1)
            self.assertEqual(cache.read_bytes(),linked.read_bytes())

    def test_author_build_requires_fixed_release_and_actual_module(self):
        root=Path(__file__).resolve().parents[2]
        release=root/'.learning-validation/learning-system-next-delivery/e1-release-06'
        installed=read_json(release/'release.json')['installedFiles']
        manifest=read_json(root/'patches/deeptutor/e1-authored-delivery/manifest.json')
        build={'capability':'learning-authored-delivery/1','baseCommit':manifest['baseCommit'],
               'patchSha256':manifest['patchSha256'],
               'moduleSha256':installed['deeptutor/book/author_delivery.py']}
        self.assertEqual(verify_author_install(installed,build),build)
        for key in ('patchSha256','moduleSha256'):
            invalid={**build,key:'0'*64}
            with self.assertRaises(DeliveryError) as error:
                verify_author_install(installed,invalid)
            self.assertEqual(error.exception.code,
                             'install_author_build' if key=='patchSha256' else 'install_author_module')

    def test_extension_build_requires_fixed_release_and_actual_module(self):
        root=Path(__file__).resolve().parents[2]
        release=root/'.learning-validation/learning-controlled-extension/release-04'
        installed=read_json(release/'release.json')['installedFiles']
        manifest=read_json(root/'patches/deeptutor/controlled-extension/manifest.json')
        build={'capability':'learning-controlled-extension/1','baseCommit':manifest['baseCommit'],
               'patchSha256':manifest['patchSha256'],
               'moduleSha256':installed['deeptutor/book/extension_delivery.py']}
        self.assertEqual(verify_extension_install(installed,build),build)
        for key in ('patchSha256','moduleSha256'):
            invalid={**build,key:'0'*64}
            with self.assertRaises(DeliveryError) as error:
                verify_extension_install(installed,invalid)
            self.assertEqual(error.exception.code,
                             'install_extension_build' if key=='patchSha256' else 'install_extension_module')


if __name__=='__main__':unittest.main()
