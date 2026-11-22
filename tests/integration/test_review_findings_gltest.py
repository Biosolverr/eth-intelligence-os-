"""gltest scenarios for what DIRECT MODE CANNOT PROVE (real node: child transactions, value, view calls).

STATUS: executed on the hosted Studio (genlayer-test 0.29.x). G1, G2, G4, G5, G6, G9 (one run) and G7 (one run) passed on
the final deployment (see docs/TEST_RESULTS.md); G3 passed earlier on a freshly deployed stack. A failure is information:
record the exact tx status / error text of anything that differs from the expectation.
Existing deployments: set ETH_VERDICT_ADDRESS, ETH_LEDGER_ADDRESS and ETH_BOUNTY_ADDRESS (G3 needs owner rights, so run it
without them, on a fresh stack: -k g3). Full instructions: docs/TESTING_GUIDE.md, section 2.

Run (Studio or localnet up, validators with LLM + web access):
    gltest tests/integration/test_review_findings_gltest.py -v -s
Cross-contract tests wait for FINALIZED child transactions, so they are slow; run them one at a time (-k g7).
Without a reachable node every test is skipped.
"""
import json
import os
import subprocess
import sys
import time

import pytest

from gltest import get_accounts, get_contract_factory, get_default_account
from gltest.assertions import tx_execution_failed, tx_execution_succeeded
from genlayer_py.types import TransactionStatus

TEMPLATE = os.environ.get(
    "ETH_PRICE_TEMPLATE",
    "https://data-api.binance.vision/api/v3/klines?symbol=ETHUSDT&interval=1h&startTime={start_ms}&limit=1")   # api.binance.com answers HTTP 451 to the hosted-Studio validators
FIN = TransactionStatus.FINALIZED
REWARD = 10 ** 15


READ_METHODS = ("eth_getTransactionByHash", "eth_getTransactionReceipt", "eth_call", "gen_call",
                "eth_blockNumber", "eth_getBalance", "eth_getTransactionCount")


@pytest.fixture(autouse=True, scope="session")
def _retry_flaky_reads():
    """The RPC goes through a local proxy on some setups and a single dropped poll would kill a long test.
    Retry READ methods only; transaction submission is never retried (it could double-send)."""
    from genlayer_py.exceptions import GenLayerError
    from genlayer_py.provider.provider import GenLayerProvider
    original = GenLayerProvider.make_request

    def patched(self, method, params):
        for attempt in range(8):
            try:
                return original(self, method, params)
            except GenLayerError as exc:
                if method not in READ_METHODS or attempt == 7 or "Request to" not in str(exc):
                    raise
                time.sleep(2 * (attempt + 1))

    GenLayerProvider.make_request = patched
    yield
    GenLayerProvider.make_request = original


def _snapshot(price=3000.0, tweak=0.0, **meta):
    env = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
    last = None
    for _ in range(3):                           # numpy/OpenBLAS can fail to allocate on a loaded Windows box
        try:
            out = subprocess.check_output([sys.executable, "scripts/make_snapshot.py"], env=env)
            break
        except subprocess.CalledProcessError as exc:
            last = exc
            time.sleep(2)
    else:
        raise last
    snap = json.loads(out)                      # observed_at = now (make_snapshot stamps it)
    snap["price"]["current"] = price
    snap["price"]["rsi_1d"] = 40.0 + tweak      # vary to get a fresh snapshot id per test
    snap["meta"].update(meta)
    return snap


def _why(res, tag):
    """Explain a failed transaction: status, leader/validator outcome, stderr. Full JSON goes to gltest_failure_<tag>.json."""
    import pathlib
    try:
        pathlib.Path("gltest_failure_%s.json" % tag).write_text(json.dumps(res, default=str, indent=1)[:3_000_000])
    except Exception:
        pass
    cd = (res.get("consensus_data") or {}) if hasattr(res, "get") else {}
    parts = ["status=%s" % (res.get("status_name") or res.get("status")),
             "result=%s" % (res.get("result_name") or res.get("result"))]
    for i, r in enumerate((cd.get("leader_receipt") or [])[:2]):
        gv = r.get("genvm_result") or {}
        parts.append("leader[%d]: exec=%s result=%.900s stderr=%.600s stdout=%.300s" % (
            i, r.get("execution_result"), json.dumps(r.get("result"), default=str), gv.get("stderr"), gv.get("stdout")))
    for i, v in enumerate((cd.get("validators") or [])[:5]):
        gv = v.get("genvm_result") or {}
        parts.append("validator[%d]: exec=%s vote=%s stderr=%.200s" % (
            i, v.get("execution_result"), v.get("vote"), gv.get("stderr")))
    return " || ".join(parts) + "  (full JSON: gltest_failure_%s.json)" % tag


