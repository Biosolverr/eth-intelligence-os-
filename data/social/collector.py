"""
data/social/collector.py
Orchestrates parallel collection from all registered social providers.

Responsibilities:
  - Holds a shared aiohttp session for connection pooling
  - Fans out to all providers concurrently (asyncio.gather)
  - Merges and deduplicates posts by id
  - Returns a raw list ready for SocialProcessor

Design constraint: collector knows nothing about features or narratives.
That is the processor's domain.  Collector only aggregates raw posts.

Usage:
    async with SocialCollector() as collector:
        posts = await collector.collect(asset="ETH")
"""

from __future__ import annotations

import asyncio
import logging
from typing import List, Optional

import aiohttp

from data.social.providers.base import SocialProvider
from data.social.providers.openklav import OpenKlavProvider
from data.social.providers.hermes import HermesProvider
from data.social.providers.rss import RSSNewsProvider
from data.social.schemas import RawSocialPost

logger = logging.getLogger(__name__)


def _default_providers(session: aiohttp.ClientSession) -> List[SocialProvider]:
    """
    Returns the default provider stack.
    Providers are tried in parallel; failures are silently skipped.

    To add a new provider:
      1. Implement SocialProvider subclass
      2. Instantiate it here with `session=session`
      3. Append to the list
    """
    return [
        OpenKlavProvider(session=session),
        HermesProvider(session=session),
        RSSNewsProvider(session=session),
    ]


class SocialCollector:
    """
    Async context manager that collects raw social posts from all providers.

    Parameters
    ----------
    providers : optional list of SocialProvider instances.
        Defaults to [OpenKlav, Hermes, RSS].  Pass a custom list for testing
        or to extend with new providers.
    timeout : int
        Maximum seconds to wait for all providers (default 20).
    """

    def __init__(
        self,
        providers: Optional[List[SocialProvider]] = None,
        timeout: int = 20,
    ):
        self._providers = providers  # None → build from session in __aenter__
        self.timeout = timeout
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self) -> "SocialCollector":
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.timeout)
        )
        if self._providers is None:
            self._providers = _default_providers(self._session)
        return self

    async def __aexit__(self, *exc) -> None:
        if self._session:
            await self._session.close()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def collect(self, asset: str = "ETH") -> List[RawSocialPost]:
        """
        Collect posts from all enabled providers in parallel.

        Returns deduplicated list sorted by timestamp descending.
        """
        if not self._providers:
            return []

        tasks = [p.safe_collect(asset=asset) for p in self._providers]
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as exc:
            logger.error("SocialCollector.collect() gather failed: %s", exc)
            return []

        all_posts: List[RawSocialPost] = []
        seen_ids: set[str] = set()

        for provider, result in zip(self._providers, results):
            if isinstance(result, Exception):
                logger.warning("[%s] raised exception: %s", provider.name, result)
                continue
            for post in result:
                if post.id not in seen_ids:
                    seen_ids.add(post.id)
                    all_posts.append(post)

        # Sort: newest first (ISO timestamps compare correctly as strings)
        all_posts.sort(key=lambda p: p.timestamp, reverse=True)

        logger.info(
            "SocialCollector collected %d unique posts from %d providers for %s",
            len(all_posts), len(self._providers), asset,
        )
        return all_posts

    async def collect_with_coverage(
        self, asset: str = "ETH"
    ) -> tuple[List[RawSocialPost], dict[str, int]]:
        """
        Like collect(), but also returns per-provider post counts.
        Used by SocialSnapshot to populate provider_coverage.
        """
        if not self._providers:
            return [], {}

        tasks = [p.safe_collect(asset=asset) for p in self._providers]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_posts: List[RawSocialPost] = []
        seen_ids: set[str] = set()
        coverage: dict[str, int] = {}

        for provider, result in zip(self._providers, results):
            if isinstance(result, Exception):
                coverage[provider.name] = 0
                continue
            count = 0
            for post in result:
                if post.id not in seen_ids:
                    seen_ids.add(post.id)
                    all_posts.append(post)
                    count += 1
            coverage[provider.name] = count

        all_posts.sort(key=lambda p: p.timestamp, reverse=True)
        return all_posts, coverage
