"""分级信源批量采集入口；只获取并原样落盘，不做内容处理。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Type
from uuid import uuid4

import yaml

CODE_ROOT = Path(__file__).resolve().parent
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

from src.collector import (  # noqa: E402
    DerivedWebCollector, DynamicWebL1Collector, LocalL1Collector, LocalDerivedTextCollector, OcrL1Collector,
    DerivedMediaSubtitleCollector, OfficialMediaSubtitleL1Collector,
    LolDataDragonCollector,
    OfficialApiL1Collector, OfficialDocumentL1Collector, DerivedDocumentCollector, OfficialWebL1Collector,
    OfficialSiteCrawlL1Collector,
    L2WebCollector, L3WebCollector, L4WebCollector, ReferenceTranscriptApiCollector, ReferenceWikiApiL2Collector,
    OfficialIndexFollowL1Collector,
    OfficialMediaPlaylistL1Collector,
)
from src.storage.ip_paths import IpDataPaths
from src.collector.base_collector import BaseCollector  # noqa: E402
from src.source_registry import SourceRegistry  # noqa: E402
from src.utils.file_io import append_jsonl, append_jsonl_dict  # noqa: E402
from src.utils.http_cache import NotModifiedError  # noqa: E402
from src.utils.content_hash import ContentHashStore  # noqa: E402


COLLECTORS: Dict[str, Type[BaseCollector]] = {
    "local_l1": LocalL1Collector,
    "local_derived_text": LocalDerivedTextCollector,
    "official_api_l1": OfficialApiL1Collector,
    "official_document_l1": OfficialDocumentL1Collector,
    "derived_document": DerivedDocumentCollector,
    "official_web_l1": OfficialWebL1Collector,
    "official_site_crawl_l1": OfficialSiteCrawlL1Collector,
    "ocr_l1": OcrL1Collector,
    "derived_web": DerivedWebCollector,
    "l2_web": L2WebCollector,
    "l3_web": L3WebCollector,
    "l4_web": L4WebCollector,
    "reference_wiki_api_l2": ReferenceWikiApiL2Collector,
    "reference_transcript_api_l11": ReferenceTranscriptApiCollector,
    "official_index_follow_l1": OfficialIndexFollowL1Collector,
    "official_media_playlist_l1": OfficialMediaPlaylistL1Collector,
    "dynamic_web_l1": DynamicWebL1Collector,
    "official_media_subtitle_l1": OfficialMediaSubtitleL1Collector,
    "derived_media_subtitle": DerivedMediaSubtitleCollector,
    "lol_data_dragon_l1": LolDataDragonCollector,
}


def load_config(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    if not isinstance(config.get("tasks", []), list):
        raise ValueError("配置字段 tasks 必须是列表")
    return config


def default_data_root() -> Path:
    configured = os.environ.get("IP_SOURCE_DATA_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return (CODE_ROOT.parent / f"{CODE_ROOT.name}_data").resolve()


def output_path_for(task: Dict[str, Any], data_root: Path) -> Path:
    return IpDataPaths(data_root, task["ip_domain"]).raw_output(task["output"])


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_run_event(state_path: Path, **fields: Any) -> None:
    append_jsonl_dict(state_path, {"event_ts": utc_now(), **fields})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="执行或查看分级原始信源采集")
    parser.add_argument(
        "--config", default=str(CODE_ROOT / "config" / "source_config_l1.yaml"),
        help="YAML 配置路径",
    )
    parser.add_argument(
        "--data-root",
        help="采集数据独立根目录；默认读取 IP_SOURCE_DATA_ROOT，否则使用代码目录同级的 <代码目录名>_data",
    )
    parser.add_argument(
        "--hash-index",
        help="按信源保存的内容 SHA-256 去重索引",
    )
    parser.add_argument(
        "--force-refresh", action="store_true",
        help="忽略ETag/Last-Modified条件缓存重新获取；不删除既有记录",
    )
    parser.add_argument("--ip-domain", help="只选择指定 IP")
    parser.add_argument(
        "--source", action="append", dest="source_keys",
        help="只选择指定 source_key；可重复使用",
    )
    parser.add_argument("--list-sources", action="store_true", help="列出匹配信源后退出")
    parser.add_argument("--dry-run", action="store_true", help="显示将执行的任务，不发请求、不写文件")
    parser.add_argument(
        "--include-disabled", action="store_true",
        help="允许显式选择或 dry-run 默认禁用的任务；正常批量运行不建议使用",
    )
    parser.add_argument(
        "--state-file",
        help="运行事件 JSONL 路径",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    data_root = Path(args.data_root).expanduser().resolve() if args.data_root else default_data_root()
    try:
        config = load_config(Path(args.config).resolve())
        registry = SourceRegistry(config.get("tasks", []), COLLECTORS)
        tasks = registry.list(
            ip_domain=args.ip_domain,
            source_keys=args.source_keys,
            enabled_only=not args.include_disabled,
        )
    except (OSError, ValueError, KeyError, yaml.YAMLError) as exc:
        print(f"[CONFIG-FAIL] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if args.list_sources or args.dry_run:
        for task in tasks:
            print(json.dumps(registry.describe(task), ensure_ascii=False))
        if args.dry_run:
            print(f"DRY-RUN：将执行 {len(tasks)} 个任务；未发请求，未写文件")
        return 0

    if args.force_refresh:
        for task in tasks:
            task["force_refresh"] = True

    success = failed = unchanged = 0
    run_id = f"run-{uuid4().hex}"
    domains = sorted({task["ip_domain"] for task in tasks})
    state_paths = {
        domain: (Path(args.state_file).resolve() if args.state_file else IpDataPaths(data_root, domain).state / "collect_runs.jsonl")
        for domain in domains
    }
    hash_stores = {
        domain: ContentHashStore(
            Path(args.hash_index).resolve() if args.hash_index else IpDataPaths(data_root, domain).state / "content_hashes.json"
        ) for domain in domains
    }
    for domain, state_path in state_paths.items():
        write_run_event(
            state_path, run_id=run_id, event="run_started", status="running",
            selected_count=sum(task["ip_domain"] == domain for task in tasks),
            ip_domain=domain, source_keys=args.source_keys,
        )
    for task in tasks:
        state_path = state_paths[task["ip_domain"]]
        hash_store = hash_stores[task["ip_domain"]]
        source_key = task["source_key"]
        write_run_event(
            state_path,
            run_id=run_id,
            source_key=source_key,
            event="task_started",
            status="running",
            collector=task["collector"],
            target=task.get("url", task.get("path", task.get("versions_url"))),
        )
        try:
            collector = COLLECTORS[task["collector"]](task, str(data_root))
            output = output_path_for(task, data_root)
            source_ids = []
            duplicate_source_ids = []
            for record in collector.collect_many():
                content_hash = record.extra_meta.get("content_sha256")
                if not content_hash:
                    content_hash = hashlib.sha256(record.raw_content.encode("utf-8")).hexdigest()
                    record.extra_meta["content_sha256"] = content_hash
                serialization_version = record.extra_meta.get("raw_serialization_version", 1)
                dedup_hash = f"v{serialization_version}:{content_hash}"
                existing = hash_store.existing_source_id(source_key, dedup_hash)
                if existing:
                    duplicate_source_ids.append(existing)
                    continue
                append_jsonl(output, record)
                hash_store.add(source_key, dedup_hash, record.source_id, str(output))
                source_ids.append(record.source_id)
            if not source_ids and duplicate_source_ids:
                unchanged += 1
                write_run_event(
                    state_path,
                    run_id=run_id,
                    source_key=source_key,
                    event="task_finished",
                    status="unchanged",
                    reason="duplicate_content_hash",
                    existing_source_ids=duplicate_source_ids,
                )
                print(f"[UNCHANGED] {source_key} (content hash)")
                continue
            if not source_ids:
                raise RuntimeError("采集器未返回任何原始响应")
            success += 1
            write_run_event(
                state_path,
                run_id=run_id,
                source_key=source_key,
                event="task_finished",
                status="success",
                source_ids=source_ids,
                record_count=len(source_ids),
                duplicate_count=len(duplicate_source_ids),
                output=str(output),
            )
            print(f"[OK] {source_key} -> {output}")
        except NotModifiedError as exc:
            unchanged += 1
            write_run_event(
                state_path,
                run_id=run_id,
                source_key=source_key,
                event="task_finished",
                status="unchanged",
                message=str(exc),
            )
            print(f"[UNCHANGED] {source_key}")
        except Exception as exc:  # 单任务失败不影响后续任务。
            failed += 1
            write_run_event(
                state_path,
                run_id=run_id,
                source_key=source_key,
                event="task_finished",
                status="failed",
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            print(f"[FAIL] {source_key}: {type(exc).__name__}: {exc}", file=sys.stderr)

    for domain, state_path in state_paths.items():
        write_run_event(
            state_path, run_id=run_id, event="run_finished",
            status="failed" if failed else "success",
            success_count=success, failed_count=failed,
            unchanged_count=unchanged,
            selected_count=sum(task["ip_domain"] == domain for task in tasks),
            ip_domain=domain,
        )
    print(f"完成：成功 {success}，未变化 {unchanged}，失败 {failed}，选择 {len(tasks)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
