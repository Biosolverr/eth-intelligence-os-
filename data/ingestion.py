"""
data/ingestion.py
Async market data ingestor with caching.

FIX: RawMarketData model used "flows" and "onchain" as separate fields,
but core.py and agents expect a unified "flows" dict combining both.
Merged to match schema.  Stub data structure aligned with RawInput schema.
"""

import os
import asyncio
import aiohttp
import json
import time
from datetime import datetime, UTC
from typing import Dict, Any, Optional

from pydantic import BaseModel
from data.cache_layer import get_cache


class RawMarketData(BaseModel):
    timestamp: str
    asset: str
    price: Dict
    derivatives: Dict
    flows: Dict
    macro: Dict
    recession: Dict
    corridor: Dict


class MarketIngestor:
    def __init__(self):
        self.cache = get_cache()
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15)
        )
        return self

    async def __aexit__(self, *exc):
        if self.session:
            await self.session.close()
        await self.cache.close()

    async def _safe_fetch(self, url: str, cache_key: str, ttl: int = 300) -> Optional[dict]:
        """Fetch URL with cache-aside pattern."""
        cached = await self.cache.get(cache_key)
        if cached:
            return cached
        if not self.session:
            return None
        try:
            async with self.session.get(url) as resp:
                resp.raise_for_status()
                data = await resp.json()
                await self.cache.set(cache_key, data, ttl)
                return data
        except Exception as e:
            print(f"[Ingestor] Failed {url}: {e}")
            return None

    async def fetch(self, asset: str = "ETH") -> Dict:
        """
        Returns a dict compatible with RawInput schema.
        In production: replace stub values with real API calls using _safe_fetch.
        """
        # The former stub returned HARD-CODED market numbers that looked like observations.
        # Fabricated evidence must never reach a snapshot, so it now fails loudly.
        raise NotImplementedError(
            "No live market ingestion is implemented. Supply real observations with provenance "
            "via input.json / client.snapshot.build_snapshot()."
        )
