"""
core.py
Main pipeline entry point.

FIXES:
  - Import: `from schemas import RawInput` (was `from schemas` which failed
    if file was still named shemas.py; now unambiguous).
  - final_humanity formula: original `humanity * consensus["confidence"] + net_score*50`
    is dimensionally wrong — multiplying a 0-100 score by a 0-1 confidence
    shrinks it badly, then adding 50*net (which is −50…+50) can push total
    outside 0-100 and distorts meaning.  New formula blends humanity (engine)
    and consensus direction additively with defined weights.
  - Humanity zone thresholds now read from config.HUMANITY_ZONES (single source
    of truth; original hardcoded 70/50/30 in core vs 75/60/40 in README).
  - Added main() function so `eth-analyze` console script works.
  - Added Monte-Carlo scenarios to output.
  - Fixed history path to use meta.history_dir.
  - save_json uses atomic write (temp file + rename) to avoid partial writes.

SOCIAL INTELLIGENCE EXTENSION:
  - Async run_pipeline_with_social() collects + processes social data,
    injects social features into the feature dict before agents run.
  - Synchronous run_pipeline() still works identically (social = None fallback).
  - Social snapshot summary included in output JSON.
  - WDI receives optional social adjustment via calc_social_wdi_adjustment().
  - Confidence receives optional social adjustment via calc_social_confidence_adjustment().
"""

import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime, UTC
from pathlib import Path
from typing import Optional

