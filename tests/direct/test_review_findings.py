"""Regression tests for the adversarial-review findings F1-F8 (each was a real hole; each is now fixed).

Direct mode is not validator consensus and cannot deliver cross-contract messages (see conftest). The end-to-end
parts (real emit(on="finalized") delivery, value transfers, view clock) live in tests/integration/.
"""
import json

import pytest

from tests.direct.conftest import TX_TIME, analyze_all, base_snapshot, llm_json, set_tx_time  # noqa: F401
from tests.direct.test_bounty import ch, T_ANALYZED, SID, R  # noqa: F401
from tests.direct.test_ledger import (  # noqa: F401
    ledger, reg, bus, mock_prices, kline, OBS_MS, REF_MS, END_MS, P3000, S1, SID as LSID,
)

ANY = r"analyst adjudicating"


def _rec(eth, sid):
    return json.loads(eth.get_record(sid))


def _at(iso):
    s = base_snapshot(iso)
    s["sources"] = [dict(x, observed_at=iso) for x in s["sources"]]
    return s


def _distinct(i):
    s = base_snapshot()
    s["price"]["rsi_1d"] = 20.0 + i * 0.5
    return s


# ---------------------------------------------------------------------------------------------------------------
# F1  every accepted price must be acceptable to the ledger (0 < e8 <= 1e15)
# ---------------------------------------------------------------------------------------------------------------
class TestF1PriceParity:
    @pytest.mark.parametrize("price", [0.0, 1e-9, 4e-9, 0.009, -1.0])
    def test_f1_unusable_prices_are_rejected_at_submission(self, eth, submit, snap, price):
        snap["price"]["current"] = price
        with pytest.raises(Exception, match="out of range"):
            submit(snap)

    @pytest.mark.parametrize("price,e8", [(0.01, 1_000_000), (1.0, 100_000_000), (10_000_000.0, 10 ** 15)])
    def test_f1_accepted_extremes_scale_into_the_ledgers_window(self, eth, submit, snap, direct_vm, price, e8):
        snap["price"]["current"] = price
        sid = submit(snap)
        direct_vm.mock_llm(ANY, llm_json())
        analyze_all(eth, sid)
        got = _rec(eth, sid)["asserted_price_e8"]
        assert got == e8 and 0 < got <= 10 ** 15


# ---------------------------------------------------------------------------------------------------------------
# F2  open slots can always be freed
# ---------------------------------------------------------------------------------------------------------------
class TestF2Release:
    @pytest.fixture
    def one_slot(self, eth, direct_vm, direct_owner):
        with direct_vm.prank(direct_owner):
            eth.set_policy(300, 0, 1)
        return eth

    def test_f2_submitter_can_release_and_reuse_the_slot(self, one_slot, submit, direct_vm):
        eth = one_slot
        first = submit(_at("2026-10-11T11:58:00Z"))
        with direct_vm.expect_revert("too many open snapshots"):
            submit(_at("2026-10-11T11:59:00Z"))
        eth.release_snapshot(first)
        assert eth.get_status(first) == "RELEASED"
        assert len(submit(_at("2026-10-11T11:59:30Z"))) == 64
        with direct_vm.expect_revert("not in SUBMITTED state"):
            eth.analyze(first)                       # a released snapshot can never be recorded
        with direct_vm.expect_revert("not in SUBMITTED state"):
            eth.release_snapshot(first)              # and cannot be released twice (no double slot refund)

    def test_f2_stale_snapshot_can_be_released_by_anyone(self, one_slot, submit, direct_vm, direct_bob):
        eth = one_slot
        first = submit(_at("2026-10-11T11:58:00Z"))
        with direct_vm.prank(direct_bob):
            with direct_vm.expect_revert("only the submitter may release a fresh snapshot"):
                eth.release_snapshot(first)
        set_tx_time(direct_vm, "2026-10-11T14:00:00Z")
        with direct_vm.expect_revert("stale snapshot"):
            eth.analyze(first)
        with direct_vm.prank(direct_bob):
            eth.release_snapshot(first)              # now harmless: it can never be analyzed
        assert len(submit(_at("2026-10-11T13:55:00Z"))) == 64

    def test_f2_recorded_and_unknown_snapshots_cannot_be_released(self, eth, submit, snap, direct_vm):
        sid = submit(snap)
        direct_vm.mock_llm(ANY, llm_json())
        analyze_all(eth, sid)
        with direct_vm.expect_revert("not in SUBMITTED state"):
            eth.release_snapshot(sid)
        with direct_vm.expect_revert("unknown snapshot"):
            eth.release_snapshot("0" * 64)

    def test_f2_release_does_not_free_a_slot_it_never_held(self, one_slot, submit, direct_vm, direct_bob):
        """Releasing alice's snapshot must decrement ALICE's counter, never the caller's."""
        eth = one_slot
        mine = submit(_at("2026-10-11T11:58:00Z"))
        with direct_vm.prank(direct_bob):
            theirs = eth.submit_snapshot(json.dumps(_at("2026-10-11T11:59:00Z")))
        set_tx_time(direct_vm, "2026-10-11T14:00:00Z")
        with direct_vm.prank(direct_bob):
            eth.release_snapshot(mine)               # bob releases alice's stale snapshot
            with direct_vm.expect_revert("too many open snapshots"):
                eth.submit_snapshot(json.dumps(_at("2026-10-11T13:59:00Z")))   # bob's own slot is still taken
        assert eth.get_status(theirs) == "SUBMITTED"


