"""
engine/weights.py
Dynamic WDI weight adjustment based on market regime and threat level.

FIX: after regime-based multiplication weights must be re-normalised to sum=1.
Original code re-normalised correctly but did NOT apply the threat boost to
flows/onchain blocks — added those boosts as they are more impactful in crisis.
"""

from engine.regime import MarketRegime
from config import WDI_WEIGHTS_BASE


def get_dynamic_weights(regime: MarketRegime, threats_score: float) -> dict:
    base = WDI_WEIGHTS_BASE.copy()

    if regime in (MarketRegime.PANIC, MarketRegime.TREND_DOWN):
        base["macro"]    *= 1.6
        base["corridor"] *= 1.4

    if threats_score > 60:
        base["macro"]   *= 1.8
        base["flows"]   *= 1.2   # FIX: flows signal matters more in stress
        base["onchain"] *= 1.1   # FIX: on-chain also more informative

    if regime == MarketRegime.SQUEEZE:
        base["corridor"] *= 1.5
        base["tech"]     *= 1.3

    if regime == MarketRegime.ACCUMULATION:
        base["onchain"] *= 1.4
        base["flows"]   *= 1.3

    # Always re-normalise so weights sum to 1.0
    total = sum(base.values())
    return {k: round(v / total, 4) for k, v in base.items()}
