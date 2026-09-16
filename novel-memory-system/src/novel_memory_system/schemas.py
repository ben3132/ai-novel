"""Pydantic v2 结构化提取模型（LLM 输出的强校验层）。

LLM 按本文件模型输出 JSON；校验失败即写入 etl_errors.log（含字段路径与原始输出）。
事件/剧情线中通过名字引用角色/事件，由 ETL 入库阶段解析为 id。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

# 与 init.sql 枚举保持一致
EventType = Literal[
    "combat", "dialogue", "travel", "discovery", "conflict",
    "plot_twist", "emotion", "relationship", "milestone", "other",
]
WsSource = Literal["original", "enriched", "user_confirmed"]
ThreadStatus = Literal["open", "progressing", "resolved", "abandoned"]

# 低置信度触发联网补全的类别关键词（置信度 < 0.7 且命中其一 → enriched）
ENRICH_CATEGORY_KEYWORDS = ("地理", "历史", "文化")


class CharacterRef(BaseModel):
    """事件/剧情线中对角色的引用（LLM 输出阶段用名字，入库阶段解析为 id）。"""

    name: str = Field(description="角色名，必须与 characters 表中名字一致")
    role: str = Field(default="", description="角色在事件中的职能，如 主角/反派/旁观者")


class EventRef(BaseModel):
    """剧情线对事件的引用（用事件在本章的序号引用）。"""

    event_index: int = Field(ge=0, description="本章 events 列表的下标（从 0 开始）")
    relation: str = Field(default="", description="事件与剧情线的关系，如 铺垫/推进/转折")


class CharacterState(BaseModel):
    """单章提取出的角色及其状态。"""

    name: str = Field(description="角色名")
    current_state: dict = Field(
        default_factory=dict,
        description="本章结束时该角色的状态快照，如 {位置, 健康, 关系, 目标}",
    )
    state_change: str | None = Field(
        default=None, description="本章发生的状态变化描述（用于 query_character 时间线）"
    )


class WorldSetting(BaseModel):
    """单章提取出的世界设定条目。"""

    category: str = Field(description="设定类别：地理/历史/文化/力量体系/组织 等")
    key: str = Field(description="设定键名")
    value: str = Field(description="设定值")
    confidence_score: float = Field(
        default=0.7, ge=0.0, le=1.0, description="提取置信度 0-1"
    )
    # 入库来源：原文提取(默认)/联网补全 enriched/人工确认 user_confirmed
    # （LLM 提取 JSON 可不携带；enrich 补全成功后改写为 enriched）
    source: WsSource = "original"

    @field_validator("value")
    @classmethod
    def _value_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("world_setting.value 不能为空")
        return v


class ChapterEvent(BaseModel):
    """单章提取出的事件。"""

    type: EventType = Field(description="事件类型")
    description: str = Field(description="事件一句话描述")
    related_characters: list[CharacterRef] = Field(
        default_factory=list, description="事件涉及的角色"
    )


class PlotThread(BaseModel):
    """单章提取出的剧情线/伏笔更新。"""

    title: str = Field(description="剧情线标题")
    status: ThreadStatus = Field(description="剧情线状态")
    priority: int = Field(default=0, description="优先级（越大越靠前）")
    events: list[EventRef] = Field(
        default_factory=list, description="本章 events 中与该线相关的事件引用"
    )


class ChapterExtraction(BaseModel):
    """一章的完整结构化提取结果。"""

    chapter_number: int = Field(ge=1, description="章节号（须与文件名一致）")
    title: str = Field(description="章节标题")
    summary: str = Field(description="本章摘要，供三层记忆的近程层使用")
    characters: list[CharacterState] = Field(
        default_factory=list, description="本章登场/状态变化的角色"
    )
    world_settings: list[WorldSetting] = Field(
        default_factory=list, description="本章出现的新世界设定"
    )
    events: list[ChapterEvent] = Field(
        default_factory=list, description="本章事件"
    )
    plot_threads: list[PlotThread] = Field(
        default_factory=list, description="本章剧情线更新"
    )

    @field_validator("summary")
    @classmethod
    def _summary_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("summary 不能为空")
        return v

    def events_texts(self) -> list[str]:
        """供 embedding 用的事件拼接文本（保持与 events 列表一一对应）。"""
        return [f"{e.type}: {e.description}" for e in self.events]