# ---------------------------------------------------------------------------------------------------------------
# F3  only the submitter decides when their snapshot is analyzed
# ---------------------------------------------------------------------------------------------------------------
class TestF3SubmitterOnly:
    def test_f3_stranger_cannot_analyze_or_analyze_layer(self, eth, submit, snap, direct_vm, direct_bob):
        sid = submit(snap)
        direct_vm.mock_llm(ANY, llm_json())
        with direct_vm.prank(direct_bob):
            with direct_vm.expect_revert("only the submitter"):
                eth.analyze(sid)
            with direct_vm.expect_revert("only the submitter"):
                eth.analyze_layer(sid, "macro")
        assert eth.get_status(sid) == "SUBMITTED"
        analyze_all(eth, sid)
        r = _rec(eth, sid)
        assert r["analyst"].lower() == r["submitter"].lower()


# ---------------------------------------------------------------------------------------------------------------
# F4  the owner can neither block submitted work nor change its freshness rule retroactively
# ---------------------------------------------------------------------------------------------------------------
class TestF4OwnerLevers:
    def test_f4_pause_stops_intake_but_not_already_submitted_work(self, eth, submit, snap, direct_vm, direct_owner):
        sid = submit(snap)
        with direct_vm.prank(direct_owner):
            eth.set_policy(86400, 168, 20)
        with direct_vm.expect_revert("paused"):
            submit(_distinct(1))
        direct_vm.mock_llm(ANY, llm_json())
        analyze_all(eth, sid)                        # the owner cannot stop a verdict that is already underway
        assert eth.get_status(sid) == "RECORDED"

    def test_f4_tightening_max_age_is_not_retroactive(self, eth, submit, snap, direct_vm, direct_owner):
        sid = submit(snap)                           # observed 30 min before TX_TIME, default max age 1 day
        with direct_vm.prank(direct_owner):
            eth.set_policy(300, 0, 20)               # owner now wants 5-minute freshness for NEW snapshots
        direct_vm.mock_llm(ANY, llm_json())
        analyze_all(eth, sid)                        # ... but the existing snapshot keeps the rule it was submitted under
        assert eth.get_status(sid) == "RECORDED"
        with direct_vm.expect_revert("stale snapshot"):
            submit(base_snapshot())                  # new submissions use the new rule

    def test_f4_solvency_counts_forfeited_funds_as_owed(self, ch):
        bid = ch.create(); ch.commit(bid)
        ch.at("2026-10-14T14:10:01Z")
        ch.call(ch.client, ch.c.expire, bid)             # client may claim R; the forfeited R stays in the contract
        assert ch.c.get_solvency()["ok"] is True
        ch.vm.deal(ch.addr, R + 1)                       # 2R is owed (R claimable + R forfeited), only R+1 is held
        s = ch.c.get_solvency()
        assert s["ok"] is False and s["forfeited_total"] == R

    def test_f4_non_delivery_enriches_nobody(self, ch):
        bid = ch.create(); ch.commit(bid)
        ch.at("2026-10-14T14:10:01Z")
        ch.call(ch.client, ch.c.expire, bid)
        s = ch.c.get_solvency()
        assert (ch.claimable("client"), ch.claimable("analyst")) == (R, 0)
        assert s["forfeited_total"] == R and s["ok"]


