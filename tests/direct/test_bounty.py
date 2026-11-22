import json
import pathlib
import sys

import pytest

from tests.direct.conftest import SDK_VERSION, as_addr, set_tx_time

BOUNTY = "contracts/eth_analyst_bounty.py"
T0 = "2026-10-11T12:00:00Z"
T_COMMIT = "2026-10-11T12:10:00Z"
T_ANALYZED = "2026-10-11T13:00:00Z"
SID = "a" * 64
SID2 = "b" * 64
R = 1000


class Chain:
    def __init__(self, vm, c, mod, ledger, client, analyst):
        self.vm, self.c = vm, c
        self.addr = vm._contract_address
        self.ledger, self.client, self.analyst = ledger, client, analyst
        self.hex = {k: as_addr(v).as_hex.lower() for k, v in (("ledger", ledger), ("client", client), ("analyst", analyst))}
        self.balance = 0
        self.transfers = []
        chain = self

        class _Recipient:
            def __init__(self, addr):
                self.addr = addr

            def emit_transfer(self, *, value, on="finalized"):
                amount = int(value)
                chain.transfers.append((self.addr.as_hex.lower(), amount))
                chain.balance -= amount
                vm.deal(chain.addr, chain.balance)

        mod._Recipient = _Recipient

    def at(self, iso):
        set_tx_time(self.vm, iso)

    def call(self, who, fn, *args, value=0):
        snap, before = self.vm.snapshot(), self.balance
        self.vm.value = value
        self.balance += value
        self.vm.deal(self.addr, self.balance)
        try:
            with self.vm.prank(who):
                return fn(*args)
        except BaseException:
            self.vm.revert(snap)
            self.balance = before
            self.vm.deal(self.addr, before)
            raise
        finally:
            self.vm.value = 0

    def create(self, reward=R, horizon=7, commit_window=86400, delivery_window=7200, min_conviction=50, who=None):
        self.call(who or self.client, self.c.create_bounty, horizon, commit_window, delivery_window, min_conviction, value=reward)
        return str(self.c.get_bounty_count() - 1)

    def commit(self, bid="0", at=T_COMMIT, value=None, who=None):
        self.at(at)
        reward = json.loads(self.c.get_bounty(bid))["reward"]
        self.call(who or self.analyst, self.c.commit, bid, value=reward if value is None else value)

    def verdict(self, sid=SID, ref="0", stance="bullish", conviction=70, horizon=7, analyzed=T_ANALYZED, submitter=None, who=None):
        self.call(who or self.ledger, self.c.on_verdict, sid, submitter or self.hex["analyst"], ref, stance, conviction,
                  "moderate", horizon, analyzed, 300_000_000_000)

    def resolution(self, sid=SID, ref="0", stance="bullish", result="hit", ok=True, submitter=None, who=None):
        self.call(who or self.ledger, self.c.on_resolution, sid, submitter or self.hex["analyst"], ref, stance, result,
                  ok, 1000, 300_000_000_000, 330_000_000_000)

    def bounty(self, bid="0"):
        return json.loads(self.c.get_bounty(bid))

    def claimable(self, who):
        return self.c.get_claimable(self.hex[who])

    def rejected(self, who, reason, value):
        assert self.c.get_rejection(self.hex[who]) == reason
        assert self.claimable(who) >= value
        s = self.c.get_solvency()
        assert s["ok"] and s["unaccounted"] == 0 and s["balance"] == self.balance

    def solvent(self):
        s = self.c.get_solvency()
        assert s["ok"] and s["balance"] == self.balance
        return s

    def to_delivered(self, reward=R, **kw):
        bid = self.create(reward=reward, **kw)
        self.commit(bid)
        self.at(T_ANALYZED)
        self.verdict(ref=bid)
        return bid


@pytest.fixture
def ch(direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie):
    set_tx_time(direct_vm, T0)
    from gltest.direct.sdk_loader import setup_sdk_paths
    setup_sdk_paths(pathlib.Path(BOUNTY), SDK_VERSION)
    ledger_hex = as_addr(direct_bob).as_hex
    c = direct_deploy(BOUNTY, ledger_hex, sdk_version=SDK_VERSION)
    set_tx_time(direct_vm, T0)
    mod = next(m for m in sys.modules.values() if hasattr(m, "AnalystBounty") and hasattr(m, "_Recipient"))
    return Chain(direct_vm, c, mod, direct_bob, direct_alice, direct_charlie)


