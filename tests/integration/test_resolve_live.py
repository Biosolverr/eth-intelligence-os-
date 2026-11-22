"""Resolution against the REAL price source, in minutes instead of days.

The ledger only checks that `register` comes from the address it was deployed with, and it does not compare
`analyzed_at` with the clock. So this test deploys a DEDICATED ledger whose "verdict contract" is the test account
itself, and registers entries that were "analyzed" four days ago with a 1-day horizon: they are due immediately and
their candles are historical, so the validators fetch real data from the real source.

What this proves: the real HTTP source works for validators (formats, no geo-block), exact-equality consensus on
real candles, the candle-range evidence rule (F7), scorecard counters. What it does NOT prove: the verdict -> ledger
link (G7 covers it) or bounty settlement (that waits at least 7 days by contract rules).

Run:  gltest tests/integration/test_resolve_live.py -v -s -rs --network studionet --default-wait-retries 200
STATUS: executed on the hosted Studio with data-api.binance.vision (earlier run on a fresh stack; mirrored by runbook block 9
on the final deployment, see docs/TEST_RESULTS.md). Each `resolve` is one consensus round (~1-3 min).
"""
import datetime
import hashlib
import json

import pytest

from gltest import get_contract_factory, get_default_account
from gltest.assertions import tx_execution_succeeded
from tests.integration.test_review_findings_gltest import (  # noqa: F401  (fixture re-used on purpose)
    FIN, TEMPLATE, _retry_flaky_reads, _why,
)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _sid(tag):
    return hashlib.sha256(("live-resolve-" + tag + _iso(datetime.datetime.now(datetime.timezone.utc))).encode()).hexdigest()


def test_g8_resolve_with_real_prices_now():
    acct = get_default_account()
    try:
        ledger = get_contract_factory(contract_file_path="eth_outcome_ledger.py").deploy(
            args=[acct.address, TEMPLATE, 300, 300])          # the test account stands in for the verdict contract
    except Exception as exc:
        pytest.skip("no usable GenLayer node: %r" % (exc,))

    analyzed = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=4)).replace(
        minute=30, second=0, microsecond=0)
    observed = analyzed - datetime.timedelta(minutes=10)
    sids = {"bad": _sid("bad"), "top": _sid("top"), "over": _sid("over")}

    def register(sid, price_e8, stance="bullish"):
        res = ledger.register(args=[sid, acct.address, "", stance, 60, "moderate", 1, _iso(analyzed), _iso(observed),
                                    price_e8]).transact(wait_transaction_status=FIN)
        assert tx_execution_succeeded(res), _why(res, "g8_register")
        assert ledger.get_status(args=[sid]).call() == "REGISTERED"

    def resolve(sid, tag):
        res = ledger.resolve(args=[sid]).transact(wait_transaction_status=FIN)
        assert tx_execution_succeeded(res), _why(res, "g8_resolve_" + tag)
        assert ledger.get_status(args=[sid]).call() == "RESOLVED"
        r = json.loads(ledger.get_resolution(args=[sid]).call())
        print("\nRESOLUTION %s: %s" % (tag, json.dumps(r, sort_keys=True)))
        return r

    # 1) an absurd asserted price ($1): the REAL candles are fetched and the verdict is excluded
    register(sids["bad"], 100_000_000)
    r = resolve(sids["bad"], "bad")
    assert r["result"] == "excluded" and r["evidence_ok"] is False
    assert r["obs_low_e8"] <= r["obs_open_e8"] <= r["obs_high_e8"] and r["ref_open_e8"] > 0 and r["end_open_e8"] > 0
    high, low = r["obs_high_e8"], r["obs_low_e8"]

    # 2) an asserted price at the top of the observed hour (far from the open when the hour moved): kept, deviation 0
    register(sids["top"], high)
    r = resolve(sids["top"], "top")
    assert r["evidence_ok"] is True and r["deviation_bps"] == 0 and r["result"] in ("hit", "miss", "abstain")

    # 3) 5 % above the hour's high (500 bps > 300): excluded, deviation measured against the high
    register(sids["over"], high + high // 20)
    r = resolve(sids["over"], "over")
    assert r["evidence_ok"] is False and r["result"] == "excluded" and 480 <= r["deviation_bps"] <= 520

    sc = ledger.get_scorecard(args=[]).call()
    assert (sc["registered"], sc["resolved"], sc["unresolved"], sc["excluded"]) == (3, 3, 0, 2), sc