# ---------------------------------------------------------------------------------------------------------------
# F5  removing a subscriber cannot strand outcomes it was already promised
# ---------------------------------------------------------------------------------------------------------------
class TestF5SubscriberPromise:
    def test_f5_removed_subscriber_still_gets_the_outcome_of_what_it_saw(self, ledger, reg, bus, direct_vm, direct_owner):
        with direct_vm.prank(direct_owner):
            ledger.add_subscriber(S1)
        reg(ref="7")
        with direct_vm.prank(direct_owner):
            ledger.remove_subscriber(S1)
        bus.calls.clear()
        mock_prices(direct_vm)
        ledger.resolve(LSID)
        assert [(c["to"], c["method"]) for c in bus.calls] == [(S1, "on_resolution")]

    def test_f5_removed_subscriber_gets_nothing_for_snapshots_registered_after_removal(
            self, ledger, reg, bus, direct_vm, direct_owner):
        with direct_vm.prank(direct_owner):
            ledger.add_subscriber(S1)
            ledger.remove_subscriber(S1)
        reg(ref="7")
        mock_prices(direct_vm)
        ledger.resolve(LSID)
        assert bus.calls == []

    def test_f5_no_duplicate_delivery_when_subscribed_at_registration_and_still_active(
            self, ledger, reg, bus, direct_vm, direct_owner):
        with direct_vm.prank(direct_owner):
            ledger.add_subscriber(S1)
        reg(ref="7")
        mock_prices(direct_vm)
        ledger.resolve(LSID)
        assert [c["method"] for c in bus.calls] == ["on_verdict", "on_resolution"]


# ---------------------------------------------------------------------------------------------------------------
# F6  an abstention settles immediately; delivery failures are explained
# ---------------------------------------------------------------------------------------------------------------
class TestF6Abstain:
    def test_f6_inconclusive_delivery_settles_at_once_and_unlocks_both_sides(self, ch):
        bid = ch.create(); ch.commit(bid); ch.at(T_ANALYZED)
        ch.verdict(ref=bid, stance="inconclusive", conviction=70)
        b = ch.bounty(bid)
        assert (b["status"], b["result"]) == ("SETTLED", "abstain")
        assert (ch.claimable("analyst"), ch.claimable("client")) == (R, R)
        assert ch.c.get_solvency()["locked_total"] == 0
        ch.resolution(ref=bid, stance="inconclusive", result="abstain")        # a late resolution changes nothing
        assert (ch.claimable("analyst"), ch.claimable("client")) == (R, R)

    def test_f6_neutral_can_never_win(self, ch):
        bid = ch.to_delivered()
        ch.resolution(ref=bid, stance="neutral", result="hit")
        assert (ch.claimable("analyst"), ch.claimable("client")) == (R, R)

    @pytest.mark.parametrize("kw,reason", [
        (dict(horizon=8), "horizon_mismatch"),
        (dict(conviction=49), "conviction_below_min"),
        (dict(analyzed="2026-10-11T12:09:59Z"), "outside_delivery_window"),
        (dict(analyzed="2026-10-11T14:10:01Z"), "outside_delivery_window"),
    ])
    def test_f6_ignored_verdicts_leave_a_reason(self, ch, kw, reason):
        bid = ch.create(); ch.commit(bid); ch.at(T_ANALYZED)
        kw.setdefault("ref", bid)
        ch.verdict(**kw)
        assert ch.bounty(bid)["status"] == "COMMITTED" and ch.c.get_ignored(SID) == reason

    def test_f6_second_verdict_after_delivery_is_explained_and_changes_nothing(self, ch):
        bid = ch.create(); ch.commit(bid); ch.at(T_ANALYZED)
        ch.verdict(ref=bid)
        ch.verdict(sid="c" * 64, ref=bid)
        assert ch.bounty(bid)["sid"] == SID and ch.c.get_ignored("c" * 64) == "bounty_not_committed"

    def test_f6_strangers_cannot_write_ignore_records(self, ch):
        bid = ch.create(); ch.commit(bid); ch.at(T_ANALYZED)
        ch.verdict(ref=bid, submitter="0x" + "9" * 40, conviction=1)
        ch.verdict(sid="d" * 64, ref="999", conviction=1)
        assert ch.c.get_ignored(SID) == "" and ch.c.get_ignored("d" * 64) == ""