class TestCreateAndCancel:
    def test_c01_create_locks_the_reward(self, ch):
        bid = ch.create()
        b = ch.bounty(bid)
        assert (bid, b["status"], b["reward"], b["client"]) == ("0", "OPEN", R, ch.hex["client"])
        assert b["commit_deadline_s"] - b["created_at_s"] == 86400
        s = ch.solvent()
        assert (s["locked_total"], s["claimable_total"], s["balance"]) == (R, 0, R)

    @pytest.mark.parametrize("kw,reason", [
        (dict(reward=0), "reward_too_small"),
        (dict(horizon=6), "horizon_days_out_of_bounds"), (dict(horizon=91), "horizon_days_out_of_bounds"),
        (dict(commit_window=3599), "commit_window_s_out_of_bounds"), (dict(commit_window=30 * 86400 + 1), "commit_window_s_out_of_bounds"),
        (dict(delivery_window=3599), "delivery_window_s_out_of_bounds"), (dict(delivery_window=172801), "delivery_window_s_out_of_bounds"),
        (dict(min_conviction=-1), "min_conviction_out_of_bounds"), (dict(min_conviction=101), "min_conviction_out_of_bounds"),
        (dict(horizon=True), "horizon_days_out_of_bounds"),
    ])
    def test_c02_invalid_parameters_create_nothing_and_refund_the_value(self, ch, kw, reason):
        reward = kw.get("reward", R)
        ch.call(ch.client, ch.c.create_bounty, kw.get("horizon", 7), kw.get("commit_window", 86400),
                kw.get("delivery_window", 7200), kw.get("min_conviction", 50), value=reward)
        assert ch.c.get_bounty_count() == 0 and ch.solvent()["locked_total"] == 0
        ch.rejected("client", reason, reward)
        assert ch.claimable("client") == reward

    def test_c03_boundary_values_are_accepted(self, ch):
        ch.create(horizon=7, commit_window=3600, delivery_window=3600, min_conviction=0)
        ch.create(horizon=90, commit_window=30 * 86400, delivery_window=172800, min_conviction=100)
        assert ch.c.get_bounty_count() == 2

    def test_c04_only_the_client_can_cancel_and_only_while_open(self, ch, direct_vm):
        bid = ch.create()
        with direct_vm.expect_revert("only the client"):
            ch.call(ch.analyst, ch.c.cancel_bounty, bid)
        ch.call(ch.client, ch.c.cancel_bounty, bid)
        assert ch.bounty(bid)["status"] == "CANCELLED" and ch.claimable("client") == R
        with direct_vm.expect_revert("not open"):
            ch.call(ch.client, ch.c.cancel_bounty, bid)
        s = ch.solvent()
        assert (s["locked_total"], s["claimable_total"]) == (0, R)

    def test_c05_cannot_cancel_after_a_commitment(self, ch, direct_vm):
        bid = ch.create(); ch.commit(bid)
        with direct_vm.expect_revert("not open"):
            ch.call(ch.client, ch.c.cancel_bounty, bid)

    def test_c06_unknown_bounty(self, ch, direct_vm):
        with direct_vm.expect_revert("unknown bounty"):
            ch.call(ch.client, ch.c.cancel_bounty, "99")
        assert ch.c.get_bounty("99") == ""


