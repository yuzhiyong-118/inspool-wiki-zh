"""固定身份的 JSON 数据入口；不是本机进程/Windows 用户沙箱。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

from ..isolation.gateway import Gateway, PermissionDenied, TOOLS

BACKEND_VERSION = '1.0'
MAX_LINE_BYTES = 2 * 1024 * 1024
MAX_DEPTH = 24
MAX_NODES = 20000


def _data(value, depth=0, budget=None):
    if budget is None:
        budget = [MAX_NODES]
    budget[0] -= 1
    if depth > MAX_DEPTH or budget[0] < 0:
        raise ValueError('limits')
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError('key')
            _data(item, depth + 1, budget)
    elif type(value) is list:
        for item in value:
            _data(item, depth + 1, budget)
    elif type(value) not in (str, int, float, bool, type(None)):
        raise ValueError('type')
    elif type(value) is float and (value != value or abs(value) == float('inf')):
        raise ValueError('finite')


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate')
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError('constant')


def parse_json(raw):
    if len(raw) > MAX_LINE_BYTES:
        raise ValueError('size')
    # Bound nesting before the JSON parser allocates recursive containers.
    depth = 0
    quoted = escaped = False
    for char in raw.decode('utf-8') if type(raw) is bytes else raw:
        if quoted:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in '[{':
            depth += 1
            if depth > MAX_DEPTH:
                raise ValueError('depth')
        elif char in ']}':
            depth -= 1
    value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_reject_constant)
    _data(value)
    return value


def _error(code):
    # Never reflect filesystem errors, model input, bootstrap paths or credentials.
    return {'ok': False, 'error': {'code': code}}


_PARAMETERS = {
    'read': {'scope': {'type': 'string'}, 'path': {'type': 'string'}},
    'candidate_write': {'path': {'type': 'string'}, 'text': {'type': 'string'}},
    'request_task': {'target': {'type': 'string', 'enum': ['worker', 'reviewer', 'auditor']},
                     'task': {'type': 'string'}},
}


class RoleBackend:
    def __init__(self, formal_root, *, role, read_scopes=None, candidate_root=None,
                 protected_roots=()):
        gateway = Gateway(formal_root, protected_roots=protected_roots)
        self.__call = gateway.bind(role, read_scopes=read_scopes,
                                   candidate_root=candidate_root)
        self.__role = role

    def catalog(self):
        return [{'name': name, 'parameters': {'type': 'object',
                 'properties': json.loads(json.dumps(_PARAMETERS[name])),
                 'required': list(_PARAMETERS[name]), 'additionalProperties': False}}
                for name in sorted(TOOLS[self.__role])]

    def descriptor(self):
        return {'backend_version': BACKEND_VERSION,
                'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'role': self.__role, 'catalog': self.catalog(),
                'boundary': 'fixed-role-json-data-channel',
                'os_isolation_verified': False, 'desktop_session_restricted': False}

    def invoke(self, tool, arguments):
        try:
            _data(arguments)
            if len(json.dumps(arguments, ensure_ascii=False).encode('utf-8')) > MAX_LINE_BYTES:
                return _error('invalid_request')
            return {'ok': True, 'result': self.__call(tool, arguments)}
        except PermissionDenied:
            return _error('denied')
        except (ValueError, TypeError, UnicodeError, RecursionError):
            return _error('invalid_request')
        except OSError:
            return _error('unavailable')

    def request(self, value):
        if type(value) is not dict or set(value) != {'tool', 'arguments'}:
            return _error('invalid_request')
        return self.invoke(value['tool'], value['arguments'])


def _bootstrap(raw):
    value = parse_json(raw)
    allowed = {'formal_root', 'role', 'read_scopes', 'candidate_root', 'protected_roots'}
    if type(value) is not dict or not {'formal_root', 'role'} <= set(value) or set(value) - allowed:
        raise ValueError('bootstrap')
    if type(value['formal_root']) is not str or type(value['role']) is not str:
        raise ValueError('bootstrap')
    if 'candidate_root' in value and value['candidate_root'] is not None and type(value['candidate_root']) is not str:
        raise ValueError('bootstrap')
    if 'read_scopes' in value and (type(value['read_scopes']) is not dict or
            any(type(v) is not str for v in value['read_scopes'].values())):
        raise ValueError('bootstrap')
    if 'protected_roots' in value and (type(value['protected_roots']) is not list or
            any(type(v) is not str for v in value['protected_roots'])):
        raise ValueError('bootstrap')
    return RoleBackend(**value)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bootstrap', required=True)
    parser.add_argument('--describe', action='store_true')
    options = parser.parse_args(argv)
    try:
        backend = _bootstrap(options.bootstrap)
    except (ValueError, TypeError, OSError, RecursionError):
        sys.stdout.write(json.dumps(_error('invalid_bootstrap')) + '\n')
        return 2
    if options.describe:
        sys.stdout.write(json.dumps(backend.descriptor()) + '\n')
        return 0
    stream = sys.stdin.buffer
    while True:
        raw = stream.readline(MAX_LINE_BYTES + 1)
        if not raw:
            break
        if len(raw) > MAX_LINE_BYTES:
            # End the channel rather than processing a tail as a new request.
            response = _error('invalid_request')
            sys.stdout.write(json.dumps(response) + '\n')
            sys.stdout.flush()
            return 2
        try:
            response = backend.request(parse_json(raw))
        except (ValueError, TypeError, UnicodeError, RecursionError):
            response = _error('invalid_request')
        sys.stdout.write(json.dumps(response, ensure_ascii=True, allow_nan=False) + '\n')
        sys.stdout.flush()
    return 0


def probe_backend():
    """可信父进程创建临时树，真实 JSONL 子进程执行探针并核对受保护字节。"""
    import os
    import subprocess
    import tempfile

    reports = []
    with tempfile.TemporaryDirectory(prefix='wiki-json-probe-') as temporary:
        root = Path(temporary)
        formal, private, candidate = (root / name for name in ('formal', 'private', 'candidate'))
        for directory in (formal, private, candidate):
            directory.mkdir()
        (formal / 'page.md').write_bytes(b'formal-original')
        (formal / 'checker.py').write_bytes(b'checker-original')
        (private / 'journal.json').write_bytes(b'private-original')
        os.link(formal / 'checker.py', candidate / 'hard.md')
        os.link(private / 'journal.json', formal / 'hard.md')
        link_kind = 'symlink'
        try:
            (candidate / 'escape').symlink_to(private, target_is_directory=True)
            (formal / 'escape').symlink_to(private, target_is_directory=True)
        except OSError:
            if os.name != 'nt':
                raise
            link_kind = 'junction'
            for parent in (candidate, formal):
                creation = subprocess.run(['cmd', '/c', 'mklink', '/J', str(parent / 'escape'), str(private)],
                                          capture_output=True, timeout=10)
                if creation.returncode:
                    raise RuntimeError('probe link fixture unavailable')
        before = {path: path.read_bytes() for directory in (formal, private)
                  for path in directory.iterdir() if path.is_file()}

        def frame(tool, arguments):
            return {'tool': tool, 'arguments': arguments}

        for role in sorted(TOOLS):
            config = {'formal_root': str(formal), 'role': role,
                      'protected_roots': [str(private)]}
            if role == 'worker':
                config['candidate_root'] = str(candidate)
            if role != 'coordinator':
                config['read_scopes'] = {'wiki': str(formal)}
            positive = (frame('request_task', {'target': 'worker', 'task': '__import__("os").system("ignored")'})
                        if role == 'coordinator' else frame('read', {'scope': 'wiki', 'path': 'page.md'}))
            cases = [('positive', positive, True)]
            if role == 'worker':
                cases.append(('candidate_write', frame('candidate_write', {'path': 'draft.md',
                             'text': '__import__("os").system("ignored")'}), True))
            else:
                cases.append(('candidate_write', frame('candidate_write', {'path': 'draft.md', 'text': 'attack'}), False))
            for tool in ('shell', 'exec_command', 'write_file', 'apply_patch', 'approve', 'Executor',
                         'journal_write', 'bind', 'register_callback', 'import_module'):
                cases.append((tool, frame(tool, {'path': str(formal / 'page.md'), 'text': 'attack'}), False))
            cases += [('role_forgery', {**positive, 'role': 'worker'}, False),
                      ('session_forgery', {**positive, 'session': 'trusted'}, False),
                      ('argument_forgery', frame('read', {'scope': 'wiki', 'path': 'page.md', 'role': 'worker'}), False)]
            for path in ('../private/journal.json', str(private / 'journal.json'), 'hard.md', 'escape/journal.json'):
                cases.append(('read_escape', frame('read', {'scope': 'wiki', 'path': path}), False))
                cases.append(('write_escape', frame('candidate_write', {'path': path, 'text': 'attack'}), False))
            wire = [json.dumps(value).encode() for _, value, _ in cases]
            wire += [b'{"tool":"read","tool":"shell","arguments":{}}',
                     b'{"tool":"read","arguments":{"x":NaN}}', b'{bad',
                     ('[' * (MAX_DEPTH + 1) + '0' + ']' * (MAX_DEPTH + 1)).encode()]
            process = subprocess.run([sys.executable, '-B', '-m', 'tools.wiki_runtime.host.backend',
                                     '--bootstrap', json.dumps(config)],
                                     input=b'\n'.join(wire) + b'\n', capture_output=True,
                                     cwd=Path(__file__).resolve().parents[3], timeout=30)
            description = subprocess.run([sys.executable, '-B', '-m', 'tools.wiki_runtime.host.backend',
                                          '--bootstrap', json.dumps(config), '--describe'],
                                         capture_output=True, cwd=Path(__file__).resolve().parents[3], timeout=30)
            descriptor = json.loads(description.stdout)
            responses = [json.loads(line) for line in process.stdout.splitlines()]
            passed = (process.returncode == 0 and description.returncode == 0 and not process.stderr
                      and descriptor['role'] == role
                      and {entry['name'] for entry in descriptor['catalog']} == TOOLS[role]
                      and len(responses) == len(wire)
                      and all(answer.get('ok') is expected for answer, (_, _, expected) in zip(responses, cases))
                      and all(answer.get('ok') is False for answer in responses[len(cases):]))
            reports.append({'role': role, 'passed': passed, 'request_count': len(wire),
                            'returncode': process.returncode, 'descriptor': descriptor,
                            'checks': [{'name': name, 'expected_ok': expected,
                                        'actual_ok': response.get('ok'),
                                        'error_code': response.get('error', {}).get('code')}
                                       for (name, _, expected), response in zip(cases, responses)],
                            'malformed_frames_rejected': all(answer.get('ok') is False
                                                             for answer in responses[len(cases):])})
        after = {path: path.read_bytes() for directory in (formal, private)
                 for path in directory.iterdir() if path.is_file()}
        unchanged = before == after
        candidate_ok = (candidate / 'draft.md').read_text() == '__import__("os").system("ignored")'
        return {'backend_version': BACKEND_VERSION, 'boundary': 'actual-jsonl-subprocess-only',
                'passed': all(item['passed'] for item in reports) and unchanged and candidate_ok,
                'protected_bytes_unchanged': unchanged, 'candidate_literal_bytes_preserved': candidate_ok,
                'link_fixture': link_kind, 'roles': reports,
                'os_isolation_verified': False, 'desktop_session_restricted': False}


if __name__ == '__main__':
    raise SystemExit(main())
