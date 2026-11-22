"""
backtest/runner.py
Historical backtesting framework.

FIXES:
  - Original loop body was completely empty (just `pass`) — runner never
    actually ran anything.  Added proper CSV column mapping and pipeline call.
  - calculate_metrics: Brier score calculation was correct but hit_rate
    used humanity>60 as "bullish signal" threshold, not humanity>70 (zone
    boundary in README).  Corrected to README-defined 70/40 boundaries.
  - Added output to a results CSV and summary JSON.

Expected CSV columns (minimum required):
    date, price_current, ret_24h, ret_7d, ret_30d,
    s1, s2, r1, r2, rsi_1d, rsi_4h, atr_pct, vol_regime,
    macd_status, ma_alignment,
    oi_usd_m, oi_d1_pct, oi_w_pct, funding_8h, liq_24h_usd_m, liq_side,
    etf_7d_usd_m, cet_supply_m_eth, cet_delta_7d_pct, stable_flow,
    stable_amount_usd_m, sopr, lth_delta_pct, l2_tvl_30d_pct,
    hy_oas_bps, dxy_weekly_pct, yield_curve_bps, fed_status,
    spx_drawdown_pct, equity_breadth_pct, btc_corr_30d, fear_greed,
    g1_usdjpy, g1_jgb10y, g2_pe_nasdaq, g2_top5_conc, g3_hy_default,
    g3_ig_refi, g3_hy_refi, g4_trade_yoy, g5_us_ur, g5_retail_mom,
    g6_debt_gdp, g6_em_defaults, g7_brent, g7_gpr,
    g8_cre_vacancy, g8_housing_yoy, g8_banks_ytd,
    fwd_ret_30d   ← forward 30-day return % for evaluation
"""

import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from core import run_pipeline


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def calculate_metrics(preds: pd.Series, fwd_rets: pd.Series, horizon: str) -> dict:
    if len(preds) == 0:
        return {"horizon": horizon, "signals": 0, "error": "no data"}

    # FIX: use 70 / 40 zone boundaries from README, not arbitrary 60/40
    hits = (
        ((preds >= 70) & (fwd_rets > 5)) |
        ((preds <= 40) & (fwd_rets < -5))
    )
    hit_rate = float(hits.sum() / len(preds))

    probs = preds / 100.0
    actuals = (fwd_rets > 0).astype(float)
    brier = float(np.mean((probs - actuals) ** 2))

    cum = (1 + fwd_rets / 100).cumprod()
    running_max = np.maximum.accumulate(cum)
    max_dd = float((cum / running_max - 1).min())

    # Directional accuracy: did the signal direction match price direction?
    dir_correct = (
        ((preds >= 60) & (fwd_rets > 0)) |
        ((preds <= 40) & (fwd_rets < 0))
    )
    dir_acc = float(dir_correct.sum() / len(preds))

    return {
        "horizon":          horizon,
        "signals":          len(preds),
        "hit_rate":         round(hit_rate, 3),
        "avg_fwd_ret_pct":  round(float(fwd_rets.mean()), 3),
        "brier_score":      round(brier, 4),
        "max_drawdown":     round(max_dd, 3),
        "directional_acc":  round(dir_acc, 3),
    }


# ---------------------------------------------------------------------------
# CSV → RawInput dict converter
# ---------------------------------------------------------------------------

