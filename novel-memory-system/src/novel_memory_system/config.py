"""全局配置：加载 .env / 环境变量，集中管理路径与常量。

所有模块一律通过 :func:`get_settings` 获取单例配置，禁止散落硬编码。
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

try:  # python-dotenv 为可选加速项；不存在时依赖真实环境变量
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - 离线环境
    load_dotenv = None  # type: ignore[assignment]

# 项目根 = src/novel_memory_system/config.py 上溯三级
PROJECT_ROOT = Path(__file__).resolve().parents[2]

if load_dotenv is not None:
    load_dotenv(PROJECT_ROOT / ".env", encoding="utf-8")


class Settings:
    """集中读取环境变量（全部带默认值，便于离线启动）。"""

    # ---- 数据库 ----
    # 必须在 .env 或环境变量里提供 DATABASE_URL；不给默认值，
    # 避免把任何具体主机/口令写进代码。.env.example 里有可直接复制改用的模板。
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", "postgresql://<user>:<password>@<host>:5432/<dbname>"
    )

    # ---- LLM / Embedding（OpenAI 兼容）----
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    EXTRACT_MODEL: str = os.getenv("EXTRACT_MODEL", "gpt-4o-mini")
    EMBED_MODEL: str = os.getenv("EMBED_MODEL", "text-embedding-3-small")
    EMBED_DIM: int = int(os.getenv("EMBED_DIM", "1536"))
    MAX_CONTEXT_TOKENS: int = int(os.getenv("MAX_CONTEXT_TOKENS", "8000"))
    EMBED_BATCH_SIZE: int = int(os.getenv("EMBED_BATCH_SIZE", "64"))

    # ---- 搜索补全（世界设定低置信度联网核对）----
    SEARCH_API_KEY: str = os.getenv("SEARCH_API_KEY", "")
    SEARCH_API_BASE_URL: str = os.getenv(
        "SEARCH_API_BASE_URL", "https://api.tavily.com/search"
    )

    # ---- ETL 时间分布（v1.1 外化）----
    ETL_TIME_BASE: str = os.getenv("ETL_TIME_BASE", "now")  # "now" 或 ISO8601
    ETL_TIME_SPAN_DAYS: float = float(os.getenv("ETL_TIME_SPAN_DAYS", "1.0"))
    TZ: str = os.getenv("TZ", "Asia/Shanghai")

    # ---- 路径 ----
    CHAPTERS_DIR: Path = PROJECT_ROOT / "data" / "chapters"
    STATE_DIR: Path = PROJECT_ROOT / "state"
    STATE_FILE: Path = STATE_DIR / "etl_state.json"
    LOCK_FILE: Path = STATE_DIR / "etl.lock"
    LOGS_DIR: Path = PROJECT_ROOT / "logs"
    ERROR_LOG: Path = LOGS_DIR / "etl_errors.log"

    # ETL 行为
    BATCH_SIZE: int = int(os.getenv("ETL_BATCH_SIZE", "10"))  # 每 N 章一个大事务
    MAX_CHAPTER_RETRIES: int = 3  # 单章连续失败上限

    # 日志
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    @property
    def local_tz(self) -> ZoneInfo:
        return ZoneInfo(self.TZ)

    def parse_time_base(self) -> datetime:
        """解析 ETL_TIME_BASE：'now' 取当前时刻，否则按 ISO8601 解析为带时区时间。"""
        raw = (self.ETL_TIME_BASE or "now").strip()
        if raw.lower() == "now":
            return datetime.now(self.local_tz)
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=self.local_tz)
        return dt

    def validate(self) -> None:
        if self.ETL_TIME_SPAN_DAYS < 0:
            raise ValueError("ETL_TIME_SPAN_DAYS 必须 >= 0")
        if self.EMBED_DIM <= 0:
            raise ValueError("EMBED_DIM 必须 > 0")
        if self.BATCH_SIZE < 1:
            raise ValueError("ETL_BATCH_SIZE 必须 >= 1")


_settings: Settings | None = None


def get_settings() -> Settings:
    """返回全局单例配置。"""
    global _settings
    if _settings is None:
        s = Settings()
        s.validate()
        _settings = s
    return _settings


def chapter_time_distribution(total: int) -> list[datetime]:
    """计算 N 个章节的 created_at 分布。

    规则（决策 D′）：
      ts(i) = ETL_TIME_BASE − (N − i) × ETL_TIME_SPAN_DAYS × 1440 / N 分钟
    最新一章锚定在 ETL_TIME_BASE；SPAN_DAYS=0 时全部取 base。
    """
    s = get_settings()
    base = s.parse_time_base()
    if total <= 0:
        return []
    if s.ETL_TIME_SPAN_DAYS == 0 or total == 1:
        return [base] * total
    step_min = s.ETL_TIME_SPAN_DAYS * 1440.0 / total
    return [
        base - timedelta(minutes=step_min * (total - i)) for i in range(1, total + 1)
    ]
