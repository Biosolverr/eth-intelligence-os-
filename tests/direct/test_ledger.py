"""Direct-mode tests: contracts/eth_outcome_ledger.py and the verdict->ledger link.

LIMITS (do not over-read): web access is mocked (vm.mock_web); cross-contract `emit` is observed through a
RECORDER stub of gl.get_contract_at (direct mode cannot deliver real messages and cannot load two contracts);
"child tx sender == verdict contract address" is documented behaviour, NOT tested here.
"""
import datetime
import json
import sys

import pytest

from tests.direct.conftest import (
    SDK_VERSION, TX_TIME, analyze_all, base_snapshot, llm_json, set_tx_time,
)

LEDGER = "contracts/eth_outcome_ledger.py"
TEMPLATE = "https://api.binance.com/api/v3/klines?symbol=ETHUSDT&interval=1h&startTime={start_ms}&limit=1"
SID = "a" * 64
SUB_A, SUB_B = "0x" + "a1" * 20, "0x" + "b2" * 20
ANALYZED = "2026-09-01T12:30:00Z"        # verdict produced; graded window starts at 13:00 (next full hour)
OBSERVED = "2026-09-01T12:10:00Z"        # submitter-asserted observation time (hour candle 12:00)
P3000 = 300_000_000_000                  # 3000.00 in e8
ANY = r"analyst adjudicating"


def ms(iso: str, plus_days: int = 0) -> int:
    d = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")) + datetime.timedelta(days=plus_days)
    return int(d.timestamp()) * 1000


OBS_MS = ms("2026-09-01T12:00:00Z")
REF_MS = ms("2026-09-01T13:00:00Z")
END_MS = ms("2026-09-01T13:00:00Z", 30)


def kline(start_ms, open_price, high=None, low=None):
    return json.dumps([[start_ms, open_price, high or open_price, low or open_price, open_price, "1", start_ms + 3599999]])


def mock_prices(vm, obs="3000.00", ref="3000.00", end="3300.00", status=200, bodies=None):
    bodies = bodies or {}
    for name, start, price in (("obs", OBS_MS, obs), ("ref", REF_MS, ref), ("end", END_MS, end)):
        vm.mock_web(r".*startTime=%d&.*" % start, {"status": status, "body": bodies.get(name) or kline(start, price)})


@pytest.fixture
def ledger(direct_vm, direct_deploy, direct_alice, direct_bob):
    set_tx_time(direct_vm, TX_TIME)
    from gltest.direct.sdk_loader import setup_sdk_paths
    setup_sdk_paths(__import__("pathlib").Path(LEDGER), SDK_VERSION)
    from genlayer import Address  # importable only after SDK paths are set up
    # public-method args are converted by the proxy; CONSTRUCTOR args are not -> wrap explicitly (idempotent).
    verdict = direct_bob if hasattr(direct_bob, "as_hex") else Address(direct_bob)
    c = direct_deploy(LEDGER, verdict, TEMPLATE, 300, 300, sdk_version=SDK_VERSION)   # bob = "verdict contract"
    set_tx_time(direct_vm, TX_TIME)
    direct_vm.sender = direct_alice
    return c


@pytest.fixture
def reg(ledger, direct_vm, direct_bob):
    def _reg(sid=SID, submitter=SUB_A, stance="bullish", conv=70, risk="moderate", horizon=30,
             analyzed=ANALYZED, observed=OBSERVED, price=P3000, ref=""):
        with direct_vm.prank(direct_bob):
            ledger.register(sid, submitter, ref, stance, conv, risk, horizon, analyzed, observed, price)
        return sid
    return _reg


def res(ledger, sid=SID):
    return json.loads(ledger.get_resolution(sid))


