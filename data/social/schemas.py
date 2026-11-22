"""
data/social/schemas.py
Pydantic models for the Social Intelligence Layer.

RawSocialPost   — one unit of raw social data from any provider
SocialFeatures  — normalized intelligence features injected into the feature engine
Narrative       — a single detected narrative with strength/velocity
SocialSnapshot  — container for a full social data collection cycle
"""

from pydantic import BaseModel, Field
from typing import Literal, Optional
from datetime import datetime


# ---------------------------------------------------------------------------
# Raw social unit — provider-agnostic
# ---------------------------------------------------------------------------

class RawSocialPost(BaseModel):
    """
    Single social signal unit.  All fields are optional except id/source/text/ts
    because not every platform surfaces the same metadata.
    """
    id: str
    source: Literal[
        "twitter", "reddit", "telegram", "openklav",
        "hermes", "news", "rss", "research", "unknown"
    ]
    text: str
    timestamp: str                      # ISO-8601 UTC
    author_id: Optional[str] = None
    author_followers: Optional[int] = None
    is_influencer: bool = False         # followers > configurable threshold

    # Engagement signals (raw counts — normalized later)
    likes: int = 0
    shares: int = 0
    comments: int = 0
    views: int = 0
    mentions: int = 0

    # Pre-tagged metadata (provider may supply, processor also computes)
    hashtags: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)

    # Provider-level sentiment if available (e.g. OpenKlav)
    provider_sentiment: Optional[float] = None  # -1…+1 or None

    # Spam/bot indicators (provider or heuristic)
    suspected_bot: bool = False


# ---------------------------------------------------------------------------
# Processed social intelligence features — injected into feature engine
# ---------------------------------------------------------------------------

class SocialFeatures(BaseModel):
    """
    All values normalized to consistent ranges:
      - Scores / ratios: 0.0…1.0
      - Velocities / accelerations: unbounded but typically -1…+3
      - Probabilities: 0.0…1.0

    These fields are injected DIRECTLY into the feature dict consumed by
    existing agents — no SocialAgent middleman required.
    """
    # --- Sentiment ---
    sentiment_score: float = 0.0       # -1 (max bearish) … +1 (max bullish)
    bullish_ratio: float = 0.0         # fraction of posts classified bullish
    bearish_ratio: float = 0.0         # fraction of posts classified bearish

    # --- Attention / engagement velocity ---
    engagement_velocity: float = 0.0   # engagement growth rate (Δengagement/t)
    attention_score: float = 0.0       # 0…1 composite attention level
    attention_acceleration: float = 0.0  # 2nd derivative — rising = new catalyst

    # --- Narrative ---
    narrative_strength: float = 0.0    # 0…1 how dominant the top narrative is
    narrative_concentration: float = 0.0  # 0…1 how focused (1 = one narrative)

    # --- Trend ---
    trend_momentum: float = 0.0        # 0…1 directional social momentum

    # --- Influence ---
    influencer_alignment: float = 0.0  # -1…+1  (positive = influencers bullish)

    # --- Manipulation / anomaly ---
    bot_probability: float = 0.0       # 0…1  fraction of posts suspected bot
    engagement_anomaly: float = 0.0    # 0…1  unusual engagement spikes

    # --- Emotional extremes ---
    panic_score: float = 0.0           # 0…1  fear / panic level
    euphoria_score: float = 0.0        # 0…1  euphoria / FOMO level

    # --- Meta ---
    post_count: int = 0
    unique_sources: int = 0
    data_quality: float = 1.0          # 0…1  coverage / freshness confidence


# ---------------------------------------------------------------------------
# Narrative detection output
# ---------------------------------------------------------------------------

class Narrative(BaseModel):
    narrative: str
    strength: float    # 0…1  share of discourse this narrative holds
    velocity: float    # 0…1  how fast it is spreading right now
    sentiment: float = 0.0  # -1…+1 net sentiment around this narrative
    sample_phrases: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Top-level snapshot — one full collection + processing cycle
# ---------------------------------------------------------------------------

class SocialSnapshot(BaseModel):
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    asset: str = "ETH"
    posts: list[RawSocialPost] = Field(default_factory=list)
    features: SocialFeatures = Field(default_factory=SocialFeatures)
    narratives: list[Narrative] = Field(default_factory=list)
    provider_coverage: dict[str, int] = Field(default_factory=dict)