from engine.features import (
    calc_threats_score, calc_suspicion_index, calc_mss_tss,
    calc_wdi, calc_confidence, calc_humanity,
    inject_social_features,
    calc_social_wdi_adjustment,
    calc_social_confidence_adjustment,
)
from engine.regime import detect_regime
from engine.weights import get_dynamic_weights
from engine.scenarios import monte_carlo_scenarios
from agents.macro import MacroAgent
from agents.flow import FlowAgent
from agents.manipulation import ManipAgent
from agents.quant import QuantAgent
from agents.risk import RiskAgent
from agents.consensus import run_consensus
from schemas import RawInput
from config import HUMANITY_ZONES


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def save_json(data: dict, path: str) -> None:
    """Atomic JSON write: write to temp file then rename."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        os.unlink(tmp)
        raise


def _zone(score: float) -> tuple[str, str]:
    for threshold, zone, color in HUMANITY_ZONES:
        if score >= threshold:
            return zone, color
    return "CRISIS", "🔴"


# ---------------------------------------------------------------------------
# Core pipeline (market data only — always synchronous)
# ---------------------------------------------------------------------------

def run_pipeline(raw_data: dict, social_features=None) -> dict:
    """
    Validate input, compute all metrics, run agents, return result dict.

    Parameters
    ----------
    raw_data : dict
        Market data dict (matches input.json schema).
    social_features : SocialFeatures | dict | None
        Pre-computed social features to inject.  When None, agents run
        without social signals (backward-compatible).
    """
    validated = RawInput(**raw_data)

    p     = validated.price
    deriv = validated.derivatives
    f     = validated.flows
    m     = validated.macro
    rec   = validated.recession
    c     = validated.corridor

    # --- Engine metrics ---
    threats   = calc_threats_score(rec)
    suspicion = calc_suspicion_index(p, deriv, c.flags)
    mss, tss, truth = calc_mss_tss(p, deriv, f, m)
    wdi       = calc_wdi(p, deriv, f, m, c)
    conf      = calc_confidence(mss, tss, p.atr_pct, threats)
    humanity  = calc_humanity(wdi, conf, threats)

    # --- Social enrichment of WDI and confidence ---
    social_wdi_adj  = calc_social_wdi_adjustment(social_features)
    social_conf_adj = calc_social_confidence_adjustment(social_features)

    wdi_final  = float(max(-100.0, min(100.0, wdi + social_wdi_adj)))
    conf_final = float(max(0.0, min(1.0, conf + social_conf_adj)))

    # Recalculate humanity if social changed wdi/conf meaningfully
    if abs(social_wdi_adj) > 0.5 or abs(social_conf_adj) > 0.005:
        humanity = calc_humanity(wdi_final, conf_final, threats)

    # --- Regime & dynamic weights ---
    regime  = detect_regime(p.atr_pct, p.rsi_1d, deriv.funding_8h, f.cet_delta_7d_pct)
    weights = get_dynamic_weights(regime, threats)

    # --- Build enriched feature dict for agents ---
    base_agent_input = validated  # agents also accept RawInput directly

    # For agents that read social from raw dict, inject social features
    if social_features is not None:
        raw_dict_enriched = inject_social_features(
            validated.model_dump_unified(), social_features
        )
    else:
        raw_dict_enriched = None

    # --- Agents (pass enriched dict when available, else RawInput) ---
    agents = [MacroAgent(), FlowAgent(), ManipAgent(), QuantAgent(), RiskAgent()]
    if raw_dict_enriched is not None:
        agent_results = [a.analyze(raw_dict_enriched) for a in agents]
    else:
        agent_results = [a.analyze(validated) for a in agents]

    consensus = run_consensus(agent_results)

    # --- Final Humanity Score ---
    consensus_adj  = consensus["net_score"] * 15.0
    final_humanity = float(max(0.0, min(100.0, humanity * 0.70 + (humanity + consensus_adj) * 0.30)))

    zone, color = _zone(final_humanity)

    # --- Monte-Carlo ---
    scenarios = monte_carlo_scenarios(wdi=wdi_final, vol=p.atr_pct, n_sims=5000,
                                      horizon=validated.meta.horizon_days)

    # --- Cascade timeline label ---
    if threats > 70:
        cascade = "🔴 T-3/T-0"
    elif threats > 50:
        cascade = "🟠 T-7/T-3"
    elif threats > 30:
        cascade = "🟡 T-14/T-7"
    else:
        cascade = "🟢 T-30/Safe"

    result = {
        "timestamp":      datetime.now(UTC).isoformat(),
        "asset":          validated.meta.asset,
        "horizon_days":   validated.meta.horizon_days,
        "humanity_score": round(final_humanity, 1),
        "zone":           zone,
        "color":          color,
        "regime":         regime.value,
        "base_scores": {
            "wdi":            wdi,
            "wdi_final":      wdi_final,
            "social_wdi_adj": social_wdi_adj,
            "mss":            mss,
            "tss":            tss,
            "truth":          truth,
            "threats":        threats,
            "suspicion":      suspicion,
            "confidence":     round(conf, 2),
            "confidence_final": round(conf_final, 2),
            "social_conf_adj": social_conf_adj,
        },
        "dynamic_weights": weights,
        "consensus":      consensus,
        "scenarios":      scenarios,
        "agents":         [a.model_dump() for a in agent_results],
        "cascade_timeline": cascade,
        "human_summary": (
            f"Humanity {final_humanity:.0f} {color} | Режим {regime.value}. "
            f"WDI:{wdi_final:.0f} | Угрозы:{threats:.0f}/100. "
            f"{'Перегрев' if mss > 60 else 'Манипуляции в норме'}. "
            f"Конфиденс: {conf_final:.0%}"
        ),
    }

    # --- Persist history ---
    hist_dir = str(validated.meta.history_dir).rstrip("/")
    date_str = result["timestamp"][:10]
    save_json(result, f"{hist_dir}/{validated.meta.asset}_{date_str}.json")

    return result


# ---------------------------------------------------------------------------
# Social-enriched async pipeline
# ---------------------------------------------------------------------------

async def run_pipeline_async(
    raw_data: dict,
    collect_social: bool = True,
    asset: str = "ETH",
) -> dict:
    """
    Full async pipeline: collects social data → processes → injects → runs agents.

    Parameters
    ----------
    raw_data : dict
        Market data dict.
    collect_social : bool
        Set False to skip social collection (e.g. in tests or when offline).
    asset : str
        Asset ticker for social data queries.

    Returns
    -------
    dict
        Same structure as run_pipeline(), plus "social" key with snapshot summary.
    """
    social_features = None
    social_summary = {"enabled": False, "reason": "disabled"}
    narratives_out = []

    if collect_social:
        try:
            # Lazy import to avoid circular deps and keep sync path fast
            from data.social.collector import SocialCollector
            from data.social.processor import SocialProcessor

            async with SocialCollector() as collector:
                posts, coverage = await collector.collect_with_coverage(asset=asset)

            processor = SocialProcessor()
            features, narratives = processor.process(posts, asset=asset)
            features = SocialProcessor.enrich_features_with_narratives(features, narratives)
            social_features = features
            narratives_out = [n.model_dump() for n in narratives]

            social_summary = {
                "enabled": True,
                "post_count": features.post_count,
                "unique_sources": features.unique_sources,
                "data_quality": features.data_quality,
                "provider_coverage": coverage,
                "sentiment_score": features.sentiment_score,
                "attention_score": features.attention_score,
                "panic_score": features.panic_score,
                "euphoria_score": features.euphoria_score,
                "narrative_strength": features.narrative_strength,
                "bot_probability": features.bot_probability,
            }
        except Exception as exc:
            social_summary = {"enabled": False, "reason": str(exc)}

    result = run_pipeline(raw_data, social_features=social_features)
    result["social"] = social_summary
    result["narratives"] = narratives_out

    return result


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(description="ETH Intelligence OS — CLI")
    parser.add_argument("--input", "-i", default="input.json",
                        help="Path to input.json file (default: input.json)")
    parser.add_argument("--output", "-o", default=None,
                        help="Save result to this JSON path (optional)")
    parser.add_argument("--social", action="store_true", default=False,
                        help="Enable Social Intelligence Layer (async)")
    parser.add_argument("--no-social", dest="social", action="store_false")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"❌ Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    with open(input_path, encoding="utf-8") as fh:
        raw = json.load(fh)

    if args.social:
        result = asyncio.run(run_pipeline_async(raw, collect_social=True))
    else:
        result = run_pipeline(raw)

    score = result["humanity_score"]
    color = result["color"]
    zone  = result["zone"]
    cons  = result["consensus"]

    print(f"\n{'='*60}")
    print(f"  {color} HUMANITY SCORE: {score:.1f} / 100  |  {zone}")
    print(f"  🎯 Consensus: {cons['direction'].upper()}  "
          f"| Agreement: {cons['agreement']:.0%}  "
          f"| Conf: {cons['confidence']:.0%}")
    print(f"  📊 WDI: {result['base_scores'].get('wdi_final', result['base_scores']['wdi']):.1f}  "
          f"| Threats: {result['base_scores']['threats']:.1f}/100  "
          f"| Suspicion: {result['base_scores']['suspicion']:.1f}/100")
    print(f"  ⏱  Cascade: {result['cascade_timeline']}")

    if "social" in result and result["social"].get("enabled"):
        s = result["social"]
        print(f"  📡 Social: {s['post_count']} posts | "
              f"Sentiment: {s['sentiment_score']:+.2f} | "
              f"Attention: {s['attention_score']:.2f} | "
              f"Panic: {s['panic_score']:.2f}")
        if result.get("narratives"):
            top = result["narratives"][0]
            print(f"  📰 Top narrative: {top['narrative']} "
                  f"(str={top['strength']:.2f}, vel={top['velocity']:.2f})")

    print(f"{'='*60}")
    print(f"  {result['human_summary']}")
    print(f"{'='*60}\n")

    if args.output:
        save_json(result, args.output)
        print(f"💾 Result saved to {args.output}")


if __name__ == "__main__":
    main()

