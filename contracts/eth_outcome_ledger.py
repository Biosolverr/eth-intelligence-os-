# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

import json
import re
import datetime

from genlayer import *

SCHEMA_VERSION = "1"
STANCES = ("bullish", "bearish", "neutral", "inconclusive")
RISK_LEVELS = ("low", "moderate", "elevated", "high")
RESULTS = ("hit", "miss", "abstain")
MAX_PAGE = 50
RESOLVE_BUFFER_S = 7200
MIN_BAND_BPS = 50
MAX_BAND_BPS = 5000
E8 = 100_000_000
MIN_DEV_BPS = 50
MAX_DEV_BPS = 2000
MAX_ASSERTED_E8 = 10 ** 15
MAX_OBSERVATION_LAG_S = 8 * 86400
_SUBMITTER_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_REF_RE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,39}$")
MAX_SUBSCRIBERS = 5
MAX_SUBSCRIBER_ADDS = 20
MAX_REBROADCAST = 3

_SID_RE = re.compile(r"^[0-9a-f]{64}$")
_PRICE_RE = re.compile(r"^[0-9]{1,9}(\.[0-9]{1,8})?$")


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


def parse_ts(value, field: str, assume_utc: bool = False) -> datetime.datetime:
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
        if assume_utc:
            return parsed.replace(tzinfo=datetime.timezone.utc)
        raise _err("EXPECTED", "%s must carry an explicit timezone" % field)
    return parsed.astimezone(datetime.timezone.utc)


def hour_start_ms(ts_seconds: int) -> int:
    return (ts_seconds // 3600) * 3600 * 1000


def next_hour_start_ms(ts_seconds: int) -> int:
    return (ts_seconds // 3600 + 1) * 3600 * 1000


def parse_price_e8(text) -> int:
    if not isinstance(text, str) or not _PRICE_RE.match(text):
        raise _err("EXTERNAL", "unparseable price")
    whole, _, frac = text.partition(".")
    value = int(whole) * E8 + int((frac + "00000000")[:8])
    if value <= 0:
        raise _err("EXTERNAL", "non-positive price")
    return value


def parse_kline_open_e8(body, expected_start_ms: int) -> int:
    try:
        text = body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else body
        data = json.loads(text)
    except Exception:
        raise _err("EXTERNAL", "price source returned invalid JSON")
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], list) or len(data[0]) < 2:
        raise _err("EXTERNAL", "unexpected kline shape")
    open_time, open_price = data[0][0], data[0][1]
    if isinstance(open_time, bool) or open_time != expected_start_ms:
        raise _err("EXTERNAL", "returned candle is not the requested hour")
    return parse_price_e8(open_price)


def parse_kline_range_e8(body, expected_start_ms: int) -> tuple:
    try:
        text = body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else body
        data = json.loads(text)
    except Exception:
        raise _err("EXTERNAL", "price source returned invalid JSON")
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], list) or len(data[0]) < 4:
        raise _err("EXTERNAL", "unexpected kline shape")
    open_time = data[0][0]
    if isinstance(open_time, bool) or open_time != expected_start_ms:
        raise _err("EXTERNAL", "returned candle is not the requested hour")
    open_e8, high_e8, low_e8 = parse_price_e8(data[0][1]), parse_price_e8(data[0][2]), parse_price_e8(data[0][3])
    if not (low_e8 <= open_e8 <= high_e8):
        raise _err("EXTERNAL", "inconsistent candle (open outside high/low)")
    return open_e8, high_e8, low_e8


def _get_kline_body(url_template: str, start_ms: int):
    url = url_template.replace("{start_ms}", str(start_ms))
    resp = gl.nondet.web.get(url)
    if not hasattr(resp, "body") and hasattr(resp, "get"):
        resp = resp.get()
    status = getattr(resp, "status", None)
    if status is None:
        status = getattr(resp, "status_code", None)
    if status != 200:
        raise _err("EXTERNAL", "price source HTTP status %s" % status)
    return resp.body