class TestRegister:
    def test_l01_registered_by_verdict_contract(self, ledger, reg):
        reg()
        e = json.loads(ledger.get_entry(SID))
        assert ledger.get_status(SID) == "REGISTERED"
        assert (e["obs_ms"], e["ref_ms"], e["target_ms"]) == (OBS_MS, REF_MS, END_MS)
        assert e["resolve_not_before_s"] == END_MS // 1000 + 7200 and e["submitter"] == SUB_A
        sc = ledger.get_scorecard()
        assert (sc["registered"], sc["resolved"], sc["unresolved"]) == (1, 0, 1)

    def test_l02_grading_window_is_forward_only(self, ledger, reg):
        """P1 regression: window used to start at the submitter-asserted observed_at (up to a day BEFORE the
        verdict), so most of a 1-day window was already known. It must start after the verdict."""
        reg(analyzed="2026-10-11T12:50:00Z", observed="2026-10-10T13:00:00Z", horizon=1)
        e = json.loads(ledger.get_entry(SID))
        analyzed_s = ms("2026-10-11T12:50:00Z") // 1000
        assert e["ref_ms"] // 1000 > analyzed_s                       # graded window starts after the verdict
        assert e["ref_ms"] // 1000 - analyzed_s <= 3600               # ... at the very next full hour
        assert e["ref_ms"] == ms("2026-10-11T13:00:00Z")
        assert e["target_ms"] - e["ref_ms"] == 86400 * 1000           # exactly the declared horizon, all of it unknown at verdict time

    def test_l03_other_senders_cannot_register(self, ledger, direct_vm):
        with direct_vm.expect_revert("only the verdict contract"):
            ledger.register(SID, SUB_A, "", "bullish", 70, "moderate", 30, ANALYZED, OBSERVED, P3000)   # alice
        assert ledger.get_status(SID) == "UNKNOWN" and ledger.get_scorecard()["registered"] == 0

    def test_l04_redelivery_is_idempotent_never_overwrites_never_double_counts(self, ledger, reg, direct_vm, direct_bob):
        reg(stance="bullish")
        with direct_vm.prank(direct_bob):
            ledger.register(SID, SUB_B, "", "bearish", 99, "high", 7, ANALYZED, OBSERVED, P3000)
        e = json.loads(ledger.get_entry(SID))
        assert e["stance"] == "bullish" and e["submitter"] == SUB_A
        assert ledger.get_scorecard()["registered"] == 1 and ledger.get_submitter_scorecard(SUB_B)["registered"] == 0

    @pytest.mark.parametrize("kw,needle", [
        (dict(stance="moon"), "invalid stance"), (dict(risk="extreme"), "invalid stance"),
        (dict(conv=101), "invalid conviction"), (dict(conv=True), "invalid conviction"),
        (dict(horizon=0), "invalid horizon"), (dict(horizon=91), "invalid horizon"),
        (dict(sid="xyz"), "invalid snapshot id"),
        (dict(submitter="0x123"), "invalid submitter"), (dict(submitter="a1" * 20), "invalid submitter"),
        (dict(price=0), "invalid asserted price"), (dict(price=-5), "invalid asserted price"),
        (dict(price=True), "invalid asserted price"), (dict(price=10 ** 15 + 1), "invalid asserted price"),
        (dict(observed="2026-09-01T12:10:00"), "explicit timezone"),
        (dict(observed="2026-09-01T12:40:00Z"), "inconsistent"),      # observed AFTER the verdict
        (dict(observed="2026-08-01T12:10:00Z"), "inconsistent"),      # absurdly stale claim
    ])
    def test_l05_invalid_registration_rejected(self, ledger, reg, direct_vm, kw, needle):
        with direct_vm.expect_revert(needle):
            reg(**kw)
        assert ledger.get_scorecard()["registered"] == 0

    @pytest.mark.parametrize("tpl,band,dev", [
        ("http://x/{start_ms}", 300, 300), ("https://x/no-placeholder", 300, 300),
        (TEMPLATE, 10, 300), (TEMPLATE, 9999, 300), (TEMPLATE, 300, 10), (TEMPLATE, 300, 5000),
    ])
    def test_l06_constructor_validation(self, direct_vm, direct_deploy, direct_bob, tpl, band, dev):
        from gltest.direct.sdk_loader import setup_sdk_paths
        setup_sdk_paths(__import__("pathlib").Path(LEDGER), SDK_VERSION)
        from genlayer import Address
        verdict = direct_bob if hasattr(direct_bob, "as_hex") else Address(direct_bob)
        with pytest.raises(Exception, match="EXPECTED"):
            direct_deploy(LEDGER, verdict, tpl, band, dev, sdk_version=SDK_VERSION)


