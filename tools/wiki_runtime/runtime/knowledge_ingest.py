"""非教学知识准入；共享 Runtime 任务与预算，不创建学习状态或 Readiness。"""
from __future__ import annotations

from contextlib import contextmanager
import copy

from ..contracts import digest, validate
from .protocol import _record, _text, _hash, _integer, parse_admission
from .storage import _json, _load


SCHEMA = 'knowledge-ingest-admission/1'
FIELDS = ('schema', 'task_id', 'learning_task_id', 'run_id', 'operation_id', 'workflow_id',
    'policy_digest', 'submission_epoch', 'created_generation', 'manifest_digest',
    'candidate_digest', 'dependencies_digest', 'rules_digest', 'mapping_digest',
    'preparation_digest', 'authorization_digest', 'view_scope')


def is_knowledge(value):
    return isinstance(value, dict) and value.get('schema') == SCHEMA


def parse_knowledge_admission(record):
    _record(record, FIELDS, 'KnowledgeIngestAdmission')
    if record['schema'] != SCHEMA or record['view_scope'] != 'knowledge_content':
        raise ValueError('未知知识准入类型或内容范围')
    for k in ('task_id', 'learning_task_id', 'run_id', 'operation_id', 'workflow_id'):
        _text(record[k], 'KnowledgeIngestAdmission.' + k)
    for k in FIELDS:
        if k.endswith('_digest'): _hash(record[k], 'KnowledgeIngestAdmission.' + k)
    for k in ('submission_epoch', 'created_generation'):
        _integer(record[k], 'KnowledgeIngestAdmission.' + k, 1)
    return record


def parse_executor_admission(value):
    return parse_knowledge_admission(value) if is_knowledge(value) else parse_admission(value)


def executor_admission_digest(value):
    return digest(parse_executor_admission(value))


def initialize(runtime):
    # 沿用 RuntimeService 的可选领域表扩展方式；不改变既有记录或核心 schema。
    statements = (
        'CREATE TABLE IF NOT EXISTS knowledge_ingest_admissions ('
        'operation_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id), '
        'binding_digest TEXT NOT NULL, record_json TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0)',
        'CREATE TRIGGER IF NOT EXISTS knowledge_ingest_no_rebind '
        'BEFORE UPDATE OF binding_digest, record_json ON knowledge_ingest_admissions '
        "BEGIN SELECT RAISE(ABORT, 'knowledge ingest admission is immutable'); END",
        'CREATE TABLE IF NOT EXISTS knowledge_ingest_results ('
        'operation_id TEXT PRIMARY KEY REFERENCES knowledge_ingest_admissions(operation_id), '
        'record_json TEXT NOT NULL)',
    )
    def create(c):
        for statement in statements: c.execute(statement)
    runtime.store.mutate(create)


def load(runtime, operation_id):
    initialize(runtime)
    def read(c):
        row = c.execute('SELECT record_json FROM knowledge_ingest_admissions WHERE operation_id=?',
                        (operation_id,)).fetchone()
        return copy.deepcopy(parse_knowledge_admission(_load(row[0]))) if row else None
    return runtime.store.mutate(read)


def reject_cross_type(connection, operation_id):
    if (connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='knowledge_ingest_admissions'").fetchone()
            and connection.execute('SELECT 1 FROM knowledge_ingest_admissions WHERE operation_id=?',
                                   (operation_id,)).fetchone()):
        raise ValueError('知识入库 operation 不得改绑学习或维护准入')


def _bound(c, admission):
    parse_knowledge_admission(admission)
    row = c.execute('SELECT * FROM knowledge_ingest_admissions WHERE operation_id=?',
                    (admission['operation_id'],)).fetchone()
    if row is None or row['binding_digest'] != digest(admission) or _load(row['record_json']) != admission:
        raise ValueError('知识准入缺少原始不可变 Runtime 绑定')
    return row


def _current(runtime, c, admission):
    row = _bound(c, admission)
    if row['revoked']: raise ValueError('知识准入已撤销')
    return runtime._submission_context(c, admission)


