"""统一 API 客户端。

公开端点由 YAML 传入；API Key、Token 等私密信息只按环境变量名称读取，
禁止在 Python、YAML、日志或 JSONL 中硬编码、回显或持久化。
"""

from __future__ import annotations

import os
from typing import Any, Dict, Mapping, Optional, Tuple

import requests

from src.utils.request_helper import RequestHelper


class ApiClient:
    """所有官方 API 采集共用的唯一凭据与请求入口。"""

    def __init__(self, helper: RequestHelper, auth: Optional[Mapping[str, Any]] = None) -> None:
        self.helper = helper
        self.auth = dict(auth or {})

    @staticmethod
    def _credential(auth: Mapping[str, Any]) -> str:
        env_name = auth.get("env")
        if not isinstance(env_name, str) or not env_name:
            raise ValueError("http.auth 必须指定环境变量名称 env")
        secret = os.environ.get(env_name)
        if not secret:
            # 只报告变量名，绝不回显密钥值。
            raise ValueError(f"认证环境变量未设置: {env_name}")
        return secret

    @classmethod
    def auth_values(cls, auth: Optional[Mapping[str, Any]]) -> Tuple[Dict[str, str], Dict[str, str]]:
        if not auth:
            return {}, {}
        secret = cls._credential(auth)
        auth_type = auth.get("type")
        if auth_type == "bearer":
            return {"Authorization": f"Bearer {secret}"}, {}
        if auth_type == "api_key":
            name = auth.get("name")
            if not isinstance(name, str) or not name:
                raise ValueError("api_key 认证必须指定 name")
            location = auth.get("location", "header")
            if location == "header":
                return {name: secret}, {}
            if location == "query":
                return {}, {name: secret}
            raise ValueError("api_key location 只能是 header 或 query")
        raise ValueError(f"不支持的认证类型: {auth_type!r}")

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        auth_headers, auth_params = self.auth_values(self.auth)
        headers = {**kwargs.pop("headers", {}), **auth_headers}
        params = {**kwargs.pop("params", {}), **auth_params}
        response = self.helper.request(
            method, url, headers=headers or None, params=params or None, **kwargs
        )
        # requests 会把查询参数密钥写入 response.url/request.url；返回采集器前统一脱敏。
        if self.auth:
            secret = self._credential(self.auth)
            replacement = "[REDACTED]"
            response.url = response.url.replace(secret, replacement)
            if response.request is not None and response.request.url:
                response.request.url = response.request.url.replace(secret, replacement)
            for history_item in response.history:
                history_item.url = history_item.url.replace(secret, replacement)
                location = history_item.headers.get("Location")
                if location:
                    history_item.headers["Location"] = location.replace(secret, replacement)
        return response
