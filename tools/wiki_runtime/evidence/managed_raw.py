"""标准采集薄记录到完整抽取正文的有界绑定。"""
import json
from pathlib import Path
import re
import tempfile

from ..capture import validate_package
from ..contracts import validate, bytes_digest
from ..gates.core import raw_parts
from ..host.backend import parse_json
from .preparation import _need


def managed_extracted(view, path):
    fields, body = raw_parts(view._read_baseline(path))
    match = re.fullmatch(rb'!\[\[(raw/assets/([^/\r\n]+)/([0-9a-f]{64})/extracted/content\.md)\]\]\r?\n?', body)
    _need(match is not None and 'source_package' in fields, 'managed_raw_record')
    extracted, sid, revision = (x.decode('utf-8') for x in match.groups())
    base = extracted.rsplit('/extracted/',1)[0]
    ref = fields['source_package'].decode('utf-8').split(':',1)[1].strip()
    ref = json.loads(ref) if ref.startswith('"') else ref[1:-1].replace("''", "'") if ref.startswith("'") else ref
    _need(ref == '[['+base+'/source-package.json]]', 'managed_raw_package_ref')
    package_data = view._read_baseline(base+'/source-package.json')
    package = parse_json(package_data.decode('utf-8'))
    validate('source_package', package)
    _need(package['source_id'] == sid and package['source_revision'] == revision
        and package['extracted']['path'] == 'extracted/content.md', 'managed_raw_identity')
    _need(package['input_type'] in ('markdown','wechat') and package['quality']['status'] == 'complete'
        and not package['parser']['used_ocr'] and not package['parser']['used_model'], 'managed_raw_quality')
    records = [*package['originals'], package['extracted'], *package['attachments']]
    _need(len(records) <= 128, 'managed_raw_member_limit')
    fixed = {r['path']:view._read_baseline(base+'/'+r['path']) for r in records}
    with tempfile.TemporaryDirectory(prefix='knowledge-managed-raw-') as directory:
        for locator,data in fixed.items():
            target = Path(directory)/locator;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
        validate_package(package, directory)
    return extracted, fixed['extracted/content.md']
