"""
agents/consensus.py

FIXES:
  - net_score: original weighted bullish/bearish separately, then divided
    by total_conf — but neutral agents contributed 0 to numerator while
    still inflating denominator, making the metric inconsistent.
    Simplified to a clear confidence-weighted directional vote.
  - agreement: original took max(weights) / total_conf which could exceed 1.0
    if a single direction dominated.  Clamped to [0, 1].
  - Added 'dominant_agent' field showing which agent had highest risk_score.
"""

from typing import List
from agents.base import AgentResult


def run_consensus(results: List[AgentResult]) -> dict:
    if not results:
        return {
            "direction": "neutral", "agreement": 0.0, "confidence": 0.0,
            "net_score": 0.0, "agent_breakdown": {}, "dominant_risk_agent": None,
        }

    dir_map = {"bullish": 1.0, "bearish": -1.0, "neutral": 0.0}

    total_conf = sum(r.confidence for r in results)
    if total_conf < 1e-8:
        total_conf = 1e-8

    # Confidence-weighted net directional score (–1…+1)
    net = sum(dir_map[r.direction] * r.confidence for r in results) / total_conf

    # Agreement: fraction of total confidence aligned with winning direction
    winning_dir = "bullish" if net > 0 else ("bearish" if net < 0 else "neutral")
    aligned_conf = sum(
        r.confidence for r in results if r.direction == winning_dir
    )
    agreement = float(min(aligned_conf / total_conf, 1.0))

    # Conflict penalty if both bullish AND bearish agents present
    active_dirs = {r.direction for r in results if r.direction != "neutral"}
    conflict_penalty = 0.15 if len(active_dirs) > 1 else 0.0

    avg_conf = total_conf / len(results)
    final_conf = float(max(0.0, avg_conf - conflict_penalty))

    # Final direction (deadband ±0.2 → neutral)
    if net > 0.2:
        direction = "bullish"
    elif net < -0.2:
        direction = "bearish"
    else:
        direction = "neutral"

    # Dominant risk agent (highest risk_score)
    dominant = max(results, key=lambda r: r.risk_score)

    return {
        "direction":         direction,
        "agreement":         round(agreement, 2),
        "confidence":        round(final_conf, 2),
        "net_score":         round(net, 2),
        "conflict_penalty":  round(conflict_penalty, 2),
        "dominant_risk_agent": dominant.agent_name,
        "agent_breakdown": {
            r.agent_name: {
                "dir":  r.direction,
                "conf": r.confidence,
                "risk": r.risk_score,
            }
            for r in results
        },
    }