# ---------------------------------------------------------------------------------------------------------------
# F7  evidence is checked against the whole observed hour (low..high), not only its open
# ---------------------------------------------------------------------------------------------------------------
class TestF7CandleRange:
    def _resolve(self, ledger, reg, direct_vm, asserted_e8, *, open_="3000.00", high="3200.00", low="2980.00"):
        reg(price=asserted_e8)
        mock_prices(direct_vm, bodies={"obs": kline(OBS_MS, open_, high=high, low=low)}, ref="3000.00", end="3300.00")
        set_tx_time(direct_vm, "2026-10-02T14:00:00Z")
        ledger.resolve(LSID)
        return json.loads(ledger.get_resolution(LSID))

    def test_f7_honest_intrahour_price_inside_the_range_is_kept(self, ledger, reg, direct_vm):
        r = self._resolve(ledger, reg, direct_vm, 315_000_000_000)             # 3150 vs open 3000 (+5%) but inside [2980, 3200]
        assert r["evidence_ok"] is True and r["deviation_bps"] == 0 and r["result"] == "hit"
        assert (r["obs_open_e8"], r["obs_high_e8"], r["obs_low_e8"]) == (300_000_000_000, 320_000_000_000, 298_000_000_000)

    @pytest.mark.parametrize("asserted,dev", [(310_000_000_000, 0), (329_000_000_000, 281), (270_000_000_000, 939)])
    def test_f7_deviation_is_distance_to_the_nearest_bound(self, ledger, reg, direct_vm, asserted, dev):
        r = self._resolve(ledger, reg, direct_vm, asserted)
        assert r["deviation_bps"] == dev and r["evidence_ok"] is (dev <= 300)
        assert r["result"] == ("hit" if dev <= 300 else "excluded")

    def test_f7_inconsistent_or_malformed_candles_prevent_resolution(self, ledger, reg, direct_vm):
        reg()
        mock_prices(direct_vm, bodies={"obs": kline(OBS_MS, "3000.00", high="2999.00", low="2900.00")})
        with direct_vm.expect_revert("inconsistent candle"):
            ledger.resolve(LSID)
        direct_vm.clear_mocks()
        mock_prices(direct_vm, bodies={"obs": json.dumps([[OBS_MS, "3000.00"]])})
        with direct_vm.expect_revert("unexpected kline shape"):
            ledger.resolve(LSID)
        assert ledger.get_status(LSID) == "REGISTERED"


