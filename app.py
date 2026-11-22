"""
ETH Intelligence — Streamlit CLIENT of the GenLayer protocol.

This UI is NOT a decision engine. The verdict shown comes only from the contract's stored
record (read after the transaction). Local numbers are labelled diagnostics. If the contract
is not configured or the transaction is unresolved/failed, NO verdict is displayed.
Private key: server-side env var GENLAYER_PRIVATE_KEY only (never typed into the browser).
SECURITY: the server key signs for EVERY visitor of this page. Therefore protocol actions are locked unless
ETH_UI_PASSWORD is set (and entered) or ETH_UI_LOCAL_ONLY=1 (run with --server.address 127.0.0.1). For a public
demo use a funded-nothing testnet key, or a browser wallet (genlayer-js) instead of this page.
Pin the contract with ETH_INTEL_CONTRACT: any other address needs an explicit confirmation.
Run: streamlit run app.py
"""
import hmac
import json
import os
from datetime import datetime, timezone

import streamlit as st

from core import run_diagnostics, DIAGNOSTICS_NOTICE
from client.snapshot import build_snapshot, to_json

st.set_page_config(page_title="ETH Intelligence (GenLayer client)", layout="wide")
st.title("ETH Intelligence — GenLayer consensus client")
st.caption("Authoritative judgment = GenLayer Intelligent Contract + validator consensus. "
           "This UI never computes a verdict.")

with st.sidebar:
    network = st.selectbox("Network", ["studionet", "localnet", "testnet_asimov", "testnet_bradbury"])
    pinned = os.getenv("ETH_INTEL_CONTRACT", "")
    address = st.text_input("Deployed contract address", value=pinned)
    key_ok = bool(os.getenv("GENLAYER_PRIVATE_KEY"))
    st.write("Signer key (server env GENLAYER_PRIVATE_KEY):", "✅ set" if key_ok else "❌ not set")
    pw_env, local_only = os.getenv("ETH_UI_PASSWORD", ""), os.getenv("ETH_UI_LOCAL_ONLY") == "1"
    if pw_env:
        typed = st.text_input("UI password", type="password")
        authed = hmac.compare_digest(typed.encode(), pw_env.encode())
        if not authed:
            st.error("Protocol actions LOCKED: enter the UI password.")
    elif local_only:
        authed = True
        st.info("Local-only mode: run with --server.address 127.0.0.1; anyone who can open this page can sign.")
    else:
        authed = False
        st.error("Protocol actions LOCKED: set ETH_UI_PASSWORD (shared host) or ETH_UI_LOCAL_ONLY=1 (local use). "
                 "The server key would otherwise sign for every visitor.")
    addr_ok = True
    if pinned and address.strip().lower() != pinned.lower():
        addr_ok = st.checkbox("I know this is NOT the pinned contract (ETH_INTEL_CONTRACT)")
        st.error("This address differs from the pinned contract. A different contract can show any 'verdict'.")
    elif not pinned and address:
        st.warning("No pinned contract (ETH_INTEL_CONTRACT). Verify this address yourself: the page shows "
                   "whatever the contract at this address says.")
    configured = bool(address) and key_ok and authed and addr_ok
    if not configured:
        st.warning("Contract/key/access not configured → protocol actions are UNAVAILABLE (read-only diagnostics only).")


def get_client():
    from client.gl_client import EthIntelligenceClient
    return EthIntelligenceClient(network, address, os.environ["GENLAYER_PRIVATE_KEY"])


def show_outcome(o):
    st.write({"state": o.state, "snapshot_id": o.snapshot_id, "tx_hash": o.tx_hash,
              "contract_address": o.contract_address, "tx_status": o.tx_status, "phase": o.phase,
              "finality": o.finality, "detail": o.detail})
    if o.state == "RECORDED" and o.record:
        r = o.record["result"]
        headline = (f"Stance: **{r['stance'].upper()}** · conviction {r['conviction']}/100 "
                    f"(cap {r['conviction_cap']}) · risk {r['risk_level']}")
        if o.finality == "FINAL":
            st.success(headline + "  ·  FINAL (appeal window closed)")
        elif o.finality == "PROVISIONAL":
            st.warning(headline + "  ·  PROVISIONAL: accepted but appealable; this result may change")
        else:
            st.info(headline + "  ·  finality NOT verified (supply the tx hash to check)")
        if o.record.get("layers"):
            st.markdown("**Layers** (arith = formula · consensus = its own validator consensus)")
            st.table([{"layer": k, "mode": v["mode"], "stance": v["stance"], "score": v["score"],
                       "caution": v["caution"], "note": v["note"][:120]}
                      for k, v in o.record["layers"].items()])
            st.caption(f"directional tally: {o.record.get('layer_tally')}")
        st.write("Bullish evidence:", r["bullish_evidence"], "| Bearish evidence:", r["bearish_evidence"])
        st.write("Conflicts:", r["conflicts"], "| Data gaps:", r["data_gaps"])
        st.text(r["summary"])  # st.text: model output rendered as inert text
        st.caption(o.record["disclaimer"] + " All evidence and provenance were asserted by the submitter.")
        st.json(o.record["quality"])
    elif o.state == "SUBMITTED":
        st.info("Snapshot stored on-chain; analysis not yet recorded. No verdict exists.")
    elif o.phase == "UNDETERMINED":
        st.error("NO VERDICT (yet): consensus was UNDETERMINED. Nothing is recorded, but an appeal may still "
                 "produce a result; do not treat this as a final failure.")
    elif o.phase == "PENDING":
        st.info("NO VERDICT (yet): the transaction is still in progress.")
    else:
        st.error("NO VERDICT: the on-chain record does not exist (failed, timed out, or error). "
                 "Nothing is substituted locally.")


