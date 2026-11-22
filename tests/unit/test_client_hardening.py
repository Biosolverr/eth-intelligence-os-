"""P2 client/UI hardening (fake RPC; NOT a chain): weakest finality, advisory dry-run, UI access control, scorecard."""
import json
from types import SimpleNamespace

import pytest

from client.gl_client import EthIntelligenceClient, EthOutcomeLedgerClient, weakest_finality
from tests.unit.test_client_and_ui import FakeRpc, REC, SID, at, all_text, make  # noqa: F401
from tests.unit.test_client_layers import LayerRpc, fns  # noqa: F401


# ---- weakest finality --------------------------------------------------------------------------
@pytest.mark.parametrize("vals,expect", [
    (["FINAL", "FINAL"], "FINAL"), (["FINAL", "PROVISIONAL"], "PROVISIONAL"), (["FINAL", "UNKNOWN"], "UNKNOWN"),
    (["PROVISIONAL", "UNKNOWN", "FINAL"], "UNKNOWN"), (["FINAL", "NONE"], "NONE"), ([], "UNKNOWN"),
])
def test_t100_weakest_finality_order(vals, expect):
    assert weakest_finality(vals) == expect


def test_t101_final_tx_finalized_but_a_layer_only_accepted_is_provisional():
    """P2 regression: run_full used to report only the final tx's finality."""
    rpc = LayerRpc(layer_status="ACCEPTED", final_status="FINALIZED")
    o = make(EthIntelligenceClient, rpc).run_full(SID)
    assert o.state == "RECORDED" and o.finality == "PROVISIONAL"
    assert "finality limited by" in o.detail and o.extra["step_finality"]["final"] == "FINAL"


def test_t102_everything_finalized_is_final():
    o = make(EthIntelligenceClient, LayerRpc(layer_status="FINALIZED", final_status="FINALIZED")).run_full(SID)
    assert o.finality == "FINAL" and set(o.extra["step_finality"].values()) == {"FINAL"}


def test_t103_a_layer_stored_by_an_earlier_run_makes_finality_unknown_not_final():
    rpc = LayerRpc(prestored=("macro",), layer_status="FINALIZED", final_status="FINALIZED")
    o = make(EthIntelligenceClient, rpc).run_full(SID)
    assert o.finality == "UNKNOWN" and o.extra["step_finality"]["macro"] == "UNKNOWN"


# ---- advisory dry-run ---------------------------------------------------------------------------
def test_t104_contract_rejection_in_dry_run_stops_before_any_transaction():
    rpc = FakeRpc(dry_run_error="[EXPECTED] stale snapshot: age 99999s exceeds 86400s")
    o = make(EthIntelligenceClient, rpc).submit("{}")
    assert o.state == "ERROR" and "rejected" in o.detail and rpc.write_calls == []


def test_t105_a_view_that_merely_fails_does_not_block_the_authoritative_tx():
    """P2 regression: a read context without tx time must not make the UI unable to submit anything."""
    rpc = FakeRpc(status="SUBMITTED", dry_run_error="KeyError: 'datetime'")
    o = make(EthIntelligenceClient, rpc).submit("{}")
    assert [c["function_name"] for c in rpc.write_calls] == ["submit_snapshot"]
    assert o.state == "SUBMITTED" and o.snapshot_id == SID and "dry-run unavailable" in o.detail


def test_t106_unknown_new_id_is_not_guessed():
    rpc = FakeRpc(status="SUBMITTED", dry_run_error="boom")
    rpc.write_contract = lambda **kw: (rpc.write_calls.append(kw), "0xtx")[1]     # tx 'succeeds' but no id appears
    o = make(EthIntelligenceClient, rpc).submit("{}")
    assert o.snapshot_id is None and o.state == "NOT_RECORDED"


def test_t112_new_id_is_found_among_other_senders_snapshots_not_guessed():
    rpc = FakeRpc(status="SUBMITTED", dry_run_error="boom")
    other = "f" * 64
    rpc.ids, rpc.submitter_of = [other], {other: "0x" + "22" * 20}          # someone else's snapshot is already there
    o = make(EthIntelligenceClient, rpc).submit("{}")
    assert o.snapshot_id == SID and o.snapshot_id != other


# ---- UI access control --------------------------------------------------------------------------
def _env(monkeypatch, **kv):
    for k in ("GENLAYER_PRIVATE_KEY", "ETH_INTEL_CONTRACT", "ETH_UI_PASSWORD", "ETH_UI_LOCAL_ONLY"):
        monkeypatch.delenv(k, raising=False)
    for k, v in kv.items():
        monkeypatch.setenv(k, v)


