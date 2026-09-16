"""Riot Data Dragon专用获取器；只解析版本号用于端点发现，数据响应全部原样独立保存。"""

from __future__ import annotations

from typing import Iterator

from .base_collector import RawRecord
from .official_api_l1_collector import OfficialApiL1Collector


class LolDataDragonCollector(OfficialApiL1Collector):
    def collect_many(self) -> Iterator[RawRecord]:
        helper = self._helper()
        versions_url = self.task.get(
            "versions_url", "https://ddragon.leagueoflegends.com/api/versions.json"
        )
        versions_response = self._request(helper, versions_url, {})
        versions_record = self._record(versions_response, 1)
        versions_record.extra_meta.update({
            "dataset": "versions",
            "endpoint_discovery_parse": True,
            "note": "仅解析版本列表用于构造官方Data Dragon URL；raw_content保持原样",
        })
        yield versions_record

        try:
            versions = versions_response.json()
            version = self.task.get("version") or versions[0]
        except (ValueError, IndexError, TypeError) as exc:
            raise RuntimeError("Data Dragon版本列表不是预期的非空JSON数组") from exc
        if not isinstance(version, str) or not version:
            raise ValueError("Data Dragon version 必须为非空字符串")

        locales = list(self.task.get("locales", ["en_US"]))
        datasets = list(self.task.get("datasets", ["champion", "item", "runesReforged"]))
        allowed_datasets = {
            "champion": "champion.json",
            "item": "item.json",
            "runesReforged": "runesReforged.json",
            "summoner": "summoner.json",
            "profileicon": "profileicon.json",
        }
        unknown = set(datasets).difference(allowed_datasets)
        if unknown:
            raise ValueError(f"不支持的Data Dragon数据集: {', '.join(sorted(unknown))}")
        base = self.task.get("cdn_base_url", "https://ddragon.leagueoflegends.com/cdn").rstrip("/")
        page_index = 1
        for locale in locales:
            if not isinstance(locale, str) or not locale.replace("_", "").isalnum():
                raise ValueError(f"非法Data Dragon locale: {locale!r}")
            for dataset in datasets:
                page_index += 1
                url = f"{base}/{version}/data/{locale}/{allowed_datasets[dataset]}"
                response = self._request(helper, url, {})
                record = self._record(response, page_index)
                record.extra_meta.update({
                    "dataset": dataset,
                    "data_dragon_version": version,
                    "locale": locale,
                    "endpoint_discovery_parse": False,
                })
                yield record
