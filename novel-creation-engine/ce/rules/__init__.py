# -*- coding: utf-8 -*-
"""rules —— 把总纲 V2.0 的判据变成可执行检查。

**唯一依据**：作者自建的小说写作规范文档（总纲），每一节的编号（§23 / §24 / §25）
与规范文档的章节号一一对应。本项目不内置规范正文——它属于作者的作品资产，不属于工具。

| 模块 | 覆盖 | 对应总纲 |
|---|---|---|
| `forbidden.py` | 八条一级禁则（红线） | §23 |
| `ironclad.py`  | 写作铁律 + 章节四层判定 | §24 / §25 |

设计约定：
  · 每个检查产出 `Hit`（依据 / 命中 / 位置 / 建议 / 置信度），不做布尔判断。
  · 命中的定位是**人工复核线索**，不是自动拦截。总纲判据本身含大量主观项
    （"这段有戏剧作用吗？"），凡机器给不出确定答案的，一律标 `confidence="low"`
    并在建议里写明"需人读"。
  · 判据只读正文，不读设定；需要设定交叉的检查统一走 `ce.review` 的设定闸。
"""

from .hit import Hit, Severity  # noqa: F401
from . import forbidden, ironclad  # noqa: F401

ALL_RULES = {
    "§23": ("一级禁则（红线）", forbidden.CHECKS),
    "§24": ("写作铁律", ironclad.IRONCLAD_CHECKS),
    "§25": ("章节四层判定", ironclad.GATE_CHECKS),
}


def run(text, chapter_no=None, rules=None):
    """对一段正文跑判据。

    参数：
        text       —— 章正文（纯文本）
        chapter_no —— 章号（int 或 None）。部分判据只在第 1 章生效（群像开场）。
        rules      —— 要跑的判据集，如 ["§23","§24","§25"]；None 表示全跑。

    返回：Hit 列表（已按位置排序）。
    """
    want = set(rules) if rules else set(ALL_RULES)
    hits = []
    for key, (_, checks) in ALL_RULES.items():
        if key not in want:
            continue
        for check in checks:
            hits.extend(check(text, chapter_no=chapter_no))
    return sorted(hits, key=lambda h: (h.line, h.rule_id))