t1, t2, t3, t5, t4 = st.tabs(["1 Evidence", "2 Submit & analyze", "3 Read result", "4 Scorecard", "Local diagnostics"])

with t1:
    st.markdown("Paste legacy `input.json`; supply **provenance** for each group (not independently verified).")
    raw_txt = st.text_area("input.json", value=open("input.json").read() if os.path.exists("input.json") else "{}", height=260)
    observed = st.text_input("observed_at (UTC, ISO-8601 with Z)", value=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    prov_txt = st.text_area("sources (JSON list of {group, source_id, observed_at, kind})", height=160,
                            value=json.dumps([{"group": g, "source_id": "manual.entry", "observed_at": observed, "kind": "raw"}
                                              for g in ("price", "derivs", "flows", "macro")] +
                                             [{"group": "risk", "source_id": "engine.local", "observed_at": observed, "kind": "derived"}], indent=1))
    if st.button("Build snapshot"):
        try:
            snap = build_snapshot(json.loads(raw_txt), observed, json.loads(prov_txt))
            st.session_state["snapshot_json"] = to_json(snap)
            st.success("Snapshot built (all values and provenance are submitter-asserted and unverified).")
        except Exception as e:
            st.error(f"Invalid input: {e}")
    if "snapshot_json" in st.session_state:
        st.code(st.session_state["snapshot_json"], language="json")

with t2:
    if "snapshot_json" not in st.session_state:
        st.info("Build a snapshot first.")
    elif not configured:
        st.error("UNAVAILABLE: configure contract address and signer key.")
    else:
        if st.button("Dry-run validation (read-only)"):
            try:
                st.success(f"Valid. Snapshot id: {get_client().dry_run(st.session_state['snapshot_json'])}")
            except Exception as e:
                st.error(f"Contract rejected snapshot: {e}")
        if st.button("Submit snapshot (tx)"):
            o = get_client().submit(st.session_state["snapshot_json"])
            st.session_state["sid"] = o.snapshot_id
            show_outcome(o)
        if st.button("Layer plan (read-only)"):
            sid = st.session_state.get("sid")
            if not sid:
                st.error("Submit first.")
            else:
                st.json(get_client().preview_layers(sid))
        if st.button("Run all: consensus layers, then final verdict (txs)", type="primary"):
            sid = st.session_state.get("sid")
            if not sid:
                st.error("Submit first.")
            else:
                steps = []
                with st.spinner("Waiting for consensus (each consensus layer is its own transaction)…"):
                    o = get_client().run_full(sid, on_step=lambda name, r: steps.append(
                        {"step": name, "state": r.state, "phase": r.phase, "tx": r.tx_hash}))
                st.table(steps)
                show_outcome(o)

with t3:
    sid_in = st.text_input("Snapshot id", value=st.session_state.get("sid") or "")
    tx_in = st.text_input("Analyze tx hash (optional; enables the finality check)")
    if st.button("Read authoritative record"):
        if not configured or not sid_in:
            st.error("UNAVAILABLE: configure contract/key and provide an id.")
        else:
            c = get_client()
            o = c.authoritative_record(sid_in, tx_hash=tx_in or None)
            show_outcome(o)
            if o.state == "RECORDED":
                st.subheader("Evidence snapshot bound to this result")
                st.json(json.loads(c._read("get_snapshot", sid_in)))
                st.download_button("Export record (verbatim)", json.dumps(o.record, indent=2, sort_keys=True), "record.json")

with t4:
    st.warning(DIAGNOSTICS_NOTICE)
    try:
        st.json(run_diagnostics(json.loads(open("input.json").read())))
    except Exception as e:
        st.error(str(e))

with t5:
    st.markdown("**Outcome ledger scorecard** (validator-graded, forward-only). Read `unresolved` before any hit rate.")
    ledger_addr = st.text_input("Ledger contract address", value=os.getenv("ETH_LEDGER_CONTRACT", ""))
    who = st.text_input("Submitter address (optional: that account's own record)")
    if st.button("Read scorecard"):
        if not (configured and ledger_addr):
            st.error("UNAVAILABLE: configure access, signer and the ledger address.")
        else:
            from client.gl_client import EthOutcomeLedgerClient
            lc = EthOutcomeLedgerClient(network, ledger_addr, os.environ["GENLAYER_PRIVATE_KEY"])
            sc = lc.submitter_scorecard(who) if who else lc.scorecard()
            hits = sum(v for k, v in sc.items() if k.endswith(":hit"))
            misses = sum(v for k, v in sc.items() if k.endswith(":miss"))
            reg_, res_ = sc["registered"], sc["resolved"]
            st.table([{"registered": reg_, "resolved": res_, "unresolved": sc["unresolved"],
                       "excluded (implausible asserted price)": sc["excluded"], "hits": hits, "misses": misses}])
            if sc["unresolved"]:
                st.warning(f"{sc['unresolved']} verdict(s) are not resolved yet: hit rates below are PARTIAL. "
                           "Anyone can resolve due entries; do not trust a rate computed only over resolved ones.")
            if reg_:
                st.write(f"hits / registered = {hits}/{reg_}  ·  hits / (hits+misses) = {hits}/{hits + misses}  ·  "
                         "compare with a naive baseline before reading skill into this.")
            st.json(sc)
