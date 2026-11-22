"""Builder output must be accepted by the REAL contract validation (direct mode)."""
import json
from client.snapshot import build_snapshot, to_json
from tests.direct.conftest import OBSERVED

SOURCES = [{"group": g, "source_id": "manual.entry", "observed_at": OBSERVED, "kind": "raw"}
           for g in ("price", "derivs", "flows", "macro")] + \
          [{"group": "risk", "source_id": "engine.local", "observed_at": OBSERVED, "kind": "derived"}]


def test_t60_legacy_input_json_maps_to_contract_valid_snapshot(eth):
    raw = json.load(open("input.json"))
    snap = build_snapshot(raw, OBSERVED, SOURCES)
    sid = eth.validate_snapshot(to_json(snap))  # raises if the contract rejects it
    assert len(sid) == 64
    assert snap["risk"]["threats_score"] == 29.6 and snap["risk"]["regime"] == "accumulation"


def test_t61_builder_does_not_invent_missing_data(eth, direct_vm):
    raw = json.load(open("input.json"))
    snap = build_snapshot(raw, OBSERVED, SOURCES)
    snap["price"].pop("atr_pct")
    with direct_vm.expect_revert("missing critical field"):
        eth.validate_snapshot(to_json(snap))
