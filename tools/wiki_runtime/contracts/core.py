"""标准库实现的封闭 v1 JSON Schema 子集与跨字段不变量。"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

VERSION = '1.0'
_HERE = Path(__file__).parent
_HASH = re.compile(r'^[0-9a-f]{64}$')


class ContractError(ValueError):
    """拒绝契约；消息包括字段位置，调用方不得把异常降级为通过。"""


def canonical_json(value) -> bytes:
    """排序对象键、保留数组顺序、无空白、UTF-8；不做 Unicode/换行归一化。"""
    def check(item):
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise ContractError('JSON 对象键必须是字符串')
            for val in item.values():
                check(val)
        elif isinstance(item, list):
            for val in item:
                check(val)
        elif item is None or type(item) in (str, bool, int):
            pass
        elif type(item) is float and math.isfinite(item):
            pass
        else:
            raise ContractError('非 JSON 数据或非有限数值')
    check(value)
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False,
                          separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (ValueError, UnicodeError) as exc:
        raise ContractError(str(exc)) from exc


def bytes_digest(value: bytes) -> str:
    """SHA-256 小写十六进制；文件必须 read_bytes，不用 read_text。"""
    if not isinstance(value, bytes):
        raise ContractError('bytes_digest 只接受 bytes')
    return hashlib.sha256(value).hexdigest()


def digest(value) -> str:
    return bytes_digest(canonical_json(value))


def validate_path(value: str) -> str:
    """词法检查库根相对 POSIX 路径；不接触文件系统，不自动修正输入。"""
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise ContractError('path: 必须是非空相对路径')
    if '\\' in value or value.startswith('/') or any(ord(c) < 32 for c in value):
        raise ContractError('path: 禁止绝对路径、反斜杠和控制字符')
    for part in value.split('/'):
        if part in ('', '.', '..') or part.endswith((' ', '.')):
            raise ContractError('path: 禁止空段、点段和末尾空格/点')
        if any(c in part for c in ':*?"<>|'):
            raise ContractError('path: 禁止驱动器、ADS 与 Windows 保留字符')
        if re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])', part.split('.')[0], re.I):
            raise ContractError('path: Windows 保留设备名')
    return value


def resolve_path(root, value: str) -> Path:
    """检查已存在的 symlink/junction 解析后仍在根内；执行前必须再次检查。"""
    validate_path(value)
    base = Path(root).resolve(strict=True)
    target = (base / value).resolve(strict=False)
    if not target.is_relative_to(base) or target == base:
        raise ContractError('path: 解析后越出库根')
    return target


def load_schema(kind: str) -> dict:
    if kind not in ('source_package', 'manifest', 'candidate', 'dependency_snapshot',
                    'gate_report', 'review_report', 'appeal_report', 'execution_result'):
        raise ContractError(f'未知契约: {kind}')
    return json.loads((_HERE / 'schemas.json').read_text(encoding='utf-8'))['$defs'][kind]


def _check(schema, value, loc, defs):
    if '$ref' in schema:
        return _check(defs[schema['$ref'].rsplit('/', 1)[-1]], value, loc, defs)
    if 'oneOf' in schema:
        count = 0
        for option in schema['oneOf']:
            try:
                _check(option, value, loc, defs)
                count += 1
            except ContractError:
                pass
        if count != 1:
            raise ContractError(f'{loc}: 不符合唯一允许结构')
        return
    expected = schema.get('type')
    matches = {'object': type(value) is dict, 'array': type(value) is list,
               'string': type(value) is str, 'integer': type(value) is int,
               'boolean': type(value) is bool, 'null': value is None}
    if expected and not matches.get(expected, False):
        raise ContractError(f'{loc}: 应为 {expected}')
    if 'enum' in schema and value not in schema['enum']:
        raise ContractError(f'{loc}: 未知值 {value!r}')
    if 'const' in schema and value != schema['const']:
        raise ContractError(f'{loc}: 仅支持 {schema["const"]!r}')
    if type(value) is dict:
        props = schema.get('properties', {})
        for name in schema.get('required', []):
            if name not in value:
                raise ContractError(f'{loc}.{name}: 缺少必需字段')
        if schema.get('additionalProperties') is False and set(value) - set(props):
            raise ContractError(f'{loc}: 未知字段 {sorted(set(value) - set(props))}')
        for key, val in value.items():
            if key in props:
                _check(props[key], val, f'{loc}.{key}', defs)
    if type(value) is list:
        if len(value) < schema.get('minItems', 0):
            raise ContractError(f'{loc}: 数组为空')
        if schema.get('uniqueItems') and len({canonical_json(x) for x in value}) != len(value):
            raise ContractError(f'{loc}: 重复项')
        for i, item in enumerate(value):
            _check(schema.get('items', {}), item, f'{loc}[{i}]', defs)
    if type(value) is str:
        if len(value) < schema.get('minLength', 0):
            raise ContractError(f'{loc}: 字符串为空')
        if 'pattern' in schema and re.fullmatch(schema['pattern'], value) is None:
            raise ContractError(f'{loc}: 格式错误')
        if schema.get('format') == 'vault-path':
            validate_path(value)
    if type(value) is int and value < schema.get('minimum', value):
        raise ContractError(f'{loc}: 小于下界')


def validate(kind: str, value: dict) -> dict:
    """校验结构与本地不变量，成功返回原对象；不验证文件、事实或凭据真实性。"""
    schema = load_schema(kind)
    defs = json.loads((_HERE / 'schemas.json').read_text(encoding='utf-8'))['$defs']
    canonical_json(value)
    _check(schema, value, kind, defs)
    if kind == 'candidate':
        targets = [entry['path'].casefold() for entry in value['changes']]
        if len(targets) != len(set(targets)):
            raise ContractError('candidate: 目标路径重复（Windows 大小写折叠）')
        if any(a != b and b.startswith(a + '/') for a in targets for b in targets):
            raise ContractError('candidate: 目标文件存在父子路径冲突')
        sources = [e['source'].casefold() for e in value['changes'] if e['action'] == 'move']
        if len(sources) != len(set(sources)) or set(sources) & set(targets):
            raise ContractError('candidate: 移动源重复或与目标交叉；v1 禁止移动链')
    if kind == 'dependency_snapshot':
        paths = [entry['path'].casefold() for entry in value['files']]
        if len(paths) != len(set(paths)):
            raise ContractError('dependency_snapshot: 路径重复')
    if kind == 'gate_report' and value['result'] == 'pass':
        if any(f['severity'] == 'blocking' for f in value['findings']):
            raise ContractError('gate_report: 阻塞项不能通过')
    if kind == 'review_report' and value['result'] == 'recommend_pass':
        if any(f['severity'] == 'blocking' for f in value['findings']):
            raise ContractError('review_report: 阻塞项不能建议通过')
    if kind == 'source_package':
        if value['quality']['status'] == 'complete' and value['quality']['missing']:
            raise ContractError('source_package: 有缺失项不能声称完整')
        if value['quality']['status'] == 'complete' and value['quality']['errors']:
            raise ContractError('source_package: 有错误不能声称完整')
    return value


def candidate_digest(candidate: dict) -> str:
    """摘要绑定完整候选清单（含内容哈希/前提），变更数组顺序有意义。"""
    validate('candidate', candidate)
    return digest(candidate)


def bindings_match(report: dict, *, operation_id: str, candidate_digest: str, dependencies_digest: str,
                   rules_digest: str, mapping_digest: str, validator_version: str,
                   review_prompt_version: str) -> bool:
    """通过结果失效判断；仅比对绑定，不认证报告，也不授予 apply 权限。"""
    expected = locals().copy()
    expected.pop('report')
    return all(report.get(k) == v for k, v in expected.items())


def validate_transition(before: str, after: str) -> None:
    """操作执行状态转换，与 raw processing_status 完全分离。"""
    table = json.loads((_HERE / 'state-machine.json').read_text(encoding='utf-8'))
    if before not in table['transitions'] or after not in table['transitions'][before]:
        raise ContractError(f'非法操作状态转换: {before} -> {after}')