def _analyze_all(c, sid, tag, **wait):
    """The real flow: every consensus-mode layer is its own transaction, then the final verdict (as in direct tests)."""
    modes = c.get_snapshot_modes(args=[sid]).call()
    for layer, mode in modes.items():
        if mode == "consensus" and not c.get_layer_result(args=[sid, layer]).call():
            r = c.analyze_layer(args=[sid, layer]).transact(wait_transaction_status=FIN)
            assert tx_execution_succeeded(r), _why(r, "%s_layer_%s" % (tag, layer))
    return c.analyze(args=[sid]).transact(wait_transaction_status=FIN, **wait)


def _last_sid(verdict):
    """Id of the snapshot that was just submitted (ids are appended in order; each run deploys fresh contracts).

    NOTE: snapshot_id_for / validate_snapshot cannot be used here: Studio's gen_call fails to decode a ~1.4 KB string
    argument in a VIEW call ("RLP string ends with N superfluous bytes"), while the same payload works in a transaction.
    """
    n = verdict.get_id_count(args=[]).call()
    return verdict.get_ids_page(args=[n - 1, 1]).call()[0]


@pytest.fixture(scope="module")
def stack():
    """Fresh deployments by default. To run the scenarios ON the final reviewer deployments instead, set
    ETH_VERDICT_ADDRESS, ETH_LEDGER_ADDRESS and ETH_BOUNTY_ADDRESS (already wired, as in the runbook, part A)."""
    existing = [os.environ.get(k) for k in ("ETH_VERDICT_ADDRESS", "ETH_LEDGER_ADDRESS", "ETH_BOUNTY_ADDRESS")]
    try:
        if all(existing):
            verdict = get_contract_factory(contract_file_path="eth_intelligence.py").build_contract(existing[0])
            ledger = get_contract_factory(contract_file_path="eth_outcome_ledger.py").build_contract(existing[1])
            bounty = get_contract_factory(contract_file_path="eth_analyst_bounty.py").build_contract(existing[2])
        else:
            verdict = get_contract_factory(contract_file_path="eth_intelligence.py").deploy(args=[])
            ledger = get_contract_factory(contract_file_path="eth_outcome_ledger.py").deploy(
                args=[verdict.address, TEMPLATE, 300, 300])
            assert tx_execution_succeeded(verdict.set_ledger(args=[ledger.address]).transact())
            bounty = get_contract_factory(contract_file_path="eth_analyst_bounty.py").deploy(args=[ledger.address])
            assert tx_execution_succeeded(ledger.add_subscriber(args=[bounty.address]).transact())
    except Exception as exc:                    # no node / not funded
        pytest.skip("no usable GenLayer node: %r" % (exc,))
    return {"verdict": verdict, "ledger": ledger, "bounty": bounty}


# G1 (F1) a zero price must be refused at submission instead of producing an orphan verdict
def test_g1_zero_price_is_rejected_at_submission(stack):
    v = stack["verdict"]
    res = v.submit_snapshot(args=[json.dumps(_snapshot(price=0.0, tweak=0.11))]).transact()
    assert tx_execution_failed(res, match_std_err="out of range")


# G2 (F8) the due-page view takes `now_s` and must work on a real node
def test_g2_unresolved_due_page_view_works_on_a_real_node(stack):
    page = stack["ledger"].get_unresolved_due_page(args=[0, 10, int(time.time())]).call()
    assert isinstance(page, list)


# G3 (F4) a pause stops intake but not work that is already underway
def test_g3_pause_blocks_new_submissions_not_submitted_work(stack):
    v = stack["verdict"]
    snap = _snapshot(tweak=0.22)
    assert tx_execution_succeeded(v.submit_snapshot(args=[json.dumps(snap)]).transact())
    sid = _last_sid(v)
    assert tx_execution_succeeded(v.set_policy(args=[86400, 1, 20]).transact())          # pause 1 h
    try:
        res = v.submit_snapshot(args=[json.dumps(_snapshot(tweak=0.23))]).transact()
        assert tx_execution_failed(res, match_std_err="paused")
        ana = _analyze_all(v, sid, "g3")                                                      # layers + verdict, while paused
        assert tx_execution_succeeded(ana), _why(ana, "g3_analyze")
    finally:
        v.set_policy(args=[86400, 0, 20]).transact()                                      # lift


# G4 (F3) a stranger cannot trigger analysis of someone else's snapshot
def test_g4_stranger_cannot_analyze_foreign_snapshot(stack):
    v = stack["verdict"]
    snap = _snapshot(tweak=0.33)
    assert tx_execution_succeeded(v.submit_snapshot(args=[json.dumps(snap)]).transact())
    sid = _last_sid(v)
    stranger = v.connect(get_accounts()[1])      # funded localnet account; use faucet on Studio if needed
    assert tx_execution_failed(stranger.analyze(args=[sid]).transact(), match_std_err="only the submitter")
    assert v.get_status(args=[sid]).call() == "SUBMITTED"


