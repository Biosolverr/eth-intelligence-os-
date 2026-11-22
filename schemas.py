"""
schemas.py
Pydantic models for raw input validation.

FIXES vs original shemas.py:
  - File renamed: shemas.py → schemas.py (typo)
  - RawInput: added field_validator for deriv/flow aliases so both
    input.json keys ("deriv"/"flow") and agent keys ("derivatives"/"flows")
    work transparently via model_config aliases.
  - Added horizon_days to MetaLayer (was silently ignored before).
  - DerivLayer / FlowLayer: exported with canonical names used by agents.
"""

from pydantic import BaseModel, Field, model_validator
from typing import List, Literal, Optional


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class MetaLayer(BaseModel):
    asset: str = "ETH"
    date_utc: str = ""
    horizon_days: int = 30
    history_dir: str = "./data/history/"


class PriceLayer(BaseModel):
    current: float
    ret_24h: float
    ret_7d: float
    ret_30d: float
    s1: float
    s2: float
    r1: float
    r2: float
    rsi_1d: float
    rsi_4h: float
    atr_pct: float
    vol_regime: Literal["low", "normal", "high"]
    macd_status: Literal["bullish_cross", "bearish_cross", "neutral"]
    ma_alignment: Literal["bullish", "bearish", "neutral"]


class DerivLayer(BaseModel):
    oi_usd_m: float
    oi_d1_pct: float
    oi_w_pct: float
    funding_8h: float
    liq_24h_usd_m: float
    liq_side: Literal["longs", "shorts", "mixed"]


class FlowLayer(BaseModel):
    etf_7d_usd_m: float
    cet_supply_m_eth: float
    cet_delta_7d_pct: float
    stable_flow: Literal["in", "out", "flat"]
    stable_amount_usd_m: float
    sopr: float
    lth_delta_pct: float
    l2_tvl_30d_pct: float


class MacroLayer(BaseModel):
    hy_oas_bps: float
    dxy_weekly_pct: float
    yield_curve_bps: float
    fed_status: Literal["easing", "hold", "hawkish"]
    spx_drawdown_pct: float
    equity_breadth_pct: float
    btc_corr_30d: float
    fear_greed: int


class RecessionRaw(BaseModel):
    g1_usdjpy: float
    g1_jgb10y: float
    g2_pe_nasdaq: float
    g2_top5_conc: float
    g3_hy_default: float
    g3_ig_refi: float
    g3_hy_refi: float
    g4_trade_yoy: float
    g5_us_ur: float
    g5_retail_mom: float
    g6_debt_gdp: float
    g6_em_defaults: int
    g7_brent: float
    g7_gpr: float
    g8_cre_vacancy: float
    g8_housing_yoy: float
    g8_banks_ytd: float


class CorridorLayer(BaseModel):
    active: bool = False
    cs: float = 0.0
    cr: float = 0.0
    cm: float = 0.0
    cwidth_pct: float = 0.0
    touch_s: int = 0
    touch_r: int = 0
    false_breaks: int = 0
    vol_at_s_pct: int = 0
    vol_at_r_pct: int = 0
    vol_at_mid_pct: int = 0
    flags: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Root input model
# ---------------------------------------------------------------------------

class RawInput(BaseModel):
    """
    Accepts both input.json key names ("deriv", "flow") and internal names
    ("derivatives", "flows") via model_validator so agents can use either.
    """
    meta: MetaLayer = Field(default_factory=MetaLayer)
    price: PriceLayer
    # Accept "deriv" OR "derivatives" from JSON
    derivatives: Optional[DerivLayer] = None
    deriv: Optional[DerivLayer] = None
    # Accept "flow" OR "flows" from JSON
    flows: Optional[FlowLayer] = None
    flow: Optional[FlowLayer] = None
    macro: MacroLayer
    recession: RecessionRaw
    corridor: CorridorLayer = Field(default_factory=CorridorLayer)

    @model_validator(mode="after")
    def _unify_aliases(self) -> "RawInput":
        # Normalise derivatives
        if self.derivatives is None and self.deriv is not None:
            self.derivatives = self.deriv
        elif self.derivatives is None:
            raise ValueError("Either 'derivatives' or 'deriv' field is required.")
        # Normalise flows
        if self.flows is None and self.flow is not None:
            self.flows = self.flow
        elif self.flows is None:
            raise ValueError("Either 'flows' or 'flow' field is required.")
        return self

    def model_dump_unified(self) -> dict:
        """
        Returns a dict with canonical keys 'derivatives' and 'flows'
        so all agents/features can access data consistently.
        """
        d = self.model_dump(exclude={"deriv", "flow"})
        d["derivatives"] = self.derivatives.model_dump()
        d["flows"] = self.flows.model_dump()
        return d