def check_current(runtime, admission):
    return runtime.store.mutate(lambda c: _current(runtime,c,admission))


def bind(runtime, admission):
    initialize(runtime)
    admission = copy.deepcopy(parse_knowledge_admission(admission))
    def insert(c):
        for table in ('maintenance_bindings', 'operation_admissions'):
            if c.execute('SELECT 1 FROM ' + table + ' WHERE operation_id=?',
                         (admission['operation_id'],)).fetchone():
                raise ValueError('operation 已属于其他类型准入')
        row = c.execute('SELECT 1 FROM knowledge_ingest_admissions WHERE operation_id=?',
                        (admission['operation_id'],)).fetchone()
        if row:
            _current(runtime, c, admission)
            return admission
        runtime._submission_context(c, admission)
        if c.execute('SELECT 1 FROM learning_states WHERE task_id=?',
                     (admission['task_id'],)).fetchone():
            raise ValueError('学习任务不能转换为非教学知识准入')
        c.execute('INSERT INTO knowledge_ingest_admissions VALUES (?,?,?,?,0)',
                  (admission['operation_id'], admission['task_id'], digest(admission), _json(admission)))
        return admission
    return runtime.store.mutate(insert)


@contextmanager
def acceptance(runtime, admission, recheck):
    c = runtime.store._connection()
    try:
        runtime.store._check_schema(c)
        c.execute('BEGIN IMMEDIATE')
        context = _current(runtime, c, admission)
        # 外部原件、K2、scope 也须在接受锁/Runtime 事务内最后重检。
        recheck()
        yield context
        c.execute('COMMIT')
    except BaseException:
        if c.in_transaction: c.execute('ROLLBACK')
        raise


def revoke(runtime, admission):
    with runtime._barrier():
        def update(c):
            _bound(c, admission)
            c.execute('UPDATE knowledge_ingest_admissions SET revoked=1 WHERE operation_id=?',
                      (admission['operation_id'],))
        runtime.store.mutate(update)
    return {'status':'revoked', 'applied':False, 'operation_id':admission['operation_id']}


def reconcile(runtime, admission, result):
    validate('execution_result', result)
    if runtime.executor is None: raise ValueError('知识执行结果缺少真实 WAL 核验器')
    runtime.executor.verify_knowledge_execution(result, admission)
    def update(c):
        _bound(c, admission)
        row = c.execute('SELECT record_json FROM knowledge_ingest_results WHERE operation_id=?',
                        (admission['operation_id'],)).fetchone()
        if row:
            old = _load(row[0])
            if old['state'] in ('applied','recovered'):
                if {k:v for k,v in old.items() if k!='errors'} != {k:v for k,v in result.items() if k!='errors'}:
                    raise ValueError('知识执行终态不得覆盖')
                return {'state':old['state'],'applied':old['state']=='applied','execution':old}
            if old['recovery_status'] == 'conflict' and old != result:
                raise ValueError('知识恢复冲突需要人工对账')
        c.execute('INSERT INTO knowledge_ingest_results VALUES (?,?) '
                  'ON CONFLICT(operation_id) DO UPDATE SET record_json=excluded.record_json',
                  (admission['operation_id'], _json(result)))
        if result['state'] in ('applied','recovered') or result['recovery_status']=='conflict':
            task = runtime._task(c, admission['task_id'])
            state = 'completed' if result['state']=='applied' else 'blocked'
            if task['state'] != state:
                task['state'] = state; task['revision'] += 1
                runtime._save_task(c, task)
                run = c.execute('SELECT record_json FROM runs WHERE run_id=?',(admission['run_id'],)).fetchone()
                data = _load(run[0]); data['state'] = state
                c.execute('UPDATE runs SET record_json=? WHERE run_id=?',(_json(data),admission['run_id']))
        return {'state':result['state'], 'applied':result['state']=='applied', 'execution':copy.deepcopy(result)}
    return runtime.store.mutate(update)
