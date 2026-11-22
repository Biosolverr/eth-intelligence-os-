"""P2 hardening of the verdict contract: caution-based conviction cap, spam limits, ownership, pause expiry,
ledger re-pointing. DIRECT mode, mocked LLM."""
import datetime
import json
import sys

import pytest

from tests.direct.conftest import (
    TX_TIME, analyze_all, as_addr, base_snapshot, layer_pat, llm_json, set_llm_mock, set_tx_time,
)

ANY = r"analyst adjudicating"
TX_EPOCH = int(datetime.datetime.fromisoformat(TX_TIME.replace("Z", "+00:00")).timestamp())


def rec(eth, sid):
    return json.loads(eth.get_record(sid))


def distinct(i):
    s = base_snapshot(); s["price"]["rsi_1d"] = 20.0 + i * 0.5
    return s


class TestCautionCap:
    def test_c01_manipulation_caution_bounds_conviction(self, eth, submit, snap, direct_vm):
        """P2 regression: caution layers used to have NO deterministic effect (caution 100 -> conviction 95 allowed)."""
        sid = submit(snap)
        set_llm_mock(direct_vm, layer_pat("manipulation"), json.dumps(
            {"caution": 100, "inconclusive": False, "drivers": [], "note": "very suspicious"}))
        direct_vm.mock_llm(ANY, llm_json("bullish", 95, "low"))
        analyze_all(eth, sid)
        r = rec(eth, sid)["result"]
        assert (r["conviction_cap_layers"], r["conviction_cap_structure"], r["conviction_cap"], r["conviction"]) == (50, 100, 50, 50)
        assert r["stance"] == "bullish"                                 # direction is never changed by a cap

    def test_c02_arithmetic_risk_layer_bounds_conviction_too(self, eth, submit, direct_vm):
        s = base_snapshot(); s["risk"]["threats_score"] = 90.0
        sid = submit(s)
        direct_vm.mock_llm(ANY, llm_json("bullish", 95))
        analyze_all(eth, sid)
        r = rec(eth, sid)
        assert r["layers"]["risk"]["caution"] == 90
        assert r["result"]["conviction_cap_layers"] == 55 and r["result"]["conviction"] == 55

    def test_c03_inconclusive_caution_layer_is_ignored_missing_data_is_not_double_penalised(self, eth, submit, snap, direct_vm):
        sid = submit(snap)
        set_llm_mock(direct_vm, layer_pat("manipulation"), json.dumps(
            {"caution": 100, "inconclusive": True, "drivers": [], "note": "cannot tell"}))
        direct_vm.mock_llm(ANY, llm_json("bullish", 95))
        analyze_all(eth, sid)
        r = rec(eth, sid)["result"]
        assert r["conviction_cap_layers"] == 85                          # only risk (30) counts: 100 - 30//2
        assert r["conviction"] == 85

    def test_c04_the_tighter_of_structure_and_layers_wins(self, eth, submit, direct_vm):
        s = base_snapshot()
        for g in ("derivs", "macro"):
            s.pop(g)
        s["sources"] = [x for x in s["sources"] if x["group"] in ("price", "flows", "risk")]
        sid = submit(s)
        direct_vm.mock_llm(ANY, llm_json("bullish", 99))
        analyze_all(eth, sid)
        r = rec(eth, sid)["result"]
        assert (r["conviction_cap_structure"], r["conviction_cap_layers"], r["conviction_cap"]) == (80, 85, 80)

    def test_c05_low_caution_does_not_reduce_below_structure(self, eth, submit, snap, direct_vm):
        sid = submit(snap)
        set_llm_mock(direct_vm, layer_pat("manipulation"), json.dumps(
            {"caution": 0, "inconclusive": False, "drivers": [], "note": "clean"}))
        direct_vm.mock_llm(ANY, llm_json("bullish", 99))
        analyze_all(eth, sid)
        assert rec(eth, sid)["result"]["conviction_cap_layers"] == 85    # risk layer (30) still binds


