"""
engine/scenarios.py
Monte-Carlo scenario simulation for 30-day forward return distribution.

FIX: vol input is already in % (e.g. 3.9 for 3.9%), so dividing by 100
and then by sqrt(252) is correct.  Added seed parameter for reproducibility
in tests.  Added 5th/95th percentile outputs.
"""

import numpy as np
from typing import Optional


def monte_carlo_scenarios(
    wdi: float,
    vol: float,
    n_sims: int = 5_000,
    horizon: int = 30,
    seed: Optional[int] = None,
) -> dict:
    """
    Parameters
    ----------
    wdi     : Weighted Directional Index (−100…+100); used as drift signal.
    vol     : ATR % (e.g. 3.9 for 3.9%).
    n_sims  : Number of Monte-Carlo paths.
    horizon : Days to simulate.
    seed    : Random seed for reproducibility (optional).

    Returns
    -------
    Dict with scenario probabilities and percentile returns.
    """
    rng = np.random.default_rng(seed)

    daily_drift = (wdi / 100.0) * 0.002          # scale WDI → daily expected return
    daily_vol   = (vol / 100.0) / np.sqrt(252)   # annualised vol → daily vol

    daily_ret = rng.normal(
        loc=daily_drift,
        scale=daily_vol,
        size=(n_sims, horizon),
    )
    cum_ret = np.cumprod(1 + daily_ret, axis=1)[:, -1] - 1

    p_bull = float(np.mean(cum_ret >  0.15))
    p_base = float(np.mean((cum_ret > -0.05) & (cum_ret <= 0.15)))
    p_bear = float(np.mean(cum_ret <= -0.05))

    return {
        "p1_bull":   round(p_bull, 3),
        "p2_base":   round(p_base, 3),
        "p3_bear":   round(p_bear, 3),
        "pct_05":    round(float(np.percentile(cum_ret,  5)) * 100, 1),
        "pct_50":    round(float(np.percentile(cum_ret, 50)) * 100, 1),
        "pct_95":    round(float(np.percentile(cum_ret, 95)) * 100, 1),
        "n_sims":    n_sims,
        "horizon_d": horizon,
    }