class TestResolve:
    def test_l10_bullish_hit_and_fields(self, ledger, reg, direct_vm):
        reg(); mock_prices(direct_vm, "3000.00", "3000.00", "3300.00")
        ledger.resolve(SID)
        r = res(ledger)
        assert (r["return_bps"], r["realized"], r["result"], r["evidence_ok"], r["deviation_bps"]) == (1000, "up", "hit", True, 0)
        assert (r["obs_open_e8"], r["ref_open_e8"], r["end_open_e8"]) == (P3000, P3000, 330_000_000_000)
        assert ledger.get_status(SID) == "RESOLVED"

    def test_l11_miss_bearish_hit_neutral_hit(self, ledger, reg, direct_vm):
        for sid, stance, end, expect in [("b" * 64, "bullish", "2700.00", "miss"), ("c" * 64, "bearish", "2700.00", "hit"),
                                          ("d" * 64, "neutral", "3030.00", "hit")]:
            reg(sid=sid, stance=stance); direct_vm.clear_mocks(); mock_prices(direct_vm, end=end)
            ledger.resolve(sid)
            assert res(ledger, sid)["result"] == expect, (stance, expect)

    def test_l12_inconclusive_abstains(self, ledger, reg, direct_vm):
        reg(stance="inconclusive"); mock_prices(direct_vm, end="3600.00")
        ledger.resolve(SID)
        sc = ledger.get_scorecard()
        assert res(ledger)["result"] == "abstain" and sc["inconclusive:abstain"] == 1
        assert sum(v for k, v in sc.items() if k.endswith(":hit") or k.endswith(":miss")) == 0

    def test_l13_return_uses_ref_and_end_not_the_observation_candle(self, ledger, reg, direct_vm):
        reg(); mock_prices(direct_vm, obs="3010.00", ref="10000.00", end="10300.00")   # obs differs slightly; ref->end = +300 bps
        ledger.resolve(SID)
        r = res(ledger)
        assert r["return_bps"] == 300 and r["realized"] == "up" and r["evidence_ok"] is True

    def test_l14_negative_return_truncates_toward_zero(self, ledger, reg, direct_vm):
        reg(stance="bearish"); mock_prices(direct_vm, end="2990.00")
        ledger.resolve(SID)
        r = res(ledger)
        assert r["return_bps"] == -33 and r["realized"] == "flat" and r["result"] == "miss"

    def test_l15_before_horizon_rejected(self, ledger, reg, direct_vm):
        reg(sid="e" * 64, analyzed="2026-10-10T12:00:00Z", observed="2026-10-10T11:50:00Z"); mock_prices(direct_vm)
        with direct_vm.expect_revert("horizon not reached"):
            ledger.resolve("e" * 64)

    def test_l16_resolution_immutable(self, ledger, reg, direct_vm):
        reg(); mock_prices(direct_vm); ledger.resolve(SID)
        first = ledger.get_resolution(SID)
        direct_vm.clear_mocks(); mock_prices(direct_vm, end="1.00")
        with direct_vm.expect_revert("already resolved"):
            ledger.resolve(SID)
        assert ledger.get_resolution(SID) == first and ledger.get_scorecard()["resolved"] == 1

    def test_l17_unknown_snapshot(self, ledger, direct_vm):
        with direct_vm.expect_revert("unknown snapshot"):
            ledger.resolve("f" * 64)

    @pytest.mark.parametrize("kw,needle", [
        (dict(status=500), "HTTP status 500"), (dict(status=404), "HTTP status 404"),
        (dict(bodies={"ref": "not json"}), "invalid JSON"), (dict(bodies={"end": "[]"}), "unexpected kline shape"),
        (dict(bodies={"obs": json.dumps([[OBS_MS + 3600000, "3000", "3000", "3000", "3000", "1", 0]])}), "not the requested hour"),
        (dict(bodies={"obs": json.dumps([[OBS_MS, "abc", "3000", "3000", "3000", "1", 0]])}), "unparseable price"),
        (dict(bodies={"end": json.dumps([[END_MS, 3000.0, "0"]])}), "unparseable price"),
        (dict(bodies={"ref": json.dumps([[REF_MS, "0.00000000", "0"]])}), "non-positive price"),
    ])
    def test_l18_any_one_candle_failing_means_no_resolution(self, ledger, reg, direct_vm, kw, needle):
        reg(); mock_prices(direct_vm, **kw)
        with direct_vm.expect_revert(needle):
            ledger.resolve(SID)
        assert ledger.get_status(SID) == "REGISTERED" and ledger.get_resolution(SID) == ""
        assert ledger.get_scorecard()["resolved"] == 0

    def test_l19_failed_resolution_is_retryable(self, ledger, reg, direct_vm):
        reg(); mock_prices(direct_vm, status=503)
        with direct_vm.expect_revert("HTTP status 503"):
            ledger.resolve(SID)
        direct_vm.clear_mocks(); mock_prices(direct_vm)
        ledger.resolve(SID)
        assert ledger.get_status(SID) == "RESOLVED"

    def test_l20_global_scorecard_counts(self, ledger, reg, direct_vm):
        for sid, stance, end in [("1" * 64, "bullish", "3300.00"), ("2" * 64, "bullish", "2700.00"), ("3" * 64, "bearish", "2700.00")]:
            reg(sid=sid, stance=stance); direct_vm.clear_mocks(); mock_prices(direct_vm, end=end)
            ledger.resolve(sid)
        sc = ledger.get_scorecard()
        assert (sc["bullish:hit"], sc["bullish:miss"], sc["bearish:hit"], sc["resolved"], sc["unresolved"]) == (1, 1, 1, 3, 0)


