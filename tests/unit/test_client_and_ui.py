"""Client-layer and UI behaviour WITHOUT a network (fake RPC). Not live-chain evidence."""
import ast, json, pathlib
from types import SimpleNamespace
import pytest
from client.gl_client import EthIntelligenceClient, EthOutcomeLedgerClient, classify_tx_status

ROOT = pathlib.Path(__file__).resolve().parents[2]
SID = "a" * 64


class FakeRpc:
    def __init__(self, status="SUBMITTED", record=None, tx_error=None, tx_status="FINALIZED", tx_lookup_error=False,
                 resolution=None, dry_run_error=None):
        self.dry_run_error, self.ids = dry_run_error, []
        self.status_v, self.record_v, self.tx_error = status, record, tx_error
        self.tx_status, self.tx_lookup_error, self.resolution = tx_status, tx_lookup_error, resolution
        self.write_calls = []

    def read_contract(self, address, function_name, args=None, **kw):
        if function_name == "get_status": return self.status_v
        if function_name == "get_record": return json.dumps(self.record_v)
        if function_name == "get_resolution": return json.dumps(self.resolution)
        if function_name == "validate_snapshot":
            if self.dry_run_error: raise RuntimeError(self.dry_run_error)
            return SID
        if function_name == "get_id_count": return len(self.ids)
        if function_name == "get_ids_page": return self.ids[args[0]:args[0] + args[1]]
        if function_name == "get_submitter": return getattr(self, "submitter_of", {}).get(args[0], "0x" + "11" * 20)
        if function_name == "preview_layers": return json.dumps({"pending_consensus_layers": []})
        if function_name == "get_scorecard": return {"total:resolved": 0}
        raise AssertionError(function_name)

    def write_contract(self, **kw):
        self.write_calls.append(kw)
        if self.tx_error: raise RuntimeError(self.tx_error)
        if kw["function_name"] == "submit_snapshot": self.ids.append(SID)
        return "0xtx"

    def wait_for_transaction_receipt(self, **kw): return {}

    def get_transaction(self, transaction_hash):
        if self.tx_lookup_error: raise RuntimeError("rpc down")
        return SimpleNamespace(status_name=self.tx_status)


def make(cls, rpc):
    c = cls.__new__(cls)
    c.c, c.address, c.chain_name, c.account = rpc, "0x" + "ab" * 20, "studionet", SimpleNamespace(address="0x" + "11" * 20)
    return c


GOOD = {"snapshot_id": SID, "result": {"stance": "bullish"}}


def test_t70_placeholder_address_rejected():
    with pytest.raises(ValueError):
        EthIntelligenceClient("studionet", "0x" + "0" * 40, "0x" + "1" * 64)


def test_t71_recorded_and_finalized_is_final():
    o = make(EthIntelligenceClient, FakeRpc("RECORDED", GOOD, tx_status="FINALIZED")).analyze(SID)
    assert o.state == "RECORDED" and o.record == GOOD and o.tx_hash == "0xtx" and o.finality == "FINAL"


@pytest.mark.parametrize("status", ["ACCEPTED", "READY_TO_FINALIZE", "APPEAL_COMMITTING"])
def test_t71b_recorded_but_accepted_is_provisional_never_final(status):
    o = make(EthIntelligenceClient, FakeRpc("RECORDED", GOOD, tx_status=status)).analyze(SID)
    assert o.state == "RECORDED" and o.finality == "PROVISIONAL" and "appealable" in o.detail


@pytest.mark.parametrize("status", ["SUBMITTED", "UNKNOWN"])
def test_t72_tx_ok_but_not_recorded_gives_no_verdict(status):
    o = make(EthIntelligenceClient, FakeRpc(status, GOOD)).analyze(SID)  # record data present but status says no
    assert o.state == "NOT_RECORDED" and o.record is None and o.finality == "NONE"


def test_t73_tx_failure_or_timeout_never_becomes_verdict():
    o = make(EthIntelligenceClient, FakeRpc("SUBMITTED", GOOD, tx_error="boom")).analyze(SID)
    assert o.state == "ERROR" and o.record is None


def test_t74_record_for_other_snapshot_is_rejected():
    o = make(EthIntelligenceClient, FakeRpc("RECORDED", {"snapshot_id": "b" * 64, "result": {}})).authoritative_record(SID)
    assert o.state == "ERROR" and o.record is None


def test_t75_leader_only_is_never_used():
    rpc = FakeRpc("RECORDED", GOOD); c = make(EthIntelligenceClient, rpc)
    c.analyze(SID); c.submit("{}"); c.republish(SID)
    assert len(rpc.write_calls) == 3 and all(call.get("leader_only") is False for call in rpc.write_calls)


def test_t76_production_code_does_not_import_legacy_consensus():
    banned = {"legacy", "agents", "run_consensus"}
    for rel in ["app.py", "core.py", "client/gl_client.py", "client/snapshot.py"] + \
               [str(p.relative_to(ROOT)) for p in (ROOT / "engine").glob("*.py")]:
        tree = ast.parse((ROOT / rel).read_text())
        for n in ast.walk(tree):
            names = []
            if isinstance(n, ast.Import): names = [a.name.split(".")[0] for a in n.names]
            if isinstance(n, ast.ImportFrom) and n.module: names = [n.module.split(".")[0]] + [a.name for a in n.names]
            assert not (set(names) & banned), (rel, names)


def test_t77_legacy_package_is_not_importable_by_default():
    with pytest.raises(ImportError):
        __import__("legacy")


