"""统一 robots.txt 判定，遵循公开协议语义并保持故障时安全停止。"""

from __future__ import annotations

from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

from src.utils.request_helper import RequestHelper


def assert_robots_allowed(
    helper: RequestHelper,
    url: str,
    user_agent: str,
    on_error: str = "deny",
) -> None:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    parser = RobotFileParser()
    parser.set_url(robots_url)
    try:
        response = helper.get(robots_url)
        content_type = response.headers.get("Content-Type", "").lower()
        prefix = response.text.lstrip()[:32].lower()
        if "html" in content_type or prefix.startswith(("<!doctype html", "<html")):
            raise RuntimeError(f"robots.txt 返回HTML而非规则文本: {robots_url}")
        parser.parse(response.text.splitlines())
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None
        # RFC 9309：除401/403外的4xx表示robots.txt不可用，可正常访问。
        if status is not None and 400 <= status < 500 and status not in {401, 403}:
            return
        if status in {401, 403}:
            raise PermissionError(f"robots.txt 返回 {status}，拒绝采集: {url}") from exc
        if on_error != "allow":
            raise RuntimeError(f"无法确认 robots.txt，按安全策略停止: {robots_url}") from exc
        return
    except Exception as exc:
        if on_error != "allow":
            raise RuntimeError(f"无法确认 robots.txt，按安全策略停止: {robots_url}") from exc
        return
    if not parser.can_fetch(user_agent, url):
        raise PermissionError(f"robots.txt 不允许采集: {url}")