def fetch_open_e8(url_template: str, start_ms: int) -> int:
    return parse_kline_open_e8(_get_kline_body(url_template, start_ms), start_ms)


def fetch_range_e8(url_template: str, start_ms: int) -> tuple:
    return parse_kline_range_e8(_get_kline_body(url_template, start_ms), start_ms)


def evidence_deviation_bps(asserted_e8: int, high_e8: int, low_e8: int) -> int:
    if low_e8 <= asserted_e8 <= high_e8:
        return 0
    if asserted_e8 > high_e8:
        return (asserted_e8 - high_e8) * 10000 // high_e8
    return (low_e8 - asserted_e8) * 10000 // low_e8


def return_bps(ref_e8: int, end_e8: int) -> int:
    num = (end_e8 - ref_e8) * 10000
    mag = abs(num) // ref_e8
    return mag if num >= 0 else -mag


def realized_direction(ret_bps: int, band_bps: int) -> str:
    if ret_bps >= band_bps:
        return "up"
    if ret_bps <= -band_bps:
        return "down"
    return "flat"


def score(stance: str, realized: str) -> str:
    if stance == "inconclusive":
        return "abstain"
    expected = {"bullish": "up", "bearish": "down", "neutral": "flat"}[stance]
    return "hit" if realized == expected else "miss"


PRICE_KEYS = {"obs_e8", "obs_hi_e8", "obs_lo_e8", "ref_e8", "end_e8"}


def prices_decision(leaders_res, leader_fn) -> bool:
    if not isinstance(leaders_res, gl.vm.Return):
        return False
    try:
        mine = leader_fn()
    except Exception:
        return False
    theirs = leaders_res.calldata
    return (isinstance(theirs, dict) and set(theirs.keys()) == PRICE_KEYS
            and all(theirs[k] == mine[k] for k in PRICE_KEYS))


def verdict_args(entry: dict) -> tuple:
    return (entry["snapshot_id"], entry["submitter"], entry["bounty_ref"], entry["stance"], entry["conviction"],
            entry["risk_level"], entry["horizon_days"], entry["analyzed_at"], entry["asserted_price_e8"])


def resolution_args(res: dict) -> tuple:
    return (res["snapshot_id"], res["submitter"], res["bounty_ref"], res["stance"], res["result"],
            res["evidence_ok"], res["return_bps"], res["ref_open_e8"], res["end_open_e8"])