# ---------------------------------------------------------------------------------------------------------------
# F8  the due-list view does not depend on a transaction clock
# ---------------------------------------------------------------------------------------------------------------
class TestF8ViewClock:
    def test_f8_due_page_uses_the_callers_now(self, ledger, reg):
        reg()                                                                   # 30-day horizon from 2026-09-01
        assert ledger.get_unresolved_due_page(0, 10, 1_788_000_000) == []       # 2026-08-29: not due
        assert list(ledger.get_unresolved_due_page(0, 10, 1_793_000_000)) == [LSID]   # 2026-10-26: due

    @pytest.mark.parametrize("bad", [-1, True])
    def test_f8_invalid_now_is_rejected(self, ledger, direct_vm, bad):
        with direct_vm.expect_revert("invalid now_s"):
            ledger.get_unresolved_due_page(0, 10, bad)


# ---------------------------------------------------------------------------------------------------------------
# Gaps found while re-running the mutation suite (the verdict contract had NO test for these two rules)
# ---------------------------------------------------------------------------------------------------------------
class TestCoverageGaps:
    def test_g1_unknown_source_kind_is_rejected(self, eth, submit, snap):
        snap["sources"][0]["kind"] = "observed"                 # a self-asserted 'verified-sounding' label
        with pytest.raises(Exception, match="source kind must be one of"):
            submit(snap)

    def test_g2_verdict_paging_is_bounded(self, eth, submit, direct_vm, direct_owner):
        with direct_vm.prank(direct_owner):
            eth.set_policy(86400, 0, 1000)
        for i in range(55):
            submit(_distinct(i))
        assert eth.get_id_count() == 55
        assert len(eth.get_ids_page(0, 1000)) == 50             # capped at MAX_PAGE
        assert len(eth.get_ids_page(50, 50)) == 5
        assert list(eth.get_ids_page(55, 10)) == []

    @pytest.mark.parametrize("which,start", [("ref", REF_MS), ("end", END_MS)])
    def test_g3_wrong_hour_for_the_start_or_end_candle_prevents_resolution(self, ledger, reg, direct_vm, which, start):
        """The hour check must hold for every candle, not only the observation candle (found by mutant L08)."""
        reg()
        wrong = json.dumps([[start + 3600000, "3000.00", "3000.00", "3000.00", "3000.00", "1", 0]])
        mock_prices(direct_vm, bodies={which: wrong})
        with direct_vm.expect_revert("not the requested hour"):
            ledger.resolve(LSID)
        assert ledger.get_status(LSID) == "REGISTERED"


class TestUnaccountedFunds:
    def test_u1_funds_nobody_owns_are_reported_and_do_not_break_solvency(self, ch):
        bid = ch.create()
        s = ch.c.get_solvency()
        assert s["unaccounted"] == 0
        ch.vm.deal(ch.addr, ch.balance + 5)
        s = ch.c.get_solvency()
        assert s["unaccounted"] == 5 and s["ok"] is True
        ch.vm.deal(ch.addr, ch.balance - 1)
        assert ch.c.get_solvency()["ok"] is False and ch.c.get_solvency()["unaccounted"] == 0


class TestContractHygiene:
    """The README promises contracts with no comments and no docstrings (the rationale lives in docs/)."""
    FILES = ["contracts/eth_intelligence.py", "contracts/eth_outcome_ledger.py", "contracts/eth_analyst_bounty.py"]

    @pytest.mark.parametrize("path", FILES)
    def test_h1_no_comments_except_the_depends_header(self, path):
        import io
        import tokenize
        src = open(path, encoding="utf-8").read()
        comments = [(tok.start[0], tok.string) for tok in tokenize.generate_tokens(io.StringIO(src).readline)
                    if tok.type == tokenize.COMMENT]
        assert [line for line, _ in comments] == [1], comments
        assert '"Depends"' in comments[0][1]

    @pytest.mark.parametrize("path", FILES)
    def test_h2_no_docstrings_and_no_stray_string_statements(self, path):
        import ast
        tree = ast.parse(open(path, encoding="utf-8").read())
        strays = [n.lineno for n in ast.walk(tree)
                  if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)]
        assert strays == []

    @pytest.mark.parametrize("path", FILES)
    def test_h3_ascii_only(self, path):
        src = open(path, encoding="utf-8").read()
        assert [c for c in src if ord(c) > 127] == []