# G5 (F2) release frees the slot
def test_g5_release_snapshot_frees_the_slot(stack):
    v = stack["verdict"]
    snap = _snapshot(tweak=0.44)
    assert tx_execution_succeeded(v.submit_snapshot(args=[json.dumps(snap)]).transact())
    sid = _last_sid(v)
    assert tx_execution_succeeded(v.release_snapshot(args=[sid]).transact())
    assert v.get_status(args=[sid]).call() == "RELEASED"
    assert tx_execution_failed(v.analyze(args=[sid]).transact(), match_std_err="not in SUBMITTED")


# G6 bounty value flow on a real node: payable create, cancel, emit_transfer to an EOA, solvency invariant
def test_g6_bounty_cancel_and_withdraw_moves_value(stack):
    b = stack["bounty"]
    before = b.get_solvency(args=[]).call()
    assert tx_execution_succeeded(b.create_bounty(args=[7, 3600, 3600, 50]).transact(value=REWARD))
    bid = str(b.get_bounty_count(args=[]).call() - 1)
    assert b.get_solvency(args=[]).call()["ok"] is True
    assert tx_execution_succeeded(b.cancel_bounty(args=[bid]).transact())
    me = get_default_account().address.lower()
    assert b.get_claimable(args=[me]).call() >= REWARD
    assert tx_execution_succeeded(b.withdraw(args=[]).transact(wait_transaction_status=FIN))
    time.sleep(5)
    after = b.get_solvency(args=[]).call()
    assert after["ok"] is True and after["balance"] == before["balance"]                  # value really left the contract


# G9 (U20) a REFUSED payable call must not keep the value: it is credited back to the sender and can be withdrawn
def test_g9_refused_payable_call_refunds_the_value(stack):
    b = stack["bounty"]
    me = get_default_account().address.lower()
    before = b.get_solvency(args=[]).call()
    claim0 = int(b.get_claimable(args=[me]).call())
    count0 = b.get_bounty_count(args=[]).call()
    res = b.create_bounty(args=[6, 3600, 3600, 0]).transact(value=REWARD)          # horizon 6 is invalid
    assert tx_execution_succeeded(res), _why(res, "g9_create")
    assert b.get_rejection(args=[me]).call() == "horizon_days_out_of_bounds"
    assert int(b.get_claimable(args=[me]).call()) - claim0 == REWARD
    mid = b.get_solvency(args=[]).call()
    assert mid["unaccounted"] == before["unaccounted"] and mid["ok"] is True
    assert b.get_bounty_count(args=[]).call() == count0
    assert tx_execution_succeeded(b.withdraw(args=[]).transact(wait_transaction_status=FIN))
    time.sleep(5)
    after = b.get_solvency(args=[]).call()
    assert after["ok"] is True and after["unaccounted"] == before["unaccounted"]
    assert int(b.get_claimable(args=[me]).call()) == 0


# G7 end-to-end: analyze -> ledger.register -> bounty.on_verdict through real emit(on="finalized") + sender check
def test_g7_end_to_end_delivery_reaches_the_bounty(stack):
    v, b = stack["verdict"], stack["bounty"]
    client, analyst_acct = get_accounts()[0], get_accounts()[1]
    # 1. client opens a bounty (min_conviction 0, 1 h delivery window)
    assert tx_execution_succeeded(b.connect(client).create_bounty(args=[7, 3600, 3600, 0]).transact(value=REWARD))
    bid = str(b.get_bounty_count(args=[]).call() - 1)
    # 2. analyst submits BEFORE committing (a pause can no longer strand it), then commits with an equal bond
    av, ab = v.connect(analyst_acct), b.connect(analyst_acct)
    snap = _snapshot(tweak=0.55, horizon_days=7, bounty_ref=bid)
    assert tx_execution_succeeded(av.submit_snapshot(args=[json.dumps(snap)]).transact())
    sid = _last_sid(v)
    assert tx_execution_succeeded(ab.commit(args=[bid]).transact(value=REWARD))
    # 3. analysis after the commit; wait for the whole message chain to finalize
    res = _analyze_all(av, sid, "g7", wait_triggered_transactions=True, wait_triggered_transactions_status=FIN)
    assert tx_execution_succeeded(res), _why(res, "g7_analyze")
    time.sleep(10)
    assert stack["ledger"].get_status(args=[sid]).call() == "REGISTERED"
    bounty = json.loads(b.get_bounty(args=[bid]).call())
    ignored = b.get_ignored(args=[sid]).call()
    assert bounty["status"] in ("DELIVERED", "SETTLED"), "bounty status %s, ignored reason %r" % (bounty["status"], ignored)