class TestNoSurvivorshipBias:
    def test_s01_unresolved_entries_stay_visible(self, ledger, reg, direct_vm):
        """P1 regression: a keeper resolving only the flattering verdict used to show '1 hit of 1'."""
        for sid, stance in [("1" * 64, "bullish"), ("2" * 64, "bullish"), ("3" * 64, "bearish")]:
            reg(sid=sid, stance=stance)
        mock_prices(direct_vm, end="3300.00"); ledger.resolve("1" * 64)   # only the lucky one
        sc = ledger.get_scorecard()
        assert (sc["registered"], sc["resolved"], sc["unresolved"], sc["bullish:hit"]) == (3, 1, 2, 1)

    def test_s02_anyone_can_list_and_resolve_the_overdue_ones(self, ledger, reg, direct_vm):
        for sid in ("1" * 64, "2" * 64):
            reg(sid=sid)
        reg(sid="3" * 64, analyzed="2026-10-10T12:00:00Z", observed="2026-10-10T11:50:00Z")      # not due yet
        assert set(ledger.get_unresolved_due_page(0, 50, NOW_S())) == {"1" * 64, "2" * 64}
        mock_prices(direct_vm); ledger.resolve("1" * 64)
        assert list(ledger.get_unresolved_due_page(0, 50, NOW_S())) == ["2" * 64]
        with direct_vm.expect_revert("invalid page"):
            ledger.get_unresolved_due_page(0, 0, NOW_S())

    def test_s03_due_page_scan_is_bounded(self, ledger, reg):
        for i in range(1, 56):
            reg(sid="%064x" % i)
        assert len(ledger.get_unresolved_due_page(0, 1000, NOW_S())) == 50
        assert len(ledger.get_unresolved_due_page(50, 50, NOW_S())) == 5


class TestNoScorecardPollution:
    def test_p01_scorecards_are_per_submitter(self, ledger, reg, direct_vm):
        reg(sid="1" * 64, submitter=SUB_A, stance="bullish")
        reg(sid="2" * 64, submitter=SUB_B, stance="bullish")
        mock_prices(direct_vm, end="3300.00"); ledger.resolve("1" * 64)
        direct_vm.clear_mocks(); mock_prices(direct_vm, end="2700.00"); ledger.resolve("2" * 64)
        a, b = ledger.get_submitter_scorecard(SUB_A), ledger.get_submitter_scorecard(SUB_B)
        assert (a["bullish:hit"], a["bullish:miss"], a["registered"], a["resolved"]) == (1, 0, 1, 1)
        assert (b["bullish:hit"], b["bullish:miss"], b["registered"], b["resolved"]) == (0, 1, 1, 1)
        assert ledger.get_scorecard()["registered"] == 2
        assert ledger.get_submitter_scorecard(SUB_A.upper().replace("0X", "0x")) == a        # case-insensitive
        assert ledger.get_submitter_scorecard("0x" + "c3" * 20)["registered"] == 0
        with direct_vm.expect_revert("invalid submitter"):
            ledger.get_submitter_scorecard("nobody")

    def test_p02_implausible_asserted_price_is_excluded_not_scored(self, ledger, reg, direct_vm):
        """A verdict built on a price that validators do not see is not allowed to move hit/miss statistics."""
        reg(price=2_000_00000000)                                     # claims 2000 while the market was 3000
        mock_prices(direct_vm, obs="3000.00", end="3300.00")
        ledger.resolve(SID)
        r = res(ledger)
        assert (r["evidence_ok"], r["result"], r["deviation_bps"]) == (False, "excluded", 3333)
        sc = ledger.get_scorecard()
        assert (sc["excluded"], sc["resolved"], sc["bullish:hit"], sc["bullish:miss"]) == (1, 1, 0, 0)
        assert ledger.get_submitter_scorecard(SUB_A)["excluded"] == 1

    def test_p03_deviation_boundary(self, ledger, reg, direct_vm):
        reg(sid="1" * 64, price=309_000_000_000)                     # |3090-3000|/3000 = 300 bps -> allowed
        reg(sid="2" * 64, price=309_100_000_000)                     # 303 bps -> excluded
        mock_prices(direct_vm); ledger.resolve("1" * 64); ledger.resolve("2" * 64)
        assert res(ledger, "1" * 64)["evidence_ok"] is True and res(ledger, "1" * 64)["result"] == "hit"
        assert res(ledger, "2" * 64)["evidence_ok"] is False and res(ledger, "2" * 64)["result"] == "excluded"


    def test_p04_submitter_case_is_normalised_on_registration(self, ledger, reg):
        reg(submitter="0x" + "A1" * 20)                               # checksummed-style mixed case
        assert json.loads(ledger.get_entry(SID))["submitter"] == SUB_A
        assert ledger.get_submitter_scorecard(SUB_A)["registered"] == 1

    def test_p05_asserted_price_is_checked_against_the_observation_candle_not_the_start_candle(self, ledger, reg, direct_vm):
        reg(price=P3000)                                              # asserted == observation-hour price
        mock_prices(direct_vm, obs="3000.00", ref="3500.00", end="3850.00")   # market moved afterwards (ref differs)
        ledger.resolve(SID)
        r = res(ledger)
        assert r["evidence_ok"] is True and r["deviation_bps"] == 0 and r["return_bps"] == 1000


