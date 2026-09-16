# -*- coding: utf-8 -*-
"""hit.py —— 判据命中的统一数据结构。

报告的三段式（依据 → 命中 → 建议）由 `Hit` 直接承载，
不允许各检查自己拼字符串——否则报告格式一定会散。
"""
from dataclasses import dataclass, field


class Severity:
    """命中等级。只影响报告里的排序与分组，不影响是否阻断。"""

    RED = "红线"       # §23：总纲明令禁止，命中即需改
    RULE = "铁律"      # §24：写作方法要求
    GATE = "闸门"      # §25：写完必过的问题，多为"需人读"
    NOTE = "提示"      # 机器只能给线索，无法定性


def _clip(s, n=60):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[:n] + "…"


@dataclass
class Hit:
    rule_id: str          # 如 "§23-1"
    rule_name: str        # 如 "禁止「不是A——是B」句式"
    severity: str         # Severity.*
    line: int             # 行号（1-based）
    snippet: str          # 命中的原文片段
    basis: str            # 【依据】总纲原文/条目
    advice: str           # 【建议】怎么改
    confidence: str = "low"   # high / mid / low —— 启发式必诚实标注
    context: str = ""     # 上下文（前后句），便于人工复核

    # ---------------------------------------------------------------- 渲染
    def as_dict(self):
        return {
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "severity": self.severity,
            "line": self.line,
            "snippet": self.snippet,
            "basis": self.basis,
            "advice": self.advice,
            "confidence": self.confidence,
            "context": self.context,
        }

    def render(self, idx=None):
        """渲染为报告里的一个条目（三段式）。"""
        head = f"**[{self.rule_id}] {self.rule_name}**"
        if idx is not None:
            head = f"`{idx}` " + head
        tag = f"`{self.severity}` · 置信度 `{self.confidence}` · L{self.line}"
        out = [f"{head}　{tag}"]
        out.append(f"  - 依据：{self.basis}")
        out.append(f"  - 命中：`{_clip(self.snippet, 80)}`")
        if self.context:
            out.append(f"  - 上下文：{_clip(self.context, 120)}")
        out.append(f"  - 建议：{self.advice}")
        return "\n".join(out)
