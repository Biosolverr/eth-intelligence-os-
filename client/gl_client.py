"""Thin GenLayer clients (genlayer-py).

AUTHORITY RULES
* A verdict exists only if the contract's own state says RECORDED (read via get_status/get_record).
  A receipt alone is never turned into a verdict.
* "RECORDED" is not "final": an Accepted transaction is PROVISIONAL (appealable, may be recomputed).
  Every Outcome carries `finality` so no caller can display a provisional verdict as final.
* Undetermined is NOT a final failure: a leader appeal may still produce a result.
Not exercised against a live network in this repo (see docs/TEST_REGISTER.md).
"""
import json
from dataclasses import dataclass, field
from typing import Optional

_FINAL = {"FINALIZED"}
_PROVISIONAL = {"ACCEPTED", "READY_TO_FINALIZE", "APPEAL_COMMITTING", "APPEAL_REVEALING"}
_PENDING = {"UNINITIALIZED", "PENDING", "PROPOSING", "COMMITTING", "REVEALING"}
_FAILED = {"CANCELED", "LEADER_TIMEOUT", "VALIDATORS_TIMEOUT"}


def classify_tx_status(name: Optional[str]) -> dict:
    """Pure mapping of protocol transaction status -> what a UI may claim."""
    n = (name or "").upper().replace("TRANSACTIONSTATUS.", "")
    if n in _FINAL:
        return {"phase": "FINAL", "finality": "FINAL", "note": "finalized: appeal window closed"}
    if n in _PROVISIONAL:
        return {"phase": "PROVISIONAL", "finality": "PROVISIONAL",
                "note": "accepted but still appealable; the result may be recomputed"}
    if n == "UNDETERMINED":
        return {"phase": "UNDETERMINED", "finality": "NONE",
                "note": "undetermined: nothing recorded; a leader appeal may still produce a result"}
    if n in _PENDING:
        return {"phase": "PENDING", "finality": "NONE", "note": "in progress; no verdict yet"}
    if n in _FAILED:
        return {"phase": "FAILED", "finality": "NONE", "note": "%s: not a verdict" % n.lower()}
    return {"phase": "UNKNOWN", "finality": "UNKNOWN", "note": "transaction status unavailable (%s)" % (n or "none")}


@dataclass
class Outcome:
    state: str                      # RECORDED | SUBMITTED | NOT_RECORDED | ERROR
    snapshot_id: Optional[str] = None
    tx_hash: Optional[str] = None
    contract_address: Optional[str] = None
    record: Optional[dict] = None   # ONLY set when on-chain status == RECORDED
    detail: str = ""
    tx_status: Optional[str] = None
    phase: str = "UNKNOWN"          # FINAL | PROVISIONAL | UNDETERMINED | PENDING | FAILED | UNKNOWN
    finality: str = "UNKNOWN"       # FINAL | PROVISIONAL | UNKNOWN | NONE
    extra: dict = field(default_factory=dict)


_FIN_RANK = {"NONE": 0, "UNKNOWN": 1, "PROVISIONAL": 2, "FINAL": 3}


def weakest_finality(values) -> str:
    """A verdict is only as final as the WEAKEST transaction it depends on (layers + final)."""
    vals = list(values)
    return min(vals, key=lambda f: _FIN_RANK.get(f, 0)) if vals else "UNKNOWN"


def _chains(name: str):
    from genlayer_py import localnet, studionet, testnet_asimov, testnet_bradbury
    chains = {"localnet": localnet, "studionet": studionet,
              "testnet_asimov": testnet_asimov, "testnet_bradbury": testnet_bradbury}
    if name not in chains:
        raise ValueError("unknown network; choose one of %s" % sorted(chains))
    return chains[name]


