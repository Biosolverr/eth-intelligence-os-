"""
data/social/providers/base.py
Abstract base class for all social data providers.

Design principles:
  - Provider-agnostic interface: every provider returns List[RawSocialPost]
  - Async-first: collect() is always a coroutine
  - Composable: collectors stack providers without knowing their internals
  - Graceful degradation: failed providers return empty list, never raise

Adding a new provider:
    1. Subclass SocialProvider
    2. Implement collect() — return List[RawSocialPost]
    3. Register in data/social/providers/__init__.py
    4. Instantiate in SocialCollector (data/social/collector.py)

The base class handles:
  - Provider identity (name, source_tag)
  - Influencer classification threshold
  - Bot heuristic hook (override _is_bot() for provider-specific logic)
  - Safe collect wrapper that catches all exceptions
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import List, Optional

from data.social.schemas import RawSocialPost

logger = logging.getLogger(__name__)

# Default follower count to classify a post author as an influencer
DEFAULT_INFLUENCER_THRESHOLD = 10_000


class SocialProvider(ABC):
    """
    Abstract base for social data providers.

    Attributes
    ----------
    name : str
        Human-readable provider name (e.g. "OpenKlav").
    source_tag : str
        Literal matching RawSocialPost.source discriminator.
    influencer_threshold : int
        Minimum follower count to flag author as influencer.
    enabled : bool
        Set to False to skip this provider without removing it.
    """

    name: str = "base"
    source_tag: str = "unknown"
    influencer_threshold: int = DEFAULT_INFLUENCER_THRESHOLD

    def __init__(
        self,
        enabled: bool = True,
        influencer_threshold: int = DEFAULT_INFLUENCER_THRESHOLD,
    ):
        self.enabled = enabled
        self.influencer_threshold = influencer_threshold

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def safe_collect(self, asset: str = "ETH") -> List[RawSocialPost]:
        """
        Wrapper around collect() that:
          - Skips disabled providers
          - Catches all exceptions and returns [] on failure
          - Logs errors for observability
        """
        if not self.enabled:
            return []
        try:
            posts = await self.collect(asset=asset)
            # Post-process: classify influencers, run bot heuristic
            for post in posts:
                if post.author_followers is not None:
                    post.is_influencer = post.author_followers >= self.influencer_threshold
                if not post.suspected_bot:
                    post.suspected_bot = self._is_bot(post)
            logger.debug("[%s] collected %d posts for %s", self.name, len(posts), asset)
            return posts
        except asyncio.CancelledError:
            raise  # always propagate cancellation
        except Exception as exc:
            logger.warning("[%s] collection failed: %s", self.name, exc)
            return []

    @abstractmethod
    async def collect(self, asset: str = "ETH") -> List[RawSocialPost]:
        """
        Fetch raw posts from the provider.

        Must be implemented by each subclass.  Should NOT catch exceptions —
        safe_collect() handles that.

        Parameters
        ----------
        asset : str
            The asset ticker to query (e.g. "ETH", "BTC").

        Returns
        -------
        List[RawSocialPost]
        """
        ...

    # ------------------------------------------------------------------
    # Override hooks
    # ------------------------------------------------------------------

    def _is_bot(self, post: RawSocialPost) -> bool:
        """
        Heuristic bot detection.  Override in subclasses for provider-
        specific signals (account age, follower/following ratio, etc.).

        Base implementation checks:
          - Zero followers, positive engagement (bot amplifier pattern)
          - Suspiciously uniform post timing (hard to detect here, done in processor)
        """
        if post.author_followers == 0 and (post.likes + post.shares) > 10:
            return True
        return False

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r} enabled={self.enabled}>"
