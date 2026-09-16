#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ce.py —— novel-creation-engine 零安装入口（只依赖 Python 标准库）。

用法：
    python ce.py review <章.md>            # 判据裁决，出报告
    python ce.py review <目录>              # 批量
    python ce.py brief <名字…>             # 拼装上下文（第二步）
    python ce.py commit <章.md>            # 落正文并触发审计（第二步）

设计依据：novel-asset-hub/docs/creation-layer.md
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ce.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