class _Base:
    def __init__(self, chain_name: str, contract_address: str, private_key: str, rpc_url: Optional[str] = None):
        from genlayer_py import create_client, create_account
        chain = _chains(chain_name)
        if not contract_address or set(contract_address.lower().replace("0x", "")) <= {"0"}:
            raise ValueError("a real deployed contract address is required (no placeholders)")
        self.chain_name, self.address = chain_name, contract_address
        self.account = create_account(private_key)
        kwargs = {"chain": chain, "account": self.account}
        if rpc_url:
            kwargs["endpoint"] = rpc_url
        self.c = create_client(**kwargs)

    def _read(self, fn, *args):
        return self.c.read_contract(address=self.address, function_name=fn, args=list(args))

    def _write(self, fn, *args):
        # leader_only is deliberately never exposed: it skips validator consensus.
        return self.c.write_contract(address=self.address, function_name=fn, args=list(args), leader_only=False)

    def tx_info(self, tx_hash) -> dict:
        try:
            t = self.c.get_transaction(transaction_hash=tx_hash)
            name = getattr(t, "status_name", None) or str(getattr(t, "status", ""))
        except Exception as exc:
            info = classify_tx_status(None)
            info["note"] += " | %s" % str(exc)[:120]
            return {**info, "tx_status": None}
        return {**classify_tx_status(name), "tx_status": name}

    def wait_final(self, tx_hash, retries: int = 60, interval_ms: int = 5000) -> dict:
        """Optional: block until FINALIZED (appeal window closed). Returns tx_info; never raises."""
        try:
            from genlayer_py.types import TransactionStatus
            self.c.wait_for_transaction_receipt(transaction_hash=tx_hash, status=TransactionStatus.FINALIZED,
                                                interval=interval_ms, retries=retries)
        except Exception:
            pass
        return self.tx_info(tx_hash)


class EthIntelligenceClient(_Base):
    def dry_run(self, snapshot_json: str) -> str:
        return self._read("validate_snapshot", snapshot_json)

    def status(self, sid: str) -> str:
        return self._read("get_status", sid)

    def authoritative_record(self, sid: str, tx_hash=None) -> Outcome:
        info = self.tx_info(tx_hash) if tx_hash else {**classify_tx_status(None), "tx_status": None,
                                                      "note": "finality not verified (no tx hash supplied)"}
        st = self.status(sid)
        base = dict(snapshot_id=sid, tx_hash=str(tx_hash) if tx_hash else None, contract_address=self.address,
                    tx_status=info["tx_status"], phase=info["phase"], finality=info["finality"])
        if st != "RECORDED":
            return Outcome("NOT_RECORDED", detail="on-chain status=%s | %s" % (st, info["note"]),
                           **{**base, "finality": "NONE"})
        rec = json.loads(self._read("get_record", sid))
        if rec.get("snapshot_id") != sid:  # input/result association guard
            return Outcome("ERROR", detail="record/snapshot id mismatch", **base)
        return Outcome("RECORDED", record=rec, detail=info["note"], **base)

    def submit(self, snapshot_json: str) -> Outcome:
        """Dry-run is ADVISORY: a contract rejection ([EXPECTED]) stops us, but a view that merely fails to
        run (e.g. a read context without tx time) must not block the authoritative transaction path."""
        sid, advisory = None, ""
        try:
            sid = self.dry_run(snapshot_json)
        except Exception as exc:
            if "[EXPECTED]" in str(exc):
                return Outcome("ERROR", detail="contract rejected the snapshot: %s" % str(exc)[:300],
                               contract_address=self.address)
            advisory = "dry-run unavailable (%s); " % str(exc)[:120]
        try:
            before = int(self._read("get_id_count"))
            tx = self._write("submit_snapshot", snapshot_json)
            self.c.wait_for_transaction_receipt(transaction_hash=tx)
            if sid is None:
                sid = self._find_new_id(before)
            st = self.status(sid) if sid else "UNKNOWN"
            info = self.tx_info(tx)
            return Outcome("SUBMITTED" if st == "SUBMITTED" else "NOT_RECORDED", sid, str(tx), self.address,
                           detail=advisory + "on-chain status=%s | %s" % (st, info["note"]),
                           tx_status=info["tx_status"], phase=info["phase"], finality="NONE")
        except Exception as exc:
            return Outcome("ERROR", sid, detail=advisory + str(exc)[:300], contract_address=self.address)

    def _find_new_id(self, before: int):
        """Locate our new snapshot id when the dry-run could not tell us (ids are append-only)."""
        total = int(self._read("get_id_count"))
        mine = str(self.account.address).lower()
        for i in range(before, min(total, before + 50)):
            sid = self._read("get_ids_page", i, 1)[0]
            if str(self._read("get_submitter", sid)).lower() == mine:
                return sid
        return None

    def analyze(self, sid: str) -> Outcome:
        try:
            tx = self._write("analyze", sid)
        except Exception as exc:
            return Outcome("ERROR", sid, contract_address=self.address, detail="send failed: %s" % str(exc)[:250])
        wait_err = ""
        try:
            self.c.wait_for_transaction_receipt(transaction_hash=tx)
        except Exception as exc:  # timeout / undetermined / failed: never fabricate a verdict
            wait_err = "wait: %s | " % str(exc)[:200]
        o = self.authoritative_record(sid, tx_hash=tx)
        o.detail = wait_err + o.detail
        return o

    def republish(self, sid: str):
        return self._write("republish", sid)

    # ---- layers -------------------------------------------------------------
    def layer_modes(self) -> dict:
        return self._read("get_layer_modes")

    def preview_layers(self, sid: str) -> dict:
        return json.loads(self._read("preview_layers", sid))

    def analyze_layer(self, sid: str, layer: str) -> Outcome:
        """Own consensus for one layer. A layer result is on-chain truth only if get_layer_result is non-empty."""
        try:
            tx = self._write("analyze_layer", sid, layer)
        except Exception as exc:
            return Outcome("ERROR", sid, contract_address=self.address,
                           detail="send failed (%s): %s" % (layer, str(exc)[:250]))
        wait_err = ""
        try:
            self.c.wait_for_transaction_receipt(transaction_hash=tx)
        except Exception as exc:
            wait_err = "wait: %s | " % str(exc)[:200]
        info = self.tx_info(tx)
        raw = self._read("get_layer_result", sid, layer)
        base = dict(snapshot_id=sid, tx_hash=str(tx), contract_address=self.address,
                    tx_status=info["tx_status"], phase=info["phase"], extra={"layer": layer})
        if not raw:
            return Outcome("NOT_RECORDED", detail=wait_err + "layer %s not recorded | %s" % (layer, info["note"]),
                           finality="NONE", **base)
        return Outcome("RECORDED", record=json.loads(raw), detail=wait_err + info["note"],
                       finality=info["finality"], **base)

    def run_full(self, sid: str, on_step=None) -> Outcome:
        """Sequence: every consensus-mode layer that lacks a stored result -> final verdict.
        Stops at the first layer that does not record (nothing is substituted); already stored layers are kept,
        so a retry re-runs only what is missing. The returned finality is the WEAKEST of all steps; consensus
        layers stored by an earlier run (no tx hash here) count as UNKNOWN."""
        preview = json.loads(self._read("preview_layers", sid))
        pending = preview["pending_consensus_layers"]
        fins = {k: "UNKNOWN" for k, v in preview.get("layers", {}).items()
                if v.get("mode") == "consensus" and k not in pending}
        for layer in pending:
            o = self.analyze_layer(sid, layer)
            fins[layer] = o.finality
            if on_step:
                on_step(layer, o)
            if o.state != "RECORDED":
                o.detail = "STOPPED at layer %s (final verdict not attempted) | %s" % (layer, o.detail)
                return o
        final = self.analyze(sid)
        if on_step:
            on_step("final", final)
        if final.state == "RECORDED":
            fins["final"] = final.finality
            weakest = weakest_finality(fins.values())
            if weakest != final.finality:
                culprit = [k for k, v in fins.items() if v == weakest and k != "final"]
                final.detail = "finality limited by %s (%s) | %s" % (",".join(culprit), weakest, final.detail)
            final.finality = weakest
            final.extra["step_finality"] = fins
        return final

    def snapshot_modes(self, sid: str) -> dict:
        return self._read("get_snapshot_modes", sid)


