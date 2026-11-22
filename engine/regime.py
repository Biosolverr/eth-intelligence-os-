"""
engine/regime.py
Market regime detection based on ATR, RSI, funding rate, and CEX delta.

FIX: added TREND_DOWN branch (was missing — RSI < 35 + high ATR went to CHOP).
"""

from enum import Enum


class MarketRegime(str, Enum):
    TREND_UP     = "trend_up"
    TREND_DOWN   = "trend_down"
    CHOP         = "chop"
    SQUEEZE      = "squeeze"
    PANIC        = "panic"
    ACCUMULATION = "accumulation"
    DISTRIBUTION = "distribution"


def detect_regime(
    atr: float,
    rsi: float,
    funding: float,
    cex_delta: float,
) -> MarketRegime:
    """
    Priority order (highest specificity first):
      1. PANIC       – high vol + negative funding (forced selling)
      2. SQUEEZE     – very low ATR (coiling)
      3. ACCUMULATION – CEX outflow + neutral RSI
      4. DISTRIBUTION – CEX inflow + overbought RSI
      5. TREND_UP    – overbought RSI, normal vol
      6. TREND_DOWN  – oversold RSI, elevated vol  [NEW FIX]
      7. CHOP        – everything else
    """
    if atr > 5.0 and funding < -0.05:
        return MarketRegime.PANIC
    if atr < 2.0:
        return MarketRegime.SQUEEZE
    if cex_delta < -2.0 and rsi < 55:
        return MarketRegime.ACCUMULATION
    if cex_delta > 2.0 and rsi > 65:
        return MarketRegime.DISTRIBUTION
    if rsi > 65:
        return MarketRegime.TREND_UP
    if rsi < 35 and atr > 3.5:           # FIX: was falling through to CHOP
        return MarketRegime.TREND_DOWN
    return MarketRegime.CHOP
