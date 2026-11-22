"""Build a contract-schema evidence snapshot from the legacy input.json format.

Deterministic mapping only. Nothing is invented: absent source data stays absent.
`risk` is computed locally by engine/ and therefore tagged kind="derived". ALL provenance is submitter-asserted.
"""
import json
from datetime import datetime, timezone

from core import run_diagnostics
from schemas import RawInput

_PRICE = ["current", "ret_24h", "ret_7d", "ret_30d", "rsi_1d", "atr_pct", "vol_regime", "macd_status", "ma_alignment"]
_DERIVS = ["oi_d1_pct", "oi_w_pct", "funding_8h", "liq_24h_usd_m", "liq_side"]
_FLOWS = ["etf_7d_usd_m", "cet_delta_7d_pct", "stable_flow", "stable_amount_usd_m", "sopr", "lth_delta_pct", "l2_tvl_30d_pct"]
_MACRO = ["hy_oas_bps", "dxy_weekly_pct", "yield_curve_bps", "fed_status", "spx_drawdown_pct", "equity_breadth_pct", "btc_corr_30d", "fear_greed"]


def _pick(model, keys):
    d = model.model_dump()
    return {k: d[k] for k in keys}


def build_snapshot(raw: dict, observed_at: str, sources: list[dict]) -> dict:
    """`sources`: [{group, source_id, observed_at, kind}] — REQUIRED provenance supplied by the caller."""
    v = RawInput(**raw)
    diag = run_diagnostics(raw)
    snap = {
        "schema_version": "1",
        "meta": {"asset": v.meta.asset, "horizon_days": v.meta.horizon_days, "observed_at": observed_at},
        "price": _pick(v.price, _PRICE),
        "derivs": _pick(v.derivatives, _DERIVS),
        "flows": _pick(v.flows, _FLOWS),
        "macro": _pick(v.macro, _MACRO),
        "risk": {"threats_score": diag["threats"], "regime": diag["regime"]},
        "sources": sources,
    }
    if v.corridor.flags:
        snap["flags"] = sorted(set(v.corridor.flags))
    return snap


def to_json(snapshot: dict) -> str:
    return json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
