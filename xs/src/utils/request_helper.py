"""HTTP 通用层：认证、超时、重试、限流等待与重定向；不解析业务内容。"""

from __future__ import annotations

import time
import base64
import re
from typing import Any, Dict, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class RequestHelper:
    def __init__(
        self,
        *,
        timeout: float = 20.0,
        retries: int = 3,
        backoff_factor: float = 0.8,
        delay_seconds: float = 0.0,
        headers: Optional[Dict[str, str]] = None,
        max_redirects: int = 10,
    ) -> None:
        self.timeout = timeout
        self.delay_seconds = delay_seconds
        self.session = requests.Session()
        self.session.max_redirects = max_redirects
        retry = Retry(
            total=retries,
            connect=retries,
            read=retries,
            status=retries,
            backoff_factor=backoff_factor,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "HEAD", "POST"}),
            respect_retry_after_header=True,
        )
        self.session.mount("http://", HTTPAdapter(max_retries=retry))
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        if headers:
            self.session.headers.update(headers)

    def request(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> requests.Response:
        if self.delay_seconds > 0:
            time.sleep(self.delay_seconds)
        headers = kwargs.pop("headers", None)
        params = kwargs.pop("params", None)
        response = self.session.request(
            method.upper(), url, timeout=kwargs.pop("timeout", self.timeout),
            headers=headers, params=params, **kwargs,
        )
        response.raise_for_status()
        return response

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        return self.request("GET", url, **kwargs)


def redirect_chain(response: requests.Response) -> list[Dict[str, Any]]:
    """返回响应重定向历史；只读取 HTTP 元数据。"""
    return [
        {"status_code": item.status_code, "url": item.url, "location": item.headers.get("Location")}
        for item in response.history
    ]


def safe_response_headers(response: requests.Response) -> Dict[str, str]:
    """保存响应头结构，但对可能携带会话/认证信息的值强制脱敏。"""
    sensitive = {
        "set-cookie", "set-cookie2", "authorization", "proxy-authorization",
        "www-authenticate", "proxy-authenticate",
    }
    return {
        name: "[REDACTED]" if name.lower() in sensitive else value
        for name, value in response.headers.items()
    }


def sanitize_public_url(url: str) -> str:
    """脱敏 URL中常见凭据型查询参数；保留参数名用于溯源。"""
    parts = urlsplit(url)
    sensitive_tokens = ("token", "key", "secret", "signature", "session", "auth", "credential")
    query = [
        (name, "[REDACTED]" if any(token in name.lower() for token in sensitive_tokens) else value)
        for name, value in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def response_text_and_encoding(response: requests.Response) -> tuple[str, str]:
    """把原始响应字节可逆地放入字符串字段；不清洗或修改正文内容。"""
    content_type = response.headers.get("Content-Type", "")
    declared_charset = None
    for part in content_type.split(";")[1:]:
        if part.strip().lower().startswith("charset="):
            declared_charset = part.split("=", 1)[1].strip().strip('"\'')
            break
    prefix = response.content[:8192].decode("ascii", errors="ignore")
    meta_match = re.search(
        r"(?:<meta[^>]+charset\s*=\s*['\"]?\s*|charset\s*=\s*)([A-Za-z0-9._-]+)",
        prefix,
        flags=re.IGNORECASE,
    )
    meta_charset = meta_match.group(1) if meta_match else None
    candidates = [declared_charset, meta_charset]
    # requests对无charset的text/html默认ISO-8859-1；中文旧站常因此乱码。
    if not declared_charset:
        candidates.append(response.apparent_encoding)
    candidates.extend([response.encoding, "utf-8"])
    seen = set()
    for encoding in candidates:
        if not encoding or encoding.lower() in seen:
            continue
        seen.add(encoding.lower())
        try:
            return response.content.decode(encoding, errors="strict"), encoding
        except (LookupError, UnicodeDecodeError):
            continue
    return base64.b64encode(response.content).decode("ascii"), "base64"