class TestCommit:
    def test_m01_commit_locks_an_equal_bond_and_sets_deadlines(self, ch):
        bid = ch.create(); ch.commit(bid)
        b = ch.bounty(bid)
        assert (b["status"], b["analyst"], b["bond"]) == ("COMMITTED", ch.hex["analyst"], R)
        assert b["deliver_deadline_s"] - b["committed_at_s"] == 7200
        s = ch.solvent()
        assert (s["locked_total"], s["balance"]) == (2 * R, 2 * R)

    @pytest.mark.parametrize("value", [0, R - 1, R + 1, 2 * R])
    def test_m02_bond_must_equal_the_reward_exactly_and_a_wrong_bond_is_refunded(self, ch, value):
        bid = ch.create()
        ch.commit(bid, value=value)
        assert ch.bounty(bid)["status"] == "OPEN" and ch.solvent()["locked_total"] == R
        ch.rejected("analyst", "bond_must_equal_reward", value)
        assert ch.claimable("analyst") == value

    def test_m03_client_cannot_commit_to_its_own_bounty_and_gets_the_bond_back(self, ch):
        bid = ch.create()
        ch.commit(bid, who=ch.client)
        assert ch.bounty(bid)["status"] == "OPEN"
        ch.rejected("client", "client_cannot_commit", R)
        assert ch.claimable("client") == R

    def test_m04_commit_window_is_enforced_and_a_late_bond_is_refunded(self, ch):
        bid = ch.create(commit_window=3600)
        ch.commit(bid, at="2026-10-11T13:00:01Z")
        assert ch.bounty(bid)["status"] == "OPEN"
        ch.rejected("analyst", "commit_window_closed", R)
        ch.commit(bid, at="2026-10-11T13:00:00Z")
        assert ch.bounty(bid)["status"] == "COMMITTED" and ch.c.get_rejection(ch.hex["analyst"]) == ""

    def test_m05_second_commit_is_refused_and_refunded(self, ch):
        bid = ch.create(); ch.commit(bid)
        ch.commit(bid, who=ch.ledger)
        assert ch.bounty(bid)["analyst"] == ch.hex["analyst"]
        ch.rejected("ledger", "bounty_not_open", R)
        assert ch.claimable("ledger") == R

    def test_m06_commit_unknown_bounty_refunds_the_value(self, ch):
        ch.call(ch.analyst, ch.c.commit, "5", value=R)
        ch.rejected("analyst", "unknown_bounty", R)
        assert ch.claimable("analyst") == R and ch.c.get_bounty_count() == 0

    def test_m07_a_refund_can_be_withdrawn(self, ch):
        ch.call(ch.analyst, ch.c.commit, "5", value=R)
        ch.call(ch.analyst, ch.c.withdraw)
        assert ch.transfers == [(ch.hex["analyst"], R)] and ch.claimable("analyst") == 0
        s = ch.solvent()
        assert (s["balance"], s["claimable_total"], s["unaccounted"]) == (0, 0, 0)

    def test_m08_a_successful_call_clears_the_previous_rejection_reason(self, ch):
        ch.call(ch.client, ch.c.create_bounty, 6, 86400, 7200, 50, value=R)
        assert ch.c.get_rejection(ch.hex["client"]) == "horizon_days_out_of_bounds"
        ch.create()
        assert ch.c.get_rejection(ch.hex["client"]) == ""


class TestDelivery:
    def test_d01_only_the_ledger_can_deliver(self, ch, direct_vm):
        bid = ch.create(); ch.commit(bid)
        with direct_vm.expect_revert("only the ledger"):
            ch.verdict(ref=bid, who=ch.analyst)
        with direct_vm.expect_revert("only the ledger"):
            ch.resolution(ref=bid, who=ch.client)

    def test_d02_matching_verdict_marks_delivered(self, ch):
        bid = ch.create(); ch.commit(bid); ch.at(T_ANALYZED); ch.verdict(ref=bid)
        b = ch.bounty(bid)
        assert (b["status"], b["sid"], b["stance"]) == ("DELIVERED", SID, "bullish")
        assert b["resolve_deadline_s"] > b["committed_at_s"] + 7 * 86400

    @pytest.mark.parametrize("kw", [
        dict(ref="42"), dict(submitter="0x" + "9" * 40), dict(horizon=8), dict(stance="moon"), dict(conviction=49),
        dict(analyzed="2026-10-11T12:09:59Z"), dict(analyzed="2026-10-11T14:10:01Z"),
    ])
    def test_d03_non_matching_verdicts_are_ignored_not_errors(self, ch, kw):
        bid = ch.create(); ch.commit(bid); ch.at(T_ANALYZED)
        kw.setdefault("ref", bid)
        ch.verdict(**kw)
        assert ch.bounty(bid)["status"] == "COMMITTED" and ch.c.get_pending_resolution(SID) == ""

    def test_d04_window_edges_are_inclusive(self, ch):
        bid = ch.create(); ch.commit(bid); ch.at(T_ANALYZED)
        ch.verdict(sid=SID, ref=bid, analyzed="2026-10-11T12:10:00Z")
        assert ch.bounty(bid)["status"] == "DELIVERED"
        bid2 = ch.create(); ch.commit(bid2, at="2026-10-11T12:20:00Z")
        ch.verdict(sid=SID2, ref=bid2, analyzed="2026-10-11T14:20:00Z")
        assert ch.bounty(bid2)["status"] == "DELIVERED"

    def test_d05_submitter_case_does_not_matter(self, ch):
        bid = ch.create(); ch.commit(bid); ch.at(T_ANALYZED)
        ch.verdict(ref=bid, submitter="0x" + ch.hex["analyst"][2:].upper())
        assert ch.bounty(bid)["status"] == "DELIVERED"

    def test_d06_first_valid_verdict_wins(self, ch):
        bid = ch.create(); ch.commit(bid); ch.at(T_ANALYZED)
        ch.verdict(sid=SID, ref=bid, stance="bullish")
        ch.verdict(sid=SID2, ref=bid, stance="bearish")
        b = ch.bounty(bid)
        assert (b["sid"], b["stance"]) == (SID, "bullish")

    def test_d07_verdict_for_an_open_bounty_is_ignored(self, ch):
        bid = ch.create()
        ch.verdict(ref=bid)
        assert ch.bounty(bid)["status"] == "OPEN"


