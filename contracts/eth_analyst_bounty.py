# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
import json
import re
import datetime

from genlayer import *

SCHEMA_VERSION = "1"
STANCES = ("bullish", "bearish", "neutral", "inconclusive")
RESULTS = ("hit", "miss", "abstain", "excluded")
MIN_REWARD = 1
MIN_HORIZON_DAYS = 7
MAX_HORIZON_DAYS = 90
MIN_COMMIT_WINDOW_S = 3600
MAX_COMMIT_WINDOW_S = 30 * 86400
MIN_DELIVERY_WINDOW_S = 3600
MAX_DELIVERY_WINDOW_S = 172800
ARRIVAL_GRACE_S = 3 * 86400
RESOLVE_GRACE_S = 14 * 86400
REF_OFFSET_S = 3600
MAX_PAGE = 50
_ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


def _err(kind: str, msg: str):
    return gl.vm.UserError("[%s] %s" % (kind, msg))


def _to_address(value) -> Address:
    if isinstance(value, Address):
        return value
    if isinstance(value, bool):
        raise _err("EXPECTED", "invalid address")
    if isinstance(value, int):
        if value < 0 or value >= 1 << 160:
            raise _err("EXPECTED", "invalid address")
        return Address(value.to_bytes(20, "big"))
    if isinstance(value, (str, bytes, bytearray)):
        try:
            return Address(value)
        except Exception:
            raise _err("EXPECTED", "invalid address")
    raise _err("EXPECTED", "invalid address")


def parse_ts(value, field: str) -> datetime.datetime:
    if not isinstance(value, str) or len(value) > 40:
        raise _err("EXPECTED", "%s must be an ISO-8601 string" % field)
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except ValueError:
        raise _err("EXPECTED", "%s is not a valid ISO-8601 timestamp" % field)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.astimezone(datetime.timezone.utc)


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


@gl.evm.contract_interface
class _Recipient:
    class View:
        pass

    class Write:
        pass


