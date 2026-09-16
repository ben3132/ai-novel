"""将 HTTP 响应正文写入 WARC；JSONL只记录可定位的归档信息。"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any, Dict

from src.utils.request_helper import safe_response_headers
from src.storage.ip_paths import IpDataPaths


def archive_http_response(
    project_root: str,
    task: Dict[str, Any],
    response: Any,
) -> Dict[str, Any]:
    """追加一条 WARC response 记录。

    响应体逐字节写入；可能携带凭据的响应头已脱敏。为避免 API Key 泄漏，
    WARC 不保存 request 记录，目标 URL 使用 ApiClient 已脱敏后的 response.url。
    """
    if task.get("archive_warc", True) is False:
        return {"warc_archived": False}
    try:
        from warcio.statusandheaders import StatusAndHeaders
        from warcio.warcwriter import WARCWriter
    except ImportError as exc:
        raise RuntimeError("启用 WARC 归档需要安装 requirements-l1.txt 中的 warcio") from exc

    configured = task.get("warc_output", f"warc/{task['source_key']}.warc.gz")
    path = IpDataPaths(project_root, task["ip_domain"]).raw_output(configured)
    path.parent.mkdir(parents=True, exist_ok=True)

    headers = list(safe_response_headers(response).items())
    protocol = "HTTP/1.1"
    raw_version = getattr(response.raw, "version", None)
    if raw_version == 10:
        protocol = "HTTP/1.0"
    status_line = f"{response.status_code} {response.reason or ''}".rstrip()
    http_headers = StatusAndHeaders(status_line, headers, protocol=protocol)

    with path.open("ab") as stream:
        writer = WARCWriter(stream, gzip=True)
        record = writer.create_warc_record(
            response.url,
            "response",
            payload=BytesIO(response.content),
            http_headers=http_headers,
        )
        writer.write_record(record)

    # Store a project-relative path when possible so copied archives remain portable.
    try:
        recorded_path = str(path.relative_to(Path(project_root)))
    except ValueError:
        recorded_path = str(path)
    return {
        "warc_archived": True,
        "warc_path": recorded_path,
        "warc_record_id": record.rec_headers.get_header("WARC-Record-ID"),
        "warc_target_uri": response.url,
    }
