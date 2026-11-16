"""创建不含个人资料的本地目录；不覆盖已有文件。"""
from datetime import date
from pathlib import Path
try:
    from tools.raw_index import render_queue
except ModuleNotFoundError:
    from raw_index import render_queue


def initialize(root):
    root = Path(root).resolve()
    today = date.today().isoformat()
    directories = ['raw/unprocessed', 'raw/processed', 'raw/assets',
                   'wiki/sources', 'wiki/entities', 'wiki/concepts',
                   'wiki/synthesis', 'wiki/meta']
    # Do not follow a user-provided directory link into another workspace.
    for relative in directories:
        current = root
        for part in Path(relative).parts:
            current = current / part
            if current.is_symlink() or (current.exists() and
                    getattr(current.stat(), 'st_file_attributes', 0) & 0x400):
                raise ValueError(f'拒绝链接目录: {relative}')
    for relative in directories:
        (root / relative).mkdir(parents=True, exist_ok=True)
    files = {
        'raw/index.md': '# 原始资料索引\n\n' + render_queue(root / 'raw') + '\n',
        'wiki/index.md': '# 知识索引\n\n- [[meta/overview]]：知识库概览与当前结论。\n',
        'wiki/log.md': f'# 维护日志\n\n## [{today}] init | 初始化空知识库\n\n'
                       '- 创建空索引与目录；未导入资料。\n',
        'wiki/meta/overview.md': f'---\ntype: meta\ntitle: 知识库概览\nstatus: active\n'
                                 f'updated: {today}\n---\n\n# 知识库概览\n\n'
                                 '## 综合结论\n\n尚无资料，待首次 ingest 后更新。\n',
    }
    created = []
    for relative, text in files.items():
        try:
            with (root / relative).open('x', encoding='utf-8', newline='\n') as file:
                file.write(text)
            created.append(relative)
        except FileExistsError:
            pass
    return created


if __name__ == '__main__':
    for name in initialize(Path(__file__).resolve().parents[1]):
        print('创建:', name)
