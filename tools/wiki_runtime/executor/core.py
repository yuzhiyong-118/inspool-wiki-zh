"""协作模式执行器。文件哈希和回调认证不代替操作系统权限隔离。"""
from __future__ import annotations

import base64
import copy
from contextlib import contextmanager, nullcontext
import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile
import uuid

from ..candidate import CandidateView
from ..contracts import (ContractError, bytes_digest, candidate_digest,
                         canonical_json, digest, validate, validate_path)
from ..coordinator import requires_review
from ..gates import run_gates, raw_parts, VALIDATOR_VERSION
from ..review import build_request, review, PROMPT_VERSION

BINDINGS = ('operation_id', 'candidate_digest', 'dependencies_digest', 'rules_digest',
            'mapping_digest', 'validator_version', 'review_prompt_version')
MAPPING = 'tools/wiki_runtime/contracts/rules.json'


class ExecutionError(ContractError):
    """拒绝写入；已经准备 journal 的异常返回 recovery_required。"""


def _safe(base, relative, *, allow_hardlink=False):
    validate_path(relative)
    base = Path(os.path.abspath(base))
    for part in (base, *base.parents):
        if part.exists() and _reparse(part):
            raise ExecutionError('拒绝重解析根: ' + str(part))
    current = base
    for component in relative.split('/'):
        if current.is_dir():
            aliases = [p.name for p in current.iterdir() if p.name.casefold() == component.casefold()]
            if aliases and aliases != [component]:
                raise ExecutionError('大小写路径别名: ' + relative)
        current /= component
        if current.exists() or current.is_symlink():
            if _reparse(current) or (current.is_file() and current.stat().st_nlink != 1
                                    and not (allow_hardlink and current == base / relative)):
                raise ExecutionError('拒绝 symlink/junction/hardlink: ' + relative)
    if not current.resolve().is_relative_to(base.resolve()):
        raise ExecutionError('路径越界')
    return current


def _reparse(path):
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def _atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix='.executor-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _encode(value):
    return None if value is None else base64.b64encode(value).decode('ascii')


def _decode(value):
    return None if value is None else base64.b64decode(value, validate=True)


def _hash(value):
    return None if value is None else bytes_digest(value)