OUTCOMES = [
    ("hit", "bullish", dict(analyst=2 * R, client=0)),
    ("hit", "bearish", dict(analyst=2 * R, client=0)),
    ("hit", "neutral", dict(analyst=R, client=R)),
    ("abstain", "inconclusive", dict(analyst=R, client=R)),
    ("miss", "bullish", dict(analyst=0, client=2 * R)),
    ("miss", "bearish", dict(analyst=0, client=2 * R)),
    ("excluded", "bullish", dict(analyst=0, client=2 * R)),
    ("hit", "inconclusive", dict(analyst=R, client=R)),
]


class TestSettlement:
    @pytest.mark.parametrize("result,stance,pay", OUTCOMES)
    def test_s01_payout_table(self, ch, result, stance, pay):
        bid = ch.to_delivered()
        ch.resolution(ref=bid, stance=stance, result=result, ok=(result != "excluded"))
        assert (ch.claimable("analyst"), ch.claimable("client")) == (pay["analyst"], pay["client"])
        b = ch.bounty(bid)
        assert (b["status"], b["result"]) == ("SETTLED", result)
        s = ch.solvent()
        assert (s["locked_total"], s["claimable_total"]) == (0, 2 * R)

    def test_s02_settlement_happens_once(self, ch):
        bid = ch.to_delivered()
        ch.resolution(ref=bid, result="hit"); ch.resolution(ref=bid, result="miss")
        assert (ch.claimable("analyst"), ch.claimable("client")) == (2 * R, 0)
        assert ch.solvent()["claimable_total"] == 2 * R

    def test_s03_resolution_before_delivery_is_held_and_applied_on_delivery(self, ch):
        bid = ch.create(); ch.commit(bid)
        ch.at(T_ANALYZED)
        ch.resolution(ref=bid, result="hit", stance="bullish")
        assert ch.bounty(bid)["status"] == "COMMITTED" and ch.c.get_pending_resolution(SID) != ""
        ch.verdict(ref=bid)
        assert ch.bounty(bid)["status"] == "SETTLED" and ch.claimable("analyst") == 2 * R
        assert ch.c.get_pending_resolution(SID) == ""

    def test_s04_held_resolution_for_the_wrong_analyst_is_not_stored(self, ch):
        bid = ch.create(); ch.commit(bid)
        ch.resolution(ref=bid, submitter="0x" + "9" * 40)
        assert ch.c.get_pending_resolution(SID) == ""

    def test_s05_resolution_for_unknown_or_unrelated_sids_is_ignored(self, ch):
        ch.resolution(sid=SID2, ref="77")
        ch.resolution(sid=SID2, ref="")
        assert ch.c.get_bounty_count() == 0 and ch.c.get_pending_resolution(SID2) == ""

    def test_s06_invalid_result_or_stance_is_ignored(self, ch):
        bid = ch.to_delivered()
        ch.resolution(ref=bid, result="win")
        ch.resolution(ref=bid, stance="moon")
        assert ch.bounty(bid)["status"] == "DELIVERED"

    def test_s07_resolution_uses_the_ledgers_stance(self, ch):
        bid = ch.to_delivered()
        ch.resolution(ref=bid, stance="neutral", result="hit")
        assert (ch.claimable("analyst"), ch.claimable("client")) == (R, R)

    def test_s08_two_bounties_settle_independently(self, ch):
        b0 = ch.to_delivered()
        b1 = ch.create(reward=300); ch.commit(b1, at="2026-10-11T12:20:00Z"); ch.at(T_ANALYZED)
        ch.verdict(sid=SID2, ref=b1)
        ch.resolution(sid=SID, ref=b0, result="hit")
        ch.resolution(sid=SID2, ref=b1, result="miss")
        assert (ch.claimable("analyst"), ch.claimable("client")) == (2 * R, 600)
        assert ch.solvent()["locked_total"] == 0


