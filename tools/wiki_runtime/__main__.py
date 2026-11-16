"""通过 python -m wiki_runtime 启动公共命令入口。"""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
