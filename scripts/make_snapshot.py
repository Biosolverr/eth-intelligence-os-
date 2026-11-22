"""Print a contract-valid snapshot built from input.json with observed_at = now (UTC).
All values/provenance are submitter-asserted; this is for TESTING the contracts in Studio.
Usage: python scripts/make_snapshot.py [--horizon 30] > snapshot.json"""
import argparse, json, os, sys
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from client.snapshot import build_snapshot, to_json

ap = argparse.ArgumentParser(); ap.add_argument("--horizon", type=int, default=None)
a = ap.parse_args()
raw = json.load(open(os.path.join(os.path.dirname(__file__), "..", "input.json")))
if a.horizon:
    raw["meta"]["horizon_days"] = a.horizon
now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
src = [{"group": g, "source_id": "manual.entry", "observed_at": now, "kind": "raw"} for g in ("price", "derivs", "flows", "macro")]
src.append({"group": "risk", "source_id": "engine.local", "observed_at": now, "kind": "derived"})
print(to_json(build_snapshot(raw, now, src)))
