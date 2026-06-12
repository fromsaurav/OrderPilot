"""Async Postgres access (asyncpg). Used by both the FastAPI process and the worker
process; each holds its own pool against the same database.
"""
from __future__ import annotations

import pathlib
from typing import Any, Optional

import asyncpg

from .config import get_settings

_SCHEMA_PATH = pathlib.Path(__file__).with_name("schema.sql")


class Database:
    def __init__(self) -> None:
        self._pool: Optional[asyncpg.Pool] = None

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("Database pool not initialized; call connect() first")
        return self._pool

    async def connect(self) -> None:
        s = get_settings()
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                dsn=s.dsn, min_size=s.db_min_size, max_size=s.db_max_size
            )

    async def init_schema(self) -> None:
        """Idempotent schema creation (Decision #8)."""
        sql = _SCHEMA_PATH.read_text()
        async with self.pool.acquire() as conn:
            await conn.execute(sql)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def execute(self, query: str, *args: Any) -> str:
        async with self.pool.acquire() as conn:
            return await conn.execute(query, *args)

    async def fetch(self, query: str, *args: Any) -> list[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, *args)

    async def fetchrow(self, query: str, *args: Any) -> Optional[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(query, *args)


# Module-level singletons (one per process).
db = Database()
