"""
data/cache_layer.py
Two-backend async cache: SQLite (default/dev) and Redis (production).

FIX: SQLiteCache._init() used an instance attribute self.conn that could
be set to None in close() and then re-initialised in the next call —
safe, but used a bare 'if self.conn' check which evaluates False for a
closed connection object too.  Changed to check for None explicitly.
"""

import os
import json
import time
from abc import ABC, abstractmethod
from typing import Any, Optional

import aiosqlite
import redis.asyncio as aioredis


class BaseCache(ABC):
    @abstractmethod
    async def get(self, key: str) -> Optional[Any]: ...
    @abstractmethod
    async def set(self, key: str, value: Any, ttl: int = 3600) -> bool: ...
    @abstractmethod
    async def close(self) -> None: ...


class SQLiteCache(BaseCache):
    def __init__(self, path: str = "cache/data.db"):
        self.path = path
        self.conn: Optional[aiosqlite.Connection] = None

    async def _init(self):
        if self.conn is not None:  # FIX: explicit None check
            return
        import pathlib
        pathlib.Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = await aiosqlite.connect(self.path)
        await self.conn.execute(
            "CREATE TABLE IF NOT EXISTS api_cache "
            "(key TEXT PRIMARY KEY, value TEXT, expires_at REAL)"
        )
        await self.conn.commit()

    async def get(self, key: str) -> Optional[Any]:
        await self._init()
        async with self.conn.execute(
            "SELECT value, expires_at FROM api_cache WHERE key = ?", (key,)
        ) as cur:
            row = await cur.fetchone()
        if row and row[1] > time.time():
            return json.loads(row[0])
        return None

    async def set(self, key: str, value: Any, ttl: int = 3600) -> bool:
        await self._init()
        await self.conn.execute(
            "INSERT OR REPLACE INTO api_cache VALUES (?, ?, ?)",
            (key, json.dumps(value, default=str), time.time() + ttl),
        )
        await self.conn.commit()
        return True

    async def close(self):
        if self.conn is not None:
            await self.conn.close()
            self.conn = None


class RedisCache(BaseCache):
    def __init__(self, url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")):
        self.client = aioredis.from_url(url, decode_responses=True)

    async def get(self, key: str) -> Optional[Any]:
        val = await self.client.get(key)
        return json.loads(val) if val else None

    async def set(self, key: str, value: Any, ttl: int = 3600) -> bool:
        await self.client.set(key, json.dumps(value, default=str), ex=ttl)
        return True

    async def close(self):
        await self.client.aclose()


def get_cache() -> BaseCache:
    backend = os.getenv("CACHE_BACKEND", "sqlite").lower()
    if backend == "redis":
        return RedisCache()
    return SQLiteCache()
