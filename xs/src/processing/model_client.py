"""处理层唯一模型接口；凭据、地址和模型名只从环境变量读取。"""

from __future__ import annotations

import json
import os
from urllib.request import Request, urlopen


class ModelClient:
    """最小 Ollama/OpenAI-compatible JSON 客户端，禁止记录 API Key。"""

    def __init__(self) -> None:
        self.provider = os.environ.get("IP_LLM_PROVIDER", "ollama").lower()
        self.base_url = os.environ.get("IP_LLM_BASE_URL", "http://localhost:11434").rstrip("/")
        self.model = os.environ.get("IP_LLM_MODEL", "qwen2.5:3b")
        self.num_ctx = int(os.environ.get("IP_LLM_NUM_CTX", "4096"))
        self.num_predict = int(os.environ.get("IP_LLM_NUM_PREDICT", "256"))
        self.api_key = os.environ.get("IP_LLM_API_KEY")
        if self.provider not in {"ollama", "openai_compatible"}:
            raise ValueError("IP_LLM_PROVIDER 只能是 ollama 或 openai_compatible")
        if self.provider == "openai_compatible" and not self.api_key:
            raise ValueError("openai_compatible 必须通过 IP_LLM_API_KEY 提供密钥")

    def generate_json(self, system: str, user: str, schema: dict, timeout: int = 300) -> dict:
        if self.provider == "ollama":
            endpoint = f"{self.base_url}/api/generate"
            payload = {
                "model": self.model,
                "prompt": f"系统要求：\n{system}\n\n输入：\n{user}",
                "stream": False,
                "format": schema,
                "options": {"temperature": 0, "num_ctx": self.num_ctx, "num_predict": self.num_predict},
                "keep_alive": "10m",
            }
            headers = {"Content-Type": "application/json; charset=utf-8"}
            response_key = "response"
        else:
            endpoint = f"{self.base_url}/chat/completions"
            payload = {
                "model": self.model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "temperature": 0,
                "response_format": {"type": "json_object"},
            }
            headers = {
                "Content-Type": "application/json; charset=utf-8",
                "Authorization": f"Bearer {self.api_key}",
            }
            response_key = None
        request = Request(endpoint, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers=headers, method="POST")
        with urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
        content = result[response_key] if response_key else result["choices"][0]["message"]["content"]
        return json.loads(content)
