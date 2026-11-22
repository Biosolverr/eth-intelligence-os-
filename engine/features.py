"""
engine/features.py
Core metric calculation functions.

FIXES vs original:
  - calc_threats_score: original passed a plain dict to _score_gX functions
    that expected RecessionRaw objects (broke when called from agents via
    raw["recession"]).  Now accepts BOTH RecessionRaw and dict.
  - calc_suspicion_index: accepts both PriceLayer/DerivLayer objects AND plain
    dicts (agents pass objects, core.py passes dicts after model_dump).
  - calc_mss_tss / calc_wdi: same dual-type handling.
  - calc_wdi: WDI scores were not normalised — result could exceed ±100 then
    get scaled to ±50 via weights.  Added explicit clamp to [-100, +100].
  - calc_confidence: wrong adjustment key used ("fresh_whale_data" for low ATR
    is a proxy; renamed comment to be clearer; capped at [0, 1]).
  - _score_g3: only uses hy_default (g3_ig_refi and g3_hy_refi ignored in
    original).  Now averages all three credit metrics.
  - All _score_gX return float (numpy scalar → Python float for JSON safety).
  - Removed wildcard import `from schemas import *` (bad practice) → explicit.

SOCIAL INTELLIGENCE EXTENSION:
  - inject_social_features(): merges SocialFeatures into the base feature dict
    so all existing agents can consume social signals without any breaking changes.
  - calc_social_wdi_adjustment(): computes a ±10 point adjustment to WDI based
    on social momentum, applied after base WDI calculation.
  - calc_social_confidence_adjustment(): micro-adjustment to confidence score
    based on social data quality and sentiment alignment.
"""

import numpy as np
from typing import Union

from schemas import RecessionRaw, PriceLayer, DerivLayer, FlowLayer, MacroLayer, CorridorLayer
from engine.normalization import threshold_map, vol_adjusted_score
from config import CONFIDENCE_ADJUSTMENTS, WDI_WEIGHTS_BASE, REGIME_THRESHOLDS


# ---------------------------------------------------------------------------
# Helpers: accept both Pydantic model instances and plain dicts
# ---------------------------------------------------------------------------

