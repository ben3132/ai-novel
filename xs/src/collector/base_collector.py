"""采集器抽象基类、信源等级边界与统一原始记录模型。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, ClassVar, Dict, Iterator, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


# 统一信源体系（所有等级均可归档；是否可用于推理由 inference_policy 决定）：
# 1  L1 官方一手源：原著、官方设定/公告、官方 API/网页、客户端导出、原作扫描 OCR。
# 11 L1-derived：第三方对原作的转录/搬运副本；必须与 L1 原件交叉验证。
# 2  L2 权威粉丝 Wiki：Fandom、萌娘、灰机、TFWiki 等有引用规范的整理页面。
# 3  L3 二次整理社区：论坛、贴吧、知乎、B站考据等。
# 4  L4 低可信度：自媒体、同人、AI 文案；未来上层必须强制排除，不参与设定推理。
TRUST_L1 = 1
TRUST_L1_DERIVED = 11
TRUST_L2 = 2
TRUST_L3 = 3
TRUST_L4 = 4

META_DEFAULTS: Dict[str, Any] = {
    "authenticity_status": "unverified",
    "continuity": "unknown",
    "work_title": "unknown",
    "work_version": "unknown",
    "canon_scope": "unknown",
    "content_status": "unknown",
    "completeness": "unknown",
    "language": "unknown",
    "original_language": "unknown",
    "translation_status": "unknown",
    "published_ts": None,
    "effective_from": None,
    "effective_to": None,
    "supersedes_source_id": None,
    "evidence_status": "direct",
}


class RawRecord(BaseModel):
    """统一 JSONL 记录；内容不清洗、不纠错、不摘要、不分块、不解析。"""

    source_id: str
    trust_level: Literal[1, 2, 3, 4, 11]
    source_type: Literal[
        "local_text", "official_api_response", "official_web_html",
        "official_document", "official_media_subtitle", "ocr_scan_original",
        "derived_transcription", "browser_network_response", "browser_rendered_dom",
        "media_extractor_metadata",
        "reference_web_page",
    ]
    url: str
    collect_ts: str
    ip_domain: str
    raw_content: str
    extra_meta: Dict[str, Any] = Field(default_factory=dict)


class BaseCollector(ABC):
    """未来上层可依赖的最小采集接口；当前不包含任何内容业务逻辑。"""

    trust_level: ClassVar[int]
    source_type: ClassVar[str]

    def __init__(self, task: Dict[str, Any], project_root: str) -> None:
        self.task = task
        self.project_root = project_root
        # 陌生 IP 必须可动态接入；只校验安全的目录标识，不维护固定白名单。
        from src.storage.ip_paths import normalize_ip_domain
        normalize_ip_domain(str(task.get("ip_domain", "")))
        configured = task.get("trust_level")
        if configured is not None and configured != self.trust_level:
            raise ValueError(
                f"任务 {task.get('name', '<unnamed>')} 的 trust_level 必须固定为 "
                f"{self.trust_level}，不可改为 {configured}"
            )

    @abstractmethod
    def collect(self) -> RawRecord:
        """执行一次获取并返回一条原始记录。"""

    def collect_many(self) -> Iterator[RawRecord]:
        """批量接口；默认仅一条，分页采集器可逐响应 yield，禁止合并响应。"""
        yield self.collect()

    def make_record(
        self,
        *,
        url: str,
        raw_content: str,
        extra_meta: Dict[str, Any],
        source_type: str | None = None,
    ) -> RawRecord:
        # source_meta 只描述来源，不判断或整理 raw_content。未填写的维度明确记为 unknown。
        source_meta = {**META_DEFAULTS, **self.task.get("source_meta", {})}
        source_meta["source_key"] = self.task["source_key"]
        source_meta["raw_serialization_version"] = 2
        source_meta.update(extra_meta)
        source_meta.setdefault("inference_policy", {
            "eligible": self.trust_level in (TRUST_L1, TRUST_L2, TRUST_L3, TRUST_L1_DERIVED),
            "requires_cross_check": self.trust_level != TRUST_L1,
            "max_role": (
                "primary" if self.trust_level == TRUST_L1
                else "excluded" if self.trust_level == TRUST_L4
                else "supporting"
            ),
        })
        return RawRecord(
            source_id=f"{source_type or self.source_type}-{uuid4().hex}",
            trust_level=self.trust_level,
            source_type=source_type or self.source_type,
            url=url,
            collect_ts=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            ip_domain=self.task["ip_domain"],
            raw_content=raw_content,
            extra_meta=source_meta,
        )
