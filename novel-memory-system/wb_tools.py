"""novel-memory-system WB 工具接口层（薄封装，re-export 包内 5 个函数）。

用法（交互式 / 脚本）：
    import asyncio
    import wb_tools
    async def main():
        ctx = await wb_tools.get_chapter_context(5)
        hits = await wb_tools.search_memory("主角第一次受伤")
        profile = await wb_tools.query_character("林晓")
        ok = await wb_tools.update_world_setting(1, "新设定", "user_confirmed", 0.95)
        issues = await wb_tools.validate_consistency(5)
    asyncio.run(main())
"""
import sys
from pathlib import Path

# 允许 "import wb_tools" 直用（无需 pip install -e .）
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from novel_memory_system.wb_tools import (  # noqa: E402
    get_chapter_context,
    query_character,
    search_memory,
    update_world_setting,
    validate_consistency,
)

__all__ = [
    "get_chapter_context",
    "search_memory",
    "query_character",
    "update_world_setting",
    "validate_consistency",
]