def _drive(at, monkeypatch, rpc=None, address="0x" + "ab" * 20, typed=None):
    import client.gl_client as g
    monkeypatch.setattr(g, "EthIntelligenceClient", lambda *a, **k: make(EthIntelligenceClient, rpc or FakeRpc("RECORDED", REC)))
    at.run()
    at.sidebar.text_input[0].set_value(address).run()
    if typed is not None:
        at.sidebar.text_input[1].set_value(typed).run()
    at.session_state["snapshot_json"] = "{}"; at.session_state["sid"] = SID
    at.run()


def test_t107_without_password_or_local_flag_protocol_actions_are_locked(at, monkeypatch):
    _env(monkeypatch, GENLAYER_PRIVATE_KEY="0x" + "1" * 64)
    _drive(at, monkeypatch)
    txt = all_text(at)
    assert "LOCKED" in txt and "UNAVAILABLE" in txt and "UNAVAILABLE" in "".join(str(e.value) for e in at.error)


def test_t108_wrong_password_stays_locked_right_password_unlocks(at, monkeypatch):
    _env(monkeypatch, GENLAYER_PRIVATE_KEY="0x" + "1" * 64, ETH_UI_PASSWORD="s3cret")
    _drive(at, monkeypatch, typed="nope")
    assert "enter the UI password" in all_text(at) and any("UNAVAILABLE" in str(e.value) for e in at.error)
    at.sidebar.text_input[1].set_value("s3cret").run()
    assert "enter the UI password" not in all_text(at)
    assert not any("UNAVAILABLE" in str(e.value) for e in at.error)
    [b for b in at.button if "Run all" in b.label][0].click().run()
    assert "Stance: **BULLISH**" in all_text(at)


def test_t109_a_non_pinned_contract_address_is_refused_until_explicitly_confirmed(at, monkeypatch):
    _env(monkeypatch, GENLAYER_PRIVATE_KEY="0x" + "1" * 64, ETH_UI_LOCAL_ONLY="1", ETH_INTEL_CONTRACT="0x" + "cd" * 20)
    _drive(at, monkeypatch, address="0x" + "ab" * 20)                       # different from the pinned one
    assert "differs from the pinned contract" in all_text(at)
    assert any("UNAVAILABLE" in str(e.value) for e in at.error)
    at.sidebar.checkbox[0].check().run()
    assert not any("UNAVAILABLE" in str(e.value) for e in at.error)


def test_t110_the_pinned_address_needs_no_confirmation(at, monkeypatch):
    _env(monkeypatch, GENLAYER_PRIVATE_KEY="0x" + "1" * 64, ETH_UI_LOCAL_ONLY="1", ETH_INTEL_CONTRACT="0x" + "ab" * 20)
    _drive(at, monkeypatch, address="0x" + "ab" * 20)
    assert "differs from the pinned" not in all_text(at) and not at.sidebar.checkbox


# ---- scorecard tab -------------------------------------------------------------------------------
class LedgerRpc:
    def __init__(self, sc): self.sc = sc
    def read_contract(self, address, function_name, args=None, **kw):
        assert function_name in ("get_scorecard", "get_submitter_scorecard"); return self.sc


def test_t111_scorecard_warns_when_entries_are_unresolved_and_shows_partial_rates(at, monkeypatch):
    _env(monkeypatch, GENLAYER_PRIVATE_KEY="0x" + "1" * 64, ETH_UI_LOCAL_ONLY="1")
    sc = {"registered": 10, "resolved": 3, "unresolved": 7, "excluded": 1, "bullish:hit": 2, "bullish:miss": 0}
    import client.gl_client as g
    monkeypatch.setattr(g, "EthOutcomeLedgerClient", lambda *a, **k: make(EthOutcomeLedgerClient, LedgerRpc(sc)))
    _drive(at, monkeypatch)
    at.text_input[0].set_value("0x" + "ee" * 20) if False else None
    ledger_in = [t for t in at.text_input if t.label == "Ledger contract address"][0]
    ledger_in.set_value("0x" + "ee" * 20).run()
    [b for b in at.button if b.label == "Read scorecard"][0].click().run()
    txt = all_text(at)
    assert "7 verdict(s) are not resolved yet" in txt and "hits / registered = 2/10" in txt
    assert not at.exception
