import datetime
import pathlib
import random
import sys

import pytest

from tests.direct.conftest import SDK_VERSION, as_addr, set_tx_time
from tests.direct.test_bounty import BOUNTY, Chain

T_START = int(datetime.datetime(2026, 10, 11, 12, 0, tzinfo=datetime.timezone.utc).timestamp())
TERMINAL = {"SETTLED", "CANCELLED", "EXPIRED_NO_COMMIT", "EXPIRED_NO_DELIVERY", "EXPIRED_NO_RESOLUTION"}
RESULTS = ["hit", "miss", "abstain", "excluded", "hit", "miss", "bogus"]
STANCES = ["bullish", "bearish", "neutral", "inconclusive", "bullish", "bearish", "moon"]
COVERAGE = {"seeds": 0, "withdrawals": 0, "statuses": {}, "pre_sweep": {}, "results": {}}


def iso(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build(direct_vm, direct_deploy, accounts):
    set_tx_time(direct_vm, iso(T_START))
    from gltest.direct.sdk_loader import setup_sdk_paths
    setup_sdk_paths(pathlib.Path(BOUNTY), SDK_VERSION)
    ledger = accounts[0]
    c = direct_deploy(BOUNTY, as_addr(ledger).as_hex, sdk_version=SDK_VERSION)
    set_tx_time(direct_vm, iso(T_START))
    mod = next(m for m in sys.modules.values() if hasattr(m, "AnalystBounty") and hasattr(m, "_Recipient"))
    ch = Chain(direct_vm, c, mod, ledger, accounts[1], accounts[2])
    ch.people = accounts[1:5]
    ch.hexes = {as_addr(a).as_hex.lower(): a for a in accounts[1:5]}
    return ch


@pytest.mark.parametrize("seed", range(40))
def test_f01_random_action_sequences_never_break_value_conservation(seed, direct_vm, direct_deploy, direct_accounts):
    ch = build(direct_vm, direct_deploy, direct_accounts)
    rnd, now = random.Random(seed), T_START
    deposited = 0
    seen_terminal = {}
    sids = 0

    def attempt(fn, *args, who, value=0):
        nonlocal deposited
        try:
            ch.call(who, fn, *args, value=value)
        except Exception as exc:
            assert "[EXPECTED]" in str(exc), exc
            return False
        deposited += value
        return True

    for _ in range(110):
        now += rnd.choice([0, 60, 600, 600, 1800, 3600])
        if rnd.random() < 0.05:
            now += rnd.choice([86400, 5 * 86400, 20 * 86400])
        ch.at(iso(now))
        count = ch.c.get_bounty_count()
        bounties = [ch.bounty(str(i)) for i in range(count)]
        by = lambda status: [b for b in bounties if b["status"] == status]
        act = rnd.choice(["create", "create", "cancel", "commit", "commit", "commit", "verdict", "verdict", "verdict",
                          "resolution", "resolution", "resolution", "expire", "withdraw", "withdraw"])
        if act == "create":
            attempt(ch.c.create_bounty, rnd.choice([7, 7, 30, 90, 3]), rnd.choice([86400, 86400, 3600]), rnd.choice([3600, 7200, 172800]),
                    rnd.choice([0, 50, 100]), who=rnd.choice(ch.people[:2]), value=rnd.choice([0, 1, 10, 1000, 123456]))
        elif act == "cancel" and bounties:
            b = rnd.choice(bounties)
            attempt(ch.c.cancel_bounty, b["id"], who=rnd.choice(ch.people) if rnd.random() < 0.3 else ch.hexes[b["client"]])
        elif act == "commit" and bounties:
            b = rnd.choice(by("OPEN") or bounties)
            others = [a for a in ch.people if as_addr(a).as_hex.lower() != b["client"]]
            attempt(ch.c.commit, b["id"], who=rnd.choice(others) if rnd.random() < 0.9 else ch.hexes[b["client"]],
                    value=b["reward"] if rnd.random() < 0.85 else rnd.choice([b["reward"] + 1, 0]))
        elif act == "verdict" and bounties:
            cands = by("COMMITTED")
            b = rnd.choice(cands) if cands and rnd.random() < 0.9 else rnd.choice(bounties)
            sid = "%064x" % (sids + 1); sids += 1
            if b["analyst"] and rnd.random() < 0.8:
                analyzed = iso(rnd.randint(b["committed_at_s"], b["deliver_deadline_s"]))
                attempt(ch.c.on_verdict, sid, b["analyst"], b["id"], rnd.choice(STANCES[:4]), 100, "moderate",
                        b["horizon_days"], analyzed, 300_000_000_000, who=ch.ledger)
            else:
                attempt(ch.c.on_verdict, sid, rnd.choice(list(ch.hexes)), b["id"], rnd.choice(STANCES), rnd.choice([0, 49, 100]),
                        "moderate", rnd.choice([7, 8, 30]), iso(rnd.choice([now, now - 86400, now + 3600])), 300_000_000_000,
                        who=ch.ledger if rnd.random() < 0.8 else rnd.choice(ch.people))
        elif act == "resolution":
            cands = by("DELIVERED") + by("COMMITTED")
            if cands and rnd.random() < 0.9:
                b = rnd.choice(cands)
                sid = b["sid"] or "%064x" % rnd.randint(1, sids + 2)
                attempt(ch.c.on_resolution, sid, b["analyst"], b["id"], rnd.choice(STANCES[:4]), rnd.choice(RESULTS[:4]),
                        rnd.random() < 0.8, 5, 1, 2, who=ch.ledger)
            else:
                attempt(ch.c.on_resolution, "%064x" % rnd.randint(1, sids + 2), rnd.choice(list(ch.hexes)),
                        rnd.choice(bounties)["id"] if bounties else "0", rnd.choice(STANCES), rnd.choice(RESULTS), True, 5, 1, 2,
                        who=ch.ledger if rnd.random() < 0.8 else rnd.choice(ch.people))
        elif act == "expire" and bounties:
            attempt(ch.c.expire, rnd.choice(bounties)["id"], who=rnd.choice(ch.people))
        elif act == "withdraw":
            attempt(ch.c.withdraw, who=rnd.choice(ch.people))

        s = ch.c.get_solvency()
        paid_out = sum(a for _, a in ch.transfers)
        assert s["ok"] and s["balance"] == ch.balance
        assert s["balance"] == s["claimable_total"] + s["locked_total"] + s["forfeited_total"], s
        assert deposited == s["balance"] + paid_out
        total_claimable = sum(ch.c.get_claimable(h) for h in ch.hexes)
        assert total_claimable == s["claimable_total"]
        bounties = [ch.bounty(str(i)) for i in range(ch.c.get_bounty_count())]
        open_locked = sum(b["reward"] + b["bond"] for b in bounties if b["status"] not in TERMINAL)
        assert open_locked == s["locked_total"]
        assert s["forfeited_total"] == sum(b["bond"] for b in bounties if b["status"] == "EXPIRED_NO_DELIVERY")
        for b in bounties:
            if b["status"] in TERMINAL:
                assert seen_terminal.setdefault(b["id"], b) == b, "terminal bounty changed"

    for b in [ch.bounty(str(i)) for i in range(ch.c.get_bounty_count())]:
        COVERAGE["pre_sweep"][b["status"]] = COVERAGE["pre_sweep"].get(b["status"], 0) + 1
    now += 200 * 86400
    ch.at(iso(now))
    for i in range(ch.c.get_bounty_count()):
        try:
            ch.call(ch.people[0], ch.c.expire, str(i))
        except Exception as exc:
            assert "[EXPECTED]" in str(exc)
    bounties = [ch.bounty(str(i)) for i in range(ch.c.get_bounty_count())]
    assert all(b["status"] in TERMINAL for b in bounties), [b["status"] for b in bounties]
    for person in ch.people:
        try:
            ch.call(person, ch.c.withdraw)
        except Exception as exc:
            assert "nothing to withdraw" in str(exc)
    s = ch.c.get_solvency()
    assert (s["balance"], s["claimable_total"], s["locked_total"]) == (s["forfeited_total"], 0, 0), s
    assert deposited == sum(a for _, a in ch.transfers) + s["forfeited_total"]

    COVERAGE["seeds"] += 1
    COVERAGE["withdrawals"] += len(ch.transfers)
    for b in bounties:
        COVERAGE["statuses"][b["status"]] = COVERAGE["statuses"].get(b["status"], 0) + 1
        if b["result"]:
            COVERAGE["results"][b["result"]] = COVERAGE["results"].get(b["result"], 0) + 1


def test_f02_the_fuzz_really_reaches_every_terminal_state_and_pays_out():
    if COVERAGE["seeds"] < 40:
        pytest.skip("coverage is only meaningful after the full fuzz run")
    assert COVERAGE["withdrawals"] >= 20
    for status in ("SETTLED", "CANCELLED", "EXPIRED_NO_COMMIT", "EXPIRED_NO_DELIVERY", "EXPIRED_NO_RESOLUTION"):
        assert COVERAGE["statuses"].get(status, 0) >= 3, (status, COVERAGE)
    for status in ("OPEN", "COMMITTED", "DELIVERED", "SETTLED"):
        assert COVERAGE["pre_sweep"].get(status, 0) >= 3, (status, COVERAGE)
    for result in ("hit", "miss", "abstain", "excluded"):
        assert COVERAGE["results"].get(result, 0) >= 3, (result, COVERAGE)
