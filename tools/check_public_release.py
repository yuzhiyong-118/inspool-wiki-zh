"""只读检查公开 Git 暂存树；白名单之外的文件默认拒绝。"""
import argparse
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = ('raw/', 'wiki/', 'data/', 'lessons/', 'docs/learning/',
             'docs/design/evidence/', 'references/', 'reference/',
             '.wiki-runtime/', '.learning-', '.tmp/', '.obsidian/', '.codex/',
             'tools/tests/fixtures/learning_book_i3/',
             'tools/tests/fixtures/learning_book_i4/')
SECRETS = re.compile(r'(?:sk-[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{24,}|'
                     r'-----BEGIN [A-Z ]*PRIVATE KEY-----|'
                     r'https?://[^\s/:]+:[^\s/@]+@(?!example\.))')


def path_error(name, allowed):
    parts = PurePosixPath(name).parts
    if name.startswith(FORBIDDEN) or '..' in parts:
        return '私人目录或非法路径'
    if any(p in {'__pycache__', 'node_modules', '.git'} for p in parts):
        return '缓存或嵌套仓库'
    if name.startswith('.claude/settings') or '.local.' in name or name.endswith(
            ('.sqlite', '.sqlite3', '.db', '.pem', '.key', '.pyc')):
        return '本机配置或运行文件'
    if name not in allowed:
        return '未登记到公开文件白名单'
    return None


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])


def check():
    # Read both the allowlist and file content from the index, not the worktree.
    allowed = set(json.loads(git('show', ':public-files.json'))['files'])
    entries = git('ls-files', '--stage', '-z').decode('utf-8').split('\0')
    errors = []
    count = 0
    for entry in filter(None, entries):
        info, name = entry.split('\t', 1)
        mode, oid, stage = info.split()
        count += 1
        reason = path_error(name, allowed)
        if mode not in {'100644', '100755'} or stage != '0':
            reason = '链接、子模块或未解决合并'
        if reason:
            errors.append(f'{name}: {reason}')
            continue
        text = git('cat-file', 'blob', oid).decode('utf-8-sig', errors='replace')
        if SECRETS.search(text):
            errors.append(f'{name}: 疑似凭据（不输出值）')
    return count, errors


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--staged', action='store_true', help='检查完整暂存树（默认行为）')
    parser.parse_args()
    try:
        count, errors = check()
    except (subprocess.CalledProcessError, ValueError, KeyError) as exc:
        print(f'公开检查失败: {type(exc).__name__}')
        raise SystemExit(1)
    for error in errors:
        print(error)
    print(f'检查 {count} 个公开文件，发现 {len(errors)} 项问题。')
    raise SystemExit(bool(errors))
