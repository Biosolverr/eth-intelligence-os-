"""
config.py
Global thresholds and weight constants.
All values sourced from CHECK.txt / 1-3 LAYER methodology docs.
"""

THREAT_THRESHOLDS = {
    "LOW":      (0,  30),
    "CAUTION":  (30, 45),
    "ELEVATED": (45, 60),
    "HIGH":     (60, 75),
    "CRISIS":   (75, 100),
}

SUSPICION_THRESHOLDS = {
    "HEALTHY":     (0,  30),
    "CAUTIOUS":    (30, 60),
    "MANIPULATED": (60, 80),
    "CRITICAL":    (80, 100),
}

# Base WDI block weights (sum = 1.0)
WDI_WEIGHTS_BASE: dict[str, float] = {
    "flows":    0.32,
    "tech":     0.26,
    "onchain":  0.20,
    "macro":    0.14,
    "corridor": 0.08,
}

CONFIDENCE_ADJUSTMENTS: dict[str, float] = {
    "fresh_whale_data":   +0.12,
    "conflicting_signals": -0.15,
    "mature_pattern":     +0.10,
    "macro_uncertainty":  -0.10,
    "corridor_validated": +0.05,
}

REGIME_THRESHOLDS: dict[str, float] = {
    "ATR_LOW":          3.0,
    "ATR_HIGH":         5.0,
    "FUNDING_OVERHEAT": 0.05,
    "CEX_OUTFLOW":     -2.0,
}

# Humanity score zone boundaries (README table)
HUMANITY_ZONES = [
    (75, "BULLISH",  "🟢"),
    (60, "CAUTIOUS", "🟡"),
    (40, "BEARISH",  "🟠"),
    ( 0, "CRISIS",   "🔴"),
]