class EthOutcomeLedger(gl.Contract):
    owner: Address
    verdict_contract: Address
    price_url_template: str
    flat_band_bps: u256
    max_dev_bps: u256
    entries: TreeMap[str, str]
    status: TreeMap[str, str]
    resolutions: TreeMap[str, str]
    counters: TreeMap[str, u256]
    ids: DynArray[str]
    sub_list: DynArray[str]
    sub_active: TreeMap[str, str]
    sub_count: u256
    sub_log: DynArray[str]
    rebroadcast_count: TreeMap[str, u256]
    sub_at_reg: TreeMap[str, str]

    def __init__(self, verdict_contract: Address, price_url_template: str, flat_band_bps: int,
                 max_price_deviation_bps: int):
        verdict_contract = _to_address(verdict_contract)
        if "{start_ms}" not in price_url_template or not price_url_template.startswith("https://") \
                or len(price_url_template) > 300:
            raise _err("EXPECTED", "price_url_template must be https and contain {start_ms}")
        if flat_band_bps < MIN_BAND_BPS or flat_band_bps > MAX_BAND_BPS:
            raise _err("EXPECTED", "flat_band_bps out of bounds")
        if max_price_deviation_bps < MIN_DEV_BPS or max_price_deviation_bps > MAX_DEV_BPS:
            raise _err("EXPECTED", "max_price_deviation_bps out of bounds")
        self.max_dev_bps = u256(max_price_deviation_bps)
        self.owner = gl.message.sender_address
        self.verdict_contract = verdict_contract
        self.price_url_template = price_url_template
        self.flat_band_bps = u256(flat_band_bps)

    def _tx_time(self) -> datetime.datetime:
        return parse_ts(gl.message_raw["datetime"], "tx datetime", assume_utc=True)

    def _bump(self, key: str) -> None:
        self.counters[key] = u256(int(self.counters.get(key, u256(0))) + 1)

    def _active_subscribers(self) -> list:
        return [h for h in self.sub_list if self.sub_active.get(h, "") == "1"]

    def _targets(self, sid: str) -> list:
        raw = self.sub_at_reg.get(sid, "")
        out = list(json.loads(raw)) if raw else []
        for h in self._active_subscribers():
            if h not in out:
                out.append(h)
        return out

    def _broadcast(self, sid: str, method: str, args: tuple) -> None:
        for h in self._targets(sid):
            getattr(gl.get_contract_at(Address(h)).emit(on="finalized"), method)(*args)

    @gl.public.write
    def add_subscriber(self, subscriber: Address) -> None:
        if gl.message.sender_address != self.owner:
            raise _err("EXPECTED", "unauthorized: owner only")
        h = _to_address(subscriber).as_hex.lower()
        state = self.sub_active.get(h, "")
        if state == "1":
            raise _err("EXPECTED", "already subscribed")
        if int(self.sub_count) >= MAX_SUBSCRIBERS:
            raise _err("EXPECTED", "subscriber limit reached")
        if state == "":
            if len(self.sub_list) >= MAX_SUBSCRIBER_ADDS:
                raise _err("EXPECTED", "subscriber add budget exhausted")
            self.sub_list.append(h)
        self.sub_active[h] = "1"
        self.sub_count = u256(int(self.sub_count) + 1)
        self.sub_log.append("add:" + h)

    @gl.public.write
    def remove_subscriber(self, subscriber: Address) -> None:
        if gl.message.sender_address != self.owner:
            raise _err("EXPECTED", "unauthorized: owner only")
        h = _to_address(subscriber).as_hex.lower()
        if self.sub_active.get(h, "") != "1":
            raise _err("EXPECTED", "not subscribed")
        self.sub_active[h] = "0"
        self.sub_count = u256(int(self.sub_count) - 1)
        self.sub_log.append("remove:" + h)

    @gl.public.write
    def rebroadcast(self, snapshot_id: str) -> None:
        state = self.status.get(snapshot_id, "")
        if state == "":
            raise _err("EXPECTED", "unknown snapshot")
        used = int(self.rebroadcast_count.get(snapshot_id, u256(0)))
        if used >= MAX_REBROADCAST:
            raise _err("EXPECTED", "rebroadcast limit reached")
        self.rebroadcast_count[snapshot_id] = u256(used + 1)
        self._broadcast(snapshot_id, "on_verdict", verdict_args(json.loads(self.entries[snapshot_id])))
        if state == "RESOLVED":
            self._broadcast(snapshot_id, "on_resolution", resolution_args(json.loads(self.resolutions[snapshot_id])))

    @gl.public.write
    def register(self, snapshot_id: str, submitter: str, bounty_ref: str, stance: str, conviction: int,
                 risk_level: str, horizon_days: int, analyzed_at: str, observed_at: str,
                 asserted_price_e8: int) -> None:
        if gl.message.sender_address != self.verdict_contract:
            raise _err("EXPECTED", "unauthorized: only the verdict contract may register")
        if not isinstance(snapshot_id, str) or not _SID_RE.match(snapshot_id):
            raise _err("EXPECTED", "invalid snapshot id")
        if self.status.get(snapshot_id, "") != "":
            return
        if not isinstance(submitter, str) or not _SUBMITTER_RE.match(submitter):
            raise _err("EXPECTED", "invalid submitter")
        if not isinstance(bounty_ref, str) or (bounty_ref != "" and not _REF_RE.match(bounty_ref)):
            raise _err("EXPECTED", "invalid bounty_ref")
        if stance not in STANCES or risk_level not in RISK_LEVELS:
            raise _err("EXPECTED", "invalid stance or risk_level")
        if isinstance(conviction, bool) or not isinstance(conviction, int) or not (0 <= conviction <= 100):
            raise _err("EXPECTED", "invalid conviction")
        if isinstance(horizon_days, bool) or not isinstance(horizon_days, int) or not (1 <= horizon_days <= 90):
            raise _err("EXPECTED", "invalid horizon_days")
        if isinstance(asserted_price_e8, bool) or not isinstance(asserted_price_e8, int) \
                or not (0 < asserted_price_e8 <= MAX_ASSERTED_E8):
            raise _err("EXPECTED", "invalid asserted price")
        analyzed = parse_ts(analyzed_at, "analyzed_at", assume_utc=True)
        observed = parse_ts(observed_at, "observed_at")
        lag = int((analyzed - observed).total_seconds())
        if lag < -300 or lag > MAX_OBSERVATION_LAG_S:
            raise _err("EXPECTED", "observed_at inconsistent with analyzed_at")
        analyzed_s = int(analyzed.timestamp())
        ref_ms = next_hour_start_ms(analyzed_s)
        target_ms = ref_ms + horizon_days * 86400 * 1000
        entry = {
            "snapshot_id": snapshot_id, "submitter": submitter.lower(), "bounty_ref": bounty_ref,
            "stance": stance, "conviction": conviction,
            "risk_level": risk_level, "horizon_days": horizon_days,
            "analyzed_at": analyzed.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "observed_at": observed.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "asserted_price_e8": asserted_price_e8,
            "obs_ms": hour_start_ms(int(observed.timestamp())), "ref_ms": ref_ms, "target_ms": target_ms,
            "resolve_not_before_s": target_ms // 1000 + RESOLVE_BUFFER_S,
            "registered_at": gl.message_raw["datetime"],
        }
        self.entries[snapshot_id] = json.dumps(entry, sort_keys=True, separators=(",", ":"))
        self.status[snapshot_id] = "REGISTERED"
        self.ids.append(snapshot_id)
        self._bump("registered")
        self._bump("s:%s:registered" % entry["submitter"])
        self.sub_at_reg[snapshot_id] = json.dumps(self._active_subscribers(), separators=(",", ":"))
        self._broadcast(snapshot_id, "on_verdict", verdict_args(entry))

    @gl.public.write
    def resolve(self, snapshot_id: str) -> None:
        state = self.status.get(snapshot_id, "")
        if state == "":
            raise _err("EXPECTED", "unknown snapshot")
        if state == "RESOLVED":
            raise _err("EXPECTED", "already resolved; resolutions are immutable")
        entry = json.loads(self.entries[snapshot_id])
        now = self._tx_time()
        if int(now.timestamp()) < entry["resolve_not_before_s"]:
            raise _err("EXPECTED", "horizon not reached")

        template = self.price_url_template
        obs_ms, ref_ms, target_ms = entry["obs_ms"], entry["ref_ms"], entry["target_ms"]

        def leader_fn():
            obs_open, obs_hi, obs_lo = fetch_range_e8(template, obs_ms)
            return {"obs_e8": obs_open, "obs_hi_e8": obs_hi, "obs_lo_e8": obs_lo,
                    "ref_e8": fetch_open_e8(template, ref_ms),
                    "end_e8": fetch_open_e8(template, target_ms)}

        def validator_fn(leaders_res) -> bool:
            return prices_decision(leaders_res, leader_fn)

        prices = gl.vm.run_nondet_unsafe(leader_fn, validator_fn)

        band = int(self.flat_band_bps)
        max_dev = int(self.max_dev_bps)
        deviation = evidence_deviation_bps(entry["asserted_price_e8"], prices["obs_hi_e8"], prices["obs_lo_e8"])
        evidence_ok = deviation <= max_dev
        ret = return_bps(prices["ref_e8"], prices["end_e8"])
        realized = realized_direction(ret, band)
        result = score(entry["stance"], realized) if evidence_ok else "excluded"
        resolution = {
            "snapshot_id": snapshot_id, "submitter": entry["submitter"], "bounty_ref": entry["bounty_ref"],
            "stance": entry["stance"],
            "obs_open_e8": prices["obs_e8"], "obs_high_e8": prices["obs_hi_e8"], "obs_low_e8": prices["obs_lo_e8"],
            "ref_open_e8": prices["ref_e8"], "end_open_e8": prices["end_e8"],
            "asserted_price_e8": entry["asserted_price_e8"], "deviation_bps": deviation,
            "max_deviation_bps": max_dev, "evidence_ok": evidence_ok,
            "return_bps": ret, "flat_band_bps": band, "realized": realized, "result": result,
            "price_source": template, "resolved_at": gl.message_raw["datetime"],
        }
        self.resolutions[snapshot_id] = json.dumps(resolution, sort_keys=True, separators=(",", ":"))
        self.status[snapshot_id] = "RESOLVED"
        sub = "s:%s:" % entry["submitter"]
        for prefix in ("", sub):
            self._bump(prefix + "resolved")
            self._bump(prefix + ("excluded" if not evidence_ok else "%s:%s" % (entry["stance"], result)))
        self._broadcast(snapshot_id, "on_resolution", resolution_args(resolution))

    def _scorecard(self, prefix: str) -> dict:
        get = lambda k: int(self.counters.get(prefix + k, u256(0)))
        registered, resolved = get("registered"), get("resolved")
        out = {"registered": registered, "resolved": resolved, "unresolved": registered - resolved,
               "excluded": get("excluded")}
        for stance in STANCES:
            for res in RESULTS:
                out["%s:%s" % (stance, res)] = get("%s:%s" % (stance, res))
        return out

    @gl.public.view
    def get_scorecard(self) -> dict:
        return self._scorecard("")

    @gl.public.view
    def get_submitter_scorecard(self, submitter: str) -> dict:
        if not isinstance(submitter, str) or not _SUBMITTER_RE.match(submitter):
            raise _err("EXPECTED", "invalid submitter")
        return self._scorecard("s:%s:" % submitter.lower())

    @gl.public.view
    def get_unresolved_due_page(self, offset: int, limit: int, now_s: int) -> list[str]:
        if offset < 0 or limit < 1:
            raise _err("EXPECTED", "invalid page")
        if isinstance(now_s, bool) or not isinstance(now_s, int) or now_s < 0:
            raise _err("EXPECTED", "invalid now_s")
        end = min(len(self.ids), offset + min(limit, MAX_PAGE))
        out = []
        for i in range(offset, end):
            sid = self.ids[i]
            if self.status.get(sid, "") == "REGISTERED" and now_s >= json.loads(self.entries[sid])["resolve_not_before_s"]:
                out.append(sid)
        return out

    @gl.public.view
    def get_subscribers(self) -> list[str]:
        return [h for h in self.sub_list if self.sub_active.get(h, "") == "1"]

    @gl.public.view
    def get_subscriber_log(self) -> list[str]:
        return [x for x in self.sub_log]

    @gl.public.view
    def get_status(self, snapshot_id: str) -> str:
        return self.status.get(snapshot_id, "UNKNOWN")

    @gl.public.view
    def get_entry(self, snapshot_id: str) -> str:
        return self.entries.get(snapshot_id, "")

    @gl.public.view
    def get_resolution(self, snapshot_id: str) -> str:
        return self.resolutions.get(snapshot_id, "")

    @gl.public.view
    def get_id_count(self) -> int:
        return len(self.ids)

    @gl.public.view
    def get_ids_page(self, offset: int, limit: int) -> list[str]:
        if offset < 0 or limit < 1:
            raise _err("EXPECTED", "invalid page")
        end = min(len(self.ids), offset + min(limit, MAX_PAGE))
        return [self.ids[i] for i in range(offset, end)]

    @gl.public.view
    def get_policy(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "verdict_contract": self.verdict_contract.as_hex,
            "price_url_template": self.price_url_template,
            "flat_band_bps": int(self.flat_band_bps),
            "max_price_deviation_bps": int(self.max_dev_bps),
            "resolve_buffer_s": RESOLVE_BUFFER_S,
            "owner": self.owner.as_hex,
            "subscribers": int(self.sub_count),
        }