@pytest.mark.parametrize("name,phase,finality", [
    ("FINALIZED", "FINAL", "FINAL"), ("ACCEPTED", "PROVISIONAL", "PROVISIONAL"),
    ("READY_TO_FINALIZE", "PROVISIONAL", "PROVISIONAL"), ("UNDETERMINED", "UNDETERMINED", "NONE"),
    ("PENDING", "PENDING", "NONE"), ("PROPOSING", "PENDING", "NONE"), ("REVEALING", "PENDING", "NONE"),
    ("CANCELED", "FAILED", "NONE"), ("LEADER_TIMEOUT", "FAILED", "NONE"),
    ("VALIDATORS_TIMEOUT", "FAILED", "NONE"), ("TransactionStatus.FINALIZED", "FINAL", "FINAL"),
    (None, "UNKNOWN", "UNKNOWN"), ("SOMETHING_NEW", "UNKNOWN", "UNKNOWN"),
])
def test_t83_status_classification(name, phase, finality):
    r = classify_tx_status(name)
    assert (r["phase"], r["finality"]) == (phase, finality)


def test_t84_undetermined_is_not_final_failure_and_yields_no_verdict():
    o = make(EthIntelligenceClient, FakeRpc("SUBMITTED", GOOD, tx_status="UNDETERMINED")).analyze(SID)
    assert o.state == "NOT_RECORDED" and o.phase == "UNDETERMINED" and "appeal" in o.detail and o.record is None


def test_t85_without_tx_hash_finality_is_unknown_not_final():
    o = make(EthIntelligenceClient, FakeRpc("RECORDED", GOOD)).authoritative_record(SID)
    assert o.state == "RECORDED" and o.finality == "UNKNOWN"


def test_t86_status_lookup_failure_is_unknown_never_final():
    o = make(EthIntelligenceClient, FakeRpc("RECORDED", GOOD, tx_lookup_error=True)).analyze(SID)
    assert o.state == "RECORDED" and o.finality == "UNKNOWN"


RES = {"snapshot_id": SID, "result": "hit"}


def test_t87_ledger_resolve_requires_on_chain_resolved_status():
    ok = make(EthOutcomeLedgerClient, FakeRpc("RESOLVED", resolution=RES, tx_status="FINALIZED")).resolve(SID)
    assert ok.state == "RECORDED" and ok.record == RES and ok.finality == "FINAL"
    no = make(EthOutcomeLedgerClient, FakeRpc("REGISTERED", resolution=RES, tx_status="UNDETERMINED")).resolve(SID)
    assert no.state == "NOT_RECORDED" and no.record is None and no.phase == "UNDETERMINED"
    bad = make(EthOutcomeLedgerClient, FakeRpc("RESOLVED", resolution={"snapshot_id": "c" * 64})).resolve(SID)
    assert bad.state == "ERROR" and bad.record is None


# ---- UI (streamlit AppTest) ----
REC = {"snapshot_id": SID, "disclaimer": "d", "quality": {},
       "result": {"stance": "bullish", "conviction": 60, "conviction_cap": 75, "risk_level": "moderate",
                  "bullish_evidence": ["flows.sopr"], "bearish_evidence": [], "conflicts": [],
                  "data_gaps": [], "summary": "ok"}}


@pytest.fixture
def at(monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.chdir(ROOT)
    return AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)


def all_text(at):
    parts = [e.value for e in at.markdown] + [e.value for e in at.error] + [e.value for e in at.warning] + \
            [e.value for e in at.success] + [e.value for e in at.info]
    return "\n".join(map(str, parts))


def drive(at, monkeypatch, rpc):
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
    return all_text(at)


def test_t80_ui_unconfigured_shows_unavailable_and_no_verdict(at, monkeypatch):
    for k in ("GENLAYER_PRIVATE_KEY", "ETH_INTEL_CONTRACT", "ETH_UI_PASSWORD", "ETH_UI_LOCAL_ONLY"):
        monkeypatch.delenv(k, raising=False)
    at.run()
    assert not at.exception
    txt = all_text(at)
    assert "UNAVAILABLE" in txt and "Stance:" not in txt


def test_t81_ui_send_failure_shows_no_verdict(at, monkeypatch):
    txt = drive(at, monkeypatch, FakeRpc("SUBMITTED", GOOD, tx_error="boom"))
    assert "NO VERDICT" in txt and "Stance:" not in txt


def test_t82_ui_final_result_is_displayed_as_final(at, monkeypatch):
    txt = drive(at, monkeypatch, FakeRpc("RECORDED", REC, tx_status="FINALIZED"))
    assert "Stance: **BULLISH**" in txt and "FINAL (appeal window closed)" in txt and "NO VERDICT" not in txt
    assert any("PROVISIONAL" in str(w.value) for w in at.warning) is False


def test_t88_ui_accepted_result_is_labelled_provisional(at, monkeypatch):
    txt = drive(at, monkeypatch, FakeRpc("RECORDED", REC, tx_status="ACCEPTED"))
    assert "Stance: **BULLISH**" in txt and "PROVISIONAL" in txt and "FINAL (appeal window closed)" not in txt
    assert any("PROVISIONAL" in str(w.value) for w in at.warning)


def test_t89_ui_undetermined_is_not_presented_as_final_failure(at, monkeypatch):
    txt = drive(at, monkeypatch, FakeRpc("SUBMITTED", GOOD, tx_status="UNDETERMINED"))
    assert "UNDETERMINED" in txt and "appeal may still" in txt and "Stance:" not in txt
