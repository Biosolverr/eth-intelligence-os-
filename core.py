"""
core.py — DETERMINISTIC LOCAL DIAGNOSTICS ONLY (no verdict).

Computes explicit, reproducible numeric indicators from raw input (threats, suspicion,
MSS/TSS, WDI, regime). These are *evidence inputs / diagnostics*. They are NOT consensus,
NOT a verdict, and no direction/humanity/consensus is produced here. The authoritative
analytical judgment comes exclusively from the GenLayer contract (see client/).
"""
from engine.features import calc_threats_score, calc_suspicion_index, calc_mss_tss, calc_wdi
from engine.regime import detect_regime
from engine.weights import get_dynamic_weights
from schemas import RawInput

DIAGNOSTICS_NOTICE = ("Local deterministic heuristics. Not validator consensus, not a verdict, "
                      "not a forecast. Authoritative judgment: GenLayer contract only.")


def run_diagnostics(raw_data: dict) -> dict:
    v = RawInput(**raw_data)
    p, d, f, m, rec, c = v.price, v.derivatives, v.flows, v.macro, v.recession, v.corridor
    threats = calc_threats_score(rec)
    mss, tss, truth = calc_mss_tss(p, d, f, m)
    regime = detect_regime(p.atr_pct, p.rsi_1d, d.funding_8h, f.cet_delta_7d_pct)
    return {
        "notice": DIAGNOSTICS_NOTICE,
        "kind": "local_deterministic_diagnostics",
        "asset": v.meta.asset,
        "horizon_days": v.meta.horizon_days,
        "threats": threats,
        "suspicion": calc_suspicion_index(p, d, c.flags),
        "mss": mss, "tss": tss, "truth": truth,
        "wdi": calc_wdi(p, d, f, m, c),
        "regime": regime.value,
        "dynamic_weights": get_dynamic_weights(regime, threats),
    }
