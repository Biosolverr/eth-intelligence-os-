"""
data/social/providers/hermes.py
Hermes social intelligence provider.

Hermes is a crypto-native narrative tracking platform that specializes in
early narrative detection via crypto Twitter, Discord servers, and news
aggregators.  Unlike OpenKlav (which returns post-level data), Hermes
primarily returns narrative-level summaries with associated mention counts
and velocity metrics.

Integration notes:
  - Requires HERMES_API_KEY env variable
  - Hermes returns "signal bundles" — groups of posts around a detected theme
  - Rate limit: 60 req/min

API reference: https://api.hermes.finance/docs  (stub implementation)
"""

from __future__ import annotations

import os
import time
import uuid
import aiohttp
from typing import List

from data.social.providers.base import SocialProvider
from data.social.schemas import RawSocialPost

_API_BASE = "https://api.hermes.finance/v2"


class HermesProvider(SocialProvider):
    """
    Fetches narrative signal bundles from Hermes API and unpacks them
    into individual RawSocialPost records so the processor can handle
    all providers uniformly.
    """

    name = "Hermes"
    source_tag = "hermes"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = _API_BASE,
        enabled: bool = True,
        session: aiohttp.ClientSession | None = None,
    ):
        super().__init__(enabled=enabled)
        self.api_key = api_key or os.getenv("HERMES_API_KEY", "")
        self.base_url = base_url
        self._session = session

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
        headers = {"X-Api-Key": self.api_key, "Accept": "application/json"}
        params = {"ticker": asset, "window": "2h", "limit": 50}

        session = self._session
        close_after = False
        if session is None:
            session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
            close_after = True

        try:
            async with session.get(
                f"{self.base_url}/narratives", headers=headers, params=params
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
        finally:
            if close_after:
                await session.close()

        posts: List[RawSocialPost] = []
        for bundle in data.get("bundles", []):
            posts.extend(self._unpack_bundle(bundle))
        return posts

    def _unpack_bundle(self, bundle: dict) -> List[RawSocialPost]:
        """
        Hermes bundles → synthetic RawSocialPost records.

        Each bundle represents a cluster of posts around one narrative.
        We synthesize representative posts with aggregate engagement split
        across representative_texts (or a single summary if unavailable).
        """
        texts = bundle.get("representative_texts") or [bundle.get("summary", "")]
        total_mentions = bundle.get("total_mentions", 1)
        sentiment = bundle.get("sentiment", 0.0)
        now = bundle.get("detected_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

        posts = []
        per_post_mentions = max(1, total_mentions // len(texts))
        for text in texts:
            posts.append(RawSocialPost(
                id=f"hermes-{uuid.uuid4().hex[:8]}",
                source="hermes",
                text=text,
                timestamp=now,
                mentions=per_post_mentions,
                likes=per_post_mentions * 3,
                views=per_post_mentions * 20,
                topics=[bundle.get("narrative_label", "unknown")],
                provider_sentiment=sentiment,
            ))
        return posts

    # ------------------------------------------------------------------
    # Stub data
    # ------------------------------------------------------------------

    def _stub_data(self, asset: str) -> List[RawSocialPost]:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        bundles = [
            {
                "narrative_label": "base_ecosystem_growth",
                "summary": f"Base L2 ecosystem expanding rapidly, drawing attention to {asset} as settlement layer.",
                "total_mentions": 2800,
                "sentiment": 0.71,
                "detected_at": now,
            },
            {
                "narrative_label": "eth_etf_accumulation",
                "summary": f"Spot {asset} ETF sees consistent institutional inflows, supply pressure rising.",
                "total_mentions": 1950,
                "sentiment": 0.63,
                "detected_at": now,
            },
            {
                "narrative_label": "layer2_fee_compression",
                "summary": "L2 fees near zero reducing Ethereum mainnet revenue, bears highlight declining fee burn.",
                "total_mentions": 740,
                "sentiment": -0.28,
                "detected_at": now,
            },
            {
                "narrative_label": "stablecoin_demand",
                "summary": f"Stablecoin issuance on {asset} network increasing — historical on-chain bullish signal.",
                "total_mentions": 1100,
                "sentiment": 0.44,
                "detected_at": now,
            },
        ]
        posts: List[RawSocialPost] = []
        for b in bundles:
            posts.extend(self._unpack_bundle(b))
        return posts
