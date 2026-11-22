"""
data/social/providers/rss.py
Generic RSS / news feed provider.

Supports any public RSS/Atom feed.  Designed for crypto news sources such as:
  - CoinDesk  https://www.coindesk.com/arc/outboundfeeds/rss/
  - The Block  https://www.theblock.co/rss.xml
  - Decrypt    https://decrypt.co/feed
  - Cointelegraph  https://cointelegraph.com/rss

Integration notes:
  - No API key required for public feeds
  - Minimal sentiment: heuristic keyword scoring only (no NLP model)
  - Designed as a lightweight fallback / supplementary signal layer
  - Parses both RSS 2.0 and Atom 1.0

Usage:
    provider = RSSNewsProvider(feeds=[
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "https://cointelegraph.com/rss",
    ])
"""

from __future__ import annotations

import hashlib
import re
import time
import xml.etree.ElementTree as ET
import aiohttp
from typing import List

from data.social.providers.base import SocialProvider
from data.social.schemas import RawSocialPost

# Crude keyword-based sentiment signals
_BULLISH_WORDS = {
    "surge", "rally", "breakout", "bullish", "accumulation", "etf", "adoption",
    "institutional", "inflow", "upgrade", "all-time high", "ath", "growth",
    "partnership", "launch", "approval", "unlock", "milestone",
}
_BEARISH_WORDS = {
    "crash", "dump", "bearish", "outflow", "hack", "exploit", "sec", "ban",
    "regulation", "fine", "lawsuit", "fear", "sell-off", "liquidation",
    "decline", "drop", "plunge", "loss", "risk", "warning",
}

_DEFAULT_FEEDS = [
    "https://cointelegraph.com/rss",
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
]


class RSSNewsProvider(SocialProvider):
    """
    Fetches articles from RSS/Atom feeds and filters them by asset keyword.
    Returns RawSocialPost with heuristic sentiment scoring.
    """

    name = "RSS/News"
    source_tag = "news"

    def __init__(
        self,
        feeds: List[str] | None = None,
        asset_aliases: dict[str, list[str]] | None = None,
        enabled: bool = True,
        session: aiohttp.ClientSession | None = None,
    ):
        super().__init__(enabled=enabled)
        self.feeds = feeds or _DEFAULT_FEEDS
        # Mapping from asset ticker to search keywords
        self.asset_aliases = asset_aliases or {
            "ETH": ["ethereum", "eth", "ether", "vitalik"],
            "BTC": ["bitcoin", "btc", "satoshi"],
        }
        self._session = session

    # ------------------------------------------------------------------
    # collect()
    # ------------------------------------------------------------------

    async def collect(self, asset: str = "ETH") -> List[RawSocialPost]:
        keywords = [k.lower() for k in self.asset_aliases.get(asset.upper(), [asset.lower()])]
        posts: List[RawSocialPost] = []

        session = self._session
        close_after = False
        if session is None:
            session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
            close_after = True

        try:
            for feed_url in self.feeds:
                items = await self._fetch_feed(session, feed_url, keywords)
                posts.extend(items)
        finally:
            if close_after:
                await session.close()

        return posts

    # ------------------------------------------------------------------
    # Feed parsing
    # ------------------------------------------------------------------

    async def _fetch_feed(
        self, session: aiohttp.ClientSession, url: str, keywords: List[str]
    ) -> List[RawSocialPost]:
        try:
            async with session.get(url, headers={"User-Agent": "ETH-Intelligence-OS/1.0"}) as resp:
                resp.raise_for_status()
                xml_text = await resp.text()
        except Exception:
            return []

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return []

        # Support both RSS 2.0 (<item>) and Atom (<entry>)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        items = root.findall(".//item") or root.findall(".//atom:entry", ns)

        posts = []
        for item in items[:30]:  # cap at 30 per feed
            title = self._text(item, ["title", "atom:title"], ns)
            desc  = self._text(item, ["description", "summary", "atom:summary"], ns)
            link  = self._text(item, ["link", "atom:link"], ns)
            pub   = self._text(item, ["pubDate", "published", "atom:published"], ns)

            combined = f"{title} {desc}".lower()
            if not any(kw in combined for kw in keywords):
                continue  # not relevant to this asset

            sentiment = self._heuristic_sentiment(combined)
            post_id = hashlib.md5((url + title).encode()).hexdigest()[:12]

            posts.append(RawSocialPost(
                id=f"rss-{post_id}",
                source="news",
                text=f"{title}. {desc}"[:500],
                timestamp=pub or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                likes=0,
                shares=0,
                views=0,
                topics=self._extract_topics(combined),
                provider_sentiment=sentiment,
            ))
        return posts

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _text(item: ET.Element, tags: list[str], ns: dict) -> str:
        for tag in tags:
            el = item.find(tag, ns) if ":" in tag else item.find(tag)
            if el is not None and el.text:
                return el.text.strip()
        return ""

    @staticmethod
    def _heuristic_sentiment(text: str) -> float:
        """
        Fast keyword sentiment in [-1, +1].
        Not a replacement for NLP — only a coarse signal for news articles.
        """
        words = set(re.findall(r"\b\w+\b", text.lower()))
        bull = len(words & _BULLISH_WORDS)
        bear = len(words & _BEARISH_WORDS)
        total = bull + bear
        if total == 0:
            return 0.0
        return round((bull - bear) / total, 2)

    @staticmethod
    def _extract_topics(text: str) -> List[str]:
        topics = []
        topic_map = {
            "etf": ["etf", "exchange-traded fund"],
            "regulation": ["sec", "regulation", "ban", "lawsuit", "cftc"],
            "l2": ["layer 2", "l2", "rollup", "optimism", "arbitrum", "base"],
            "staking": ["staking", "stake", "validator", "yield"],
            "whale": ["whale", "large wallet", "dormant"],
            "defi": ["defi", "protocol", "liquidity", "tvl"],
            "macro": ["inflation", "fed", "interest rate", "gdp", "dollar"],
        }
        for topic, keywords in topic_map.items():
            if any(kw in text for kw in keywords):
                topics.append(topic)
        return topics
