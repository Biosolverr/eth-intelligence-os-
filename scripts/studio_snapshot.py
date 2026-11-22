"""Make a fresh, one-line snapshot for pasting into the Studio 'snapshot_json' field.

Usage (from the repo root, in cmd):
    python scripts/studio_snapshot.py 41                              # S1: rsi_1d = 41
    python scripts/studio_snapshot.py 51 --horizon 7 --bounty-ref 1   # SB1 (for bounty 1)
    python scripts/studio_snapshot.py 52 --horizon 30 --bounty-ref 2  # SB2 (for bounty 2)

The number is written to price.rsi_1d (every different number gives a different snapshot id). The result is saved to
snap_<number>.json and, on Windows, copied to the clipboard: just press Ctrl+V in the Studio field.
"""
import argparse
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rsi", type=float, help="value for price.rsi_1d (use a different one per snapshot)")
    ap.add_argument("--horizon", type=int, help="meta.horizon_days")
    ap.add_argument("--bounty-ref", help="meta.bounty_ref")
    a = ap.parse_args()
    env = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
    out = subprocess.check_output([sys.executable, os.path.join(ROOT, "scripts", "make_snapshot.py")], env=env, cwd=ROOT)
    snap = json.loads(out)
    snap["price"]["rsi_1d"] = a.rsi
    if a.horizon is not None:
        snap["meta"]["horizon_days"] = a.horizon
    if a.bounty_ref is not None:
        snap["meta"]["bounty_ref"] = a.bounty_ref
    text = json.dumps(snap, separators=(",", ":"))
    name = "snap_%s.json" % (str(a.rsi).rstrip("0").rstrip(".") or "0")
    with open(os.path.join(ROOT, name), "w", encoding="ascii") as fh:
        fh.write(text)
    copied = False
    if os.name == "nt":
        try:
            subprocess.run("clip", input=text.encode("ascii"), check=True, shell=True)
            copied = True
        except Exception:
            pass
    print("saved %s (%d chars), observed_at=%s, horizon_days=%s, bounty_ref=%r" % (
        name, len(text), snap["meta"].get("observed_at"), snap["meta"].get("horizon_days"), snap["meta"].get("bounty_ref")))
    print("copied to clipboard: paste with Ctrl+V" if copied else "open the file and copy its single line")


if __name__ == "__main__":
    main()