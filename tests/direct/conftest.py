"""Shared fixtures for DIRECT-MODE tests (in-memory GenVM SDK, mocked LLM).

IMPORTANT: direct mode is NOT validator consensus. `run_validator()` replays the
validator function against swapped mocks; it proves our comparison logic, not
real network behaviour. Real-validator evidence must come from Studio/testnet.
"""
import copy
import json
import sys

import pytest

SDK_VERSION = "v0.2.16"  # `latest` (v0.3.0-rc7) ships no genvm-universal tarball; see docs/ARCHITECTURE.md
CONTRACT = "contracts/eth_intelligence.py"
TX_TIME = "2026-10-11T12:00:00Z"
OBSERVED = "2026-10-11T11:30:00Z"


def base_snapshot(observed_at: str = OBSERVED) -> dict:
    """Values mirror input.json; `risk` is locally derived from engine/ (kind=derived)."""
    return {
        "schema_version": "1",
        "meta": {"asset": "ETH", "horizon_days": 30, "observed_at": observed_at},
        "price": {
            "current": 2995.4, "ret_24h": -0.8, "ret_7d": 1.2, "ret_30d": -2.1,
            "rsi_1d": 49.8, "atr_pct": 3.9, "vol_regime": "normal",
            "macd_status": "bullish_cross", "ma_alignment": "bullish",
        },
        "derivs": {
            "oi_d1_pct": -0.5, "oi_w_pct": -2.1, "funding_8h": 0.0088,
            "liq_24h_usd_m": 56.4, "liq_side": "longs",
        },
        "flows": {
            "etf_7d_usd_m": 67.0, "cet_delta_7d_pct": -2.1, "stable_flow": "in",
            "stable_amount_usd_m": 1160.0, "sopr": 1.02, "lth_delta_pct": 2.5,
            "l2_tvl_30d_pct": 8.0,
        },
        "macro": {
            "hy_oas_bps": 420.0, "dxy_weekly_pct": 0.4, "yield_curve_bps": 30.0,
            "fed_status": "hold", "spx_drawdown_pct": -3.5,
            "equity_breadth_pct": 48.0, "btc_corr_30d": 0.65, "fear_greed": 22,
        },
        "risk": {"threats_score": 29.6, "regime": "accumulation"},
        "sources": [
            {"group": "price", "source_id": "exchange.spot", "observed_at": observed_at, "kind": "raw"},
            {"group": "derivs", "source_id": "exchange.perp", "observed_at": observed_at, "kind": "raw"},
            {"group": "flows", "source_id": "onchain.agg", "observed_at": observed_at, "kind": "raw"},
            {"group": "macro", "source_id": "macro.feed", "observed_at": observed_at, "kind": "raw"},
            {"group": "risk", "source_id": "engine.v0_2", "observed_at": observed_at, "kind": "derived"},
        ],
    }


def dumps(snap: dict) -> str:
    return json.dumps(snap)


LAYERS = ("quant", "flow", "macro", "manipulation", "risk")
LAYER_DEFAULTS = {
    "quant": {"score": 25, "caution": 30, "inconclusive": False, "drivers": ["price.rsi_1d"], "note": "default quant"},
    "flow": {"score": 30, "caution": 25, "inconclusive": False, "drivers": ["flows.sopr"], "note": "default flow"},
    "macro": {"score": 10, "caution": 30, "inconclusive": False, "drivers": ["macro.fed_status"], "note": "default macro"},
    "manipulation": {"caution": 20, "inconclusive": False, "drivers": ["derivs.funding_8h"], "note": "default manip"},
    "risk": {"caution": 30, "inconclusive": False, "drivers": ["risk.threats_score"], "note": "default risk"},
}


def layer_pat(layer: str) -> str:
    return r"\[\[LAYER %s\]\]" % layer


def set_llm_mock(vm, pattern: str, response: str) -> None:
    """Direct mode matches the FIRST registered mock (pattern.search), so replace instead of append."""
    vm._llm_mocks[:] = [m for m in vm._llm_mocks if m[0].pattern != pattern]
    vm.mock_llm(pattern, response)


def mock_layers(vm, **overrides) -> None:
    for layer in LAYERS:
        val = overrides.get(layer, LAYER_DEFAULTS[layer])
        set_llm_mock(vm, layer_pat(layer), val if isinstance(val, str) else json.dumps(val))


def as_addr(x):
    """Direct-mode fixtures for accounts are sometimes raw bytes; contract storage needs genlayer.Address."""
    if hasattr(x, "as_hex"):
        return x
    from genlayer import Address
    return Address(x)


def analyze_all(eth, sid):
    """Run every consensus-mode layer (own transaction each), then the final verdict."""
    for layer, mode in eth.get_snapshot_modes(sid).items():
        if mode == "consensus" and not eth.get_layer_result(sid, layer):
            eth.analyze_layer(sid, layer)   # layers already stored are NOT re-run (that is the feature)
    return eth.analyze(sid)


def llm_json(stance="bullish", conviction=60, risk="moderate", bull=("flows.etf_7d_usd_m",),
             bear=("derivs.funding_8h",), conflicts=(), gaps=(), summary="Flows support; funding mixed."):
    return json.dumps({
        "stance": stance, "conviction": conviction, "risk_level": risk,
        "bullish_evidence": list(bull), "bearish_evidence": list(bear),
        "conflicts": list(conflicts), "data_gaps": list(gaps), "summary": summary,
    })


def set_tx_time(direct_vm, ts: str) -> None:
    """Change the *transaction datetime* the contract sees.

    Harness limitation (verified in gltest/direct/vm.py::_refresh_gl_message):
    `vm.warp()` patches datetime.now() but does NOT update gl.message_raw["datetime"],
    which the SDK reads once at import. The contract uses message_raw["datetime"]
    (documented as the transaction datetime), so tests set it explicitly.
    """
    direct_vm.warp(ts)
    gl = sys.modules.get("genlayer.gl")
    if gl is not None and getattr(gl, "message_raw", None) is not None:
        gl.message_raw["datetime"] = ts


@pytest.fixture
def snap():
    return copy.deepcopy(base_snapshot())


@pytest.fixture
def eth(direct_vm, direct_deploy, direct_alice):
    """Contract deployed by the default owner; transactions then sent by alice at TX_TIME."""
    direct_vm.check_pickling = True
    set_tx_time(direct_vm, TX_TIME)
    contract = direct_deploy(CONTRACT, sdk_version=SDK_VERSION)
    set_tx_time(direct_vm, TX_TIME)  # deploy may re-read message_raw; pin again
    direct_vm.sender = direct_alice
    mock_layers(direct_vm)
    _orig_clear = direct_vm.clear_mocks
    direct_vm.clear_mocks = lambda: (_orig_clear(), mock_layers(direct_vm))  # tests re-mock only the FINAL prompt
    return contract


@pytest.fixture
def submit(eth):
    def _submit(snapshot):
        return eth.submit_snapshot(dumps(snapshot))
    return _submit