class TestPriceValidators:
    def test_v01_validator_requires_all_three_prices_exactly(self, ledger, reg, direct_vm):
        reg(); mock_prices(direct_vm); ledger.resolve(SID)
        direct_vm.clear_mocks(); mock_prices(direct_vm)
        assert direct_vm.run_validator() is True
        for kw in (dict(obs="3000.01"), dict(ref="2999.99"), dict(end="3300.01")):
            direct_vm.clear_mocks(); mock_prices(direct_vm, **kw)
            assert direct_vm.run_validator() is False, kw

    def test_v02_validator_source_failure_is_disagreement(self, ledger, reg, direct_vm):
        reg(); mock_prices(direct_vm); ledger.resolve(SID)
        direct_vm.clear_mocks(); mock_prices(direct_vm, status=500)
        assert direct_vm.run_validator() is False

    def test_v03_decision_rule_directly(self, ledger):
        mod = next(m for m in sys.modules.values() if hasattr(m, "prices_decision") and hasattr(m, "EthOutcomeLedger"))
        gl = sys.modules["genlayer.gl"]
        mine = {"obs_e8": 2, "obs_hi_e8": 3, "obs_lo_e8": 1, "ref_e8": 2, "end_e8": 3}
        ok = lambda: mine
        assert mod.prices_decision(gl.vm.Return(dict(mine)), ok) is True
        for k in mine:
            assert mod.prices_decision(gl.vm.Return(dict(mine, **{k: 99})), ok) is False
        assert mod.prices_decision(gl.vm.Return(dict(mine, x=1)), ok) is False
        assert mod.prices_decision(gl.vm.Return({"ref_e8": 2, "end_e8": 3}), ok) is False
        assert mod.prices_decision(gl.vm.Return({k: v for k, v in mine.items() if k != "obs_hi_e8"}), ok) is False
        assert mod.prices_decision(gl.vm.UserError("[EXTERNAL] down"), ok) is False
        def boom(): raise RuntimeError("validator offline")
        assert mod.prices_decision(gl.vm.Return(mine), boom) is False


class TestMisc:
    def test_m01_paging_bounded(self, ledger, reg, direct_vm):
        sids = ["%064x" % i for i in range(1, 56)]
        for s in sids:
            reg(sid=s)
        assert len(ledger.get_ids_page(0, 1000)) == 50 and list(ledger.get_ids_page(50, 50)) == sids[50:]
        with direct_vm.expect_revert("invalid page"):
            ledger.get_ids_page(0, 0)

    def test_m02_policy_exposes_source_band_and_deviation(self, ledger):
        p = ledger.get_policy()
        assert (p["price_url_template"], p["flat_band_bps"], p["max_price_deviation_bps"]) == (TEMPLATE, 300, 300)


class TestInterfaceContract:
    """Direct mode cannot load two contracts in one process, so a true verdict->ledger delivery test is impossible
    here. This pins the SHARED ARGUMENT SHAPE: the literal below is asserted verbatim in test_l40 (what the verdict
    contract emits)."""
    EMITTED = ("b" * 64, SUB_A, "7", "bullish", 62, "moderate", 30, "2026-10-11T12:00:00Z", "2026-10-11T11:30:00Z", 299540000000)

    def test_l44_ledger_accepts_exactly_the_args_the_verdict_contract_emits(self, ledger, direct_vm, direct_bob):
        with direct_vm.prank(direct_bob):
            ledger.register(*self.EMITTED)
        e = json.loads(ledger.get_entry("b" * 64))
        assert (e["submitter"], e["bounty_ref"], e["stance"], e["conviction"], e["horizon_days"], e["analyzed_at"],
                e["observed_at"], e["asserted_price_e8"]) == (SUB_A, "7", "bullish", 62, 30, "2026-10-11T12:00:00Z",
                                                              "2026-10-11T11:30:00Z", 299540000000)


