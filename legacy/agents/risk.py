"""
agents/risk.py

FIXES vs original:
  - Original: threats = sum(raw["recession"].values()) / 8.0
    This averages raw field VALUES (e.g. g6_debt_gdp=335), not scored 0-100
    sub-indices → completely wrong.  Fixed to use calc_threats_score().
  - Variable shadowing: d, c, s renamed.
  - Now accepts both RawInput and dict.

SOCIAL INTELLIGENCE:
  - Consumes: panic_score, euphoria_score
  - Extreme panic → increases cascade risk estimate.
  - Extreme euphoria → adds leverage-unwind risk (crowded long liquidation).
  - Data quality check: low quality social data → no social adjustment.
"""

from agents.base import AgentResult
from engine.features import calc_threats_score


def _get(obj, key, default=0.0):
    if hasattr(obj, key):
        return getattr(obj, key)
    if isinstance(obj, dict):
        return obj.get(key, default)
    return default


class RiskAgent:
    def __init__(self):
        self.name = "Risk"

    def analyze(self, raw) -> AgentResult:
        if hasattr(raw, "derivatives"):
            deriv = raw.derivatives
            p     = raw.price
            rec   = raw.recession
        else:
            deriv = raw.get("derivatives", raw.get("deriv", {}))
            p     = raw.get("price", {})
            rec   = raw.get("recession", {})

        liq_24h  = _get(deriv, "liq_24h_usd_m", 0.0)
        vol      = _get(p, "atr_pct", 3.5)
        liq_side = _get(deriv, "liq_side", "mixed")

        # --- Social signals ---
        panic_score    = _get(raw, "panic_score", 0.0)     # 0…1
        euphoria_score = _get(raw, "euphoria_score", 0.0)  # 0…1
        data_quality   = _get(raw, "data_quality", 1.0)    # 0…1

        threats = calc_threats_score(rec)

        liq_factor = 1.2 if liq_side == "longs" else 1.0

        cascade_risk = float(min(
            (liq_24h / 500) * 40 * liq_factor + (vol > 5) * 30 + (threats > 60) * 30,
            100.0,
        ))

        # Social risk adjustments (only when data quality is sufficient)
        social_risk_delta = 0.0
        social_signals = []

        if data_quality > 0.3:
            # Panic amplifies liquidation risk: crowds rush for the exit
            if panic_score > 0.5:
                social_risk_delta += panic_score * 15
                social_signals.append(f"Social panic {panic_score:.0%}")

            # Euphoria → crowded longs → liquidation risk when sentiment reverses
            if euphoria_score > 0.6:
                social_risk_delta += euphoria_score * 10
                social_signals.append(f"Euphoria → crowded longs {euphoria_score:.0%}")

        cascade_risk = float(min(cascade_risk + social_risk_delta, 100.0))

        if cascade_risk > 65:
            direction, conf, sigs = "bearish", 0.91, [
                "Cascade imminent", "Leverage overloaded"
            ]
        elif cascade_risk < 30 and threats < 45 and panic_score < 0.3:
            direction, conf, sigs = "bullish", 0.68, [
                "Deleverage healthy", "Low cascade risk"
            ]
        else:
            direction, conf, sigs = "neutral", 0.74, [
                "Moderate risk", "Reduce size / hedge"
            ]

        sigs.extend(social_signals)

        social_note = (
            f", Panic: {panic_score:.2f}, Euphoria: {euphoria_score:.2f}"
            if data_quality > 0.3 and (panic_score > 0.1 or euphoria_score > 0.1) else ""
        )

        return AgentResult(
            agent_name=self.name,
            direction=direction,
            confidence=conf,
            risk_score=cascade_risk,
            signals=sigs,
            explanation=(
                f"Liq 24h: ${liq_24h:.0f}M ({liq_side}), "
                f"ATR: {vol:.1f}%, Threats: {threats:.1f}{social_note}"
            ),
        )
