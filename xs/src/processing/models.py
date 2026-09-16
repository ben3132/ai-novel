"""处理层数据模型。

信源等级语义沿用采集层且不可在处理时提升：
1=L1 官方一手源；11=L1-derived 第三方转录；2=权威粉丝 Wiki；
3=二次整理社区；4=低可信来源（只可检索，禁止参与设定推理）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class TextUnit(BaseModel):
    """从一条 RawRecord 派生的可定位文本单元。"""

    unit_id: str
    source_id: str
    parent_unit_id: Optional[str] = None
    trust_level: Literal[1, 2, 3, 4, 11]
    source_type: str
    ip_domain: str
    url: str
    unit_type: Literal["chapter", "paragraph", "html_block", "subtitle_cue"]
    sequence_no: int
    text: str
    content_sha256: str
    # text_start/text_end 位于本记录生成的 derived_text 坐标空间。
    text_start: int
    text_end: int
    # 对 HTML 是覆盖该文本的原始 HTML 范围；纯文本/字幕则是 raw_content 范围。
    raw_start: Optional[int] = None
    raw_end: Optional[int] = None
    extra_meta: Dict[str, Any] = Field(default_factory=dict)


class WindowUnitSpan(BaseModel):
    """证据单元在模型窗口中的精确字符范围。"""

    unit_id: str
    window_start: int
    window_end: int
    source_raw_start: Optional[int] = None
    source_raw_end: Optional[int] = None


class ContextWindow(BaseModel):
    """只在同一来源、同一章节内组合的模型上下文窗口。"""

    window_id: str
    source_id: str
    trust_level: Literal[1, 2, 3, 4, 11]
    source_type: str
    ip_domain: str
    url: str
    chapter_index: Optional[int] = None
    chapter_title: Optional[str] = None
    sequence_no: int
    text: str
    content_sha256: str
    unit_ids: List[str]
    unit_spans: List[WindowUnitSpan]
    extra_meta: Dict[str, Any] = Field(default_factory=dict)
