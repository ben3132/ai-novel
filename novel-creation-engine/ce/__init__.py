# -*- coding: utf-8 -*-
"""novel-creation-engine —— L3 创作层。

定位：**不建库、不存事实、不做检索**。只做三件事——
  1. 按正确时序调外部命令（nah / nms / xs，全部子进程只读）
  2. 把总纲 V2.0 的判据（§23 禁则 / §24 铁律 / §25 四层判定）变成可执行检查
  3. 产出「依据 → 命中 → 建议」三段式的可回查报告

边界铁律：对 nah/nms/xs 只有读权限；唯一写出口是 L4 的正文 .md。
详见 novel-asset-hub/docs/creation-layer.md
"""

__version__ = "0.1.0"
