import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.learning_book.local_backup import backup, restore, inventory, verify_backup
from tools.learning_book.contracts import DeliveryError


class BackupTests(unittest.TestCase):
    def test_exact_copy_isolated_restore_and_tamper(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for name in ('runtime','state','control'):
                (root/name).mkdir();(root/name/'sample.bin').write_bytes(b'\x00actual\xff')
            config=dict(runtime=str(root/'runtime'),projectState=str(root/'state'),controlDir=str(root/'control'),
                        guard=str(root/'missing.json'),apiPort=18136,webPort=18336)
            result=backup(config,root/'backup')
            self.assertEqual(result['status'],'succeeded')
            restore(root/'backup',root/'restored')
            for name in ('runtime','state'):
                self.assertEqual(inventory(root/name),inventory(root/'restored'/name))
            (root/'backup/runtime/sample.bin').write_bytes(b'changed')
            with self.assertRaises(DeliveryError):verify_backup(root/'backup')

    def test_backup_uses_short_temporary_directory_name(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for name in ('runtime','state','control'):
                (root/name).mkdir();(root/name/'sample.bin').write_bytes(b'actual')
            config=dict(runtime=str(root/'runtime'),projectState=str(root/'state'),controlDir=str(root/'control'),
                        guard=str(root/'missing.json'),apiPort=18136,webPort=18336)
            with patch('tools.learning_book.local_backup.uuid.uuid4') as value, \
                 patch('tools.learning_book.local_backup.os.replace', wraps=os.replace) as move:
                value.return_value.hex='0123456789abcdef0123456789abcdef'
                result=backup(config,root/'backup')
            self.assertEqual(result['status'],'succeeded')
            self.assertEqual(move.call_args.args[0].name,'.b01234567')


if __name__=='__main__':unittest.main()
