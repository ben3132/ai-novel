"""数据库访问层：asyncpg 连接池 + vector codec 注册 + 事务/savepoint 辅助。

设计说明：
  - 热路径一律 asyncpg 原生 SQL（分区表 + vector 的 DDL/DML 用 ORM 反而绕）；
  - 每个连接建立时调用 pgvector.asyncpg.register_vector 注册 vector OID codec；
  - 向量参数统一以文本数组/文本传入、SQL 端 ::vector 转换，规避 asyncpg×pgvector
    对 vector[]/向量 OID 的 prepared 语句缓存不确定性（见计划 3.6/风险 4）。
"""
from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any

import asyncpg

from .config import get_settings

_pool: asyncpg.Pool | None = None
_pool_lock = asyncio.Lock()


async def _init_connection(conn: asyncpg.Connection) -> None:
    """连接初始化：注册 pgvector 的 vector codec（异步）。"""
    try:
        from pgvector.asyncpg import register_vector  # 延迟导入，避免缺依赖时全模块失败
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "缺少 pgvector 包：请先 `pip install pgvector`（pyproject 已声明依赖）"
        ) from exc
    await register_vector(conn)


async def get_pool() -> asyncpg.Pool:
    """惰性创建全局连接池（进程内单例）。"""
    global _pool
    if _pool is None or _pool._closed:  # type: ignore[attr-defined]
        async with _pool_lock:
            if _pool is None or _pool._closed:  # type: ignore[attr-defined]
                s = get_settings()
                _pool = await asyncpg.create_pool(
                    dsn=s.DATABASE_URL,
                    min_size=1,
                    max_size=8,
                    init=_init_connection,
                    command_timeout=60,
                )
    return _pool


async def close_pool() -> None:
    """关闭全局连接池（进程退出前调用）。"""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


@contextlib.asynccontextmanager
async def connection() -> AsyncIterator[asyncpg.Connection]:
    """从池中借用一个连接，用完归还。"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


@contextlib.asynccontextmanager
async def transaction(conn: asyncpg.Connection) -> AsyncIterator[None]:
    """开启/提交一个事务；异常时回滚。"""
    await conn.execute("BEGIN")
    try:
        yield
    except BaseException:
        await conn.execute("ROLLBACK")
        raise
    else:
        await conn.execute("COMMIT")


@contextlib.asynccontextmanager
async def savepoint(
    conn: asyncpg.Connection, name: str = "etl_sp"
) -> AsyncIterator[None]:
    """在事务内建立/释放 savepoint；异常回滚到该 savepoint 后继续抛错。"""
    await conn.execute(f"SAVEPOINT {name}")
    try:
        yield
    except BaseException:
        await conn.execute(f"ROLLBACK TO SAVEPOINT {name}")
        raise
    else:
        await conn.execute(f"RELEASE SAVEPOINT {name}")


def vec_to_text(v: list[float]) -> str:
    """list[float] → pgvector 文本表示 '[0.1,0.2,...]'（供 ::vector 转换）。"""
    return "[" + ",".join(f"{x:.8f}" for x in v) + "]"


async def fetch_scalar(conn: asyncpg.Connection, sql: str, *args: Any) -> Any:
    return await conn.fetchval(sql, *args)


async def execute(conn: asyncpg.Connection, sql: str, *args: Any) -> str:
    return await conn.execute(sql, *args)
