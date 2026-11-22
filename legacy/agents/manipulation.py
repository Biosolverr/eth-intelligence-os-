"""
agents/manipulation.py

FIXES vs original:
  - Variable shadowing: original code used 'd, c, s = "bearish", ...' which
    shadowed the outer d=derivatives dict.  Renamed to direction, conf, sigs.
  - Now accepts both RawInput and dict.

SOCIAL INTELLIGENCE:
  - Consumes: bot_probability, engagement_velocity, influencer_alignment, engagement_anomaly
  - Bot-heavy social activity amplifies manipulation suspicion score.
  - Engagement anomaly (abnormal influencer vs normal ratio) is a coordination signal.
  - Influencer alignment vs price action divergence detects narrative pumps.
"""

from agents.base import AgentResult
from engine.features import calc_suspicion_index, calc_mss_tss


def _get(obj, key, default=None):
    if hasattr(obj, key):
        return getattr(obj, key)
    if isinstance(obj, dict):
        return obj.get(key, default)
    return default


class ManipAgent:
    def __init__(self):
        self.name = "Manipulation"

    def analyze(self, raw) -> AgentResult:
        if hasattr(raw, "price"):
            p        = raw.price
            deriv    = raw.derivatives
            mac      = raw.macro
            f        = raw.flows
            corridor = raw.corridor
        else:
            p        = raw.get("price", {})
            deriv    = raw.get("derivatives", raw.get("deriv", {}))
            mac      = raw.get("macro", {})
            f        = raw.get("flows", raw.get("flow", {}))
            corridor = raw.get("corridor", {})

        flags = _get(corridor, "flags", []) or []

        # --- Social signals ---
        bot_probability    = _get(raw, "bot_probability", 0.0)     # 0…1
        engagement_velocity = _get(raw, "engagement_velocity", 0.0) # Δattention
        influencer_align   = _get(raw, "influencer_alignment", 0.0) # -1…+1
        engagement_anomaly = _get(raw, "engagement_anomaly", 0.0)   # 0…1

        suspicion = calc_suspicion_index(p, deriv, flags)
        mss, tss, truth = calc_mss_tss(p, deriv, f, mac)

        # --- Social manipulation uplift ---
        # High bot probability: bots amplify narratives to move markets
        social_manip_score = 0.0
        social_signals = []

        if bot_probability > 0.3:
            social_manip_score += bot_probability * 20
            social_signals.append(f"Bot activity {bot_probability:.0%}")

        # Abnormal engagement spike on influencer content = coordinated pump
        if engagement_anomaly > 0.5:
            social_manip_score += engagement_anomaly * 15
            social_signals.append("Engagement anomaly")

        # Influencer alignment strongly opposite to market flow = narrative pump
        p_obj = p if not isinstance(p, dict) else type("P", (), p)()
        ret_24h = _get(p, "ret_24h", 0.0)
        if ret_24h < -0.5 and influencer_align > 0.5:
            social_manip_score += 15  # bears dumping while influencers scream "buy"
            social_signals.append("Influencer vs price divergence")

        social_manip_score = min(social_manip_score, 30)  # cap social contribution

        risk = float(min(suspicion + (mss > 60) * 35 + social_manip_score, 100))

        if suspicion > 70 or (mss > 60 and truth > 25) or social_manip_score > 20:
            direction, conf, sigs = "bearish", 0.88, [
                "High manipulation", "Squeeze risk", "False breakouts"
            ]
        elif tss > 75 and suspicion < 35 and bot_probability < 0.15:
            direction, conf, sigs = "bullish", 0.72, [
                "Clean trend", "Low spoofing", "Volume confirms"
            ]
        else:
            direction, conf, sigs = "neutral", 0.61, [
                "Mixed microstructure", "Watch funding/OI"
            ]

        sigs.extend(social_signals)

        social_note = (
            f", Bots: {bot_probability:.0%}, Eng.Anomaly: {engagement_anomaly:.2f}"
            if bot_probability > 0.05 or engagement_anomaly > 0.1 else ""
        )

        return AgentResult(
            agent_name=self.name,
            direction=direction,
            confidence=conf,
            risk_score=risk,
            signals=sigs,
            explanation=(
                f"MSS: {mss:.1f}, TSS: {tss:.1f}, TRUTH: {truth:.1f}, "
                f"Susp: {suspicion:.1f}{social_note}"
            ),
        )