class TestExpiry:
    def test_e01_nobody_committed(self, ch, direct_vm):
        bid = ch.create(commit_window=3600)
        with direct_vm.expect_revert("not expirable"):
            ch.call(ch.analyst, ch.c.expire, bid)
        ch.at("2026-10-11T13:00:01Z")
        ch.call(ch.analyst, ch.c.expire, bid)
        assert ch.bounty(bid)["status"] == "EXPIRED_NO_COMMIT" and ch.claimable("client") == R
        with direct_vm.expect_revert("not expirable"):
            ch.call(ch.analyst, ch.c.expire, bid)

    def test_e02_analyst_never_delivered_forfeits_the_bond(self, ch, direct_vm):
        bid = ch.create(); ch.commit(bid)
        ch.at("2026-10-14T14:10:00Z")
        with direct_vm.expect_revert("not expirable"):
            ch.call(ch.client, ch.c.expire, bid)
        ch.at("2026-10-14T14:10:01Z")
        ch.call(ch.client, ch.c.expire, bid)
        assert ch.bounty(bid)["status"] == "EXPIRED_NO_DELIVERY"
        # the client gets the reward back; the bond is FORFEITED (stays in the contract, nobody can claim it)
        assert (ch.claimable("client"), ch.claimable("analyst")) == (R, 0)
        s = ch.c.get_solvency()
        assert (s["forfeited_total"], s["locked_total"], s["ok"]) == (R, 0, True)

    def test_e03_unresolved_in_time_refunds_both(self, ch, direct_vm):
        bid = ch.to_delivered()
        ch.at("2026-10-11T13:00:00Z")
        with direct_vm.expect_revert("not expirable"):
            ch.call(ch.client, ch.c.expire, bid)
        deadline = ch.bounty(bid)["resolve_deadline_s"]
        import datetime
        ch.at(datetime.datetime.fromtimestamp(deadline + 1, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        ch.call(ch.analyst, ch.c.expire, bid)
        assert ch.bounty(bid)["status"] == "EXPIRED_NO_RESOLUTION"
        assert (ch.claimable("analyst"), ch.claimable("client")) == (R, R)

    def test_e04_late_events_after_expiry_change_nothing(self, ch):
        bid = ch.create(commit_window=3600); ch.at("2026-10-11T13:30:00Z")
        ch.call(ch.client, ch.c.expire, bid)
        ch.verdict(ref=bid); ch.resolution(ref=bid)
        assert ch.bounty(bid)["status"] == "EXPIRED_NO_COMMIT" and ch.solvent()["claimable_total"] == R

    def test_e05_settled_bounties_are_not_expirable(self, ch, direct_vm):
        bid = ch.to_delivered(); ch.resolution(ref=bid)
        ch.at("2027-01-01T00:00:00Z")
        with direct_vm.expect_revert("not expirable"):
            ch.call(ch.client, ch.c.expire, bid)

    def test_e06_a_resolution_arriving_before_anyone_expires_is_still_honoured(self, ch):
        bid = ch.to_delivered()
        deadline = ch.bounty(bid)["resolve_deadline_s"]
        import datetime
        ch.at(datetime.datetime.fromtimestamp(deadline + 100, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        ch.resolution(ref=bid, result="hit")
        assert ch.bounty(bid)["status"] == "SETTLED" and ch.claimable("analyst") == 2 * R


class TestWithdraw:
    def test_w01_pays_exactly_the_claimable_and_clears_it(self, ch, direct_vm):
        bid = ch.to_delivered(); ch.resolution(ref=bid, result="hit")
        ch.call(ch.analyst, ch.c.withdraw)
        assert ch.transfers == [(ch.hex["analyst"], 2 * R)]
        assert ch.claimable("analyst") == 0
        with direct_vm.expect_revert("nothing to withdraw"):
            ch.call(ch.analyst, ch.c.withdraw)
        s = ch.solvent()
        assert (s["balance"], s["claimable_total"], s["locked_total"]) == (0, 0, 0)

    def test_w02_nothing_to_withdraw_for_strangers(self, ch, direct_vm):
        ch.to_delivered()
        with direct_vm.expect_revert("nothing to withdraw"):
            ch.call(ch.ledger, ch.c.withdraw)
        assert ch.transfers == []

    def test_w03_a_user_can_only_withdraw_its_own_balance(self, ch):
        bid = ch.to_delivered(); ch.resolution(ref=bid, result="miss")
        ch.call(ch.client, ch.c.withdraw)
        assert ch.transfers == [(ch.hex["client"], 2 * R)] and ch.claimable("analyst") == 0

    def test_w04_split_outcome_lets_each_side_withdraw_separately(self, ch):
        bid = ch.to_delivered(); ch.resolution(ref=bid, stance="neutral", result="hit")
        ch.call(ch.client, ch.c.withdraw); ch.call(ch.analyst, ch.c.withdraw)
        assert sorted(t[1] for t in ch.transfers) == [R, R] and ch.solvent()["balance"] == 0

    def test_w05_cancelled_reward_is_withdrawable(self, ch):
        bid = ch.create(); ch.call(ch.client, ch.c.cancel_bounty, bid)
        ch.call(ch.client, ch.c.withdraw)
        assert ch.transfers == [(ch.hex["client"], R)] and ch.solvent()["balance"] == 0


class TestViewsAndConfig:
    def test_v01_paging_is_bounded(self, ch, direct_vm):
        for _ in range(55):
            ch.create(reward=1)
        assert len(ch.c.get_ids_page(0, 1000)) == 50 and list(ch.c.get_ids_page(50, 50)) == [str(i) for i in range(50, 55)]
        with direct_vm.expect_revert("invalid page"):
            ch.c.get_ids_page(0, 0)

    def test_v02_get_claimable_rejects_garbage(self, ch, direct_vm):
        with direct_vm.expect_revert("invalid address"):
            ch.c.get_claimable("nobody")
        assert ch.c.get_claimable("0x" + "7" * 40) == 0

    def test_v03_config_shows_the_trust_root(self, ch):
        cfg = ch.c.get_config()
        assert cfg["ledger"].lower() == ch.hex["ledger"] and cfg["min_horizon_days"] == 7 and cfg["arrival_grace_s"] == 3 * 86400

    def test_v04_solvency_detects_a_balance_shortfall(self, ch):
        ch.create()
        ch.vm.deal(ch.addr, R - 1)
        assert ch.c.get_solvency()["ok"] is False


class TestAddressForms:
    @pytest.mark.parametrize("form", ["int", "hex", "bytes", "object"])
    def test_a01_ledger_address_forms(self, direct_vm, direct_deploy, direct_bob, direct_alice, form):
        set_tx_time(direct_vm, T0)
        from gltest.direct.sdk_loader import setup_sdk_paths
        setup_sdk_paths(pathlib.Path(BOUNTY), SDK_VERSION)
        addr = as_addr(direct_bob)
        value = {"int": int.from_bytes(addr.as_bytes, "big"), "hex": "0x" + addr.as_bytes.hex(), "bytes": addr.as_bytes, "object": addr}[form]
        c = direct_deploy(BOUNTY, value, sdk_version=SDK_VERSION)
        set_tx_time(direct_vm, T0)
        assert c.get_config()["ledger"].lower() == addr.as_hex.lower()
        direct_vm.sender = direct_alice
        with direct_vm.expect_revert("only the ledger"):
            c.on_resolution(SID, "0x" + "1" * 40, "0", "bullish", "hit", True, 0, 1, 1)

    @pytest.mark.parametrize("bad", [True, -1, 1 << 160, "0x12", "zzz", None])
    def test_a02_invalid_ledger_forms_are_rejected(self, direct_vm, direct_deploy, bad):
        from gltest.direct.sdk_loader import setup_sdk_paths
        setup_sdk_paths(pathlib.Path(BOUNTY), SDK_VERSION)
        with pytest.raises(Exception, match="invalid address"):
            direct_deploy(BOUNTY, bad, sdk_version=SDK_VERSION)