def row_to_raw(row: pd.Series) -> dict:
    """Map a flat CSV row to the nested RawInput dict structure."""
    return {
        "meta": {
            "asset": "ETH",
            "date_utc": str(row.get("date", "")),
            "horizon_days": 30,
            "history_dir": "./data/history/",
        },
        "price": {
            "current":     float(row["price_current"]),
            "ret_24h":     float(row["ret_24h"]),
            "ret_7d":      float(row["ret_7d"]),
            "ret_30d":     float(row["ret_30d"]),
            "s1":          float(row["s1"]),
            "s2":          float(row["s2"]),
            "r1":          float(row["r1"]),
            "r2":          float(row["r2"]),
            "rsi_1d":      float(row["rsi_1d"]),
            "rsi_4h":      float(row["rsi_4h"]),
            "atr_pct":     float(row["atr_pct"]),
            "vol_regime":  str(row["vol_regime"]),
            "macd_status": str(row["macd_status"]),
            "ma_alignment": str(row["ma_alignment"]),
        },
        "deriv": {
            "oi_usd_m":     float(row["oi_usd_m"]),
            "oi_d1_pct":    float(row["oi_d1_pct"]),
            "oi_w_pct":     float(row["oi_w_pct"]),
            "funding_8h":   float(row["funding_8h"]),
            "liq_24h_usd_m": float(row["liq_24h_usd_m"]),
            "liq_side":     str(row["liq_side"]),
        },
        "flow": {
            "etf_7d_usd_m":     float(row["etf_7d_usd_m"]),
            "cet_supply_m_eth": float(row["cet_supply_m_eth"]),
            "cet_delta_7d_pct": float(row["cet_delta_7d_pct"]),
            "stable_flow":      str(row["stable_flow"]),
            "stable_amount_usd_m": float(row["stable_amount_usd_m"]),
            "sopr":             float(row["sopr"]),
            "lth_delta_pct":    float(row["lth_delta_pct"]),
            "l2_tvl_30d_pct":   float(row["l2_tvl_30d_pct"]),
        },
        "macro": {
            "hy_oas_bps":        float(row["hy_oas_bps"]),
            "dxy_weekly_pct":    float(row["dxy_weekly_pct"]),
            "yield_curve_bps":   float(row["yield_curve_bps"]),
            "fed_status":        str(row["fed_status"]),
            "spx_drawdown_pct":  float(row["spx_drawdown_pct"]),
            "equity_breadth_pct": float(row["equity_breadth_pct"]),
            "btc_corr_30d":      float(row["btc_corr_30d"]),
            "fear_greed":        int(row["fear_greed"]),
        },
        "recession": {
            "g1_usdjpy": float(row["g1_usdjpy"]), "g1_jgb10y": float(row["g1_jgb10y"]),
            "g2_pe_nasdaq": float(row["g2_pe_nasdaq"]), "g2_top5_conc": float(row["g2_top5_conc"]),
            "g3_hy_default": float(row["g3_hy_default"]), "g3_ig_refi": float(row["g3_ig_refi"]),
            "g3_hy_refi": float(row["g3_hy_refi"]), "g4_trade_yoy": float(row["g4_trade_yoy"]),
            "g5_us_ur": float(row["g5_us_ur"]), "g5_retail_mom": float(row["g5_retail_mom"]),
            "g6_debt_gdp": float(row["g6_debt_gdp"]), "g6_em_defaults": int(row["g6_em_defaults"]),
            "g7_brent": float(row["g7_brent"]), "g7_gpr": float(row["g7_gpr"]),
            "g8_cre_vacancy": float(row["g8_cre_vacancy"]),
            "g8_housing_yoy": float(row["g8_housing_yoy"]),
            "g8_banks_ytd": float(row["g8_banks_ytd"]),
        },
        "corridor": {
            "active": False, "cs": 0.0, "cr": 0.0, "cm": 0.0,
            "cwidth_pct": 0.0, "touch_s": 0, "touch_r": 0, "false_breaks": 0,
            "vol_at_s_pct": 0, "vol_at_r_pct": 0, "vol_at_mid_pct": 0, "flags": [],
        },
    }


# ---------------------------------------------------------------------------
# Main backtest runner
# ---------------------------------------------------------------------------

def run_backtest(csv_path: str, output_dir: str = "backtest/results") -> dict:
    """
    Run pipeline over each row of a historical CSV and compute performance metrics.

    Parameters
    ----------
    csv_path   : Path to the historical CSV file.
    output_dir : Directory where results CSV and summary JSON are saved.
    """
    df = pd.read_csv(csv_path, parse_dates=["date"])
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    records = []
    errors  = 0

    for idx, row in df.iterrows():
        try:
            raw   = row_to_raw(row)
            res   = run_pipeline(raw)
            score = res["humanity_score"]
            fwd   = float(row.get("fwd_ret_30d", float("nan")))
            records.append({
                "date":           str(row.get("date", "")),
                "humanity_score": score,
                "zone":           res["zone"],
                "consensus_dir":  res["consensus"]["direction"],
                "fwd_ret_30d":    fwd,
            })
        except Exception as e:
            errors += 1
            print(f"[Backtest] Row {idx} error: {e}")

    if not records:
        return {"status": "No records processed", "errors": errors}

    results_df = pd.DataFrame(records)
    out_csv = Path(output_dir) / "backtest_results.csv"
    results_df.to_csv(out_csv, index=False)

    valid = results_df.dropna(subset=["fwd_ret_30d"])
    metrics = calculate_metrics(
        preds=valid["humanity_score"],
        fwd_rets=valid["fwd_ret_30d"],
        horizon="30d",
    )
    metrics["errors"] = errors
    metrics["total_rows"] = len(df)

    summary_path = Path(output_dir) / "summary.json"
    with open(summary_path, "w") as f:
        json.dump(metrics, f, indent=2)

    print(f"[Backtest] Done. {len(records)} rows processed, {errors} errors.")
    print(f"[Backtest] Hit rate: {metrics.get('hit_rate', 0):.1%} | "
          f"Brier: {metrics.get('brier_score', 0):.4f}")

    return metrics


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m backtest.runner <path/to/historical.csv>")
        sys.exit(1)
    print(run_backtest(sys.argv[1]))