class TestVerdictLedgerLink:
    """Verdict contract -> ledger wiring. Emission observed via a recorder stub (direct mode limitation)."""

    @pytest.fixture
    def rec(self, monkeypatch):
        calls = []
        class _Msg:
            def __init__(s, addr, on): s.addr, s.on = addr, on
            def __getattr__(s, name):
                return lambda *a: calls.append({"to": s.addr, "on": s.on, "method": name, "args": a})
        class _C:
            def __init__(s, addr): s.addr = addr
            def emit(s, *, value=0, on="finalized"): return _Msg(s.addr, on)
        monkeypatch.setattr(sys.modules["genlayer.gl"], "get_contract_at", lambda addr: _C(addr))
        return calls

    def _ready(self, eth, snap, direct_vm):
        sid = eth.submit_snapshot(json.dumps(snap))
        direct_vm.mock_llm(ANY, llm_json("bullish", 62, "moderate"))
        return sid

    def test_l40_analyze_emits_finalized_registration_once_with_the_ledger_args(self, eth, rec, direct_vm, direct_owner, direct_bob):
        with direct_vm.prank(direct_owner):
            eth.set_ledger(direct_bob)
        sid = self._ready(eth, base_snapshot(), direct_vm)
        analyze_all(eth, sid)
        assert len(rec) == 1
        c = rec[0]
        assert c["on"] == "finalized" and c["method"] == "register"
        # (sid, submitter, stance, conviction, risk, horizon, analyzed_at, observed_at, asserted_price_e8) == ledger args shape (l44)
        assert c["args"] == (sid, eth.get_submitter(sid), "", "bullish", 62, "moderate", 30,
                             "2026-10-11T12:00:00Z", "2026-10-11T11:30:00Z", 299540000000)

    def test_l41_emission_uses_verdict_time_not_the_asserted_observation_time(self, eth, rec, direct_vm, direct_owner, direct_bob):
        with direct_vm.prank(direct_owner):
            eth.set_ledger(direct_bob)
        stale = base_snapshot("2026-10-10T13:00:00Z")               # claims observation 23h before the verdict
        sid = self._ready(eth, stale, direct_vm)
        analyze_all(eth, sid)
        args = rec[0]["args"]
        assert args[7] == "2026-10-11T12:00:00Z" and args[8] == "2026-10-10T13:00:00Z"

    def test_l42_no_emission_when_ledger_unset_or_analysis_fails(self, eth, rec, direct_vm, direct_owner, direct_bob):
        sid = self._ready(eth, base_snapshot(), direct_vm)
        analyze_all(eth, sid)
        assert rec == []
        s2 = base_snapshot(); s2["price"]["rsi_1d"] = 33.0
        sid2 = eth.submit_snapshot(json.dumps(s2))
        with direct_vm.prank(direct_owner):
            eth.set_ledger(direct_bob)
        direct_vm.clear_mocks(); direct_vm.mock_llm(ANY, "garbage")
        with direct_vm.expect_revert("LLM_ERROR"):
            analyze_all(eth, sid2)
        assert rec == []

    def test_l43_republish_guards_and_resend(self, eth, rec, direct_vm, direct_owner, direct_bob):
        sid = self._ready(eth, base_snapshot(), direct_vm)
        with direct_vm.expect_revert("ledger not set"):
            eth.republish(sid)
        with direct_vm.prank(direct_owner):
            eth.set_ledger(direct_bob)
        with direct_vm.expect_revert("snapshot not recorded"):
            eth.republish(sid)
        analyze_all(eth, sid); rec.clear()
        eth.republish(sid)
        assert len(rec) == 1 and rec[0]["args"][0] == sid

    def test_l45_only_the_submitter_can_trigger_the_analysis_so_the_emitted_submitter_is_the_analyst(
            self, eth, rec, direct_vm, direct_owner, direct_bob):
        with direct_vm.prank(direct_owner):
            eth.set_ledger(direct_bob)
        sid = self._ready(eth, base_snapshot(), direct_vm)
        with direct_vm.prank(direct_bob):                           # bob is not the submitter
            with direct_vm.expect_revert("only the submitter"):
                analyze_all(eth, sid)
        analyze_all(eth, sid)                                       # alice (the submitter) can
        submitted_by = eth.get_submitter(sid)
        assert rec[0]["args"][1] == submitted_by
        assert json.loads(eth.get_record(sid))["analyst"].lower() == submitted_by.lower()

    def test_l46_asserted_price_is_scaled_to_e8(self, eth, rec, direct_vm, direct_owner, direct_bob):
        with direct_vm.prank(direct_owner):
            eth.set_ledger(direct_bob)
        s = base_snapshot(); s["price"]["current"] = 1234.56789012
        sid = self._ready(eth, s, direct_vm)
        analyze_all(eth, sid)
        assert rec[0]["args"][9] == 123456789012


class TestAddressForms:
    """Studio (first real run) sent the constructor address as a plain integer and the contract crashed with
    "'int' object has no attribute 'as_bytes'". Direct mode had hidden it because the tests wrapped Address themselves."""

    def _deploy(self, direct_deploy, direct_bob, form):
        from gltest.direct.sdk_loader import setup_sdk_paths
        setup_sdk_paths(__import__("pathlib").Path(LEDGER), SDK_VERSION)
        from genlayer import Address
        addr = direct_bob if hasattr(direct_bob, "as_hex") else Address(direct_bob)
        value = {
            "int": int.from_bytes(addr.as_bytes, "big"),
            "hex_lower": "0x" + addr.as_bytes.hex(),
            "hex_checksum": addr.as_hex,
            "bytes": addr.as_bytes,
            "object": addr,
        }[form]
        return direct_deploy(LEDGER, value, TEMPLATE, 300, 300, sdk_version=SDK_VERSION), addr

    @pytest.mark.parametrize("form", ["int", "hex_lower", "hex_checksum", "bytes", "object"])
    def test_a01_every_address_form_ends_up_as_the_same_stored_address(self, direct_vm, direct_deploy, direct_bob, direct_alice, form):
        set_tx_time(direct_vm, TX_TIME)
        c, addr = self._deploy(direct_deploy, direct_bob, form)
        set_tx_time(direct_vm, TX_TIME)
        assert c.get_policy()["verdict_contract"].lower() == addr.as_hex.lower()
        direct_vm.sender = direct_alice
        with direct_vm.prank(direct_bob):                                   # the stored address really is bob's
            c.register(SID, SUB_A, "", "bullish", 70, "moderate", 30, ANALYZED, OBSERVED, P3000)
        assert c.get_status(SID) == "REGISTERED"
        with direct_vm.expect_revert("only the verdict contract"):
            c.register("b" * 64, SUB_A, "", "bullish", 70, "moderate", 30, ANALYZED, OBSERVED, P3000)

    @pytest.mark.parametrize("bad", [True, -1, 1 << 160, "0x123", "not-an-address", None, b"short"])
    def test_a02_invalid_address_forms_are_rejected_cleanly(self, direct_vm, direct_deploy, bad):
        from gltest.direct.sdk_loader import setup_sdk_paths
        setup_sdk_paths(__import__("pathlib").Path(LEDGER), SDK_VERSION)
        with pytest.raises(Exception, match="invalid address"):
            direct_deploy(LEDGER, bad, TEMPLATE, 300, 300, sdk_version=SDK_VERSION)