class TestSpamLimits:
    def test_s01_per_sender_open_cap(self, eth, submit, direct_vm, direct_owner, direct_bob):
        with direct_vm.prank(direct_owner):
            eth.set_policy(86400, 0, 2)
        a, b = submit(distinct(1)), submit(distinct(2))
        with direct_vm.expect_revert("too many open snapshots"):
            submit(distinct(3))
        with direct_vm.prank(direct_bob):                              # another sender has its own budget
            eth.submit_snapshot(json.dumps(distinct(4)))
        direct_vm.mock_llm(ANY, llm_json())
        analyze_all(eth, a)                                            # recording frees one slot
        submit(distinct(3))
        with direct_vm.expect_revert("too many open snapshots"):
            submit(distinct(5))

    def test_s02_open_cap_bounds_and_default(self, eth, direct_vm, direct_owner):
        assert eth.get_policy()["max_open_per_sender"] == 20
        with direct_vm.prank(direct_owner):
            for bad in (0, 1001):
                with direct_vm.expect_revert("max_open_per_sender out of bounds"):
                    eth.set_policy(86400, 0, bad)

    def test_s03_default_cap_actually_stops_the_21st(self, eth, submit, direct_vm):
        for i in range(20):
            submit(distinct(i))
        with direct_vm.expect_revert("too many open snapshots"):
            submit(distinct(99))

    def test_s04_failed_submission_does_not_consume_a_slot(self, eth, submit, snap, direct_vm, direct_owner):
        with direct_vm.prank(direct_owner):
            eth.set_policy(86400, 0, 1)
        bad = dict(snap); bad = base_snapshot(); bad["price"]["rsi_1d"] = 999
        with direct_vm.expect_revert("out of range"):
            submit(bad)
        submit(snap)                                                    # slot still free

    def test_s05_republish_is_capped_per_snapshot(self, eth, submit, snap, direct_vm, direct_owner, direct_bob, monkeypatch):
        calls = []
        class _M:
            def __getattr__(s, n): return lambda *a: calls.append(n)
        class _C:
            def __init__(s, a): pass
            def emit(s, *, value=0, on="finalized"): return _M()
        monkeypatch.setattr(sys.modules["genlayer.gl"], "get_contract_at", lambda a: _C(a))
        with direct_vm.prank(direct_owner):
            eth.set_ledger(direct_bob)
        sid = submit(snap)
        direct_vm.mock_llm(ANY, llm_json()); analyze_all(eth, sid)
        for _ in range(3):
            eth.republish(sid)
        with direct_vm.expect_revert("republish limit reached"):
            eth.republish(sid)
        assert len(calls) == 1 + 3                                      # the original emission + 3 republishes


class TestOwnership:
    def test_o01_two_step_transfer(self, eth, direct_vm, direct_owner, direct_bob, direct_alice):
        with direct_vm.expect_revert("owner only"):
            eth.propose_owner(direct_alice)                              # alice is not the owner
        with direct_vm.expect_revert("not the pending owner"):
            eth.accept_ownership()                                       # nothing pending
        with direct_vm.prank(direct_owner):
            eth.propose_owner(direct_bob)
        pending = eth.get_policy()["pending_owner"]
        assert pending.startswith("0x")
        with direct_vm.expect_revert("not the pending owner"):
            eth.accept_ownership()                                       # alice is not the proposed one
        with direct_vm.prank(direct_bob):
            eth.accept_ownership()
            eth.set_policy(7200, 0, 20)                                  # the new owner has the power
        assert eth.get_policy()["owner"] == pending and eth.get_policy()["pending_owner"] == ""
        with direct_vm.prank(direct_owner):
            with direct_vm.expect_revert("owner only"):
                eth.set_policy(3600, 0, 20)                              # the old owner does not

    def test_o02_accepting_twice_is_impossible(self, eth, direct_vm, direct_owner, direct_bob):
        with direct_vm.prank(direct_owner):
            eth.propose_owner(direct_bob)
        with direct_vm.prank(direct_bob):
            eth.accept_ownership()
            with direct_vm.expect_revert("not the pending owner"):
                eth.accept_ownership()


