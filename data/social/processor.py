"""
data/social/processor.py
Transforms raw social posts into SocialFeatures and detected Narratives.

Pipeline:
  Step 1  — Sentiment scoring (uses provider_sentiment if available, else heuristic)
  Step 2  — Engagement aggregation and velocity calculation
  Step 3  — Influencer / bot separation
  Step 4  — Emotional extreme detection (panic / euphoria)
  Step 5  — Narrative clustering (keyword-based topic grouping)
  Step 6  — Feature normalization to consistent ranges

All output metrics are clamped to documented ranges before returning.
No external ML models required — designed to work in any Python environment.

The processor is stateless and pure (aside from optional previous_features
for velocity calculation).  Call process() freely from any context.
"""

from __future__ import annotations

import math
import re
from typing import List, Optional

from data.social.schemas import RawSocialPost, SocialFeatures, Narrative, SocialSnapshot

# ---------------------------------------------------------------------------
# Sentiment keyword lexicons
# ---------------------------------------------------------------------------

_BULLISH = {
    "bullish", "buy", "long", "moon", "pump", "rally", "breakout", "surge",
    "accumulate", "accumulation", "undervalued", "support", "bounce", "ath",
    "etf", "inflow", "adoption", "upgrade", "bullrun", "parabolic", "rip",
    "🚀", "📈", "🟢", "🐂", "💎", "🙌",
}

_BEARISH = {
    "bearish", "sell", "short", "dump", "crash", "plunge", "decline", "drop",
    "panic", "fear", "overvalued", "resistance", "breakdown", "liquidation",
    "outflow", "hack", "exploit", "ban", "regulation", "lawsuit", "sue",
    "exit", "rug", "scam", "rekt", "bearrun", "correction",
    "😱", "📉", "🔴", "🐻", "💀",
}

_PANIC = {
    "panic", "crash", "rekt", "liquidated", "scared", "fear", "terror",
    "emergency", "disaster", "dead", "worthless", "zero", "capitulation",
}

_EUPHORIA = {
    "moon", "lambo", "millionaire", "100x", "1000x", "to the moon",
    "financial freedom", "life changing", "never selling", "fomo",
    "ath", "all time high", "parabolic", "supercycle", "🚀🚀🚀",
}

# ---------------------------------------------------------------------------
# Narrative keyword taxonomy
# (order matters — first match wins for the primary topic)
# ---------------------------------------------------------------------------

_NARRATIVE_TAXONOMY: list[tuple[str, list[str]]] = [
    ("ETH ETF accumulation",     ["etf", "etf inflow", "institutional", "blackrock", "fidelity"]),
    ("Base ecosystem growth",    ["base", "base l2", "base ecosystem", "base chain"]),
    ("L2 expansion",             ["l2", "layer 2", "rollup", "arbitrum", "optimism", "zk"]),
    ("Staking yield",            ["staking", "stake", "yield", "validator", "lido", "eigenlayer"]),
    ("DeFi resurgence",          ["defi", "protocol", "tvl", "liquidity", "amm", "lending"]),
    ("Regulatory clarity",       ["regulation", "sec", "cftc", "clarity", "approved", "legal"]),
    ("Macro risk-off",           ["recession", "inflation", "rate", "fed", "dollar", "risk-off"]),
    ("Whale activity",           ["whale", "large wallet", "dormant", "moved"]),
    ("Technical breakout",       ["breakout", "resistance", "support", "ma", "rsi", "macd"]),
    ("Stablecoin demand",        ["stablecoin", "usdc", "usdt", "dai", "stable"]),
]

# ---------------------------------------------------------------------------
# SocialProcessor
# ---------------------------------------------------------------------------