def _get(obj, key, default=0.0):
    """Attribute or dict access, with fallback."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _as_rec(rec) -> "RecessionRaw | dict":
    return rec  # type is checked on access via _get


# ---------------------------------------------------------------------------
# Recession / Threats scoring  (G1–G8)
# ---------------------------------------------------------------------------

def _score_g1(g) -> float:
    jpy = threshold_map(_get(g, "g1_usdjpy"), [(135, 75), (145, 45), (160, 15)])
    jgb = threshold_map(_get(g, "g1_jgb10y"), [(0.75, 10), (1.0, 45), (1.5, 80)])
    return float((jpy + jgb) / 2)


def _score_g2(g) -> float:
    pe   = threshold_map(_get(g, "g2_pe_nasdaq"),  [(25, 10), (35, 45), (45, 85)])
    conc = threshold_map(_get(g, "g2_top5_conc"),  [(30, 10), (40, 45), (50, 85)])
    return float((pe + conc) / 2)


def _score_g3(g) -> float:
    # FIX: original only scored hy_default; credit refi rates also matter
    hy_def  = threshold_map(_get(g, "g3_hy_default"), [(3, 10), (5, 50), (8,  90)])
    ig_refi = threshold_map(_get(g, "g3_ig_refi"),    [(4, 10), (6, 50), (9,  90)])
    hy_refi = threshold_map(_get(g, "g3_hy_refi"),    [(7, 10), (10, 50), (14, 90)])
    return float((hy_def + ig_refi + hy_refi) / 3)


def _score_g4(g) -> float:
    return float(threshold_map(_get(g, "g4_trade_yoy"), [(0, 10), (-1, 35), (-3, 65), (-10, 90)]))


def _score_g5(g) -> float:
    ur     = threshold_map(_get(g, "g5_us_ur"),      [(4.0, 10), (5.0, 50), (6.0, 90)])
    retail = threshold_map(abs(_get(g, "g5_retail_mom")), [(0.5, 10), (1.5, 50), (3.0, 85)])
    return float((ur + retail) / 2)


def _score_g6(g) -> float:
    debt     = threshold_map(_get(g, "g6_debt_gdp"),    [(250, 10), (300, 40), (350, 75)])
    defaults = threshold_map(_get(g, "g6_em_defaults"), [(1, 15),   (3, 55),   (6, 90)])
    return float((debt + defaults) / 2)


def _score_g7(g) -> float:
    oil = threshold_map(_get(g, "g7_brent"), [(80, 10), (100, 45), (130, 85)])
    gpr = threshold_map(_get(g, "g7_gpr"),   [(40, 20), (80, 60),  (120, 90)])
    return float((oil + gpr) / 2)


def _score_g8(g) -> float:
    cre   = threshold_map(_get(g, "g8_cre_vacancy"), [(15, 15), (20, 50), (30, 90)])
    house = threshold_map(abs(_get(g, "g8_housing_yoy")), [(3, 15), (8, 50), (15, 90)])
    bank  = threshold_map(abs(_get(g, "g8_banks_ytd")),   [(5, 10), (15, 45), (25, 85)])
    return float((cre + house + bank) / 3)


def calc_threats_score(rec) -> float:
    """Average of G1–G8 recession sub-scores.  Range: 0–100."""
    scores = [
        _score_g1(rec), _score_g2(rec), _score_g3(rec), _score_g4(rec),
        _score_g5(rec), _score_g6(rec), _score_g7(rec), _score_g8(rec),
    ]
    return float(round(np.mean(scores), 1))


# ---------------------------------------------------------------------------
# Suspicion Index
# ---------------------------------------------------------------------------

def calc_suspicion_index(p, d, flags: list) -> float:
    """
    Six-component orderbook/microstructure suspicion score.  Range: 0–100.
    """
    score = 0.0
    ret_24h    = _get(p, "ret_24h")
    vol_regime = _get(p, "vol_regime", "normal")
    rsi_1d     = _get(p, "rsi_1d", 50.0)
    funding    = _get(d, "funding_8h")
    liq_24h    = _get(d, "liq_24h_usd_m")

    if ret_24h > 1.0 and vol_regime == "low":      score += 20
    if rsi_1d > 70 and vol_regime != "low":        score += 20
    if funding > REGIME_THRESHOLDS["FUNDING_OVERHEAT"]: score += 15
    if "cancel_high" in flags:                     score += 15
    if liq_24h > 500:                              score += 15
    if "whale_dump" in flags:                      score += 15

    return float(min(score, 100.0))


# ---------------------------------------------------------------------------
# MSS / TSS / TRUTH
# ---------------------------------------------------------------------------

def calc_mss_tss(p, d, f, m) -> tuple[float, float, float]:
    """
    MSS  = Manipulation Signal Score  (0–100)
    TSS  = Trend Sincerity Score      (0–100)
    TRUTH = MSS + TSS – 100           (–100…+100)

    Layer scores s1–s6 each contribute 1 or 2 points (max = 12, not 18).
    FIX: original formula divided by 18 but max sum is 12 → scores were
    artificially compressed.  Corrected denominator to 12.
    """
    funding   = _get(d, "funding_8h")
    ret_24h   = _get(p, "ret_24h")
    sopr      = _get(f, "sopr", 1.0)
    fear_g    = _get(m, "fear_greed", 50)
    rsi_1d    = _get(p, "rsi_1d", 50.0)
    cet_delta = _get(f, "cet_delta_7d_pct", 0.0)
    fed       = _get(m, "fed_status", "hold")
    l2_tvl    = _get(f, "l2_tvl_30d_pct", 0.0)
    lth_delta = _get(f, "lth_delta_pct", 0.0)

    s1 = 1 if ret_24h * funding < 0 else 2          # divergence
    s2 = 2 if abs(funding) > 0.03 else 1             # funding extreme
    s3 = 1 if sopr > 1.05 else 2                     # spent outputs
    s4 = 1 if abs(fear_g - 50) > 30 else 2           # sentiment extreme
    s5 = 1 if rsi_1d > 70 or rsi_1d < 30 else 2     # RSI extreme
    s6 = 1 if cet_delta > 2 else 2                   # CEX inflow

    # FIX: max possible = 12 (6 × 2), not 18
    mss = round(((s1 + s2 + s3 + s4 + s5 + s6) / 12.0) * 100.0, 1)

    checks = [
        fed != "hawkish",
        cet_delta <= 0,
        l2_tvl > 0,
        sopr <= 1.05,
        40 < rsi_1d < 60,
    ]
    tss = round((sum(checks) / 5.0) * 100.0, 1)
    truth = round(mss + tss - 100.0, 1)
    return mss, tss, truth


# ---------------------------------------------------------------------------
# WDI (Weighted Directional Index)
# ---------------------------------------------------------------------------

def calc_wdi(p, d, f, m, c) -> float:
    """
    Composite directional index, range approximately –100…+100.

    FIX: block scores are now explicitly clamped to [–100, +100] before
    weighting so extreme inputs cannot produce absurd WDI values.
    Also corrected the 'onchain' formula: high SOPR (>1.05) indicates
    profit-taking (bearish pressure), not bullish — reversed sign logic.
    """
    cet_delta  = _get(f, "cet_delta_7d_pct", 0.0)
    stable_in  = _get(f, "stable_flow", "flat") == "in"
    sopr       = _get(f, "sopr", 1.0)
    lth_delta  = _get(f, "lth_delta_pct", 0.0)
    rsi_1d     = _get(p, "rsi_1d", 50.0)
    atr_pct    = _get(p, "atr_pct", 3.5)
    fear_g     = _get(m, "fear_greed", 50)
    dxy_pct    = _get(m, "dxy_weekly_pct", 0.0)
    c_active   = _get(c, "active", False)
    vol_s      = _get(c, "vol_at_s_pct", 0)
    vol_r      = _get(c, "vol_at_r_pct", 0)

    flows   = np.clip((cet_delta < 0) * 40 + stable_in * 40 - 30, -100, 100)
    tech    = np.clip((rsi_1d < 60) * 30 + (atr_pct < 4.0) * 20 - 25, -100, 100)
    # FIX: SOPR < 1 = HODLing (bullish); SOPR > 1.05 = profit-taking (bearish)
    onch    = np.clip((sopr < 1.0) * 40 + (lth_delta > 0) * 30 - 20, -100, 100)
    macro_s = np.clip((fear_g < 40) * 40 + (dxy_pct < 0) * 20 - 30, -100, 100)
    corr    = np.clip((c_active and vol_s > vol_r) * 20 - 10, -100, 100)

    block_scores = {
        "flows":    float(flows),
        "tech":     float(tech),
        "onchain":  float(onch),
        "macro":    float(macro_s),
        "corridor": float(corr),
    }
    w = WDI_WEIGHTS_BASE
    wdi = sum(w[k] * block_scores[k] for k in w)
    return float(round(np.clip(wdi, -100.0, 100.0), 1))


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------

def calc_confidence(mss: float, tss: float, atr: float, threats: float) -> float:
    """
    Base confidence 0.65, adjusted by signal quality indicators.
    Range: [0.0, 1.0]

    FIX: original used "fresh_whale_data" key for the ATR-low case which is
    semantically misleading — renamed to 'corridor_validated' proxy for
    low-vol confirmed signal.  Also added tss-based mature_pattern check
    (was missing), and ensured result is clamped to [0, 1].
    """
    base = 0.65
    adj = CONFIDENCE_ADJUSTMENTS

    if tss > 70:    base += adj["mature_pattern"]
    if mss > 60:    base += adj["conflicting_signals"]
    if atr < 3.0:   base += adj["corridor_validated"]   # low vol = tighter signal
    if threats > 60: base += adj["macro_uncertainty"]

    return float(max(0.0, min(1.0, base)))


# ---------------------------------------------------------------------------
# Humanity Score
# ---------------------------------------------------------------------------

def calc_humanity(wdi: float, conf: float, threats: float) -> float:
    """
    Composite health score.  Range: [0, 100].
    Formula per README: WDI_norm×0.3 + Conf×0.4 + (100–Threats)×0.3
    """
    wdi_norm = float(np.clip((wdi + 100) / 2.0, 0.0, 100.0))
    raw = (wdi_norm * 0.3) + (conf * 100 * 0.4) + ((100.0 - threats) * 0.3)
    return float(round(np.clip(raw, 0.0, 100.0), 1))


# ---------------------------------------------------------------------------
# Social Intelligence Integration
# ---------------------------------------------------------------------------

def inject_social_features(base_features: dict, social_features) -> dict:
    """
    Merges SocialFeatures into the base feature dict consumed by all agents.

    Design: social features are injected as flat keys alongside market features.
    Agents that don't know about social signals simply ignore the new keys.
    Agents that want social context can read them by name.

    Parameters
    ----------
    base_features : dict
        The existing feature dict (market, on-chain, macro metrics).
    social_features : SocialFeatures | dict | None
        Output from SocialProcessor.  Accepts both Pydantic model and dict
        for flexibility.  If None or empty, base_features is returned as-is.

    Returns
    -------
    dict
        Merged feature dict.  base_features is NOT mutated.
    """
    if social_features is None:
        return base_features

    if hasattr(social_features, "model_dump"):
        sf_dict = social_features.model_dump()
    elif isinstance(social_features, dict):
        sf_dict = social_features
    else:
        return base_features

    # Only inject keys with meaningful data (skip defaults if quality is low)
    quality = sf_dict.get("data_quality", 0.0)
    if quality < 0.1:
        # Not enough data — inject zeros so keys exist but don't distort signals
        sf_dict = {k: (0.0 if isinstance(v, float) else v)
                   for k, v in sf_dict.items()}

    merged = dict(base_features)
    merged.update(sf_dict)
    return merged


def calc_social_wdi_adjustment(social_features) -> float:
    """
    Computes a social-momentum adjustment to WDI in range [-10, +10].

    Applied AFTER base WDI calculation to add social signal without
    disrupting the calibrated market-data weighting.

    Logic:
      - Strong bullish sentiment + high attention → positive adjustment (up to +10)
      - Panic + high attention → negative adjustment (down to -10)
      - Bot-dominated or low quality → dampened adjustment
    """
    if social_features is None:
        return 0.0

    get = (lambda k, d=0.0: social_features.get(k, d)
           if isinstance(social_features, dict)
           else getattr(social_features, k, d))

    sentiment      = get("sentiment_score")       # -1…+1
    attention      = get("attention_score")        # 0…1
    panic          = get("panic_score")            # 0…1
    bot_prob       = get("bot_probability")        # 0…1
    data_quality   = get("data_quality", 1.0)      # 0…1
    inf_alignment  = get("influencer_alignment")   # -1…+1

    # Base momentum: sentiment weighted by attention
    momentum = sentiment * attention

    # Panic override: high panic dampens any bullish adjustment
    panic_dampen = 1.0 - (panic * 0.8)

    # Bot dampening: artificial signals should reduce adjustment weight
    bot_dampen = 1.0 - (bot_prob * 0.5)

    # Influencer amplification: influencer alignment adds conviction
    inf_factor = 1.0 + abs(inf_alignment) * 0.3

    raw_adj = momentum * panic_dampen * bot_dampen * inf_factor * data_quality

    # Scale to ±10 range
    return float(round(np.clip(raw_adj * 10.0, -10.0, 10.0), 2))


def calc_social_confidence_adjustment(social_features) -> float:
    """
    Micro-adjustment to confidence score in range [-0.08, +0.05].

    Positive when: high data quality + aligned influencers + low bot probability.
    Negative when: low data quality or strong panic (unreliable signal).
    """
    if social_features is None:
        return 0.0

    get = (lambda k, d=0.0: social_features.get(k, d)
           if isinstance(social_features, dict)
           else getattr(social_features, k, d))

    data_quality = get("data_quality", 1.0)
    bot_prob     = get("bot_probability")
    panic_score  = get("panic_score")
    inf_align    = abs(get("influencer_alignment"))

    if data_quality < 0.3:
        return -0.05  # not enough data to be confident

    adj = 0.0
    if data_quality > 0.7 and bot_prob < 0.1:
        adj += 0.03   # clean, high-coverage social data increases confidence
    if inf_align > 0.5:
        adj += 0.02   # influencers aligned = stronger signal
    if panic_score > 0.6:
        adj -= 0.08   # extreme fear makes markets unpredictable

    return float(round(np.clip(adj, -0.08, 0.05), 3))

