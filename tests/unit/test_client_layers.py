"""Client orchestration of per-layer consensus (fake RPC; NOT a chain)."""
import json
from types import SimpleNamespace

import pytest

from client.gl_client import EthIntelligenceClient
from tests.unit.test_client_and_ui import FakeRpc, REC, SID, at, all_text, make  # noqa: F401 (fixtures)

LAYER_REC = dict(REC, layers={
    "macro": {"layer": "macro", "mode": "consensus", "kind": "directional", "stance": "bearish", "score": -30,
              "caution": 40, "note": "hy spreads widening", "drivers": [], "inconclusive": False},
    "quant": {"layer": "quant", "mode": "arith", "kind": "directional", "stance": "bullish", "score": 25,
              "caution": 25, "note": "tech block", "drivers": [], "inconclusive": False}},
    layer_tally={"bullish": 1, "bearish": 1, "neutral": 0, "inconclusive": 0})


class LayerRpc(FakeRpc):
    def __init__(self, pending=("macro", "manipulation"), prestored=(), fail_layer=None, fail_status="UNDETERMINED",
                 fail_raise=False, swallow=False, layer_status="FINALIZED", final_status="ACCEPTED", **kw):
        self.layer_status, self.final_status = layer_status, final_status
        super().__init__(status="RECORDED", record=LAYER_REC, **kw)
        self.pending, self.store, self.statuses = list(pending), {l: "{}" for l in prestored}, {}
        self.fail_layer, self.fail_status, self.fail_raise, self.swallow = fail_layer, fail_status, fail_raise, swallow

    def read_contract(self, address, function_name, args=None, **kw):
        if function_name == "preview_layers":
            return json.dumps({"pending_consensus_layers": [l for l in self.pending if l not in self.store],
                               "layers": {l: {"mode": "consensus"} for l in list(self.pending) + list(self.store)}})
        if function_name == "get_layer_result":
            return json.dumps({"layer": args[1], "stance": "neutral"}) if args[1] in self.store else ""
        if function_name == "get_layer_modes":
            return {l: "consensus" for l in self.pending}
        return super().read_contract(address, function_name, args, **kw)

    def write_contract(self, **kw):
        self.write_calls.append(kw)
        fn, args = kw["function_name"], kw["args"]
        h = "0x%s-%d" % (fn, len(self.write_calls))
        if fn == "analyze_layer":
            if args[1] == self.fail_layer:
                self.statuses[h] = self.fail_status
                if self.fail_raise:
                    raise RuntimeError("send failed")
            else:
                self.statuses[h] = self.layer_status
                if not self.swallow:
                    self.store[args[1]] = "{}"
        else:
            self.statuses[h] = self.final_status
        return h

    def get_transaction(self, transaction_hash):
        return SimpleNamespace(status_name=self.statuses.get(transaction_hash, "FINALIZED"))


def fns(rpc):
    return [c["function_name"] + (":" + c["args"][1] if c["function_name"] == "analyze_layer" else "") for c in rpc.write_calls]


def test_t90_run_full_runs_layers_then_final_and_never_uses_leader_only():
    rpc = LayerRpc(); steps = []
    o = make(EthIntelligenceClient, rpc).run_full(SID, on_step=lambda n, r: steps.append((n, r.state)))
    assert fns(rpc) == ["analyze_layer:macro", "analyze_layer:manipulation", "analyze"]
    assert steps == [("macro", "RECORDED"), ("manipulation", "RECORDED"), ("final", "RECORDED")]
    assert o.state == "RECORDED" and o.finality == "PROVISIONAL"          # final tx is only ACCEPTED
    assert all(c.get("leader_only") is False for c in rpc.write_calls)


def test_t91_undetermined_layer_stops_the_sequence_and_no_verdict_is_attempted():
    rpc = LayerRpc(fail_layer="macro", fail_status="UNDETERMINED")
    o = make(EthIntelligenceClient, rpc).run_full(SID)
    assert fns(rpc) == ["analyze_layer:macro"]                             # manipulation and final NOT attempted
    assert o.state == "NOT_RECORDED" and o.phase == "UNDETERMINED" and o.record is None
    assert "STOPPED at layer macro" in o.detail and "appeal" in o.detail


def test_t92_send_failure_on_a_layer_stops_with_error():
    rpc = LayerRpc(fail_layer="macro", fail_raise=True)
    o = make(EthIntelligenceClient, rpc).run_full(SID)
    assert o.state == "ERROR" and fns(rpc) == ["analyze_layer:macro"] and "STOPPED" in o.detail


def test_t93_retry_reruns_only_the_missing_layers():
    rpc = LayerRpc(prestored=("macro",))
    make(EthIntelligenceClient, rpc).run_full(SID)
    assert fns(rpc) == ["analyze_layer:manipulation", "analyze"]


def test_t94_a_layer_counts_only_if_the_contract_actually_stored_it():
    rpc = LayerRpc(swallow=True)                                           # tx looks FINALIZED, nothing stored
    o = make(EthIntelligenceClient, rpc).run_full(SID)
    assert o.state == "NOT_RECORDED" and fns(rpc) == ["analyze_layer:macro"]


def test_t95_all_arithmetic_means_only_the_final_transaction():
    rpc = LayerRpc(pending=())
    o = make(EthIntelligenceClient, rpc).run_full(SID)
    assert fns(rpc) == ["analyze"] and o.state == "RECORDED"


def drive_full(at, monkeypatch, rpc):
    monkeypatch.setenv("GENLAYER_PRIVATE_KEY", "0x" + "1" * 64)
    monkeypatch.setenv("ETH_UI_LOCAL_ONLY", "1")
    import client.gl_client as g
    monkeypatch.setattr(g, "EthIntelligenceClient", lambda *a, **k: make(EthIntelligenceClient, rpc))
    at.run()
    at.sidebar.text_input[0].set_value("0x" + "ab" * 20).run()
    at.session_state["snapshot_json"] = "{}"; at.session_state["sid"] = SID
    at.run()
    [b for b in at.button if "Run all" in b.label][0].click().run()
    assert not at.exception


def test_t96_ui_shows_the_layer_table_and_labels_provisional(at, monkeypatch):
    drive_full(at, monkeypatch, LayerRpc())
    txt = all_text(at)
    assert "Layers" in txt and "PROVISIONAL" in txt and "Stance: **BULLISH**" in txt
    tables = [t.value for t in at.table]
    assert any("consensus" in str(t.to_dict()) or "macro" in str(t.to_dict()) for t in tables)


def test_t97_ui_layer_failure_shows_no_verdict_and_the_stop_reason(at, monkeypatch):
    drive_full(at, monkeypatch, LayerRpc(fail_layer="macro", fail_status="UNDETERMINED"))
    txt = all_text(at)
    assert "Stance:" not in txt and "UNDETERMINED" in txt
