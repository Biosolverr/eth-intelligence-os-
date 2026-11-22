"""Mutation sanity check: break the contracts on purpose; every mutant MUST be caught by tests/.
Run from the repo root inside the venv:  python scripts/mutate.py"""
import os, shutil, subprocess, sys

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V, L = "contracts/eth_intelligence.py", "contracts/eth_outcome_ledger.py"
B = "contracts/eth_analyst_bounty.py"
M = [
 # ---- verdict contract (core)
 (V, "V01 validator always agrees", "    return results_equivalent(leader_data, mine)\n\n\nclass", "    return True\n\n\nclass"),
 (V, "V02 no freshness check on submit", "        check_freshness(snapshot, now, int(self.max_age_s))\n        sender = gl.message.sender_address.as_hex", "        sender = gl.message.sender_address.as_hex"),
 (V, "V03 analyze open to any sender again", "        self._require_submitter(snapshot_id)\n\n        snapshot = json.loads(self.snapshots[snapshot_id])\n        now = self._tx_time()", "        snapshot = json.loads(self.snapshots[snapshot_id])\n        now = self._tx_time()"),
 (V, "V04 inconclusive matches a directional stance", "    if (leader[\"stance\"] == \"inconclusive\") != (mine[\"stance\"] == \"inconclusive\"):\n        return False\n", ""),
 (V, "V04b different stances always equivalent", "    elif abs(stance_score(leader) - stance_score(mine)) > SCORE_TOL:\n        return False\n", "    else:\n        pass\n"),
 (V, "V04c same-stance conviction not compared", "        if abs(leader[\"conviction\"] - mine[\"conviction\"]) > SCORE_TOL:\n            return False\n", "        pass\n"),
 (V, "V04d score tolerance is exclusive", "> SCORE_TOL:\n            return False\n    elif", ">= SCORE_TOL:\n            return False\n    elif"),
 (V, "V04e risk tolerance widened to two steps", "RISK_LEVELS.index(mine[\"risk_level\"])) <= 1", "RISK_LEVELS.index(mine[\"risk_level\"])) <= 2"),
 (V, "V04f neutral scored as the conviction", "    return 0\n\n\ndef results_equivalent", "    return result[\"conviction\"]\n\n\ndef results_equivalent"),
 (V, "V05 no duplicate check", "        if sid in self.status:\n            raise _err(\"EXPECTED\", \"duplicate snapshot %s\" % sid)\n", ""),
 (V, "V06 no evidence requirement", "    if stance == \"bullish\" and not bull:\n        raise _err(\"LLM_ERROR\", \"bullish stance without verifiable bullish evidence\")\n", ""),
 (V, "V07 set_policy open to anyone", "        if gl.message.sender_address != self.owner:\n            raise _err(\"EXPECTED\", \"unauthorized: owner only\")\n        if max_age_s", "        if max_age_s"),
 (V, "V08 no conviction cap", "        result[\"conviction\"] = min(result[\"conviction\"], cap)", "        pass"),
 (V, "V09 overwrite allowed", "        if state == \"RECORDED\":\n            raise _err(\"EXPECTED\", \"already recorded; results are immutable\")\n", ""),
 (V, "V10 naive timestamps accepted", "        raise _err(\"EXPECTED\", \"%s must carry an explicit timezone\" % field)", "        return parsed.replace(tzinfo=datetime.timezone.utc)"),
 (V, "V11 NaN accepted", "    raise ValueError(\"non-finite JSON constant: %s\" % name)", "    return 0.0"),
 (V, "V12 validator trusts leader error", "    if not isinstance(leaders_res, gl.vm.Return):\n        return False\n    try:", "    if not isinstance(leaders_res, gl.vm.Return):\n        return True\n    try:"),
 (V, "V13 validator skips leader schema check", "        leader_data = normalize_result(leaders_res.calldata, snapshot)\n        mine = leader_fn()", "        leader_data = leaders_res.calldata\n        mine = leader_fn()"),
 (V, "V14 validator agrees when its own run fails", "    except Exception:\n        return False\n    return results_equivalent", "    except Exception:\n        return True\n    return results_equivalent"),
 (V, "V15 self-asserted 'observed' label accepted again", 'SOURCE_KINDS = ("raw", "derived")', 'SOURCE_KINDS = ("raw", "derived", "observed")'),
 (V, "V16 unbounded page", "min(limit, MAX_PAGE)", "limit"),
 (V, "V17 emits on accepted (appealable) instead of finalized", 'emit(on="finalized")', 'emit(on="accepted")'),
 (V, "V19 republish without RECORDED check", "        if self.status.get(snapshot_id, \"\") != \"RECORDED\":\n            raise _err(\"EXPECTED\", \"snapshot not recorded\")\n", ""),
 (V, "V20 no emission after record", "        if self.ledger_set:\n            self._emit_registration(snapshot_id, record)\n", ""),
 (V, "V21 label bonus: derived groups penalised again", "        + 10 * len(quality[\"unsourced_groups\"])\n    )", "        + 10 * len(quality[\"unsourced_groups\"])\n        + 5 * len(quality[\"derived_groups\"])\n    )"),
 # ---- verdict contract (P2 hardening)
 (V, "V22 modes not frozen at submit", "        self.snap_modes[sid] = json.dumps(self._modes(), sort_keys=True, separators=(\",\", \":\"))\n", ""),
 (V, "V23 analyze reads LIVE modes", "        modes = self._frozen_modes(snapshot_id)\n        layers = {}", "        modes = self._modes()\n        layers = {}"),
 (V, "V24 caution layers do not bound conviction", "        cap = min(cap_structure, cap_layers)", "        cap = cap_structure"),
 (V, "V25 inconclusive caution layer counted", " if lr[\"kind\"] == \"caution\" and not lr[\"inconclusive\"]]", " if lr[\"kind\"] == \"caution\"]"),
 (V, "V26 no per-sender open cap", "        if open_n >= int(self.max_open):\n            raise _err(\"EXPECTED\", \"too many open snapshots for this sender\")\n", ""),
 (V, "V27 open slot never released", "        self.open_count[submitter] = u256(max(0, int(self.open_count.get(submitter, u256(0))) - 1))\n", ""),
 (V, "V28 republish unlimited", "        if used >= MAX_REPUBLISH:\n            raise _err(\"EXPECTED\", \"republish limit reached\")\n", ""),
 (V, "V29 pause never expires", "        if int(self.paused_until) > int(self._tx_time().timestamp()):", "        if int(self.paused_until) > 0:"),
 (V, "V30 pause length unbounded", "        if pause_hours < 0 or pause_hours > MAX_PAUSE_HOURS:", "        if pause_hours < 0:"),
 (V, "V31 anyone can accept ownership", "        if not self.has_pending_owner or gl.message.sender_address != self.pending_owner:", "        if not self.has_pending_owner:"),
 (V, "V32 anyone can propose an owner", "    def propose_owner(self, new_owner: Address) -> None:\n        if gl.message.sender_address != self.owner:\n            raise _err(\"EXPECTED\", \"unauthorized: owner only\")\n", "    def propose_owner(self, new_owner: Address) -> None:\n"),
 (V, "V33 ledger changes unlimited", "        if len(self.ledger_history) >= MAX_LEDGER_CHANGES:\n            raise _err(\"EXPECTED\", \"ledger change limit reached\")\n", ""),
 (V, "V34 emits observed time as the verdict time (hindsight)", "int(record[\"horizon_days\"]), record[\"analyzed_at\"], record[\"observed_at\"],", "int(record[\"horizon_days\"]), record[\"observed_at\"], record[\"observed_at\"],"),
 (V, "V35 emits a wrong submitter to the ledger", "            sid, record[\"submitter\"], record[\"bounty_ref\"]", "            sid, \"0x\" + \"0\" * 40, record[\"bounty_ref\"]"),
 (V, "V36 asserted price scaled wrongly", "int(round(snapshot[\"price\"][\"current\"] * E8))", "int(round(snapshot[\"price\"][\"current\"] * 100))"),
 # ---- layers
 (V, "Y01 final skips the 'layer analyzed' requirement", "                if stored == \"\":\n                    raise _err(\"EXPECTED\", \"layer %s not analyzed yet (run analyze_layer)\" % layer)\n", "                if stored == \"\":\n                    layers[layer] = arith_layer(layer, snapshot)\n                    continue\n"),
 (V, "Y02 analyze_layer accepts arith-mode layers", "        if self._frozen_modes(snapshot_id).get(layer, \"arith\") != \"consensus\":\n            raise _err(\"EXPECTED\", \"layer %s is in arith mode\" % layer)\n", ""),
 (V, "Y03 layer result overwritable", "        if key in self.layer_results:\n            raise _err(\"EXPECTED\", \"layer already analyzed; layer results are immutable\")\n", ""),
 (V, "Y04 layer tolerance far too wide", "LAYER_SCORE_TOL = 20\n", "LAYER_SCORE_TOL = 80\n"),
 (V, "Y05 caution layer keeps a directional score", "    score = 0 if kind == \"caution\" else _clip_int(score, -100, 100)", "    score = _clip_int(score, -100, 100)"),
 (V, "Y06 stance band collapsed", "STANCE_BAND = 15\n", "STANCE_BAND = 1\n"),
 (V, "Y07 layer drivers not grounded", "        if isinstance(item, str) and item in allowed and item not in drivers:", "        if isinstance(item, str):"),
 (V, "Y08 layer validator ignores inconclusive mismatch", "    if leader[\"inconclusive\"] != mine[\"inconclusive\"]:\n        return False\n", ""),
 (V, "Y09 set_layer_mode open to anyone", "    def set_layer_mode(self, layer: str, mode: str) -> None:\n        if gl.message.sender_address != self.owner:\n            raise _err(\"EXPECTED\", \"unauthorized: owner only\")\n", "    def set_layer_mode(self, layer: str, mode: str) -> None:\n"),
 (V, "Y10 manipulation arithmetic drifts from engine", "        score += 15; hits.append(\"funding overheat\")", "        score += 10; hits.append(\"funding overheat\")"),
 (V, "Y11 flow weights drift from engine", "(32 * flows_b + 20 * onch_b) / 52.0", "(30 * flows_b + 22 * onch_b) / 52.0"),
 (V, "Y12 missing inputs treated as a neutral reading", "make_layer(layer, \"arith\", 0, 50, True, [], \"inconclusive: missing", "make_layer(layer, \"arith\", 0, 50, False, [], \"inconclusive: missing"),
 (V, "Y13 record omits layers", "            \"layers\": layers,\n", ""),
 (V, "Y14 layers can still run after RECORDED", "        if state != \"SUBMITTED\":\n            raise _err(\"EXPECTED\", \"snapshot is not in SUBMITTED state\")\n", ""),
 (V, "Y15 final prompt ignores the layers", "        prompt = build_prompt(snapshot, quality, layers)", "        prompt = build_prompt(snapshot, quality, {})"),
 (V, "Y16 layer prompt leaks all groups", "    out = {g: snapshot[g] for g in LAYER_GROUPS[layer] if g in snapshot}", "    out = {g: snapshot[g] for g in GROUPS if g in snapshot}"),
 (V, "Y17 layer failure poisons stored state", "        out = gl.vm.run_nondet_unsafe(leader_fn, validator_fn)\n        result = consensus_layer(layer, out, prior)", "        self.layer_results[key] = \"{}\"\n        out = gl.vm.run_nondet_unsafe(leader_fn, validator_fn)\n        result = consensus_layer(layer, out, prior)"),
 # ---- ledger
 (L, "L01 register without sender check", "        if gl.message.sender_address != self.verdict_contract:\n            raise _err(\"EXPECTED\", \"unauthorized: only the verdict contract may register\")\n", ""),
 (L, "L02 re-delivery overwrites", "        if self.status.get(snapshot_id, \"\") != \"\":\n            return\n", ""),
 (L, "L03 resolve ignores horizon", "        if int(now.timestamp()) < entry[\"resolve_not_before_s\"]:\n            raise _err(\"EXPECTED\", \"horizon not reached\")\n", ""),
 (L, "L04 validator ignores the observation price", "all(theirs[k] == mine[k] for k in PRICE_KEYS)", "all(theirs[k] == mine[k] for k in (\"ref_e8\", \"end_e8\"))"),
 (L, "L05 validator trusts leader failure", "    if not isinstance(leaders_res, gl.vm.Return):\n        return False\n    try:\n        mine = leader_fn()", "    if not isinstance(leaders_res, gl.vm.Return):\n        return True\n    try:\n        mine = leader_fn()"),
 (L, "L06 resolution overwrite allowed", "        if state == \"RESOLVED\":\n            raise _err(\"EXPECTED\", \"already resolved; resolutions are immutable\")\n", ""),
 (L, "L07 HTTP status ignored", "    if status != 200:\n        raise _err(\"EXTERNAL\", \"price source HTTP status %s\" % status)\n", ""),
 (L, "L08 returned candle hour not checked", "    if isinstance(open_time, bool) or open_time != expected_start_ms:\n        raise _err(\"EXTERNAL\", \"returned candle is not the requested hour\")\n", ""),
 (L, "L09 inconclusive scored as miss", "    if stance == \"inconclusive\":\n        return \"abstain\"\n", ""),
 (L, "L10 floor instead of truncation", "    return mag if num >= 0 else -mag", "    return num // ref_e8"),
 (L, "L11 scorecard counters not updated on resolve", "        for prefix in (\"\", sub):\n            self._bump(prefix + \"resolved\")\n            self._bump(prefix + (\"excluded\" if not evidence_ok else \"%s:%s\" % (entry[\"stance\"], result)))\n", ""),
 (L, "L12 unbounded id page", "min(limit, MAX_PAGE)", "limit"),
 (L, "L13 float price parsing allowed", "    if not isinstance(text, str) or not _PRICE_RE.match(text):", "    text = str(text)\n    if not _PRICE_RE.match(text):"),
 (L, "L14 graded window starts at the asserted observation (hindsight)", "        ref_ms = next_hour_start_ms(analyzed_s)", "        ref_ms = hour_start_ms(int(observed.timestamp()))"),
 (L, "L15 window starts in the verdict's own hour", "    return (ts_seconds // 3600 + 1) * 3600 * 1000", "    return (ts_seconds // 3600) * 3600 * 1000"),
 (L, "L16 registrations not counted", "        self._bump(\"registered\")\n", ""),
 (L, "L17 per-submitter registrations not counted", "        self._bump(\"s:%s:registered\" % entry[\"submitter\"])\n", ""),
 (L, "L18 evidence check disabled", "        evidence_ok = deviation <= max_dev", "        evidence_ok = True"),
 (L, "L19 deviation boundary off by one", "        evidence_ok = deviation <= max_dev", "        evidence_ok = deviation < max_dev"),
 (L, "L20 excluded entries still scored", "        result = score(entry[\"stance\"], realized) if evidence_ok else \"excluded\"", "        result = score(entry[\"stance\"], realized)"),
 (L, "L21 unresolved always zero", "\"unresolved\": registered - resolved", "\"unresolved\": 0"),
 (L, "L22 due page includes resolved entries", "            if self.status.get(sid, \"\") == \"REGISTERED\" and now_s >=", "            if now_s >="),
 (L, "L23 submitter scorecard returns the global one", "        return self._scorecard(\"s:%s:\" % submitter.lower())", "        return self._scorecard(\"\")"),
 (L, "L24 submitter case not normalised", "\"submitter\": submitter.lower()", "\"submitter\": submitter"),
 (L, "L25 deviation measured against the open only", "        deviation = evidence_deviation_bps(entry[\"asserted_price_e8\"], prices[\"obs_hi_e8\"], prices[\"obs_lo_e8\"])", "        deviation = abs(entry[\"asserted_price_e8\"] - prices[\"obs_e8\"]) * 10000 // prices[\"obs_e8\"]"),
 (L, "L26 observation-lag sanity removed", "        if lag < -300 or lag > MAX_OBSERVATION_LAG_S:\n            raise _err(\"EXPECTED\", \"observed_at inconsistent with analyzed_at\")\n", ""),
 (L, "L27 asserted-price upper bound removed", "MAX_ASSERTED_E8 = 10 ** 15", "MAX_ASSERTED_E8 = 10 ** 30"),
 (V, "V37 int addresses rejected", "    if isinstance(value, int):\n        if value < 0 or value >= 1 << 160:", "    if False:\n        if value < 0 or value >= 1 << 160:"),
 (V, "V38 set_ledger stores the raw argument", "        ledger_address = _to_address(ledger_address)\n", ""),
 (V, "V39 propose_owner stores the raw argument", "        new_owner = _to_address(new_owner)\n", ""),
 (V, "V40 booleans accepted as addresses", "    if isinstance(value, bool):\n        raise _err(\"EXPECTED\", \"invalid address\")\n", ""),
 (V, "V41 address range not checked", "        if value < 0 or value >= 1 << 160:", "        if False:"),
 (L, "L28 int addresses rejected", "    if isinstance(value, int):\n        if value < 0 or value >= 1 << 160:", "    if False:\n        if value < 0 or value >= 1 << 160:"),
 (L, "L29 constructor stores the raw argument (the real Studio crash)", "        verdict_contract = _to_address(verdict_contract)\n", ""),
 (L, "L30 booleans accepted as addresses", "    if isinstance(value, bool):\n        raise _err(\"EXPECTED\", \"invalid address\")\n", ""),
 (L, "L31 address range not checked", "        if value < 0 or value >= 1 << 160:", "        if False:"),

 # ---- review findings F1-F8 (R = review)
 (V, "R01 price lower bound back to zero (F1)", "\"current\": (\"num\", 0.01, 10_000_000.0),", "\"current\": (\"num\", 0.0, 10_000_000.0),"),
 (V, "R02 release does not free the slot (F2)", "        self.status[snapshot_id] = \"RELEASED\"\n        self.open_count[submitter] = u256(max(0, int(self.open_count.get(submitter, u256(0))) - 1))\n", "        self.status[snapshot_id] = \"RELEASED\"\n"),
 (V, "R03 anyone may release a fresh snapshot (F2)", "            if age <= self._max_age_for(snapshot_id):\n                raise _err(\"EXPECTED\", \"unauthorized: only the submitter may release a fresh snapshot\")\n", "            pass\n"),
 (V, "R04 analyze_layer open to any sender (F3)", "        self._require_submitter(snapshot_id)\n        if self._frozen_modes", "        if self._frozen_modes"),
 (V, "R05 max age not frozen per snapshot (F4)", "        return frozen if frozen > 0 else int(self.max_age_s)", "        return int(self.max_age_s)"),
 (V, "R06 pause blocks analysis again (F4)", "    def analyze(self, snapshot_id: str) -> str:\n        state = self.status.get(snapshot_id, \"\")", "    def analyze(self, snapshot_id: str) -> str:\n        self._require_active()\n        state = self.status.get(snapshot_id, \"\")"),
 (L, "R07 removed subscribers lose promised outcomes (F5)", "        raw = self.sub_at_reg.get(sid, \"\")\n        out = list(json.loads(raw)) if raw else []", "        out = []"),
 (L, "R08 candle consistency check removed (F7)", "    if not (low_e8 <= open_e8 <= high_e8):\n        raise _err(\"EXTERNAL\", \"inconsistent candle (open outside high/low)\")\n", ""),
 (L, "R09 validators ignore the candle range (F7)", "all(theirs[k] == mine[k] for k in PRICE_KEYS)", "all(theirs[k] == mine[k] for k in (\"obs_e8\", \"ref_e8\", \"end_e8\"))"),
 (L, "R10 now_s not validated (F8)", "        if isinstance(now_s, bool) or not isinstance(now_s, int) or now_s < 0:\n            raise _err(\"EXPECTED\", \"invalid now_s\")\n", ""),
 (B, "R11 inconclusive waits for resolution (F6)", "        if stance == \"inconclusive\":", "        if False:"),
 (B, "R12 forfeited bond paid to the client (F4)", "            self._credit(b[\"client\"], b[\"reward\"])\n            self.forfeited_total = u256(int(self.forfeited_total) + b[\"bond\"])", "            self._credit(b[\"client\"], b[\"reward\"] + b[\"bond\"])"),
 (B, "R13 ignore reasons not recorded (F6)", "        self.ignored[sid] = reason", "        pass"),
 (B, "R14 strangers can write ignore records (F6)", "        if not isinstance(submitter, str) or b[\"analyst\"] == \"\" or submitter.lower() != b[\"analyst\"]:\n            return", "        if not isinstance(submitter, str):\n            return"),
 (B, "R15 solvency ignores forfeited funds (F4)", "        owed = int(self.claimable_total) + int(self.locked_total) + int(self.forfeited_total)", "        owed = int(self.claimable_total) + int(self.locked_total)"),

 # ---- bounty money rules (B)
 (B, 'B01 hit pays the client instead of the analyst', 'self._credit(b["analyst"], reward + bond)\n        elif', 'self._credit(b["client"], reward + bond)\n        elif'),
 (B, 'B02 a neutral hit pays the analyst', 'if result == "hit" and stance in ("bullish", "bearish"):', 'if result == "hit":'),
 (B, 'B03 a miss pays the analyst', 'elif result in ("miss", "excluded"):\n            self._credit(b["client"], reward + bond)', 'elif result in ("miss", "excluded"):\n            self._credit(b["analyst"], reward + bond)'),
 (B, 'B04 excluded is treated as abstain', 'elif result in ("miss", "excluded"):', 'elif result in ("miss",):'),
 (B, 'B05 abstain loses the analyst bond', '            self._credit(b["analyst"], bond)\n            self._credit(b["client"], reward)\n        self._unlock', '            self._credit(b["client"], reward)\n        self._unlock'),
 (B, 'B06 settlement does not unlock the funds', '        self._unlock(reward + bond)\n        b["status"] = "SETTLED"', '        b["status"] = "SETTLED"'),
 (B, 'B07 anyone can cancel a bounty', 'if self._sender() != b["client"]:', 'if False:'),
 (B, 'B08 cancel works on a committed bounty', '        if b["status"] != "OPEN":\n            raise _err("EXPECTED", "bounty is not open")\n        b["status"] = "CANCELLED"', '        b["status"] = "CANCELLED"'),
 (B, 'B09 commit window closes one second early', 'if now > b["commit_deadline_s"]:\n            self._reject("commit_window_closed")', 'if now >= b["commit_deadline_s"]:\n            self._reject("commit_window_closed")'),
 (B, 'B10 the client can commit to its own bounty', 'if sender == b["client"]:', 'if False:'),
 (B, 'B11 a larger bond is accepted', 'if int(gl.message.value) != b["reward"]:', 'if int(gl.message.value) < b["reward"]:'),
 (B, 'B12 commit does not lock the bond', '        self._lock(b["bond"])', '        pass'),
 (B, 'B13 delivery before the commit is accepted', 'analyzed_ts < b["committed_at_s"] or analyzed_ts > b["deliver_deadline_s"]', 'analyzed_ts > b["deliver_deadline_s"]'),
 (B, 'B14 the delivery deadline is exclusive', 'analyzed_ts > b["deliver_deadline_s"]:\n            self._ignore', 'analyzed_ts >= b["deliver_deadline_s"]:\n            self._ignore'),
 (B, 'B15 horizon is not checked on delivery', 'if horizon_days != b["horizon_days"]:', 'if False:'),
 (B, 'B16 min conviction compared the wrong way', 'conviction < b["min_conviction"]', 'conviction > b["min_conviction"]'),
 (B, 'B17 any submitter can deliver', 'if not isinstance(submitter, str) or b["analyst"] == "" or submitter.lower() != b["analyst"]:', 'if not isinstance(submitter, str) or b["analyst"] == "":'),
 (B, 'B18 a held resolution is ignored on delivery', 'elif pending != "":', 'elif False:'),
 (B, 'B19 an open bounty expires before its commit deadline', 'if status == "OPEN" and now > b["commit_deadline_s"]:', 'if status == "OPEN":'),
 (B, 'B20 no arrival grace before a no-delivery expiry', 'now > b["deliver_deadline_s"] + ARRIVAL_GRACE_S', 'now > b["deliver_deadline_s"]'),
 (B, 'B21 a no-resolution expiry loses the analyst bond', '            self._credit(b["analyst"], b["bond"])\n            self._credit(b["client"], b["reward"])\n        else:', '            self._credit(b["client"], b["reward"])\n        else:'),
 (B, 'B22 withdraw does not zero the balance', '        self.claimable[who] = u256(0)\n        self.claimable_total', '        self.claimable_total'),
 (B, 'B23 withdraw keeps claimable_total', '        self.claimable_total = u256(int(self.claimable_total) - amount)\n        _Recipient', '        _Recipient'),
 (B, 'B24 anyone can call the ledger hooks', 'if gl.message.sender_address != self.ledger:', 'if False:'),
 (B, 'B25 solvency always ok', '"ok": balance >= owed', '"ok": True'),
 (B, 'B26 a late resolution settles a settled bounty', '            if b["status"] == "DELIVERED":\n                self._settle(b, result, stance)', '            if True:\n                self._settle(b, result, stance)'),
 (B, 'B27 a rejected call keeps the value', '        self._credit(who, int(gl.message.value))\n        self.rejections[who] = reason', '        self.rejections[who] = reason'),
 (B, 'B28 the rejection reason is not stored', '        self.rejections[who] = reason', '        pass'),
 (B, 'B29 unaccounted is always zero', '"unaccounted": max(0, balance - owed)', '"unaccounted": 0'),
 (B, 'B30 create does not lock the reward', '        self._lock(reward)\n        self.rejections[b["client"]] = ""', '        self.rejections[b["client"]] = ""'),
 (B, 'B31 a successful commit keeps the old rejection', '        self.rejections[sender] = ""\n        return True', '        return True'),
]
ONLY = tuple(a for a in sys.argv[1:] if not a.startswith('-'))  # e.g. python scripts/mutate.py L Y
survivors = []
for f, name, old, new in M:
    if ONLY and not name.startswith(ONLY):
        continue
    d = "/tmp/_mut"; shutil.rmtree(d, ignore_errors=True)
    shutil.copytree(SRC, d, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"))
    p = os.path.join(d, f); t = open(p).read()
    if old not in t:
        print(f"{name:55s} -> PATTERN NOT FOUND"); survivors.append(name); continue
    open(p, "w").write(t.replace(old, new, 1))
    targets = ["tests/direct/test_bounty.py", "tests/direct/test_bounty_fuzz.py", "tests/direct/test_review_findings.py"] if f == "contracts/eth_analyst_bounty.py" else ["tests/direct"]
    r = subprocess.run([sys.executable, "-m", "pytest"] + targets + ["-q", "-x", "-p", "no:cacheprovider"], cwd=d, capture_output=True, text=True)
    last = [l for l in r.stdout.splitlines() if "passed" in l or "failed" in l or "error" in l][-1:]
    killed = r.returncode != 0
    print(f"{name:55s} -> {'KILLED' if killed else 'SURVIVED'}  {last[0].strip() if last else ''}")
    if not killed: survivors.append(name)
print("\nSURVIVORS:", survivors or "none")
sys.exit(1 if survivors else 0)
