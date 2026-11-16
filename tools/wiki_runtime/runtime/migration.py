"""旧 Host 状态的一次性离线切变；Executor WAL 始终留在原位置。"""
from __future__ import annotations

import copy
from contextlib import contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path

from ..contracts import canonical_json, digest
from ..executor import Executor, ExecutionError
from ..executor.core import _acceptance_lock, _atomic, _safe


FREEZE_VERSION = 1
TERMINAL = frozenset(('applied', 'recovered'))
RECOVERABLE = frozenset(('prepared', 'applying', 'recovery_required'))


class MigrationError(ExecutionError):
    """旧写入口或切变清单不满足冻结约束。"""


def _identity(bundle):
    return {key: copy.deepcopy(bundle[key])
            for key in ('manifest', 'candidate', 'snapshot', 'payload_root')}


def _journal_path(state_dir, operation_id):
    return state_dir / 'private/journals' / (digest(operation_id) + '.json')


def _inventory_active(root, state_dir, operations):
    path = _safe(root, '.wiki-runtime/executor-active.json')
    if not path.exists():
        return None
    try:
        active = json.loads(path.read_bytes())
        if set(active) != {'journal_root', 'operation_id'}:
            raise ValueError('active 字段不封闭')
        operation_id = active['operation_id']
        if type(operation_id) is not str or not operation_id:
            raise ValueError('active operation_id 无效')
    except (AttributeError, TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
        raise MigrationError('旧 active 不可读或结构无效') from exc
    if active['journal_root'] != str(state_dir / 'private/journals'):
        raise MigrationError('active journal_root 与 inventory state_dir 不匹配')
    item = next((item for item in operations if item['operation_id'] == operation_id and
                 item['journal_state'] is not None), None)
    if item is None:
        raise MigrationError('active 没有匹配的可定位 WAL: ' + operation_id)
    status = 'terminal_stale' if item['journal_state'] in TERMINAL else 'recoverable'
    return dict(operation_id=operation_id, journal_root=active['journal_root'], status=status,
                path='.wiki-runtime/executor-active.json')


def _authenticated_record(state_dir, path, envelope):
    if type(envelope) is not dict or set(envelope) != {'record', 'mac'}:
        raise MigrationError('pending envelope 不封闭: ' + str(path))
    record = envelope['record']
    mac = envelope['mac']
    if type(record) is not dict or type(mac) is not str:
        raise MigrationError('pending 认证字段无效: ' + str(path))
    try:
        key = (state_dir / 'private/pending.key').read_bytes()
    except OSError as exc:
        raise MigrationError('pending 密钥不可读，拒绝盘点') from exc
    if len(key) != 32:
        raise MigrationError('pending 密钥无效，拒绝盘点')
    expected = hmac.new(key, canonical_json(record), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, mac):
        raise MigrationError('pending HMAC 认证失败: ' + str(path))
    return record


def inventory_pending(state_dir, root=None):
    """只读盘点已认证 pending、原 WAL 和可选已知 root 的 active。"""
    state_dir = Path(os.path.abspath(state_dir))
    root = Path(os.path.abspath(root)) if root is not None else None
    operations = []
    roots = set()
    pending_root = state_dir / 'private/pending'
    pending_files = sorted(pending_root.glob('*.json')) if pending_root.is_dir() else []
    seen = set()
    for path in pending_files:
        try:
            envelope = json.loads(path.read_bytes())
            record = envelope['record']
            bundle = record['bundle']
            config = record['config']
            operation_id = config['operation_id']
            if digest(operation_id) + '.json' != path.name:
                raise ValueError('pending 文件名与 operation_id 不匹配')
            if bundle['manifest']['operation_id'] != operation_id:
                raise ValueError('pending manifest 与 operation_id 不匹配')
        except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
            raise MigrationError('无法盘点旧 pending: ' + str(path)) from exc
        record = _authenticated_record(state_dir, path, envelope)
        roots.add(config.get('root'))
        journal_path = _journal_path(state_dir, operation_id)
        journal = json.loads(journal_path.read_bytes()) if journal_path.exists() else None
        identity = _identity(bundle)
        if journal is not None:
            if (journal['manifest'] != identity['manifest'] or
                    journal['candidate'] != identity['candidate'] or
                    journal['snapshot'] != identity['snapshot'] or
                    journal.get('payload_root') != identity['payload_root']):
                raise MigrationError('pending 与 WAL 身份不一致: ' + operation_id)
            state = journal['state']
            if state not in TERMINAL | RECOVERABLE:
                raise MigrationError('未知旧 WAL 状态: ' + state)
            classification = 'terminal' if state in TERMINAL else 'accepted_pending_recovery'
            disposition = 'terminal_no_drain' if state in TERMINAL else 'recover_original_operation'
        else:
            state = None
            classification = 'pre_wal_pending'
            disposition = 'drain_registered'
        seen.add(operation_id)
        operations.append(dict(operation_id=operation_id,
            pending_path=path.relative_to(state_dir).as_posix(),
            journal_path=journal_path.relative_to(state_dir).as_posix() if journal else None,
            journal_state=state, classification=classification,
            drain_disposition=disposition, identity=identity,
            runtime_managed=record.get('runtime_managed') is True))

    journal_root = state_dir / 'private/journals'
    journal_files = sorted(journal_root.glob('*.json')) if journal_root.is_dir() else []
    for path in journal_files:
        try:
            journal = json.loads(path.read_bytes())
            operation_id = journal['manifest']['operation_id']
            if digest(operation_id) + '.json' != path.name:
                raise ValueError('WAL 文件名与 operation_id 不匹配')
            state = journal['state']
            if state not in TERMINAL | RECOVERABLE:
                raise ValueError('未知 WAL 状态')
        except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
            raise MigrationError('无法盘点旧 WAL: ' + str(path)) from exc
        if operation_id in seen:
            continue
        operations.append(dict(operation_id=operation_id, pending_path=None,
            journal_path=path.relative_to(state_dir).as_posix(), journal_state=state,
            classification='terminal' if state in TERMINAL else 'accepted_pending_recovery',
            drain_disposition='terminal_no_drain' if state in TERMINAL else 'recover_original_operation',
            identity=_identity(journal), runtime_managed=False))
    operations.sort(key=lambda item: item['operation_id'])
    active = _inventory_active(root, state_dir, operations) if root is not None else None
    inventory = dict(schema_version=1, state_dir=str(state_dir), operations=operations,
        roots=sorted(root for root in roots if isinstance(root, str)), active=active,
        active_checked=root is not None,
        drain_required=any(item['classification'] == 'pre_wal_pending' for item in operations))
    if not operations and active is None:
        inventory['disposition'] = 'no_drain_required'
    inventory['inventory_digest'] = _inventory_digest(inventory)
    return inventory


def _inventory_digest(inventory):
    return digest({key: value for key, value in inventory.items() if key != 'inventory_digest'})


def _freeze_path(root):
    return _safe(root, '.wiki-runtime/legacy-cutover.json')


def _freeze_digest(value):
    return digest(dict(root=value['root'], state_dir=value['state_dir'],
                       inventory_digest=value['inventory_digest']))


def _load_freeze(root, state_dir=None):
    root = Path(os.path.abspath(root))
    path = _freeze_path(root)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationError('freeze 描述不可读') from exc
    expected_keys = {'schema_version', 'root', 'state_dir', 'inventory_digest',
                     'freeze_digest', 'inventory', 'drains'}
    if (type(value) is not dict or set(value) != expected_keys or
            value['schema_version'] != FREEZE_VERSION or value['root'] != str(root) or
            value['inventory_digest'] != _inventory_digest(value['inventory']) or
            value['freeze_digest'] != _freeze_digest(value)):
        raise MigrationError('freeze 描述或 inventory 绑定无效')
    if state_dir is not None and value['state_dir'] != str(Path(os.path.abspath(state_dir))):
        raise MigrationError('freeze 描述绑定了不同 state_dir')
    return value


def _check_restart(root, state_dir, freeze):
    current = inventory_pending(state_dir, root)
    initial = {item['operation_id']: item for item in freeze['inventory']['operations']}
    current_by_id = {item['operation_id']: item for item in current['operations']}
    for item in current['operations']:
        operation_id = item['operation_id']
        if operation_id not in initial:
            if not item['runtime_managed']:
                raise MigrationError('freeze 后出现清单外旧 operation: ' + operation_id)
            continue
        before = initial[operation_id]
        if item['identity'] != before['identity']:
            raise MigrationError('freeze 后 operation 身份改变: ' + operation_id)
        if before['journal_state'] is not None and item['journal_state'] is None:
            raise MigrationError('已接受 WAL 下落不明: ' + operation_id)
        if before['journal_state'] in TERMINAL and item['journal_state'] != before['journal_state']:
            raise MigrationError('旧终态 WAL 已改变: ' + operation_id)
        receipt = freeze['drains'].get(operation_id)
        if receipt is not None and receipt['status'] == 'completed':
            result = receipt.get('result', {})
            execution = result.get('execution', {})
            if (item['journal_state'] not in TERMINAL
                    or result.get('status') != item['journal_state']
                    or execution.get('state') != item['journal_state']
                    or execution.get('operation_id') != operation_id):
                raise MigrationError('completed drain 缺少匹配的原终态 WAL: ' + operation_id)
        if before['journal_state'] is None and item['journal_state'] is not None:
            if (before['classification'] != 'pre_wal_pending' or receipt is None
                    or receipt['status'] not in ('running', 'completed')):
                raise MigrationError('清单外旧进程创建了 WAL: ' + operation_id)
    if set(initial) - set(current_by_id):
        raise MigrationError('freeze 后旧记录下落不明')
    before_active = freeze['inventory'].get('active')
    after_active = current['active']
    if before_active != after_active:
        if after_active is not None:
            operation_id = after_active['operation_id']
            if operation_id not in initial:
                if not current_by_id[operation_id]['runtime_managed']:
                    raise MigrationError('freeze 后出现未获准旧 active: ' + operation_id)
            else:
                before = initial[operation_id]
                receipt = freeze['drains'].get(operation_id)
                terminal_stale = (after_active['status'] == 'terminal_stale'
                                  and current_by_id[operation_id]['journal_state'] in TERMINAL)
                if not terminal_stale and (before['journal_state'] is not None or receipt is None
                        or receipt['status'] not in ('running', 'completed')):
                    raise MigrationError('freeze 后出现未获准 active: ' + operation_id)
        elif before_active['status'] == 'recoverable':
            operation_id = before_active['operation_id']
            item = current_by_id[operation_id]
            if item['journal_state'] in RECOVERABLE:
                raise MigrationError('可恢复 active 在原 WAL 恢复前消失: ' + operation_id)
    return current


def _intent_path(root):
    return _safe(root, '.wiki-runtime/legacy-cutover.intent.json')


def _save_intent(root, state_dir, freeze):
    value = dict(schema_version=FREEZE_VERSION, root=str(root), state_dir=str(state_dir),
                 freeze_digest=freeze['freeze_digest'])
    _atomic(_intent_path(root), canonical_json(value))


def _read_intent(root, state_dir):
    root = Path(os.path.abspath(root))
    state_dir = Path(os.path.abspath(state_dir))
    path = _intent_path(root)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationError('cutover intent 不可读') from exc
    if (type(value) is not dict
            or set(value) != {'schema_version', 'root', 'state_dir', 'freeze_digest'}
            or value['schema_version'] != FREEZE_VERSION
            or value['root'] != str(root) or value['state_dir'] != str(state_dir)
            or type(value['freeze_digest']) is not str
            or len(value['freeze_digest']) != 64
            or any(character not in '0123456789abcdef' for character in value['freeze_digest'])):
        raise MigrationError('cutover intent 结构或 root／state_dir 绑定无效')
    return value


def _locator_path(state_dir):
    return Path(state_dir) / 'private/legacy-cutover.pointer.json'


def _read_locator(state_dir):
    path = _locator_path(state_dir)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationError('freeze 定位指针不可读') from exc
    if (type(value) is not dict or set(value) != {'schema_version', 'root', 'freeze_digest'} or
            value['schema_version'] != FREEZE_VERSION or type(value['root']) is not str):
        raise MigrationError('freeze 定位指针无效')
    return value


def _save_locator(state_dir, freeze):
    value = dict(schema_version=FREEZE_VERSION, root=freeze['root'],
                 freeze_digest=freeze['freeze_digest'])
    _atomic(_locator_path(state_dir), canonical_json(value))


def freeze_legacy_entries(root, state_dir):
    """等待已登记写者退出，再原子发布与 state_dir、清单摘要绑定的冻结。"""
    root = Path(os.path.abspath(root))
    state_dir = Path(os.path.abspath(state_dir))
    with _acceptance_lock(root, wait=True):
        intent = _read_intent(root, state_dir)
        freeze = _load_freeze(root, state_dir)
        if freeze is not None:
            if intent is not None and intent['freeze_digest'] != freeze['freeze_digest']:
                raise MigrationError('cutover intent 与已有 freeze 摘要绑定不一致')
            _check_restart(root, state_dir, freeze)
            _save_intent(root, state_dir, freeze)
            _save_locator(state_dir, freeze)
            return copy.deepcopy(freeze)
        locator = _read_locator(state_dir)
        inventory = inventory_pending(state_dir, root)
        freeze = dict(schema_version=FREEZE_VERSION, root=str(root), state_dir=str(state_dir),
                      inventory_digest=inventory['inventory_digest'], inventory=inventory, drains={})
        freeze['freeze_digest'] = _freeze_digest(freeze)
        if intent is not None and intent['freeze_digest'] != freeze['freeze_digest']:
            raise MigrationError('cutover intent 与重算冻结候选不一致；拒绝吸收清单外记录')
        if locator is not None and (
                locator['root'] != str(root) or locator['freeze_digest'] != freeze['freeze_digest']):
            raise MigrationError('freeze locator 与重算候选不一致')
        _save_intent(root, state_dir, freeze)
        if locator is None:
            _save_locator(state_dir, freeze)
        _atomic(_freeze_path(root), canonical_json(freeze))
        return copy.deepcopy(freeze)


def _cutover_report(inventory, freeze):
    receipts = freeze['drains'] if freeze is not None else {}
    legacy_ids = ({item['operation_id'] for item in freeze['inventory']['operations']}
                  if freeze is not None else None)
    operations = []
    pending_actions = []
    managed_operations = 0
    counts = {'terminal': 0, 'accepted_pending_recovery': 0,
              'pre_wal_pending': 0, 'superseded_by_runtime_cutover': 0}
    for item in inventory['operations']:
        if legacy_ids is not None and item['operation_id'] not in legacy_ids:
            managed_operations += int(item['runtime_managed'])
            continue
        receipt = receipts.get(item['operation_id'])
        superseded = (item['journal_state'] is None and receipt is not None
                      and receipt['status'] == 'superseded_by_runtime_cutover')
        if superseded:
            disposition = 'superseded_by_runtime_cutover'
            counts[disposition] += 1
        else:
            disposition = item['classification']
            counts[disposition] += 1
            if disposition == 'accepted_pending_recovery':
                pending_actions.append({'operation_id': item['operation_id'],
                                        'action': 'recover_original_operation'})
            elif disposition == 'pre_wal_pending':
                pending_actions.append({'operation_id': item['operation_id'],
                                        'action': 'drain_or_supersede'})
        operations.append({'operation_id': item['operation_id'],
                           'journal_state': item['journal_state'],
                           'cutover_disposition': disposition})
    ready = freeze is not None and not pending_actions
    return {'schema_version': 1, 'operations': operations, 'counts': counts,
            'managed_operations': managed_operations,
            'pending_actions': pending_actions, 'ready_for_runtime': ready}


def supersede_pending(operation_id, reason, *, root=None, state_dir=None):
    """封闭无法 drain 的 pre-WAL pending；不修改旧 pending、预算或授权历史。"""
    if type(reason) is not str or not reason.strip():
        raise MigrationError('supersede 必须记录非空原因')
    root = Path(os.path.abspath(root if root is not None else Path.cwd()))
    with _acceptance_lock(root, wait=True):
        freeze = _load_freeze(root, state_dir)
        if freeze is None:
            raise MigrationError('尚未 freeze，拒绝 supersede')
        state_dir = Path(freeze['state_dir'])
        _check_restart(root, state_dir, freeze)
        registered = {item['operation_id']: item for item in freeze['inventory']['operations']}
        item = registered.get(operation_id)
        if item is None or item['classification'] != 'pre_wal_pending':
            raise MigrationError('只有清单内 pre-WAL pending 可以 supersede: ' + str(operation_id))
        receipt = freeze['drains'].get(operation_id)
        if receipt is not None and receipt['status'] == 'superseded_by_runtime_cutover':
            if receipt['reason'] != reason:
                raise MigrationError('同一 operation 的 supersede 原因不得重绑')
            return copy.deepcopy(receipt)
        if receipt is not None and receipt['status'] == 'completed':
            raise MigrationError('completed drain 不得被 supersede 覆盖')
        if _journal_path(state_dir, operation_id).exists():
            raise MigrationError('已有 WAL 的 operation 不得 supersede；必须查询或恢复')
        receipt = {'status': 'superseded_by_runtime_cutover', 'reason': reason}
        freeze['drains'][operation_id] = receipt
        _atomic(_freeze_path(root), canonical_json(freeze))
        return copy.deepcopy(receipt)


def inspect_cutover(state_dir, *, root=None):
    """重启检查入口；发现新增、失踪或异绑记录时拒绝继续。"""
    state_dir = Path(os.path.abspath(state_dir))
    locator = _read_locator(state_dir)
    if root is None and locator is not None:
        root = locator['root']
    inventory = inventory_pending(state_dir, root)
    roots = inventory['roots']
    if root is None and len(roots) == 1:
        root = roots[0]
    if root is None:
        report = _cutover_report(inventory, None)
        return dict(state_dir=str(state_dir), root=None, frozen=False, inventory=inventory,
                    freeze=None, drain_required=inventory['drain_required'], report=report,
                    disposition=inventory.get('disposition', 'inventory_contains_operations'))
    with _acceptance_lock(root, wait=True):
        inventory = inventory_pending(state_dir, root)
        roots = inventory['roots']
        if len(roots) > 1 or roots and str(Path(os.path.abspath(root))) != str(Path(os.path.abspath(roots[0]))):
            raise MigrationError('pending root 与 freeze 定位不一致')
        freeze = _load_freeze(root, state_dir)
        if locator is not None and (freeze is None or locator['freeze_digest'] != freeze['freeze_digest'] or
                                    locator['root'] != freeze['root']):
            raise MigrationError('freeze 定位指针与库内描述不一致')
        if freeze is not None:
            inventory = _check_restart(root, state_dir, freeze)
        report = _cutover_report(inventory, freeze)
        return dict(state_dir=str(state_dir), root=str(Path(os.path.abspath(root))),
                    frozen=freeze is not None, inventory=inventory, freeze=freeze,
                    drain_required=any(action['action'] == 'drain_or_supersede'
                                       for action in report['pending_actions']),
                    report=report,
                    disposition=inventory.get('disposition') or (
                        'ready_for_runtime' if report['ready_for_runtime'] else 'cutover_action_required'))


@contextmanager
def legacy_write_guard(root, operation_id=None):
    """旧 Python 写 API 的资格检查与实际写入必须全部位于此上下文。"""
    root = Path(os.path.abspath(root))
    with _acceptance_lock(root):
        if _intent_path(root).exists() or _load_freeze(root) is not None:
            raise MigrationError('旧写入口已冻结或正在切变；裸 operation_id 不构成 drain 授权')
        yield


def _check_executor_apply(root, journal_root, bundle, *, managed=False,
                          drain_operation_id=None):
    """只有显式 runner 可沿用 running receipt；其余路径先完成旧记录切变。"""
    root = Path(os.path.abspath(root))
    journal_root = Path(os.path.abspath(journal_root))
    freeze = _load_freeze(root)
    if freeze is None:
        if _intent_path(root).exists():
            raise MigrationError('cutover intent 已存在但 freeze 未完成，拒绝新 WAL')
        if journal_root.parent.name == 'private' and _read_locator(journal_root.parent.parent) is not None:
            raise MigrationError('freeze 定位已存在但库内描述缺失，拒绝新 WAL')
        return
    if str(journal_root) != str(Path(freeze['state_dir']) / 'private/journals'):
        raise MigrationError('Executor journal_root 与 freeze state_dir 不匹配')
    operation_id = bundle['manifest']['operation_id']
    registered = {item['operation_id']: item for item in freeze['inventory']['operations']}
    item = registered.get(operation_id)
    receipt = freeze['drains'].get(operation_id)
    if item is not None and item['identity'] != _identity(bundle):
        raise MigrationError('operation 身份与 freeze 清单不一致: ' + operation_id)
    if (item is not None and item['classification'] == 'pre_wal_pending'
            and receipt is not None and receipt['status'] == 'running'
            and drain_operation_id == operation_id):
        _check_restart(root, Path(freeze['state_dir']), freeze)
        return
    if managed:
        current = _check_restart(root, Path(freeze['state_dir']), freeze)
        report = _cutover_report(current, freeze)
        if not report['ready_for_runtime']:
            raise MigrationError('旧 pending 尚未完成切变，拒绝启用新 Runtime 写入')
        if item is not None:
            raise MigrationError('旧 operation 不得改绑新 Runtime；请恢复终态或新建 operation: ' + operation_id)
        return
    raise MigrationError('freeze 后仅显式 drain runner 可继续原 operation: ' + operation_id)


def assert_runtime_creation_allowed(root, state_dir, operation_id=None):
    """在新 pending／Task 产生前核验切变；旧 operation 必须走原恢复入口。"""
    root = Path(os.path.abspath(root))
    if (not _freeze_path(root).exists() and not _intent_path(root).exists()
            and _read_locator(state_dir) is None):
        return
    with _acceptance_lock(root, wait=True):
        freeze = _load_freeze(root, state_dir)
        if freeze is None:
            if _intent_path(root).exists() or _read_locator(state_dir) is not None:
                raise MigrationError('cutover intent／locator 已存在但 freeze 未完成，拒绝创建 Runtime 操作')
            return
        current = _check_restart(root, Path(freeze['state_dir']), freeze)
        if not _cutover_report(current, freeze)['ready_for_runtime']:
            raise MigrationError('旧 pending 尚未完成切变，拒绝创建新 Runtime 操作')
        if (operation_id is not None
                and operation_id in {item['operation_id'] for item in freeze['inventory']['operations']}):
            raise MigrationError('旧 operation 不得重新创建；请使用原恢复或终态入口: ' + operation_id)


def assert_managed_operation(root, journal_root, bundle, *, drain_operation_id=None):
    """在创建 Task／维护绑定前复核同一身份与切变资格。"""
    with _acceptance_lock(root, wait=True):
        _check_executor_apply(
            root, journal_root, bundle, managed=True,
            drain_operation_id=drain_operation_id,
        )


def _save_receipt(root, freeze, operation_id, receipt):
    with _acceptance_lock(root, wait=True):
        current = _load_freeze(root, freeze['state_dir'])
        if current['freeze_digest'] != freeze['freeze_digest']:
            raise MigrationError('drain 期间 freeze 描述已改变')
        existing = current['drains'].get(operation_id)
        if existing is not None and existing['status'] == 'superseded_by_runtime_cutover':
            raise MigrationError('已 supersede 的 operation 不得回写 drain receipt: ' + operation_id)
        current['drains'][operation_id] = receipt
        _atomic(_freeze_path(root), canonical_json(current))


def drain_registered_pending(operation_id, *, root=None, state_dir=None):
    """唯一白名单 runner；不反造 Invocation，重复调用沿用原 Executor 结果。"""
    root = Path(os.path.abspath(root if root is not None else Path.cwd()))
    with _acceptance_lock(root, wait=True):
        freeze = _load_freeze(root, state_dir)
        if freeze is None:
            raise MigrationError('尚未 freeze，拒绝 drain')
        state_dir = Path(freeze['state_dir'])
        _check_restart(root, state_dir, freeze)
        registered = {item['operation_id']: item for item in freeze['inventory']['operations']}
        item = registered.get(operation_id)
        if item is None or item['classification'] != 'pre_wal_pending':
            raise MigrationError('operation 不在获准 drain 清单: ' + str(operation_id))
        receipt = freeze['drains'].get(operation_id)
        if receipt is not None and receipt['status'] == 'superseded_by_runtime_cutover':
            raise MigrationError('operation 已由 Runtime 切变封闭，不得继续旧 drain: ' + operation_id)
        if receipt is not None and receipt['status'] == 'completed':
            return copy.deepcopy(receipt['result'])
        freeze['drains'][operation_id] = dict(status='running')
        _atomic(_freeze_path(root), canonical_json(freeze))

    from ..host.supervisor import StandaloneHost

    host = StandaloneHost(root, state_dir, offline=True)
    host._legacy_drain_operation = operation_id
    try:
        record = host.load_pending(operation_id)
        if _identity(record['bundle']) != item['identity']:
            raise MigrationError('drain pending 身份与 freeze 清单不一致')
        executor = Executor(root, state_dir / 'private/journals')
        journal_path = _journal_path(state_dir, operation_id)
        if journal_path.exists():
            try:
                terminal = executor.lookup_terminal(record['bundle'])
            except ExecutionError as exc:
                if '必须先 recover' not in str(exc):
                    raise
                execution = executor.recover(operation_id)
                result = dict(status=execution['state'], applied=execution['state'] == 'applied',
                              execution=execution)
            else:
                result = dict(status=terminal['state'], applied=terminal['state'] == 'applied',
                              execution=terminal)
        elif record.get('kind') == 'derived':
            from ..host.cli import _apply_record
            result = _apply_record(host, operation_id)
        else:
            result = host.apply_pending(operation_id)
        status = 'completed' if result['status'] in TERMINAL else 'pending'
        _save_receipt(root, freeze, operation_id, dict(status=status, result=result))
        return result
    finally:
        host.close()
