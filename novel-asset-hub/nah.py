#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel-asset-hub 启动器（零安装）。

用法：
    python nah.py --help
    python nah.py --ws 我的小说 scan ../processed/raw/ep_090.md
    python nah.py init "/path/to/新小说/设定资产" --name 新小说
    python -m nah ...          # 等价写法
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nah.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