class TestPauseExpiry:
    def test_p01_pause_blocks_then_expires_by_itself(self, eth, submit, snap, direct_vm, direct_owner):
        """P2 regression: pause used to be a boolean; a lost owner key while paused froze the contract forever."""
        with direct_vm.prank(direct_owner):
            eth.set_policy(86400, 2, 20)
        assert eth.get_policy()["paused_until_s"] == TX_EPOCH + 7200
        with direct_vm.expect_revert("paused"):
            submit(snap)
        set_tx_time(direct_vm, "2026-10-11T14:30:00Z")                   # 2.5 h later: lifted, no owner action needed
        s = base_snapshot("2026-10-11T14:00:00Z")
        assert len(submit(s)) == 64

    def test_p02_owner_can_lift_early_and_pause_is_bounded(self, eth, submit, snap, direct_vm, direct_owner):
        with direct_vm.prank(direct_owner):
            eth.set_policy(86400, 5, 20)
            eth.set_policy(86400, 0, 20)                                 # lift now
            with direct_vm.expect_revert("pause_hours out of bounds"):
                eth.set_policy(86400, 169, 20)
            with direct_vm.expect_revert("pause_hours out of bounds"):
                eth.set_policy(86400, -1, 20)
        assert eth.get_policy()["paused_until_s"] == 0 and len(submit(snap)) == 64


class TestLedgerRepointing:
    def test_r01_repointable_with_public_history_and_a_hard_cap(self, eth, direct_vm, direct_owner, direct_bob, direct_alice):
        assert list(eth.get_ledger_history()) == []
        with direct_vm.prank(direct_owner):
            for i in range(5):
                eth.set_ledger(as_addr(direct_bob) if i % 2 == 0 else as_addr(direct_alice))
            with direct_vm.expect_revert("ledger change limit reached"):
                eth.set_ledger(direct_bob)
        hist = list(eth.get_ledger_history())
        assert len(hist) == 5 and hist[0] != hist[1] and hist[0] == hist[2]
        with direct_vm.expect_revert("owner only"):
            eth.set_ledger(direct_bob)


class TestAddressForms:
    @pytest.mark.parametrize("form", ["int", "hex_lower", "bytes"])
    def test_a01_set_ledger_and_propose_owner_accept_what_studio_sends(self, eth, direct_vm, direct_owner, direct_bob, form):
        addr = as_addr(direct_bob)
        value = {"int": int.from_bytes(addr.as_bytes, "big"), "hex_lower": "0x" + addr.as_bytes.hex(), "bytes": addr.as_bytes}[form]
        with direct_vm.prank(direct_owner):
            eth.set_ledger(value)
            eth.propose_owner(value)
        assert [h.lower() for h in eth.get_ledger_history()] == [addr.as_hex.lower()]
        assert eth.get_policy()["pending_owner"].lower() == addr.as_hex.lower()
        with direct_vm.prank(direct_bob):
            eth.accept_ownership()                                          # the pending owner really is bob
        assert eth.get_policy()["owner"].lower() == addr.as_hex.lower()

    @pytest.mark.parametrize("bad", [True, -1, 1 << 160, "0x123", "zzz", None])
    def test_a02_invalid_forms_revert_with_a_clear_error(self, eth, direct_vm, direct_owner, bad):
        with direct_vm.prank(direct_owner):
            with direct_vm.expect_revert("invalid address"):
                eth.set_ledger(bad)
            with direct_vm.expect_revert("invalid address"):
                eth.propose_owner(bad)
        assert list(eth.get_ledger_history()) == [] and eth.get_policy()["pending_owner"] == ""

    def test_a03_non_owner_is_refused_before_the_address_is_even_parsed(self, eth, direct_vm):
        with direct_vm.expect_revert("owner only"):
            eth.set_ledger("garbage")