@contextmanager
def _acceptance_lock(root, *, wait=False):
    control = _safe(root, '.wiki-runtime')
    control.mkdir(exist_ok=True)
    target = _safe(root, '.wiki-runtime/executor.lock')
    with target.open('a+b') as stream:
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                mode = msvcrt.LK_LOCK if wait else msvcrt.LK_NBLCK
                msvcrt.locking(stream.fileno(), mode, 1)
            else:
                import fcntl
                mode = fcntl.LOCK_EX if wait else fcntl.LOCK_EX | fcntl.LOCK_NB
                fcntl.flock(stream.fileno(), mode)
        except OSError as exc:
            raise ExecutionError('正式库正由另一执行器占用') from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class Executor:
    def __init__(self, root, journal_root, *, reviewer=None, reserve_call=None,
                 approval_check=None, package_check=None, review_timeout=30,
                 remaining_timeout=None, deterministic_check=None, fault=None,
                 invocation_port=None, acceptance_context=None, view_scope='whole_root'):
        if (type(review_timeout) not in (int, float) or not math.isfinite(review_timeout)
                or review_timeout <= 0):
            raise ExecutionError('review_timeout 必须有限且为正')
        self.root = Path(os.path.abspath(root))
        if not self.root.is_dir():
            raise ExecutionError('正式根不存在')
        self.journal_root = Path(os.path.abspath(journal_root))
        if self.journal_root == self.root or self.root.is_relative_to(self.journal_root):
            raise ExecutionError('journal 不得包含正式库')
        if self.journal_root.is_relative_to(self.root):
            relative = self.journal_root.relative_to(self.root).as_posix()
            if not relative.startswith('.wiki-runtime/executor/'):
                raise ExecutionError('库内 journal 只允许 .wiki-runtime/executor/ 子目录')
        _safe(self.journal_root.parent, self.journal_root.name)
        self.reviewer, self.reserve_call = reviewer, reserve_call
        self.approval_check, self.package_check = approval_check, package_check
        self.deterministic_check = deterministic_check
        self.review_timeout, self.remaining_timeout = review_timeout, remaining_timeout
        self.fault = fault
        self.invocation_port = invocation_port
        self.acceptance_context = acceptance_context
        if view_scope not in ('whole_root', 'knowledge_content'):
            raise ExecutionError('未知 Executor 内容范围')
        self.view_scope = view_scope

    def _hit(self, event, index):
        if self.fault:
            self.fault(event, index)

    @contextmanager
    def _lock(self, *, wait=False):
        """复用 root/.wiki-runtime/executor.lock，不另建接受锁。"""
        with _acceptance_lock(self.root, wait=wait):
            yield

    @contextmanager
    def acceptance_barrier(self):
        """暂停、撤销和最终接受共用的跨进程文件屏障。"""
        with self._lock():
            yield self

    @property
    def _active(self):
        return _safe(self.root, '.wiki-runtime/executor-active.json')

    def _journal(self, operation_id):
        return _safe(self.journal_root, digest(operation_id) + '.json')

    def _save(self, journal):
        _safe(self.journal_root.parent, self.journal_root.name)
        _atomic(self._journal(journal['manifest']['operation_id']), canonical_json(journal))

    def _result(self, journal, *, errors=(), conflict=False):
        result = dict(contract_version='1.0', **{k: journal['manifest'][k] for k in BINDINGS},
            state=journal['state'], applied=[dict(path=s['path'], sha256=s['new_hash'])
                for s in journal['steps'] if s['status'] == 'done'],
            journal_refs=[digest(journal['manifest']['operation_id']) + '.json'],
            recovery_status=(journal.get('recovery_status') or (
                'conflict' if conflict else 'recovered' if journal['state'] == 'recovered'
                else 'required' if journal['state'] in ('prepared', 'applying', 'recovery_required')
                else 'not_needed')),
            errors=list(errors))
        return validate('execution_result', result)

    def _read(self, path):
        target = _safe(self.root, path)
        return target.read_bytes() if target.exists() else None

    def _context(self, manifest, candidate, snapshot):
        return dict(manifest=copy.deepcopy(manifest), manifest_digest=digest(manifest),
            candidate=copy.deepcopy(candidate), snapshot=copy.deepcopy(snapshot),
            operation_type=manifest['operation_type'],
            source_paths=sorted(c['source'] for c in candidate['changes'] if c['action'] == 'move'),
            bindings={k: manifest[k] for k in BINDINGS})

    def _quality(self, manifest, candidate, view, packages, context, *, derived=False):
        if manifest['operation_type'] in ('capture', 'import'):
            if not packages or self.package_check is None:
                raise ExecutionError('capture/import 缺少可信资料包验证入口')
            if self.package_check(copy.deepcopy(context), packages) is not True:
                raise ExecutionError('可信资料包验证拒绝')
        extracted, artifacts = set(), set()
        for package, package_root in packages:
            validate('source_package', package)
            if (package['input_type'] in ('pdf', 'audio', 'video') or
                    package['parser']['used_ocr'] or package['parser']['used_model'] or
                    package['quality']['status'] != 'complete' or package['quality']['errors'] or
                    package['quality']['missing'] or not package['quality']['evidence']):
                raise ExecutionError('资料质量/抽取类型需人工处理')
            for item in [*package['originals'], package['extracted'], *package['attachments']]:
                data = _safe(Path(package_root), item['path']).read_bytes()
                if bytes_digest(data) != item['sha256'] or not data:
                    raise ExecutionError('资料包字节/哈希无效')
                artifacts.add(bytes_digest(data))
            # 来源清单是受认证包的规范化流程元数据，不是模型追加的任意附件。
            artifacts.add(bytes_digest(canonical_json(package) + b'\n'))
            text = _safe(Path(package_root), package['extracted']['path']).read_bytes()
            if not text.decode('utf-8').strip():
                raise ExecutionError('抽取为空')
            extracted.add(raw_parts(text)[1])
        if manifest['operation_type'] in ('capture', 'import'):
            for change in candidate['changes']:
                if change['path'].startswith('raw/assets/') and bytes_digest(view.read_bytes(change['path'])) not in artifacts:
                    raise ExecutionError('新 raw 附件没有可信资料包字节来源')
                if change['path'].startswith('raw/unprocessed/'):
                    if not derived and raw_parts(view.read_bytes(change['path']))[1] not in extracted:
                        raise ExecutionError('新 raw 正文没有可信资料包字节来源')
        for path in manifest['input_refs']:
            if path.startswith('raw/'):
                header = self._read(path).decode('utf-8').split('---', 2)[:2]
                text = '\n'.join(header)
                if (re.search(r'(?im)^\s*(?:input_type|source_type|original_type|original_input_type):\s*[\"\x27]?(?:pdf|audio|video)\b', text)
                        or re.search(r'(?im)^\s*(?:used_ocr|used_model):\s*true\b', text)):
                    raise ExecutionError('raw 来源类型需人工处理')

    def _validate_admission(self, bundle, admission):
        from ..runtime.knowledge_ingest import is_knowledge, parse_executor_admission
        if admission is None:
            if self.view_scope != 'whole_root':
                raise ExecutionError('知识范围执行器缺少专用准入')
            return
        parse_executor_admission(admission)
        expected_scope = admission['view_scope'] if is_knowledge(admission) else 'whole_root'
        if self.view_scope != expected_scope:
            raise ExecutionError('Executor 内容范围不对应原准入')
        manifest, candidate, snapshot = (bundle[k] for k in ('manifest', 'candidate', 'snapshot'))
        if manifest['operation_type'] != 'ingest':
            raise ExecutionError('Admission 仅用于受管 ingest，不能替代其他操作的授权')
        expected = {
            'operation_id': manifest['operation_id'],
            'manifest_digest': digest(manifest),
            'candidate_digest': candidate_digest(candidate),
            'dependencies_digest': digest(snapshot),
            'rules_digest': manifest['rules_digest'],
        }
        for field, value in expected.items():
            if admission[field] != value:
                raise ExecutionError('Admission 与实际 Candidate／依赖／规则绑定不一致: ' + field)
        if (candidate['operation_id'] != admission['operation_id']
                or snapshot['operation_id'] != admission['operation_id']):
            raise ExecutionError('Candidate、snapshot 与 Admission 的 operation_id 不一致')
        if is_knowledge(admission):
            if (admission['mapping_digest'] != manifest['mapping_digest']
                    or any(c['action']!='write' or not c['path'].startswith(('wiki/','raw/'))
                           for c in candidate['changes'])):
                raise ExecutionError('知识准入不允许改变映射或候选操作范围')

    def _review(self, manifest, candidate, snapshot, view, admission):
        if self.reviewer is None:
            raise ExecutionError('G3 缺少可信 Reviewer')
        timeout = self.review_timeout
        if admission is None:
            if self.reserve_call is None:
                raise ExecutionError('G3 缺少可信调用预算入口')
            if self.remaining_timeout:
                timeout = min(timeout, self.remaining_timeout())
        else:
            if self.invocation_port is None:
                raise ExecutionError('受管 G3 缺少统一 InvocationPort')
            timeout = min(timeout, self.invocation_port.remaining_run_time(admission['run_id']))
        if not math.isfinite(timeout) or timeout <= 0:
            raise ExecutionError('G3 时间预算耗尽')
        before, after = {}, {}
        for change in candidate['changes']:
            if change['action'] == 'move':
                before[change['source']] = self._read(change['source'])
            elif change['precondition']['kind'] == 'hash':
                before[change['path']] = self._read(change['path'])
            if change['action'] != 'delete':
                after[change['path']] = view.read_bytes(change['path'])
        request = build_request(manifest, candidate, snapshot,
            rules=self._read('AGENTS.md'), mapping=self._read(MAPPING),
            originals={p: self._read(p) for p in manifest['input_refs']},
            original_pages=before, candidate_files=after)
        if admission is None:
            if self.reserve_call() is not True:
                raise ExecutionError('G3 调用预算耗尽')
            return review(request, transport=self.reviewer, timeout=timeout)
        input_digest = digest(request)
        spec = {
            'invocation_id': 'executor-g3-' + digest({
                'operation_id': admission['operation_id'], 'input_digest': input_digest,
            }),
            'task_id': admission['task_id'], 'learning_task_id': admission['learning_task_id'],
            'run_id': admission['run_id'], 'operation_id': admission['operation_id'],
            'lease_generation': admission['created_generation'],
            'policy_digest': admission['policy_digest'], 'role': 'ExecutorG3',
            'kind': 'final_candidate_review', 'input_digest': input_digest,
            'requested_budget': {
                'requests': 1, 'pages': len(before) + len(after) + len(manifest['input_refs']),
                'input_bytes': len(canonical_json(request)), 'model_calls': 1,
                'active_seconds': float(self.review_timeout), 'repairs': 0, 'appeals': 0,
            },
        }
        opinion = self.invocation_port.invoke(
            spec, lambda: review(request, transport=self.reviewer, timeout=timeout), timeout,
        )
        if opinion.get('state') == 'unknown':
            raise ExecutionError('G3 调用结果 unknown，禁止接受')
        return opinion

    def _check(self, bundle, approval, packages, *, admission=None, run_review=True):
        self._validate_admission(bundle, admission)
        manifest, candidate, snapshot = (copy.deepcopy(bundle[k]) for k in ('manifest', 'candidate', 'snapshot'))
        for kind, value in [('manifest', manifest), ('candidate', candidate), ('dependency_snapshot', snapshot)]:
            validate(kind, value)
        # 保留原始路径分量供 CandidateView 拒绝重解析根，不能先 resolve 消掉证据。
        payload_root = Path(os.path.abspath(bundle['payload_root']))
        if (payload_root == self.journal_root or payload_root.is_relative_to(self.journal_root)
                or self.journal_root.is_relative_to(payload_root)):
            raise ExecutionError('payload 和私有 journal 不得重叠')
        if self.view_scope == 'knowledge_content':
            from ..evidence.content_view import ContentView
            view = ContentView(self.root, candidate, payload_root)
        else:
            view = CandidateView(self.root, candidate, payload_root, allow_deletes=True)
        from ..runtime.knowledge_ingest import is_knowledge
        if is_knowledge(admission):
            for change in candidate['changes']:
                if change['path'].startswith('raw/unprocessed/'):
                    old = raw_parts(self._read(change['path']))[0]
                    new = raw_parts(view.read_bytes(change['path']))[0]
                    if old.get('reviewed_at') != new.get('reviewed_at'):
                        raise ExecutionError('知识 ingest 不能签发用户 approve 的 reviewed_at')
        list(view.iter_paths())
        # 外部 snapshot 可以有额外 absent 前提，但不可遗漏任何实际读取。
        view.verify_dependencies(snapshot)
        semantic = requires_review(manifest, candidate, view) or 'G3' in manifest['required_gates']
        reports = run_gates(manifest, candidate, snapshot, view,
            validator_version=VALIDATOR_VERSION, review_prompt_version=PROMPT_VERSION)
        if any(r['result'] != 'pass' for r in reports if r['gate'] in ('G0', 'G1', 'G2')):
            raise ExecutionError('G0–G2 未通过: ' + str([(r['gate'], r['findings']) for r in reports if r['result'] != 'pass' and r['gate'] in ('G0', 'G1', 'G2')]))
        context = self._context(manifest, candidate, snapshot)
        # 只有受信 host 注入的固定重算器可认证机械派生；模型字段不参与决策。
        derived = (manifest['operation_type'] in {'index_rebuild', 'health', 'capture', 'import'} and
                   self.deterministic_check is not None and
                   self.deterministic_check(copy.deepcopy(context), view, packages) is True)
        self._quality(manifest, candidate, view, packages, context, derived=derived)
        if derived:
            semantic = False
        if manifest['operation_type'] in ('approve', 'rule_maintenance', 'tool_maintenance'):
            if self.approval_check is None or self.approval_check(copy.deepcopy(context), approval) is not True:
                raise ExecutionError('G4 缺少绑定当前操作与批次的可信用户批准')
        if semantic and run_review:
            opinion = self._review(manifest, candidate, snapshot, view, admission)
            if opinion['result'] != 'recommend_pass' or any(f['severity'] == 'blocking' for f in opinion['findings']):
                raise ExecutionError('G3 独立审查未通过: ' + opinion['result'])
        # 复核调用期间的更改、规则、目录清单及 payload；不使用 bundle.review/reports。
        view.verify_dependencies(snapshot)
        if digest(view.dependency_snapshot()) != manifest['dependencies_digest']:
            raise ExecutionError('检查产生未绑定依赖')
        self._authorize(manifest, candidate, snapshot, approval)
        trusted_reports = [r for r in reports if r['gate'] in ('G0', 'G1', 'G2')]
        for gate in (['G3'] if semantic and run_review else []) + ['G4']:
            trusted_reports.append(self._gate(manifest, gate))
        return manifest, candidate, snapshot, view, trusted_reports

    def _authorize(self, manifest, candidate, snapshot, approval):
        if manifest['operation_type'] in ('approve', 'rule_maintenance', 'tool_maintenance'):
            if self.approval_check is None or self.approval_check(self._context(manifest, candidate, snapshot), approval) is not True:
                raise ExecutionError('G4 最终可信用户批准已失效')

    def _listing(self, payload_root=None, *, scope='whole_root'):
        if scope == 'knowledge_content':
            from ..evidence.content_view import content_listing
            return content_listing(self.root)
        if scope != 'whole_root': raise ExecutionError('未知 WAL 内容范围')
        files, directories = set(), set()
        for parent, dirs, names in os.walk(self.root, followlinks=False):
            current = Path(parent)
            dirs[:] = [d for d in dirs if d not in CandidateView.EXCLUDED
                       and (payload_root is None or current / d != payload_root)]
            for name in [*dirs, *names]:
                relative = (current / name).relative_to(self.root).as_posix()
                _safe(self.root, relative)
                (directories if name in dirs else files).add(relative)
        return sorted(files), sorted(directories)

    def _gate(self, manifest, gate):
        return validate('gate_report', dict(contract_version='1.0',
            **{k: manifest[k] for k in BINDINGS}, gate=gate, result='pass',
            findings=[], producer='trusted-executor'))

    def _lookup_terminal(self, bundle, admission=None):
        manifest = validate('manifest', bundle['manifest'])
        operation_id = manifest['operation_id']
        path = self._journal(operation_id)
        if path.exists():
            previous = json.loads(path.read_bytes())
            if previous['manifest']['operation_id'] != operation_id:
                raise ExecutionError('journal 操作身份错误')
            if (previous['manifest'] != manifest or previous['candidate'] != bundle['candidate']
                    or previous['snapshot'] != bundle['snapshot']):
                raise ExecutionError('operation_id 已绑定不同候选')
            from ..runtime.knowledge_ingest import executor_admission_digest as admission_digest
            self._journal_scope(previous)
            private_digest = previous.get('admission_digest')
            expected_digest = admission_digest(admission) if admission is not None else None
            if private_digest != expected_digest:
                raise ExecutionError('operation_id 已绑定不同 Admission')
            if previous['state'] in ('applied', 'recovered'):
                self._clear_active(operation_id)
                return self._result(previous)
            raise ExecutionError('未完成操作必须先 recover')
        if self._active.exists():
            active = json.loads(self._active.read_bytes())
            if active.get('journal_root') != str(self.journal_root):
                raise ExecutionError('active journal_root 与已配置路径不一致')
            raise ExecutionError('存在未恢复批次，禁止叠加写入')
        return None

    def verify_execution(self, record, admission):
        """任何学习执行状态归并前都核对真实 WAL 与原 Admission。"""
        from ..runtime.protocol import admission_digest

        with self._lock():
            path = self._journal(record['operation_id'])
            if not path.exists():
                raise ExecutionError('执行结果归并缺少完整 Executor WAL')
            journal = json.loads(path.read_bytes())
            manifest = journal['manifest']
            if (journal['state'] != record['state']
                    or manifest['operation_id'] != record['operation_id']
                    or manifest['operation_id'] != admission['operation_id']
                    or journal.get('admission_digest') != admission_digest(admission)):
                raise ExecutionError('执行结果归并与真实 WAL／Admission 不匹配')
            for field in ('candidate_digest', 'dependencies_digest', 'rules_digest'):
                if manifest[field] != record[field] or record[field] != admission[field]:
                    raise ExecutionError('执行结果归并公共绑定与 WAL 不一致: ' + field)
            expected = self._result(journal)
            if (expected['state'] != record['state']
                    or expected['recovery_status'] != record['recovery_status']):
                raise ExecutionError('执行结果状态或 recovery_status 与真实 WAL 不一致')
            return True

    def verify_applied(self, record, admission):
        """保留 applied 专用入口；实际执行全状态 WAL 核验。"""
        if record['state'] != 'applied':
            raise ExecutionError('verify_applied 只接受 applied 结果')
        return self.verify_execution(record, admission)

    def verify_knowledge_execution(self, record, admission):
        from ..runtime.knowledge_ingest import parse_knowledge_admission, executor_admission_digest
        parse_knowledge_admission(admission)
        with self._lock():
            journal = json.loads(self._journal(admission['operation_id']).read_bytes())
            if (self._journal_scope(journal) != admission['view_scope']
                    or journal.get('admission_digest') != executor_admission_digest(admission)
                    or journal.get('knowledge_admission') != admission
                    or digest(journal['manifest']) != admission['manifest_digest']
                    or candidate_digest(journal['candidate']) != admission['candidate_digest']
                    or digest(journal['snapshot']) != admission['dependencies_digest']
                    or self._result(journal, errors=record['errors']) != record):
                raise ExecutionError('知识执行结果与真实 WAL／原准入不一致')
        return True

    @staticmethod
    def _journal_scope(journal):
        from ..runtime.knowledge_ingest import parse_knowledge_admission, executor_admission_digest
        scope = journal.get('view_scope', 'whole_root')
        admission = journal.get('knowledge_admission')
        if scope == 'whole_root' and admission is None: return scope
        if scope != 'knowledge_content' or admission is None:
            raise ExecutionError('WAL 内容范围或知识准入缺失')
        parse_knowledge_admission(admission)
        if (admission['view_scope'] != scope
                or executor_admission_digest(admission) != journal.get('admission_digest')
                or digest(journal['manifest']) != admission['manifest_digest']
                or candidate_digest(journal['candidate']) != admission['candidate_digest']
                or digest(journal['snapshot']) != admission['dependencies_digest']
                or any(not step['path'].startswith(('wiki/','raw/')) for step in journal['steps'])):
            raise ExecutionError('WAL 不对应原知识准入或包含范围外写入')
        changes = {c['path']:c for c in journal['candidate']['changes']}
        if len(journal['steps']) != len(changes) or {s['path'] for s in journal['steps']} != set(changes):
            raise ExecutionError('知识 WAL 的写入集与原候选不同')
        for step in journal['steps']:
            change = changes[step['path']]
            if (step['new_hash'] != change['sha256']
                    or step['old_hash'] != change['precondition'].get('sha256')):
                raise ExecutionError('知识 WAL 的写入版本与原候选不同')
        return scope

    def verify_maintenance(self, record, binding):
        """维护结果必须与原 operation 的 WAL 及规范执行结果完全一致。"""
        with self._lock():
            path = self._journal(record['operation_id'])
            if not path.exists():
                raise ExecutionError('维护归并缺少完整 Executor WAL')
            journal = json.loads(path.read_bytes())
            manifest = journal['manifest']
            if (journal['state'] != record['state']
                    or manifest['operation_id'] != record['operation_id']
                    or journal.get('admission_digest') is not None
                    or digest(manifest) != binding['manifest_digest']
                    or candidate_digest(journal['candidate']) != binding['candidate_digest']
                    or digest(journal['snapshot']) != binding['dependencies_digest']):
                raise ExecutionError('维护归并与真实 WAL／维护绑定不匹配')
            for field in ('candidate_digest', 'dependencies_digest', 'rules_digest'):
                if manifest[field] != record[field] or record[field] != binding[field]:
                    raise ExecutionError('维护归并公共绑定与 WAL 不一致: ' + field)
            expected = self._result(journal, errors=record['errors'])
            if record != expected:
                raise ExecutionError('维护归并记录与 WAL 规范执行结果不一致')
            return True

    def lookup_terminal(self, bundle, admission=None):
        """在短锁内查询原 operation 的完整 WAL；终态不触发动态检查。"""
        self._validate_admission(bundle, admission)
        with self._lock():
            return self._lookup_terminal(bundle, admission)

    def apply(self, bundle, *, admission=None, approval=None, source_packages=()):
        """业务写入前失败抛 ExecutionError；准备后失败返回 recovery_required。"""
        self._validate_admission(bundle, admission)
        from ..runtime.migration import _check_executor_apply

        with self._lock():
            terminal = self._lookup_terminal(bundle, admission)
            if terminal is not None:
                return terminal
            _check_executor_apply(
                self.root, self.journal_root, bundle,
                managed=self.acceptance_context is not None,
                drain_operation_id=getattr(self, '_legacy_drain_operation', None),
            )
        if admission is not None and self.acceptance_context is None:
            raise ExecutionError('受管 ingest 缺少 Runtime acceptance_context')
        _manifest, _candidate, _snapshot, _view, reviewed_reports = self._check(
            bundle, approval, tuple(source_packages), admission=admission,
        )
        with self._lock():
            terminal = self._lookup_terminal(bundle, admission)
            if terminal is not None:
                return terminal
            _check_executor_apply(
                self.root, self.journal_root, bundle,
                managed=self.acceptance_context is not None,
                drain_operation_id=getattr(self, '_legacy_drain_operation', None),
            )
            manifest, candidate, snapshot, view, final_reports = self._check(
                bundle, approval, tuple(source_packages), admission=admission, run_review=False,
            )
            by_gate = {r['gate']: r for r in [*reviewed_reports, *final_reports]}
            reports = [by_gate[gate] for gate in ('G0', 'G1', 'G2', 'G3', 'G4') if gate in by_gate]
            # raw 状态必须是 ingest 的最后写入，配套页面/索引/日志已成功。
            changes = sorted(candidate['changes'], key=lambda c: manifest['operation_type'] == 'ingest'
                             and c['path'].startswith('raw/unprocessed/'))
            steps, directories = [], set()
            def step(path, after):
                old = self._read(path)
                steps.append(dict(path=path, old=_encode(old), new=_encode(after),
                    old_hash=_hash(old), new_hash=_hash(after), status='pending'))
                parent = (self.root / path).parent
                while parent != self.root and not parent.exists():
                    directories.add(parent.relative_to(self.root).as_posix())
                    parent = parent.parent
            for change in changes:
                step(change['path'], None if change['action'] == 'delete' else view.read_bytes(change['path']))
                if change['action'] == 'move':
                    step(change['source'], None)
            view.verify_dependencies(snapshot)
            self._authorize(manifest, candidate, snapshot, approval)
            baseline_files, baseline_dirs = self._listing(view.payload_root, scope=self.view_scope)
            journal = dict(manifest=manifest, candidate=candidate, snapshot=snapshot, state='prepared',
                recovery_status='required', steps=steps, reports=reports,
                baseline_files=baseline_files, baseline_dirs=baseline_dirs,
                payload_root=str(view.payload_root), directories=sorted(directories, key=lambda s: s.count('/')))
            if admission is not None:
                from ..runtime.knowledge_ingest import (executor_admission_digest as admission_digest,
                                                       is_knowledge)
                journal['admission_digest'] = admission_digest(admission)
                if is_knowledge(admission):
                    journal['view_scope'] = self.view_scope
                    journal['knowledge_admission'] = copy.deepcopy(admission)
            context = (self.acceptance_context(admission)
                       if self.acceptance_context is not None else nullcontext())
            with context:
                self._hit('after_acceptance_before_prepare', -1)
                prepared = False
                try:
                    self._hit('before_prepare', -1)
                    _safe(self.journal_root.parent, self.journal_root.name)
                    self.journal_root.mkdir(parents=True, exist_ok=True)
                    if self.journal_root.stat().st_dev != self.root.stat().st_dev:
                        raise ExecutionError('journal 必须与正式库同卷以保留原子替换备份')
                    self._save(journal)
                    prepared = True
                    self._hit('after_prepare', -1)
                    self._hit('before_active', -1)
                    _atomic(self._active, canonical_json(dict(journal_root=str(self.journal_root), operation_id=manifest['operation_id'])))
                    self._hit('after_active', -1)
                    journal['state'] = 'applying'
                    self._save(journal)
                    self._hit('after_applying', -1)
                    for index, entry in enumerate(steps):
                        self._hit('before_intent', index)
                        self._assert_all(journal, recovery=False)
                        entry['status'] = 'inflight'
                        self._save(journal)
                        self._hit('after_intent', index)
                        self._assert_all(journal, recovery=False)
                        self._mutate(journal, entry, _decode(entry['new']), entry['old_hash'], index)
                        self._hit('after_write', index)
                        entry['status'] = 'done'
                        self._save(journal)
                        self._hit('after_done', index)
                    self._assert_all(journal, recovery=False)
                    if manifest['operation_type'] == 'approve':
                        olds = [c['source'].removesuffix('.md') for c in candidate['changes'] if c['action'] == 'move']
                        for file in (self.root / 'wiki').rglob('*'):
                            if file.is_file():
                                data = self._read(file.relative_to(self.root).as_posix())
                                if any(old.encode('utf-8') in data for old in olds):
                                    raise ExecutionError('G5 approve 旧路径残留: ' + str(file))
                    journal['reports'].append(self._gate(manifest, 'G5'))
                    journal['state'] = 'applied'
                    journal['recovery_status'] = 'not_needed'
                    self._save(journal)
                    self._hit('after_commit', -1)
                    self._active.unlink()
                    return self._result(journal)
                except Exception as exc:
                    if not prepared:
                        raise
                    # 已提交结果不得因清理/返回阶段中断回退为未提交。
                    if journal['state'] != 'applied':
                        journal['state'] = 'recovery_required' if self._active.exists() else 'prepared'
                        journal['recovery_status'] = 'required'
                    self._save(journal)
                    return self._result(journal, errors=[str(exc) or type(exc).__name__])

    def _assert_all(self, journal, *, recovery):
        scope = self._journal_scope(journal)
        touched = {s['path'] for s in journal['steps']}
        if not recovery:
            files, directories = self._listing(Path(journal['payload_root']), scope=scope)
            allowed_files = set(journal['baseline_files']) | touched
            expected_untouched = set(journal['baseline_files']) - touched
            if (set(files) - allowed_files or expected_untouched - set(files)
                    or set(directories) - (set(journal['baseline_dirs']) | set(journal['directories']))
                    or set(journal['baseline_dirs']) - set(directories)):
                raise ExecutionError('目录清单已改变')
            for entry in journal['snapshot']['files']:
                if entry['path'] in touched:
                    continue
                pre = entry['precondition']
                expected = pre.get('sha256') if pre['kind'] == 'hash' else None
                if _hash(self._read(entry['path'])) != expected:
                    raise ExecutionError('读取依赖已改变: ' + entry['path'])
        for entry in journal['steps']:
            for backup in entry.get('replacement_backups', []):
                target = _safe(self.journal_root, backup['ref'])
                if target.exists() and bytes_digest(target.read_bytes()) != backup['expected']:
                    raise ExecutionError('替换期间检测到并保留外部编辑: ' + backup['ref'])
            status = entry['status']
            allowed = ({entry['old_hash']} if status in ('pending', 'reverted') else
                       {entry['old_hash'], entry['new_hash']} if status == 'reverting' or recovery and status == 'inflight'
                       else {entry['old_hash']} if status == 'inflight' else {entry['new_hash']})
            if _hash(self._read(entry['path'])) not in allowed:
                raise ExecutionError('用户编辑/版本冲突: ' + entry['path'])

    def _mutate(self, journal, entry, data, expected, index):
        path = entry['path']
        if _hash(self._read(path)) != expected:
            raise ExecutionError('写前版本冲突: ' + path)
        target = _safe(self.root, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        backup = None
        try:
            if data is not None:
                temporary = str(target.parent / ('.executor-' + uuid.uuid4().hex + '.tmp'))
                entry.setdefault('temporary_files', []).append(dict(
                    path=Path(temporary).relative_to(self.root).as_posix(), sha256=bytes_digest(data)))
                self._save(journal)
                with open(temporary, 'xb') as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
            if expected is not None:
                ref = 'replaced-' + uuid.uuid4().hex + '.bin'
                backup = _safe(self.journal_root, ref)
                entry.setdefault('replacement_backups', []).append(dict(ref=ref, expected=expected))
                self._save(journal)  # 备份位置和预期字节先于原子替换持久化。
            self._hit('before_replace', index)
            _safe(self.root, path)
            _safe(self.journal_root.parent, self.journal_root.name)
            if expected is None:
                if data is not None:
                    # 独占安装：并发创建目标时直接失败，不覆盖其字节。
                    os.link(temporary, target)
            elif data is None:
                os.replace(target, backup)
            elif os.name == 'nt':
                import ctypes
                from ctypes import wintypes
                replace = ctypes.WinDLL('kernel32', use_last_error=True).ReplaceFileW
                replace.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                    wintypes.DWORD, wintypes.LPVOID, wintypes.LPVOID]
                replace.restype = wintypes.BOOL
                if not replace(str(target), temporary, str(backup), 0, None, None):
                    raise ctypes.WinError(ctypes.get_last_error())
            else:
                # 非 Windows 不宣称有原子 exchange；先保存实际被移走的版本，独占安装。
                os.replace(target, backup)
                os.link(temporary, target)
            self._hit('after_replace', index)
            if backup and backup.exists() and bytes_digest(backup.read_bytes()) != expected:
                raise ExecutionError('替换期间外部编辑已保留: ' + str(backup))
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)

    def recover(self, operation_id):
        """整批先查冲突，随后逆序回滚；重复调用无重复业务写入。"""
        with self._lock():
            journal = json.loads(self._journal(operation_id).read_bytes())
            self._journal_scope(journal)
            if journal['manifest']['operation_id'] != operation_id:
                raise ExecutionError('journal 操作身份错误')
            if journal['state'] in ('applied', 'recovered'):
                # 最终 journal 已落盘而 active 清除前崩溃，可安全清除本操作指针。
                self._clear_active(operation_id)
                return self._result(journal)
            for entry in journal['steps']:
                if _hash(_decode(entry['old'])) != entry['old_hash'] or _hash(_decode(entry['new'])) != entry['new_hash']:
                    raise ExecutionError('journal 备份校验失败')
            active = json.loads(self._active.read_bytes()) if self._active.exists() else None
            if active is None and journal['state'] == 'prepared' and all(s['status'] == 'pending' for s in journal['steps']):
                pass
            elif active != dict(journal_root=str(self.journal_root), operation_id=operation_id):
                raise ExecutionError('active journal 不匹配')
            try:
                # 真实进程退出可能留下已写完、尚未替换的临时文件；只清本操作持有的版本。
                cleanup = []
                for entry in journal['steps']:
                    for temporary in entry.get('temporary_files', []):
                        file = _safe(self.root, temporary['path'], allow_hardlink=True)
                        if file.exists():
                            if bytes_digest(file.read_bytes()) != temporary['sha256']:
                                raise ExecutionError('临时文件不完整或被修改: ' + temporary['path'])
                            info = file.stat()
                            if info.st_nlink != 1:
                                target = _safe(self.root, entry['path'], allow_hardlink=True)
                                other = target.stat() if target.exists() else None
                                if (info.st_nlink != 2 or other is None
                                        or (info.st_dev, info.st_ino) != (other.st_dev, other.st_ino)
                                        or bytes_digest(target.read_bytes()) != temporary['sha256']):
                                    raise ExecutionError('临时硬链接不属于本操作目标')
                            cleanup.append(file)
                for file in cleanup:
                    file.unlink()
                self._assert_all(journal, recovery=True)
                for index in reversed(range(len(journal['steps']))):
                    entry = journal['steps'][index]
                    if entry['status'] in ('pending', 'reverted'):
                        continue
                    self._hit('recover_before_intent', index)
                    self._assert_all(journal, recovery=True)
                    entry['status'] = 'reverting'
                    self._save(journal)
                    self._hit('recover_after_intent', index)
                    self._assert_all(journal, recovery=True)
                    current = _hash(self._read(entry['path']))
                    self._mutate(journal, entry, _decode(entry['old']), current, index)
                    self._hit('recover_after_write', index)
                    entry['status'] = 'reverted'
                    self._save(journal)
                    self._hit('recover_after_done', index)
                for directory in reversed(journal['directories']):
                    path = _safe(self.root, directory)
                    if path.is_dir() and not any(path.iterdir()):
                        path.rmdir()
                self._assert_all(journal, recovery=True)
                journal['state'] = 'recovered'
                journal['recovery_status'] = 'recovered'
                self._save(journal)
                self._clear_active(operation_id)
                return self._result(journal)
            except Exception as exc:
                journal['state'] = 'recovery_required'
                journal['recovery_status'] = (
                    'conflict' if isinstance(exc, ExecutionError) else 'required'
                )
                self._save(journal)
                return self._result(journal, errors=[str(exc) or type(exc).__name__])

    def _clear_active(self, operation_id):
        if self._active.exists():
            active = json.loads(self._active.read_bytes())
            if active == dict(journal_root=str(self.journal_root), operation_id=operation_id):
                self._active.unlink()