class SocialProcessor:
    """
    Stateless processor that converts a list of RawSocialPost into
    SocialFeatures + List[Narrative].

    Parameters
    ----------
    previous_features : optional SocialFeatures from the prior cycle.
        Used to compute velocity (attention_acceleration).
    influencer_weight : float
        Multiplier applied to influencer post engagement in weighted averages.
    min_posts_for_confidence : int
        Below this count, data_quality degrades linearly.
    """

    def __init__(
        self,
        previous_features: Optional[SocialFeatures] = None,
        influencer_weight: float = 3.0,
        min_posts_for_confidence: int = 20,
    ):
        self.prev = previous_features
        self.influencer_weight = influencer_weight
        self.min_posts_for_confidence = min_posts_for_confidence

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def process(self, posts: List[RawSocialPost], asset: str = "ETH") -> tuple[SocialFeatures, List[Narrative]]:
        """
        Process raw posts → (SocialFeatures, [Narrative]).

        Returns default features if posts is empty.
        """
        if not posts:
            return SocialFeatures(data_quality=0.0), []

        features = self._compute_features(posts)
        narratives = self._detect_narratives(posts)
        return features, narratives

    def build_snapshot(
        self,
        posts: List[RawSocialPost],
        coverage: dict[str, int],
        asset: str = "ETH",
    ) -> SocialSnapshot:
        """Convenience: build full SocialSnapshot from collection output."""
        features, narratives = self.process(posts, asset=asset)
        return SocialSnapshot(
            asset=asset,
            posts=posts,
            features=features,
            narratives=narratives,
            provider_coverage=coverage,
        )

    # ------------------------------------------------------------------
    # Step 1 — Sentiment
    # ------------------------------------------------------------------

    def _sentiment(self, post: RawSocialPost) -> float:
        """
        Returns sentiment in [-1, +1].
        Provider-supplied sentiment trusted at 80%, blended with 20% heuristic.
        """
        heuristic = self._heuristic_sentiment(post.text)
        if post.provider_sentiment is not None:
            return 0.8 * post.provider_sentiment + 0.2 * heuristic
        return heuristic

    @staticmethod
    def _heuristic_sentiment(text: str) -> float:
        tokens = set(re.findall(r"\b\w+\b", text.lower()))
        # include emoji-like chars
        tokens.update(ch for ch in text if ord(ch) > 0x2000)
        bull = len(tokens & _BULLISH)
        bear = len(tokens & _BEARISH)
        total = bull + bear
        if total == 0:
            return 0.0
        return (bull - bear) / total

    # ------------------------------------------------------------------
    # Step 2 — Engagement
    # ------------------------------------------------------------------

    @staticmethod
    def _engagement_weight(post: RawSocialPost) -> float:
        """Log-compressed engagement so viral posts don't dominate."""
        raw = post.likes + post.shares * 2 + post.comments + post.views / 100 + post.mentions
        return math.log1p(raw)

    # ------------------------------------------------------------------
    # Steps 3–4 — Influencer / bot / emotional extremes
    # ------------------------------------------------------------------

    @staticmethod
    def _panic_score(text: str) -> float:
        tokens = set(re.findall(r"\b\w+\b", text.lower()))
        hits = len(tokens & _PANIC)
        return min(hits / 3.0, 1.0)

    @staticmethod
    def _euphoria_score(text: str) -> float:
        tokens = set(re.findall(r"\b\w+\b", text.lower()))
        hits = len(tokens & _EUPHORIA)
        return min(hits / 3.0, 1.0)

    # ------------------------------------------------------------------
    # Feature computation
    # ------------------------------------------------------------------

    def _compute_features(self, posts: List[RawSocialPost]) -> SocialFeatures:
        n = len(posts)
        data_quality = min(1.0, n / self.min_posts_for_confidence)

        sentiments: list[float] = []
        weighted_sentiments: list[tuple[float, float]] = []  # (sentiment, weight)
        influencer_sentiments: list[float] = []
        bot_count = 0
        panic_scores: list[float] = []
        euphoria_scores: list[float] = []
        total_engagement = 0.0
        influencer_engagements: list[float] = []

        for post in posts:
            s = self._sentiment(post)
            w = self._engagement_weight(post)
            if post.is_influencer:
                w_adj = w * self.influencer_weight
                influencer_sentiments.append(s)
                influencer_engagements.append(w_adj)
            else:
                w_adj = w
            sentiments.append(s)
            weighted_sentiments.append((s, w_adj))
            total_engagement += w_adj
            if post.suspected_bot:
                bot_count += 1
            panic_scores.append(self._panic_score(post.text))
            euphoria_scores.append(self._euphoria_score(post.text))

        # --- Sentiment score (engagement-weighted mean) ---
        if total_engagement > 0:
            sentiment_score = sum(s * w for s, w in weighted_sentiments) / total_engagement
        else:
            sentiment_score = sum(sentiments) / n if n > 0 else 0.0

        # --- Bullish/bearish ratios ---
        bullish_ratio = sum(1 for s in sentiments if s > 0.1) / n
        bearish_ratio = sum(1 for s in sentiments if s < -0.1) / n

        # --- Engagement metrics ---
        # attention_score: normalized total engagement (log scale, capped at 1.0)
        attention_score = min(math.log1p(total_engagement) / 15.0, 1.0)

        # engagement_velocity: compare to previous cycle if available
        prev_attention = self.prev.attention_score if self.prev else attention_score
        engagement_velocity = max(-2.0, min(3.0, attention_score - prev_attention))
        attention_acceleration = max(-2.0, min(3.0,
            engagement_velocity - (self.prev.engagement_velocity if self.prev else 0.0)
        ))

        # --- Influencer alignment: mean sentiment of influencer posts ---
        if influencer_sentiments:
            influencer_alignment = sum(influencer_sentiments) / len(influencer_sentiments)
        else:
            influencer_alignment = 0.0

        # --- Bot probability ---
        bot_probability = bot_count / n

        # --- Engagement anomaly: if influencer engagement >> normal average ---
        normal_posts = n - len(influencer_sentiments)
        if normal_posts > 0 and influencer_engagements:
            avg_inf_eng = sum(influencer_engagements) / len(influencer_engagements) / self.influencer_weight
            avg_norm_eng = (total_engagement - sum(influencer_engagements)) / normal_posts
            engagement_anomaly = min(1.0, max(0.0,
                (avg_inf_eng - avg_norm_eng) / (avg_norm_eng + 1e-6)
            ))
        else:
            engagement_anomaly = 0.0

        # --- Emotional extremes ---
        panic_score = min(1.0, sum(panic_scores) / n * 3)
        euphoria_score = min(1.0, sum(euphoria_scores) / n * 3)

        # --- Trend momentum: directional strength 0…1 ---
        trend_momentum = abs(sentiment_score) * attention_score

        # --- Narrative metrics (placeholder until _detect_narratives runs) ---
        # Will be filled by the caller who also has narrative output
        narrative_strength = 0.0
        narrative_concentration = 0.0

        return SocialFeatures(
            sentiment_score=round(sentiment_score, 3),
            bullish_ratio=round(bullish_ratio, 3),
            bearish_ratio=round(bearish_ratio, 3),
            engagement_velocity=round(engagement_velocity, 3),
            attention_score=round(attention_score, 3),
            attention_acceleration=round(attention_acceleration, 3),
            narrative_strength=round(narrative_strength, 3),
            narrative_concentration=round(narrative_concentration, 3),
            trend_momentum=round(trend_momentum, 3),
            influencer_alignment=round(influencer_alignment, 3),
            bot_probability=round(bot_probability, 3),
            engagement_anomaly=round(engagement_anomaly, 3),
            panic_score=round(panic_score, 3),
            euphoria_score=round(euphoria_score, 3),
            post_count=n,
            unique_sources=len({p.source for p in posts}),
            data_quality=round(data_quality, 2),
        )

    # ------------------------------------------------------------------
    # Step 5 — Narrative detection
    # ------------------------------------------------------------------

    def _detect_narratives(self, posts: List[RawSocialPost]) -> List[Narrative]:
        """
        Keyword-based narrative clustering.

        For each taxonomy entry, score how many posts match and what
        their aggregate engagement and sentiment are.  Returns narratives
        sorted by strength descending.
        """
        n = max(len(posts), 1)
        narrative_data: dict[str, dict] = {}

        for label, keywords in _NARRATIVE_TAXONOMY:
            narrative_data[label] = {
                "matches": 0,
                "engagement": 0.0,
                "sentiments": [],
                "sample_phrases": [],
            }

        for post in posts:
            text_lower = post.text.lower()
            for label, keywords in _NARRATIVE_TAXONOMY:
                if any(kw in text_lower for kw in keywords):
                    d = narrative_data[label]
                    d["matches"] += 1
                    d["engagement"] += self._engagement_weight(post)
                    d["sentiments"].append(self._sentiment(post))
                    if len(d["sample_phrases"]) < 3:
                        phrase = post.text[:80].strip()
                        if phrase not in d["sample_phrases"]:
                            d["sample_phrases"].append(phrase)

        narratives: List[Narrative] = []
        for label, d in narrative_data.items():
            if d["matches"] == 0:
                continue
            strength = min(1.0, d["matches"] / (n * 0.3))  # 30% of posts = full strength
            # velocity: if we have previous snapshot, could compare; for now use engagement density
            velocity = min(1.0, math.log1p(d["engagement"]) / 10.0)
            avg_sentiment = (
                sum(d["sentiments"]) / len(d["sentiments"]) if d["sentiments"] else 0.0
            )
            narratives.append(Narrative(
                narrative=label,
                strength=round(strength, 2),
                velocity=round(velocity, 2),
                sentiment=round(avg_sentiment, 2),
                sample_phrases=d["sample_phrases"],
            ))

        narratives.sort(key=lambda x: x.strength, reverse=True)
        return narratives[:6]  # top 6 narratives

    # ------------------------------------------------------------------
    # Narrative → feature enrichment (call after process())
    # ------------------------------------------------------------------

    @staticmethod
    def enrich_features_with_narratives(
        features: SocialFeatures, narratives: List[Narrative]
    ) -> SocialFeatures:
        """
        Back-fill narrative_strength and narrative_concentration into features
        after narrative detection completes.

        Returns a new SocialFeatures instance (features are immutable by convention).
        """
        if not narratives:
            return features

        top_strength = narratives[0].strength
        total_strength = sum(n.strength for n in narratives)
        concentration = top_strength / total_strength if total_strength > 0 else 0.0

        return features.model_copy(update={
            "narrative_strength": round(top_strength, 3),
            "narrative_concentration": round(concentration, 3),
        })
