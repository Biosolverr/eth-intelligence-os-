"""
agents/macro.py

FIXES:
  - analyze() now accepts RawInput object and uses attribute access.
    Original used dict-style access raw["recession"] which raises AttributeError
    on a Pydantic model instance.
  - calc_threats_score is called with the recession object directly.
"""

from agents.base import AgentResult
from engine.features import calc_threats_score


class MacroAgent:
    def __init__(self):
        self.name = "Macro"

    def analyze(self, raw) -> AgentResult:
        # Support both RawInput object and plain dict
        if hasattr(raw, "recession"):
            rec  = raw.recession
            mac  = raw.macro
        else:
            rec  = raw["recession"]
            mac  = raw["macro"]

        threats  = calc_threats_score(rec)
        dxy_up   = (getattr(mac, "dxy_weekly_pct", None) or mac.get("dxy_weekly_pct", 0)) > 0.5
        spx_dd   = getattr(mac, "spx_drawdown_pct", None) or mac.get("spx_drawdown_pct", 0)
        fed      = getattr(mac, "fed_status", None) or mac.get("fed_status", "hold")

        risk = min(threats * 0.6 + abs(spx_dd) * 2.5, 100.0)

        if fed == "easing" and not dxy_up and spx_dd > -5:
            direction, conf, signals = "bullish", 0.78, ["Fed dovish", "DXY stable", "Equity resilient"]
        elif threats > 65 or spx_dd < -12:
            direction, conf, signals = "bearish", 0.85, ["Threats elevated", "Equity stress", "Liquidity drain"]
        else:
            direction, conf, signals = "neutral", 0.62, ["Mixed macro", "Watch Fed/DXY"]

        return AgentResult(
            agent_name=self.name,
            direction=direction,
            confidence=conf,
            risk_score=round(risk, 1),
            signals=signals,
            explanation=f"Threats: {threats:.1f}, Fed: {fed}, SPX DD: {spx_dd:.1f}%",
        )
