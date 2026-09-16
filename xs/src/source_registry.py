"""统一信源注册表：只负责配置校验、筛选和能力声明，不判断内容。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Type

from src.collector.base_collector import BaseCollector


@dataclass(frozen=True)
class CollectorCapability:
    """采集器静态能力，供未来选择层查询。"""

    collector: str
    acquisition_kind: str
    network_required: bool
    supports_incremental: bool
    supported_trust_levels: tuple[int, ...]


CAPABILITIES: Dict[str, CollectorCapability] = {
    "local_l1": CollectorCapability("local_l1", "local_text", False, False, (1,)),
    "local_derived_text": CollectorCapability(
        "local_derived_text", "local_text", False, False, (11,)
    ),
    "official_api_l1": CollectorCapability("official_api_l1", "http_api", True, False, (1,)),
    "official_web_l1": CollectorCapability("official_web_l1", "http_html", True, False, (1,)),
    "official_site_crawl_l1": CollectorCapability(
        "official_site_crawl_l1", "limited_domain_crawl", True, False, (1,)
    ),
    "official_document_l1": CollectorCapability(
        "official_document_l1", "http_binary", True, False, (1,)
    ),
    "derived_document": CollectorCapability(
        "derived_document", "http_binary", True, False, (11,)
    ),
    "ocr_l1": CollectorCapability("ocr_l1", "local_ocr", False, False, (1,)),
    "derived_web": CollectorCapability("derived_web", "http_html", True, False, (11,)),
    "l2_web": CollectorCapability("l2_web", "reference_html", True, False, (2,)),
    "l3_web": CollectorCapability("l3_web", "reference_html", True, False, (3,)),
    "l4_web": CollectorCapability("l4_web", "reference_html", True, False, (4,)),
    "reference_wiki_api_l2": CollectorCapability(
        "reference_wiki_api_l2", "reference_api_mediawiki", True, False, (2,)
    ),
    "reference_transcript_api_l11": CollectorCapability(
        "reference_transcript_api_l11", "reference_api_mediawiki", True, False, (11,)
    ),
    "official_index_follow_l1": CollectorCapability(
        "official_index_follow_l1", "official_index_follow", True, False, (1,)
    ),
    "official_media_playlist_l1": CollectorCapability(
        "official_media_playlist_l1", "public_media_playlist_metadata", True, False, (1,)
    ),
    "dynamic_web_l1": CollectorCapability(
        "dynamic_web_l1", "browser_network_capture", True, False, (1,)
    ),
    "official_media_subtitle_l1": CollectorCapability(
        "official_media_subtitle_l1", "public_media_subtitle", True, False, (1,)
    ),
    "derived_media_subtitle": CollectorCapability(
        "derived_media_subtitle", "public_media_subtitle", True, False, (11,)
    ),
    "lol_data_dragon_l1": CollectorCapability(
        "lol_data_dragon_l1", "official_versioned_api", True, True, (1,)
    ),
}


class SourceRegistry:
    """配置驱动的信源目录；source_key 是跨运行稳定标识。"""

    def __init__(
        self,
        tasks: Iterable[Mapping[str, Any]],
        collectors: Mapping[str, Type[BaseCollector]],
    ) -> None:
        self._collectors = dict(collectors)
        self._tasks: Dict[str, Dict[str, Any]] = {}
        for raw_task in tasks:
            task = dict(raw_task)
            source_key = task.get("source_key")
            if not isinstance(source_key, str) or not source_key.strip():
                raise ValueError("每个信源任务必须提供非空 source_key")
            if source_key in self._tasks:
                raise ValueError(f"source_key 重复: {source_key}")
            collector_name = task.get("collector")
            if collector_name not in self._collectors:
                raise ValueError(f"信源 {source_key} 使用了未注册采集器: {collector_name!r}")
            capability = CAPABILITIES.get(collector_name)
            if capability is None:
                raise ValueError(f"采集器缺少能力声明: {collector_name}")
            trust_level = task.get("trust_level")
            if trust_level not in capability.supported_trust_levels:
                raise ValueError(
                    f"信源 {source_key} 的 trust_level={trust_level} 与采集器 "
                    f"{collector_name} 能力不匹配"
                )
            if "ip_domain" not in task or "output" not in task:
                raise ValueError(f"信源 {source_key} 缺少 ip_domain 或 output")
            self._tasks[source_key] = task

    def get(self, source_key: str) -> Dict[str, Any]:
        try:
            return dict(self._tasks[source_key])
        except KeyError as exc:
            raise KeyError(f"未知 source_key: {source_key}") from exc

    def list(
        self,
        *,
        ip_domain: Optional[str] = None,
        source_keys: Optional[Iterable[str]] = None,
        enabled_only: bool = False,
    ) -> List[Dict[str, Any]]:
        selected = set(source_keys) if source_keys else None
        if selected:
            unknown = selected.difference(self._tasks)
            if unknown:
                raise ValueError(f"未知 source_key: {', '.join(sorted(unknown))}")
        result: List[Dict[str, Any]] = []
        for source_key, task in self._tasks.items():
            if selected is not None and source_key not in selected:
                continue
            if ip_domain is not None and task.get("ip_domain") != ip_domain:
                continue
            if enabled_only and not task.get("enabled", False):
                continue
            result.append(dict(task))
        return result

    def capability_for(self, source_key: str) -> CollectorCapability:
        task = self.get(source_key)
        return CAPABILITIES[task["collector"]]

    def describe(self, task: Mapping[str, Any]) -> Dict[str, Any]:
        capability = CAPABILITIES[task["collector"]]
        return {
            "source_key": task["source_key"],
            "name": task.get("name", task["source_key"]),
            "ip_domain": task["ip_domain"],
            "trust_level": task["trust_level"],
            "collector": task["collector"],
            "acquisition_kind": capability.acquisition_kind,
            "network_required": capability.network_required,
            "supports_incremental": capability.supports_incremental,
            "enabled": bool(task.get("enabled", False)),
            "target": task.get("url", task.get("path", task.get("versions_url"))),
            "output": task["output"],
        }
