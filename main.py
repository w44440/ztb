#!/usr/bin/env -S uv run --python 3.12
# import sys
# from pathlib import Path

# 保留这个是为了防止直接运行 python main.py 时找不到 src
# sys.path.insert(0, str(Path(__file__).parent))
# 关键：把 app 导入到顶层
from ztb_fetcher.cli import app

# 这样 [project.scripts] 里的 main:app 就能找到了
if __name__ == "__main__":
    app()
