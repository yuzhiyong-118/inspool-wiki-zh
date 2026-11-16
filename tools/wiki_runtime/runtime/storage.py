"""S1 的 SQLite 当前状态存储、不可变策略引用与一致性备份。"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import threading

from tools.wiki_runtime.contracts import (
    ContractError, bytes_digest, canonical_json, validate_path,
)


SCHEMA_VERSION = 1


class RuntimeStoreError(RuntimeError):
    pass


class SchemaVersionError(RuntimeStoreError):
    pass


class ArtifactReferenceError(RuntimeStoreError):
    pass


class BackupError(RuntimeStoreError):
    pass


_SCHEMA = """
CREATE TABLE policy_revisions (
    policy_digest TEXT PRIMARY KEY,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    record_json TEXT NOT NULL
);
CREATE TRIGGER policy_revisions_no_update
BEFORE UPDATE ON policy_revisions
BEGIN SELECT RAISE(ABORT, 'PolicyRevision is immutable'); END;
CREATE TRIGGER policy_revisions_no_delete
BEFORE DELETE ON policy_revisions
BEGIN SELECT RAISE(ABORT, 'PolicyRevision is immutable'); END;

CREATE TABLE tasks (
    task_id TEXT PRIMARY KEY,
    learning_task_id TEXT NOT NULL,
    current_policy_digest TEXT NOT NULL REFERENCES policy_revisions(policy_digest),
    record_json TEXT NOT NULL,
    concurrency_limit INTEGER NOT NULL CHECK (concurrency_limit >= 1),
    final_review_reserve_json TEXT NOT NULL
);
CREATE TABLE task_finance (
    task_id TEXT PRIMARY KEY REFERENCES tasks(task_id),
    budget_json TEXT NOT NULL,
    reserved_json TEXT NOT NULL,
    actual_json TEXT NOT NULL,
    blocked INTEGER NOT NULL DEFAULT 0 CHECK (blocked IN (0, 1)),
    block_reason TEXT
);
CREATE TABLE runs (
    run_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    learning_task_id TEXT NOT NULL,
    record_json TEXT NOT NULL,
    concurrency_limit INTEGER NOT NULL CHECK (concurrency_limit >= 1),
    final_review_reserve_json TEXT NOT NULL
);
CREATE TABLE run_finance (
    run_id TEXT PRIMARY KEY REFERENCES runs(run_id),
    budget_json TEXT NOT NULL,
    reserved_json TEXT NOT NULL,
    actual_json TEXT NOT NULL,
    blocked INTEGER NOT NULL DEFAULT 0 CHECK (blocked IN (0, 1)),
    block_reason TEXT
);
CREATE TABLE execution_ownerships (
    task_id TEXT PRIMARY KEY REFERENCES tasks(task_id),
    learning_task_id TEXT NOT NULL,
    owner TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation >= 1),
    expires_at REAL NOT NULL,
    record_json TEXT NOT NULL,
    UNIQUE (task_id, generation)
);
CREATE TABLE invocations (
    invocation_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    policy_digest TEXT NOT NULL REFERENCES policy_revisions(policy_digest),
    spec_digest TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    record_json TEXT NOT NULL,
    resource_state TEXT NOT NULL CHECK (
        resource_state IN ('not_started', 'inflight', 'draining', 'released')
    )
);
CREATE INDEX invocations_task_resources
ON invocations(task_id, resource_state);
CREATE INDEX invocations_run_resources
ON invocations(run_id, resource_state);
CREATE TABLE invocation_executions (
    invocation_id TEXT PRIMARY KEY REFERENCES invocations(invocation_id),
    execution_token TEXT NOT NULL UNIQUE,
    recovery_epoch INTEGER NOT NULL CHECK (recovery_epoch >= 1),
    send_state TEXT NOT NULL CHECK (send_state IN ('not_sent', 'sent')),
    result_state TEXT NOT NULL CHECK (result_state IN ('pending', 'succeeded', 'unknown'))
);
CREATE TABLE artifacts (
    artifact_digest TEXT PRIMARY KEY,
    relative_path TEXT NOT NULL UNIQUE,
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0)
);
CREATE TRIGGER artifacts_no_update
BEFORE UPDATE ON artifacts
BEGIN SELECT RAISE(ABORT, 'artifact is immutable'); END;
CREATE TRIGGER artifacts_no_delete
BEFORE DELETE ON artifacts
BEGIN SELECT RAISE(ABORT, 'referenced artifact is immutable'); END;
CREATE TABLE invocation_artifacts (
    invocation_id TEXT NOT NULL REFERENCES invocations(invocation_id),
    artifact_digest TEXT NOT NULL REFERENCES artifacts(artifact_digest),
    PRIMARY KEY (invocation_id, artifact_digest)
);
"""


def _json(record) -> str:
    return canonical_json(record).decode('utf-8')


def _load(value: str):
    return json.loads(value)


class RuntimeStore:
    def __init__(self, root, *, busy_timeout: float = 2.0):
        if type(busy_timeout) not in (int, float) or not 0 <= busy_timeout <= 60:
            raise ValueError('busy_timeout 必须在 0 到 60 秒之间')
        self.root = Path(root)
        self.learning_root = self.root / '.wiki-runtime' / 'learning'
        self.db_path = self.learning_root / 'runtime.db'
        self.artifact_root = self.learning_root / 'artifacts'
        self.busy_timeout = float(busy_timeout)
        self._local = threading.local()
        self._connections = set()
        self._connections_lock = threading.Lock()
        self._closed = False
        self.learning_root.mkdir(parents=True, exist_ok=True)
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        connection = self._new_connection()
        try:
            self._initialize(connection)
        finally:
            connection.close()

    def _new_connection(self) -> sqlite3.Connection:
        try:
            connection = sqlite3.connect(
                self.db_path, timeout=self.busy_timeout, isolation_level=None,
                check_same_thread=False,
            )
            connection.row_factory = sqlite3.Row
            connection.execute(f'PRAGMA busy_timeout={int(self.busy_timeout * 1000)}')
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('PRAGMA journal_mode=WAL')
            connection.execute('PRAGMA synchronous=FULL')
            return connection
        except sqlite3.Error as exc:
            raise RuntimeStoreError(f'SQLite 连接或 pragma 失败: {exc}') from exc

    def _connection(self) -> sqlite3.Connection:
        if self._closed:
            raise RuntimeStoreError('RuntimeStore 已关闭，拒绝迟到调用重新打开数据库')
        connection = getattr(self._local, 'connection', None)
        if connection is None:
            connection = self._new_connection()
            self._check_schema(connection)
            with self._connections_lock:
                if self._closed:
                    connection.close()
                    raise RuntimeStoreError('RuntimeStore 已关闭，拒绝新建连接')
                self._connections.add(connection)
            self._local.connection = connection
        return connection

    def close(self) -> None:
        with self._connections_lock:
            self._closed = True
            connections = list(self._connections)
            self._connections.clear()
        for connection in connections:
            connection.close()
        self._local.connection = None

    @staticmethod
    def _check_schema(connection: sqlite3.Connection) -> None:
        version = connection.execute('PRAGMA user_version').fetchone()[0]
        if version != SCHEMA_VERSION:
            raise SchemaVersionError(f'未知 runtime schema 版本: {version}')

    def _initialize(self, connection: sqlite3.Connection) -> None:
        try:
            connection.execute('BEGIN IMMEDIATE')
            version = connection.execute('PRAGMA user_version').fetchone()[0]
            if version == 0:
                tables = connection.execute(
                    "SELECT count(*) FROM sqlite_master WHERE type='table'"
                ).fetchone()[0]
                if tables:
                    raise SchemaVersionError('存在未标记版本的 runtime 数据库，拒绝重置')
                statement = ''
                for line in _SCHEMA.splitlines(keepends=True):
                    statement += line
                    if sqlite3.complete_statement(statement):
                        connection.execute(statement)
                        statement = ''
                if statement.strip():
                    raise RuntimeStoreError('schema v1 定义不完整')
                connection.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
            elif version != SCHEMA_VERSION:
                raise SchemaVersionError(f'未知 runtime schema 版本: {version}')
            self._check_schema(connection)
            connection.execute('COMMIT')
        except sqlite3.Error as exc:
            if connection.in_transaction:
                connection.execute('ROLLBACK')
            raise RuntimeStoreError(f'SQLite 初始化失败: {exc}') from exc
        except Exception:
            if connection.in_transaction:
                connection.execute('ROLLBACK')
            raise

    def read(self, query: str) -> list[dict]:
        if not isinstance(query, str) or not query.lstrip().lower().startswith(('select', 'with')):
            raise ValueError('read 只接受单条 SELECT/WITH 查询')
        if ';' in query.rstrip().rstrip(';'):
            raise ValueError('read 只接受单条查询')
        connection = self._connection()
        try:
            self._check_schema(connection)
            connection.execute('PRAGMA query_only=ON')
            try:
                return [dict(row) for row in connection.execute(query).fetchall()]
            finally:
                connection.execute('PRAGMA query_only=OFF')
        except SchemaVersionError:
            raise
        except sqlite3.Error as exc:
            raise RuntimeStoreError(f'SQLite 读取失败: {exc}') from exc

    def mutate(self, fn):
        connection = self._connection()
        try:
            self._check_schema(connection)
            connection.execute('BEGIN IMMEDIATE')
            self._check_schema(connection)
            result = fn(connection)
            connection.execute('COMMIT')
            return result
        except sqlite3.Error as exc:
            if connection.in_transaction:
                connection.execute('ROLLBACK')
            raise RuntimeStoreError(f'SQLite 写事务失败: {exc}') from exc
        except Exception:
            if connection.in_transaction:
                connection.execute('ROLLBACK')
            raise

    def publish_artifact(self, invocation_id: str, relative_path: str) -> str:
        validate_path(relative_path)
        path = self.artifact_root / relative_path
        try:
            resolved_root = self.artifact_root.resolve(strict=True)
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(resolved_root) or not resolved.is_file():
                raise ArtifactReferenceError('产物不是受控目录内的普通文件')
            payload = resolved.read_bytes()
        except (OSError, ValueError) as exc:
            raise ArtifactReferenceError(f'产物不可读取: {relative_path}') from exc
        artifact_digest = bytes_digest(payload)

        def publish(connection):
            invocation = connection.execute(
                'SELECT invocation_id FROM invocations WHERE invocation_id=?', (invocation_id,)
            ).fetchone()
            if invocation is None:
                raise ArtifactReferenceError('产物引用的 Invocation 不存在')
            existing = connection.execute(
                'SELECT relative_path, byte_size FROM artifacts WHERE artifact_digest=?',
                (artifact_digest,),
            ).fetchone()
            if existing is not None and (
                existing['relative_path'] != relative_path or existing['byte_size'] != len(payload)
            ):
                raise ArtifactReferenceError('相同摘要不得绑定不同产物引用')
            connection.execute(
                'INSERT OR IGNORE INTO artifacts VALUES (?, ?, ?)',
                (artifact_digest, relative_path, len(payload)),
            )
            connection.execute(
                'INSERT INTO invocation_artifacts VALUES (?, ?)',
                (invocation_id, artifact_digest),
            )
            return artifact_digest

        return self.mutate(publish)

    def backup(self, destination) -> dict:
        destination = Path(destination)
        if destination.exists():
            raise BackupError('备份目标必须不存在，拒绝覆盖')
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = self._connection()
        try:
            self._check_schema(source)
            with tempfile.TemporaryDirectory(
                prefix='.runtime-backup-', dir=destination.parent
            ) as temporary:
                work = Path(temporary) / 'package'
                work.mkdir()
                snapshot_path = Path(temporary) / 'runtime.db'
                snapshot = sqlite3.connect(snapshot_path, timeout=self.busy_timeout,
                                           isolation_level=None)
                snapshot.row_factory = sqlite3.Row
                try:
                    source.backup(snapshot)
                    snapshot.execute('PRAGMA foreign_keys=ON')
                    self._check_schema(snapshot)
                    references = snapshot.execute(
                        'SELECT a.artifact_digest, a.relative_path, a.byte_size '
                        'FROM artifacts a ORDER BY a.relative_path'
                    ).fetchall()
                finally:
                    snapshot.close()
                copied = []
                for reference in references:
                    relative_path = reference['relative_path']
                    validate_path(relative_path)
                    source_path = (self.artifact_root / relative_path).resolve(strict=True)
                    if not source_path.is_relative_to(self.artifact_root.resolve(strict=True)):
                        raise ArtifactReferenceError('备份产物路径越出受控目录')
                    payload = source_path.read_bytes()
                    if (len(payload) != reference['byte_size']
                            or bytes_digest(payload) != reference['artifact_digest']):
                        raise ArtifactReferenceError(f'产物缺失或摘要不匹配: {relative_path}')
                    target_path = work / 'artifacts' / relative_path
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    with target_path.open('xb') as output:
                        output.write(payload)
                    if bytes_digest(target_path.read_bytes()) != reference['artifact_digest']:
                        raise ArtifactReferenceError(f'备份产物复制校验失败: {relative_path}')
                    copied.append(relative_path)
                os.replace(snapshot_path, work / 'runtime.db')
                os.replace(work, destination)
            return {
                'database': str(destination / 'runtime.db'),
                'artifacts': copied,
            }
        except (OSError, sqlite3.Error, ContractError, RuntimeStoreError) as exc:
            if isinstance(exc, BackupError):
                raise
            raise BackupError(f'runtime 备份失败: {exc}') from exc
