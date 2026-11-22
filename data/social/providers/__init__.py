"""data/social/providers/__init__.py"""
from data.social.providers.base import SocialProvider
from data.social.providers.openklav import OpenKlavProvider
from data.social.providers.hermes import HermesProvider
from data.social.providers.rss import RSSNewsProvider

__all__ = [
    "SocialProvider",
    "OpenKlavProvider",
    "HermesProvider",
    "RSSNewsProvider",
]
