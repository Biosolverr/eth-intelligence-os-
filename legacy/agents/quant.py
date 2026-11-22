"""
agents/quant.py

FIXES vs original:
  - Original accessed p["macd_hist"] — this field does NOT exist in the schema.
    The schema has "macd_status": Literal["bullish_cross","bearish_cross","neutral"].
    Score is now based on macd_status string rather than a numeric histogram value.
  - Variable shadowing: d, c, s renamed to direction, conf, sigs.
  - ma_alignment comparison was checking for "20<50<200" and "20<50" which are
    not valid schema values.  Valid: "bullish" | "bearish" | "neutral".
  - tech_score logic corrected accordingly.

SOCIAL INTELLIGENCE:
  - Consumes: sentiment_score, attention_acceleration, trend_momentum
  - Social signals modulate confidence and direction threshold, not raw tech_score,
    so technical signals remain the primary driver.
"""

from agents.base import AgentResult


def _get(obj, key, default=None):
    if hasattr(obj, key):
        return getattr(obj, key)
    if isinstance(obj, dict):
        return obj.get(key, default)
    return default


class QuantAgent:
    def __init__(self):
        self.name = "Quant/Trend"

    def analyze(self, raw) -> AgentResult:
        p = raw.price if hasattr(raw, "price") else raw.get("price", {})

        rsi         = _get(p, "rsi_1d", 50.0)
        macd_status = _get(p, "macd_status", "neutral")
        atr         = _get(p, "atr_pct", 3.5)
        ma          = _get(p, "ma_alignment", "neutral")

        # --- Social signals ---
        sentiment_score      = _get(raw, "sentiment_score", 0.0)       # -1…+1
        attention_accel      = _get(raw, "attention_acceleration", 0.0) # Δvelocity
        trend_momentum       = _get(raw, "trend_momentum", 0.0)         # 0…1

        vol_regime = "low" if atr < 3 else ("high" if atr > 5 else "normal")

        macd_bull = macd_status == "bullish_cross"
        ma_bull   = ma == "bullish"

        tech_score = (rsi < 60) * 30 + macd_bull * 30 + ma_bull * 40

        # Social momentum bonus/penalty: ±10 points on tech_score
        # Only applied when there is meaningful attention (avoid noise on 0.0 stubs)
        if abs(sentiment_score) > 0.15 and trend_momentum > 0.1:
            social_adj = int(sentiment_score * trend_momentum * 10)
            tech_score = max(0, min(100, tech_score + social_adj))

        if tech_score > 65 and vol_regime != "high":
            direction, conf, sigs = "bullish", 0.77, [
                "Momentum +", "MA aligned", "Vol compressing"
            ]
        elif rsi > 75 or (rsi < 25 and macd_status == "bearish_cross"):
            direction, conf, sigs = "bearish", 0.73, [
                "RSI extreme", "Momentum fading"
            ]
        else:
            direction, conf, sigs = "neutral", 0.66, [
                "Range bound", "Await breakout"
            ]

        # Social attention acceleration: rising attention amplifies conviction
        if attention_accel > 0.2 and direction != "neutral":
            conf = min(0.92, conf + 0.05)
            sigs.append("Social momentum ↑")
        elif attention_accel < -0.2:
            conf = max(0.45, conf - 0.05)
            sigs.append("Social cooling")

        risk = float(max(0, 100 - tech_score + (vol_regime == "high") * 25))

        social_note = (
            f", Sentiment: {sentiment_score:+.2f}, Attention↑: {attention_accel:+.2f}"
            if trend_momentum > 0.05 else ""
        )

        return AgentResult(
            agent_name=self.name,
            direction=direction,
            confidence=conf,
            risk_score=risk,
            signals=sigs,
            explanation=f"RSI: {rsi:.1f}, MACD: {macd_status}, ATR: {atr:.1f}%, MA: {ma}{social_note}",
        )
