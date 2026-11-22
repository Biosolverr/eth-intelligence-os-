"""
data/social/providers/openklav.py
OpenKlav social intelligence provider.

OpenKlav is a crypto-native social analytics platform that aggregates
signals from Twitter/X, Telegram, and Reddit, providing pre-processed
sentiment scores alongside raw post data.

Integration notes:
  - Requires OPENKLAV_API_KEY env variable
  - Rate limit: 100 req/min on standard tier
  - Response includes provider_sentiment (-1…+1) which the processor
    trusts at 0.8 weight vs local NLP

API reference: https://docs.openklav.io  (stub implementation)
"""

from __future__ import annotations

import os
import time
import uuid
import aiohttp
from typing import List

from data.social.providers.base import SocialProvider
from data.social.schemas import RawSocialPost

_API_BASE = "https://api.openklav.io/v1"
_INFLUENCER_THRESHOLD = 50_000  # OpenKlav tracks macro-influencers


class OpenKlavProvider(SocialProvider):
    """
    Fetches social signals from OpenKlav API.

    In production: set OPENKLAV_API_KEY and OPENKLAV_API_BASE (optional override).
    In development / CI: stub data is returned when no API key is set.
    """

    name = "OpenKlav"
    source_tag = "openklav"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = _API_BASE,
        influencer_threshold: int = _INFLUENCER_THRESHOLD,
        enabled: bool = True,
        session: aiohttp.ClientSession | None = None,
    ):
        super().__init__(enabled=enabled, influencer_threshold=influencer_threshold)
        self.api_key = api_key or os.getenv("OPENKLAV_API_KEY", "")
        self.base_url = base_url
        self._session = session  # injected from collector for connection pooling

    # ------------------------------------------------------------------
    # collect()
    # ------------------------------------------------------------------

    async def collect(self, asset: str = "ETH") -> List[RawSocialPost]:
        if not self.api_key:
            return self._stub_data(asset)
        return await self._fetch_live(asset)

    # ------------------------------------------------------------------
    # Live fetch
    # ------------------------------------------------------------------

    async def _fetch_live(self, asset: str) -> List[RawSocialPost]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        params = {
            "asset": asset,
            "limit": 100,
            "include_sentiment": "true",
            "window": "1h",
        }

        session = self._session
        close_after = False
        if session is None:
            session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
            close_after = True

        try:
            async with session.get(
                f"{self.base_url}/signals", headers=headers, params=params
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
        finally:
            if close_after:
                await session.close()

        return [self._parse_post(item) for item in data.get("signals", [])]

    def _parse_post(self, item: dict) -> RawSocialPost:
        return RawSocialPost(
            id=item.get("id", str(uuid.uuid4())),
            source="openklav",
            text=item.get("text", ""),
            timestamp=item.get("created_at", ""),
            author_id=item.get("author_id"),
            author_followers=item.get("followers"),
            likes=item.get("likes", 0),
            shares=item.get("shares", 0),
            comments=item.get("comments", 0),
            views=item.get("views", 0),
            mentions=item.get("mentions", 0),
            hashtags=item.get("hashtags", []),
            topics=item.get("topics", []),
            provider_sentiment=item.get("sentiment"),
            suspected_bot=item.get("is_bot", False),
        )

    # ------------------------------------------------------------------
    # Stub data (development / no API key)
    # ------------------------------------------------------------------

    def _stub_data(self, asset: str) -> List[RawSocialPost]:
        """
        Returns realistic stub posts representing a mild bullish narrative.
        Used when OPENKLAV_API_KEY is absent so the pipeline still runs.
        """
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        posts = [
            RawSocialPost(
                id="ok-stub-001", source="openklav", timestamp=now,
                text=f"{asset} ETF inflows picking up. Institutions accumulating quietly.",
                author_followers=120_000, likes=840, shares=210, views=45_000,
                provider_sentiment=0.65,
                hashtags=["ETH", "ETF", "accumulation"],
                topics=["etf", "institutional"],
            ),
            RawSocialPost(
                id="ok-stub-002", source="openklav", timestamp=now,
                text=f"Base ecosystem TVL hit new ATH. L2 narrative very much alive for {asset}.",
                author_followers=85_000, likes=530, shares=170, views=28_000,
                provider_sentiment=0.72,
                hashtags=["Base", "L2", "ETH"],
                topics=["l2", "base", "ecosystem"],
            ),
            RawSocialPost(
                id="ok-stub-003", source="openklav", timestamp=now,
                text=f"{asset} staking yields declining — could rotate capital elsewhere.",
                author_followers=32_000, likes=190, shares=55, views=8_400,
                provider_sentiment=-0.20,
                hashtags=["ETH", "staking", "yield"],
                topics=["staking", "yield"],
            ),
            RawSocialPost(
                id="ok-stub-004", source="openklav", timestamp=now,
                text=f"Funding rates cooling on {asset}. Healthier setup for continuation.",
                author_followers=67_000, likes=410, shares=120, views=19_000,
                provider_sentiment=0.48,
                hashtags=["ETH", "funding", "derivatives"],
                topics=["derivatives", "funding"],
            ),
            RawSocialPost(
                id="ok-stub-005", source="openklav", timestamp=now,
                text=f"BREAKING: Large {asset} wallet moved 15k ETH to exchange. Watch out.",
                author_followers=9_000, likes=1_200, shares=680, views=92_000,
                provider_sentiment=-0.55,
                hashtags=["ETH", "whale", "exchange"],
                topics=["whale", "sell_pressure"],
            ),
        ]
        return posts