class AnalystBounty(gl.Contract):
    ledger: Address
    count: u256
    bounties: TreeMap[str, str]
    sid_to_bounty: TreeMap[str, str]
    pending_res: TreeMap[str, str]
    claimable: TreeMap[str, u256]
    claimable_total: u256
    locked_total: u256
    forfeited_total: u256
    ignored: TreeMap[str, str]
    rejections: TreeMap[str, str]

    def __init__(self, ledger: Address):
        self.ledger = _to_address(ledger)
        self.count = u256(0)
        self.claimable_total = u256(0)
        self.locked_total = u256(0)
        self.forfeited_total = u256(0)

    def _now(self) -> int:
        return int(parse_ts(gl.message_raw["datetime"], "tx datetime").timestamp())

    def _sender(self) -> str:
        return gl.message.sender_address.as_hex.lower()

    def _get(self, bid: str) -> dict:
        raw = self.bounties.get(bid, "")
        if raw == "":
            raise _err("EXPECTED", "unknown bounty")
        return json.loads(raw)

    def _put(self, b: dict) -> None:
        self.bounties[b["id"]] = json.dumps(b, sort_keys=True, separators=(",", ":"))

    def _lock(self, amount: int) -> None:
        self.locked_total = u256(int(self.locked_total) + amount)

    def _unlock(self, amount: int) -> None:
        self.locked_total = u256(int(self.locked_total) - amount)

    def _credit(self, who: str, amount: int) -> None:
        if amount <= 0:
            return
        self.claimable[who] = u256(int(self.claimable.get(who, u256(0))) + amount)
        self.claimable_total = u256(int(self.claimable_total) + amount)

    def _reject(self, reason: str):
        who = self._sender()
        self._credit(who, int(gl.message.value))
        self.rejections[who] = reason

    def _ignore(self, sid: str, reason: str) -> None:
        self.ignored[sid] = reason

    def _require_ledger(self) -> None:
        if gl.message.sender_address != self.ledger:
            raise _err("EXPECTED", "unauthorized: only the ledger")

    def _settle(self, b: dict, result: str, stance: str) -> None:
        reward, bond = b["reward"], b["bond"]
        if result == "hit" and stance in ("bullish", "bearish"):
            self._credit(b["analyst"], reward + bond)
        elif result in ("miss", "excluded"):
            self._credit(b["client"], reward + bond)
        else:
            self._credit(b["analyst"], bond)
            self._credit(b["client"], reward)
        self._unlock(reward + bond)
        b["status"] = "SETTLED"
        b["result"] = result
        b["settled_at_s"] = self._now()
        self._put(b)

    @gl.public.write.payable
    def create_bounty(self, horizon_days: int, commit_window_s: int, delivery_window_s: int,
                      min_conviction: int) -> str:
        reward = int(gl.message.value)
        if reward < MIN_REWARD:
            self._reject("reward_too_small")
            return ""
        if not _is_int(horizon_days) or not (MIN_HORIZON_DAYS <= horizon_days <= MAX_HORIZON_DAYS):
            self._reject("horizon_days_out_of_bounds")
            return ""
        if not _is_int(commit_window_s) or not (MIN_COMMIT_WINDOW_S <= commit_window_s <= MAX_COMMIT_WINDOW_S):
            self._reject("commit_window_s_out_of_bounds")
            return ""
        if not _is_int(delivery_window_s) or not (MIN_DELIVERY_WINDOW_S <= delivery_window_s <= MAX_DELIVERY_WINDOW_S):
            self._reject("delivery_window_s_out_of_bounds")
            return ""
        if not _is_int(min_conviction) or not (0 <= min_conviction <= 100):
            self._reject("min_conviction_out_of_bounds")
            return ""
        now = self._now()
        bid = str(int(self.count))
        b = {
            "id": bid, "client": self._sender(), "reward": reward, "horizon_days": horizon_days,
            "commit_window_s": commit_window_s, "delivery_window_s": delivery_window_s,
            "min_conviction": min_conviction, "created_at_s": now, "commit_deadline_s": now + commit_window_s,
            "status": "OPEN", "analyst": "", "bond": 0, "committed_at_s": 0, "deliver_deadline_s": 0,
            "sid": "", "stance": "", "resolve_deadline_s": 0, "result": "", "settled_at_s": 0,
        }
        self._put(b)
        self.count = u256(int(self.count) + 1)
        self._lock(reward)
        self.rejections[b["client"]] = ""
        return bid

    @gl.public.write
    def cancel_bounty(self, bounty_id: str) -> None:
        b = self._get(bounty_id)
        if self._sender() != b["client"]:
            raise _err("EXPECTED", "unauthorized: only the client")
        if b["status"] != "OPEN":
            raise _err("EXPECTED", "bounty is not open")
        b["status"] = "CANCELLED"
        self._put(b)
        self._unlock(b["reward"])
        self._credit(b["client"], b["reward"])

    @gl.public.write.payable
    def commit(self, bounty_id: str) -> bool:
        raw = self.bounties.get(bounty_id, "")
        if raw == "":
            self._reject("unknown_bounty")
            return False
        b = json.loads(raw)
        if b["status"] != "OPEN":
            self._reject("bounty_not_open")
            return False
        now = self._now()
        if now > b["commit_deadline_s"]:
            self._reject("commit_window_closed")
            return False
        sender = self._sender()
        if sender == b["client"]:
            self._reject("client_cannot_commit")
            return False
        if int(gl.message.value) != b["reward"]:
            self._reject("bond_must_equal_reward")
            return False
        b["status"] = "COMMITTED"
        b["analyst"] = sender
        b["bond"] = b["reward"]
        b["committed_at_s"] = now
        b["deliver_deadline_s"] = now + b["delivery_window_s"]
        self._put(b)
        self._lock(b["bond"])
        self.rejections[sender] = ""
        return True

    @gl.public.write
    def on_verdict(self, snapshot_id: str, submitter: str, bounty_ref: str, stance: str, conviction: int,
                   risk_level: str, horizon_days: int, analyzed_at: str, asserted_price_e8: int) -> None:
        self._require_ledger()
        raw = self.bounties.get(bounty_ref, "")
        if raw == "":
            return
        b = json.loads(raw)
        if not isinstance(submitter, str) or b["analyst"] == "" or submitter.lower() != b["analyst"]:
            return
        if b["status"] != "COMMITTED":
            self._ignore(snapshot_id, "bounty_not_committed")
            return
        if horizon_days != b["horizon_days"]:
            self._ignore(snapshot_id, "horizon_mismatch")
            return
        if stance not in STANCES:
            self._ignore(snapshot_id, "invalid_stance")
            return
        if not _is_int(conviction) or conviction < b["min_conviction"]:
            self._ignore(snapshot_id, "conviction_below_min")
            return
        analyzed_ts = int(parse_ts(analyzed_at, "analyzed_at").timestamp())
        if analyzed_ts < b["committed_at_s"] or analyzed_ts > b["deliver_deadline_s"]:
            self._ignore(snapshot_id, "outside_delivery_window")
            return
        b["status"] = "DELIVERED"
        b["sid"] = snapshot_id
        b["stance"] = stance
        b["resolve_deadline_s"] = analyzed_ts + horizon_days * 86400 + REF_OFFSET_S + RESOLVE_GRACE_S
        self.sid_to_bounty[snapshot_id] = bounty_ref
        pending = self.pending_res.get(snapshot_id, "")
        if stance == "inconclusive":
            self._settle(b, "abstain", stance)
        elif pending != "":
            self.pending_res[snapshot_id] = ""
            held = json.loads(pending)
            self._settle(b, held["result"], held["stance"])
        else:
            self._put(b)

    @gl.public.write
    def on_resolution(self, snapshot_id: str, submitter: str, bounty_ref: str, stance: str, result: str,
                      evidence_ok: bool, return_bps: int, ref_open_e8: int, end_open_e8: int) -> None:
        self._require_ledger()
        if result not in RESULTS or stance not in STANCES:
            return
        bid = self.sid_to_bounty.get(snapshot_id, "")
        if bid != "":
            b = json.loads(self.bounties[bid])
            if b["status"] == "DELIVERED":
                self._settle(b, result, stance)
            return
        raw = self.bounties.get(bounty_ref, "")
        if raw == "":
            return
        b = json.loads(raw)
        if b["status"] == "COMMITTED" and isinstance(submitter, str) and submitter.lower() == b["analyst"]:
            self.pending_res[snapshot_id] = json.dumps({"result": result, "stance": stance})

    @gl.public.write
    def expire(self, bounty_id: str) -> None:
        b = self._get(bounty_id)
        now = self._now()
        status = b["status"]
        if status == "OPEN" and now > b["commit_deadline_s"]:
            b["status"] = "EXPIRED_NO_COMMIT"
            self._unlock(b["reward"])
            self._credit(b["client"], b["reward"])
        elif status == "COMMITTED" and now > b["deliver_deadline_s"] + ARRIVAL_GRACE_S:
            b["status"] = "EXPIRED_NO_DELIVERY"
            self._unlock(b["reward"] + b["bond"])
            self._credit(b["client"], b["reward"])
            self.forfeited_total = u256(int(self.forfeited_total) + b["bond"])
        elif status == "DELIVERED" and now > b["resolve_deadline_s"]:
            b["status"] = "EXPIRED_NO_RESOLUTION"
            self._unlock(b["reward"] + b["bond"])
            self._credit(b["analyst"], b["bond"])
            self._credit(b["client"], b["reward"])
        else:
            raise _err("EXPECTED", "not expirable")
        b["settled_at_s"] = now
        self._put(b)

    @gl.public.write
    def withdraw(self) -> None:
        who = self._sender()
        amount = int(self.claimable.get(who, u256(0)))
        if amount <= 0:
            raise _err("EXPECTED", "nothing to withdraw")
        self.claimable[who] = u256(0)
        self.claimable_total = u256(int(self.claimable_total) - amount)
        _Recipient(gl.message.sender_address).emit_transfer(value=u256(amount))

    @gl.public.view
    def get_bounty(self, bounty_id: str) -> str:
        return self.bounties.get(bounty_id, "")

    @gl.public.view
    def get_bounty_count(self) -> int:
        return int(self.count)

    @gl.public.view
    def get_ids_page(self, offset: int, limit: int) -> list[str]:
        if offset < 0 or limit < 1:
            raise _err("EXPECTED", "invalid page")
        end = min(int(self.count), offset + min(limit, MAX_PAGE))
        return [str(i) for i in range(offset, end)]

    @gl.public.view
    def get_claimable(self, account: str) -> int:
        if not isinstance(account, str) or not _ADDR_RE.match(account):
            raise _err("EXPECTED", "invalid address")
        return int(self.claimable.get(account.lower(), u256(0)))

    @gl.public.view
    def get_ignored(self, snapshot_id: str) -> str:
        return self.ignored.get(snapshot_id, "")

    @gl.public.view
    def get_rejection(self, account: str) -> str:
        if not isinstance(account, str) or not _ADDR_RE.match(account):
            raise _err("EXPECTED", "invalid address")
        return self.rejections.get(account.lower(), "")

    @gl.public.view
    def get_pending_resolution(self, snapshot_id: str) -> str:
        return self.pending_res.get(snapshot_id, "")

    @gl.public.view
    def get_solvency(self) -> dict:
        balance = int(self.balance)
        owed = int(self.claimable_total) + int(self.locked_total) + int(self.forfeited_total)
        return {"balance": balance, "claimable_total": int(self.claimable_total),
                "locked_total": int(self.locked_total), "forfeited_total": int(self.forfeited_total),
                "unaccounted": max(0, balance - owed), "ok": balance >= owed}

    @gl.public.view
    def get_config(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION, "ledger": self.ledger.as_hex,
            "min_reward": MIN_REWARD, "min_horizon_days": MIN_HORIZON_DAYS, "max_horizon_days": MAX_HORIZON_DAYS,
            "min_commit_window_s": MIN_COMMIT_WINDOW_S, "max_commit_window_s": MAX_COMMIT_WINDOW_S,
            "min_delivery_window_s": MIN_DELIVERY_WINDOW_S, "max_delivery_window_s": MAX_DELIVERY_WINDOW_S,
            "arrival_grace_s": ARRIVAL_GRACE_S, "resolve_grace_s": RESOLVE_GRACE_S,
        }