class EthOutcomeLedgerClient(_Base):
    def status(self, sid: str) -> str:
        return self._read("get_status", sid)

    def resolve(self, sid: str) -> Outcome:
        try:
            tx = self._write("resolve", sid)
        except Exception as exc:
            return Outcome("ERROR", sid, contract_address=self.address, detail="send failed: %s" % str(exc)[:250])
        wait_err = ""
        try:
            self.c.wait_for_transaction_receipt(transaction_hash=tx)
        except Exception as exc:
            wait_err = "wait: %s | " % str(exc)[:200]
        info = self.tx_info(tx)
        st = self.status(sid)
        base = dict(snapshot_id=sid, tx_hash=str(tx), contract_address=self.address,
                    tx_status=info["tx_status"], phase=info["phase"])
        if st != "RESOLVED":
            return Outcome("NOT_RECORDED", detail=wait_err + "ledger status=%s | %s" % (st, info["note"]),
                           finality="NONE", **base)
        res = json.loads(self._read("get_resolution", sid))
        if res.get("snapshot_id") != sid:
            return Outcome("ERROR", detail="resolution/snapshot id mismatch", finality=info["finality"], **base)
        return Outcome("RECORDED", record=res, detail=wait_err + info["note"], finality=info["finality"], **base)

    def scorecard(self) -> dict:
        return self._read("get_scorecard")

    def submitter_scorecard(self, submitter: str) -> dict:
        return self._read("get_submitter_scorecard", submitter)

    def unresolved_due(self, offset: int = 0, limit: int = 50) -> list:
        import time
        return self._read("get_unresolved_due_page", offset, limit, int(time.time()))