class _Bus:
    def __init__(self):
        self.calls = []


@pytest.fixture
def bus(monkeypatch):
    rec = _Bus()
    class _Msg:
        def __init__(s, addr, on): s.addr, s.on = addr, on
        def __getattr__(s, name):
            return lambda *a: rec.calls.append({"to": s.addr.as_hex.lower(), "on": s.on, "method": name, "args": a})
    class _C:
        def __init__(s, addr): s.addr = addr
        def emit(s, *, value=0, on="finalized"): return _Msg(s.addr, on)
    monkeypatch.setattr(sys.modules["genlayer.gl"], "get_contract_at", lambda addr: _C(addr))
    return rec


def NOW_S():
    import datetime as _d
    from tests.direct.conftest import TX_TIME as _T
    return int(_d.datetime.fromisoformat(_T.replace("Z", "+00:00")).timestamp())


S1, S2, S3 = "0x" + "c1" * 20, "0x" + "c2" * 20, "0x" + "c3" * 20


class TestBus:
    def test_b01_subscriber_management_is_owner_only(self, ledger, direct_vm, direct_owner):
        with direct_vm.expect_revert("owner only"):
            ledger.add_subscriber(S1)
        with direct_vm.prank(direct_owner):
            ledger.add_subscriber(S1)
        with direct_vm.expect_revert("owner only"):
            ledger.remove_subscriber(S1)
        assert list(ledger.get_subscribers()) == [S1] and ledger.get_policy()["subscribers"] == 1

    @pytest.mark.parametrize("form", ["int", "hex", "bytes"])
    def test_b02_address_forms_are_accepted_for_subscribers(self, ledger, direct_vm, direct_owner, form):
        raw = bytes.fromhex(S1[2:])
        value = {"int": int.from_bytes(raw, "big"), "hex": S1, "bytes": raw}[form]
        with direct_vm.prank(direct_owner):
            ledger.add_subscriber(value)
        assert [h.lower() for h in ledger.get_subscribers()] == [S1]

    def test_b03_duplicates_unknown_and_double_removal(self, ledger, direct_vm, direct_owner):
        with direct_vm.prank(direct_owner):
            ledger.add_subscriber(S1)
            with direct_vm.expect_revert("already subscribed"):
                ledger.add_subscriber(S1)
            with direct_vm.expect_revert("not subscribed"):
                ledger.remove_subscriber(S2)
            ledger.remove_subscriber(S1)
            with direct_vm.expect_revert("not subscribed"):
                ledger.remove_subscriber(S1)
            with direct_vm.expect_revert("invalid address"):
                ledger.add_subscriber("zzz")

    def test_b04_at_most_five_active_subscribers(self, ledger, direct_vm, direct_owner):
        subs = ["0x%02x" % (0x10 + i) + "00" * 19 for i in range(6)]
        with direct_vm.prank(direct_owner):
            for s in subs[:5]:
                ledger.add_subscriber(s)
            with direct_vm.expect_revert("subscriber limit reached"):
                ledger.add_subscriber(subs[5])
            ledger.remove_subscriber(subs[0])
            ledger.add_subscriber(subs[5])
        assert len(list(ledger.get_subscribers())) == 5

    def test_b05_lifetime_add_budget_bounds_the_broadcast_loop(self, ledger, direct_vm, direct_owner):
        with direct_vm.prank(direct_owner):
            for i in range(20):
                a = "0x%02x" % (0x20 + i) + "00" * 19
                ledger.add_subscriber(a); ledger.remove_subscriber(a)
            with direct_vm.expect_revert("budget exhausted"):
                ledger.add_subscriber("0x" + "ff" * 20)
            ledger.add_subscriber("0x%02x" % 0x20 + "00" * 19)

    def test_b06_log_records_every_change_in_order(self, ledger, direct_vm, direct_owner):
        with direct_vm.prank(direct_owner):
            ledger.add_subscriber(S1); ledger.add_subscriber(S2); ledger.remove_subscriber(S1); ledger.add_subscriber(S1)
        assert list(ledger.get_subscriber_log()) == ["add:" + S1, "add:" + S2, "remove:" + S1, "add:" + S1]

    def test_b10_register_broadcasts_on_verdict_to_active_subscribers_only(self, ledger, reg, bus, direct_vm, direct_owner):
        with direct_vm.prank(direct_owner):
            ledger.add_subscriber(S1); ledger.add_subscriber(S2); ledger.add_subscriber(S3); ledger.remove_subscriber(S2)
        reg(ref="7")
        assert sorted(c["to"] for c in bus.calls) == sorted([S1, S3])
        assert all(c["on"] == "finalized" and c["method"] == "on_verdict" for c in bus.calls)
        assert bus.calls[0]["args"] == (SID, SUB_A, "7", "bullish", 70, "moderate", 30, "2026-09-01T12:30:00Z", P3000)

    def test_b11_no_subscribers_means_no_messages(self, ledger, reg, bus):
        reg()
        assert bus.calls == [] and ledger.get_status(SID) == "REGISTERED"

    def test_b12_redelivered_registration_does_not_rebroadcast(self, ledger, reg, bus, direct_vm, direct_owner):
        with direct_vm.prank(direct_owner):
            ledger.add_subscriber(S1)
        reg(); reg()
        assert len(bus.calls) == 1

    def test_b13_resolve_broadcasts_on_resolution_with_exact_args(self, ledger, reg, bus, direct_vm, direct_owner):
        with direct_vm.prank(direct_owner):
            ledger.add_subscriber(S1)
        reg(ref="9", stance="bearish"); bus.calls.clear()
        mock_prices(direct_vm, obs="3000.00", ref="3000.00", end="2700.00")
        ledger.resolve(SID)
        assert bus.calls == [{"to": S1, "on": "finalized", "method": "on_resolution",
                              "args": (SID, SUB_A, "9", "bearish", "hit", True, -1000, P3000, 270_000_000_000)}]

    def test_b14_excluded_resolution_is_broadcast_as_excluded(self, ledger, reg, bus, direct_vm, direct_owner):
        with direct_vm.prank(direct_owner):
            ledger.add_subscriber(S1)
        reg(price=2_000_00000000); bus.calls.clear()
        mock_prices(direct_vm)
        ledger.resolve(SID)
        a = bus.calls[0]["args"]
        assert a[4] == "excluded" and a[5] is False

    def test_b15_failed_resolution_broadcasts_nothing(self, ledger, reg, bus, direct_vm, direct_owner):
        with direct_vm.prank(direct_owner):
            ledger.add_subscriber(S1)
        reg(); bus.calls.clear()
        mock_prices(direct_vm, status=500)
        with direct_vm.expect_revert("HTTP status 500"):
            ledger.resolve(SID)
        assert bus.calls == []

    def test_b16_rebroadcast_registered_then_resolved_and_cap(self, ledger, reg, bus, direct_vm, direct_owner):
        reg(ref="7")
        with direct_vm.prank(direct_owner):
            ledger.add_subscriber(S1)
        ledger.rebroadcast(SID)
        assert [c["method"] for c in bus.calls] == ["on_verdict"]
        mock_prices(direct_vm); ledger.resolve(SID); bus.calls.clear()
        ledger.rebroadcast(SID)
        assert [c["method"] for c in bus.calls] == ["on_verdict", "on_resolution"]
        ledger.rebroadcast(SID)
        with direct_vm.expect_revert("rebroadcast limit reached"):
            ledger.rebroadcast(SID)

    def test_b17_rebroadcast_unknown_snapshot(self, ledger, direct_vm):
        with direct_vm.expect_revert("unknown snapshot"):
            ledger.rebroadcast("f" * 64)

    def test_b18_late_subscriber_catches_up_through_rebroadcast(self, ledger, reg, bus, direct_vm, direct_owner):
        reg()
        with direct_vm.prank(direct_owner):
            ledger.add_subscriber(S1)
        assert bus.calls == []
        ledger.rebroadcast(SID)
        assert [c["to"] for c in bus.calls] == [S1]

    @pytest.mark.parametrize("good", ["", "7", "b_1.2:x-y", "a" * 40])
    def test_b20_valid_bounty_refs_are_stored(self, ledger, reg, good):
        reg(ref=good)
        assert json.loads(ledger.get_entry(SID))["bounty_ref"] == good

    @pytest.mark.parametrize("bad", ["A1", "has space", "a" * 41, 5, None, "-x", "x\ny"])
    def test_b21_invalid_bounty_refs_are_rejected(self, ledger, reg, direct_vm, bad):
        with direct_vm.expect_revert("invalid bounty_ref"):
            reg(ref=bad)
        assert ledger.get_scorecard()["registered"] == 0

    def test_b22_ref_travels_into_the_resolution_record(self, ledger, reg, direct_vm):
        reg(ref="42"); mock_prices(direct_vm); ledger.resolve(SID)
        assert res(ledger)["bounty_ref"] == "42"
