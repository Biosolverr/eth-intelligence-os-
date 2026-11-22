"""
agents/flow.py

FIXES vs original:
  - Original used wrong dict keys: "flows_onchain", "cex_balance_7d_pct",
    "stable_inflow_7d_usd_m", "funding_8h_pct" — none of these exist in the
    schema.  Correct keys: "flows", "cet_delta_7d_pct", "stable_amount_usd_m",
    "funding_8h".
  - Variable shadowing bug: local variables d, c, s shadowed the outer d
    (derivatives dict).  Renamed to direction, conf, sigs.
  - Now accepts both RawInput objects and plain dicts.

SOCIAL INTELLIGENCE:
  - Consumes: narrative_strength, attention_score
  - Strong social narrative backing capital flows increases conviction.
  - High attention with no narrative (speculative spike) is a warning sign.
  - narrative_strength > 0.6 adds +0.08 confidence to confirmed bullish flow.
"""

from agents.base import AgentResult


def _get(obj, key, default=0.0):
    if hasattr(obj, key):
        return getattr(obj, key)
    if isinstance(obj, dict):
        return obj.get(key, default)
    return default


class FlowAgent:
    def __init__(self):
        self.name = "Flow"

    def analyze(self, raw) -> AgentResult:
        if hasattr(raw, "flows"):
            f = raw.flows
            d = raw.derivatives
        else:
            f = raw.get("flows", raw.get("flow", {}))
            d = raw.get("derivatives", raw.get("deriv", {}))

        cex_chg   = _get(f, "cet_delta_7d_pct")
        etf       = _get(f, "etf_7d_usd_m")
        stable    = _get(f, "stable_amount_usd_m")
        funding   = _get(d, "funding_8h")
        stable_in = _get(f, "stable_flow", "flat") == "in"

        # --- Social signals ---
        narrative_strength = _get(raw, "narrative_strength", 0.0)  # 0…1
        attention_score    = _get(raw, "attention_score", 0.0)      # 0…1

        bull_pts = (cex_chg < 0) * 40 + (etf > 0) * 30 + stable_in * 30
        risk = float(max(0, 100 - bull_pts))

        if bull_pts > 65 and funding < 0.04:
            direction, conf, sigs = "bullish", 0.82, [
                "CEX outflow", "ETF inflow", "Stable demand", "Funding cool"
            ]
        elif funding > 0.07 or (etf < -80 and not stable_in):
            direction, conf, sigs = "bearish", 0.76, [
                "Funding overheated", "Outflows active"
            ]
        else:
            direction, conf, sigs = "neutral", 0.64, [
                "Balanced flows", "Monitor ETF trend"
            ]

        # Social enrichment: narrative backing amplifies flow conviction
        social_signals = []
        if narrative_strength > 0.6 and attention_score > 0.4:
            if direction == "bullish":
                conf = min(0.92, conf + 0.08)
                social_signals.append(f"Narrative backing ↑ {narrative_strength:.0%}")
            elif direction == "bearish":
                conf = min(0.92, conf + 0.06)
                social_signals.append(f"Social confirms outflow {narrative_strength:.0%}")
        elif attention_score > 0.6 and narrative_strength < 0.2:
            # High attention with no clear narrative = speculative spike
            conf = max(0.45, conf - 0.08)
            social_signals.append("Speculative spike, no narrative")

        sigs.extend(social_signals)

        social_note = (
            f", Narrative: {narrative_strength:.2f}, Attention: {attention_score:.2f}"
            if narrative_strength > 0.05 or attention_score > 0.05 else ""
        )

        return AgentResult(
            agent_name=self.name,
            direction=direction,
            confidence=conf,
            risk_score=risk,
            signals=sigs,
            explanation=f"CEX Δ: {cex_chg:.1f}%, ETF: ${etf:.0f}M, Funding: {funding:.4f}{social_note}",
        )
