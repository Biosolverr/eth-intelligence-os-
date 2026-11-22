# Studio runbook: manual check of every method of all three contracts

How to read a step. Every step names: **Account** (who signs), **Contract**, **Method**, the **Fields** to type (in order), and **Expect**.
`(view)` = read call, no transaction. Anything that differs from **Expect** is a finding: write the exact text in the **Result** line.
Studio has account balances and no gas, so switching accounts costs nothing. Wait for each write to reach FINALIZED (or at least ACCEPTED) before reading its effect; consensus steps take 1-3 minutes each.

---

## 0. Preparation

**Accounts (switch in Studio):**
- `ACC1` = OWNER of every contract, CLIENT of the bounties, default submitter.
- `ACC2` = ANALYST (bounty), second user.
- `ACC3` = STRANGER (must be refused everywhere it should be).

**Write down the addresses as you create them (fill in):**
- ACC1 = `0x________`   ACC2 = `0x________`   ACC3 = `0x________`
- V (verdict) = `0x________`   L (ledger) = `0x________`   B (bounty) = `0x________`   L2 (test ledger, part E) = `0x________`

**Value amount R:** pick one small number for the Value field (for example `1`) and use the SAME number everywhere a step says "value = R". Note which unit the Studio field uses.

**Snapshots.** Each snapshot is one line of JSON from this command, run in a normal `cmd` window in the repo root (NOT PowerShell, it changes the encoding):
```
python scripts/make_snapshot.py > snap.json
```
Open `snap.json`, copy the whole line. A snapshot is valid for 24 hours counted from its own `observed_at` (the PC clock must be correct) and each one needs a DIFFERENT id: for snapshot number n change `"rsi_1d"` inside `"price"` to a new number (S1: 41, S2: 42, S3: 43, and so on). Generate a fresh file right before using it.
- **S1** = unchanged, rsi_1d 41.
- **SB1** = for bounty 1: in `"meta"` set `"horizon_days": 7` and add `"bounty_ref": "1"`; rsi_1d 51.
- **SB2** = for bounty 2: in `"meta"` keep `"horizon_days": 30` and add `"bounty_ref": "2"`; rsi_1d 52.

Time-gated checks are collected in part F; start the bounties early (part D) so the waiting overlaps.

---

## A. Deploy and wire

---

### A1. Deploy the verdict contract
- Account: ACC1
- Contract file: `eth_intelligence.py` (EthIntelligence)
- Constructor fields: none
- Expect: deployed. Write the address into V.
- Result: ________

---

### A2. Deploy the ledger
- Account: ACC1
- Contract file: `eth_outcome_ledger.py` (EthOutcomeLedger)
- Constructor fields, in order:
  - `verdict_contract` = V
  - `price_url_template` = `https://data-api.binance.vision/api/v3/klines?symbol=ETHUSDT&interval=1h&startTime={start_ms}&limit=1`
  - `flat_band_bps` = `300`
  - `max_price_deviation_bps` = `300`
- Expect: deployed. Write the address into L.
- NOTE: use the `data-api.binance.vision` host exactly as written. `api.binance.com` answered `HTTP status 451` (region block) to the hosted-Studio validators in the first live resolve attempt. The host is fixed at deploy time and cannot be changed later.
- Result: ________

---

### A3. Point the verdict contract at the ledger
- Account: ACC1
- Contract: V
- Method: `set_ledger`
- Fields: `ledger_address` = L
- Expect: success.
- Then (view) V `get_ledger_history()`: a list containing L.
- Then (view) V `get_policy()`: `ledger_set` = true, `max_age_s` = 86400, `max_open_per_sender` = 20, `paused_until_s` = 0, `pending_owner` empty.
- Result: ________

---

### A4. Deploy the bounty
- Account: ACC1
- Contract file: `eth_analyst_bounty.py` (AnalystBounty)
- Constructor fields: `ledger` = L
- Expect: deployed. Write the address into B.
- Then (view) B `get_config()`: `ledger` = L, `min_horizon_days` 7, `max_horizon_days` 90, `min_delivery_window_s` 3600, `max_delivery_window_s` 172800, `arrival_grace_s` 259200, `resolve_grace_s` 1209600.
- Then (view) B `get_solvency()`: `balance` 0, `locked_total` 0, `claimable_total` 0, `forfeited_total` 0, `ok` true.
- Then (view) B `get_bounty_count()`: 0.
- Result: ________

---

### A5. Subscribe the bounty to the ledger
- Account: ACC1
- Contract: L
- Method: `add_subscriber`
- Fields: `subscriber` = B
- Expect: success. (view) L `get_subscribers()` = [B]; (view) L `get_policy()`: `subscribers` = 1, `owner` = ACC1.
- Result: ________

---

### A6. Strangers cannot manage subscribers or policy
- Account: ACC2, Contract: L, Method: `add_subscriber`, Field: `subscriber` = ACC3
- Expect: fails, message contains `owner only`.
- Account: ACC2, Contract: V, Method: `set_policy`, Fields: `max_age_s` = 86400, `pause_hours` = 0, `max_open_per_sender` = 20
- Expect: fails, `owner only`.
- Result: ________

---

## B. Verdict contract (V)

---

### B1. Initial reads (all view)
- V `get_id_count()` = 0.
- V `get_layer_modes()`: `macro` and `manipulation` = `consensus`; `quant`, `flow`, `risk` = `arith`.
- Result: ________

---

### B2. Validate a snapshot (view)
- Account: any
- Contract: V
- Method: `validate_snapshot`
- Fields: `snapshot_json` = S1 (whole line)
- Expect: a success answer. KNOWN QUIRK: on the hosted Studio this view can fail with `RLP string ends with N superfluous bytes` because the argument is large. If it does, write "quirk" in Result and continue; it is not a contract bug.
- Result: ________

---

### B3. Submit S1
- Account: ACC1
- Contract: V
- Method: `submit_snapshot`
- Fields: `snapshot_json` = S1
- Expect: success, returns a 64-hex id.
- Then (view) V `get_ids_page(0, 10)` -> [one id]. Write it down as SID1 (plain 64 hex characters, no `0x`): `________`
- (view) V `get_status(SID1)` = `SUBMITTED`.
- (view) V `get_submitter(SID1)` = ACC1 address.
- (view) V `get_snapshot(SID1)`: the stored canonical JSON.
- (view) V `get_snapshot_modes(SID1)`: same modes as B1.
- Result: ________

---

### B4. Duplicate submit is refused
- Account: ACC1, Contract: V, Method: `submit_snapshot`, Fields: `snapshot_json` = S1 (the same text)
- Expect: fails, message starts `duplicate snapshot`.
- Result: ________

---

### B5. A stranger cannot analyze someone else's snapshot
- Account: ACC3, Contract: V, Method: `analyze`, Fields: `snapshot_id` = SID1
- Expect: fails, `only the submitter`.
- Account: ACC3, Contract: V, Method: `analyze_layer`, Fields: `snapshot_id` = SID1, `layer` = `macro`
- Expect: fails, `only the submitter`.
- (view) V `get_status(SID1)` still `SUBMITTED`.
- Result: ________

---

### B6. The verdict needs the consensus layers first
- Account: ACC1, Contract: V, Method: `analyze`, Fields: `snapshot_id` = SID1
- Expect: fails, `layer macro not analyzed yet (run analyze_layer)`.
- Account: ACC1, Contract: V, Method: `analyze_layer`, Fields: `snapshot_id` = SID1, `layer` = `quant`
- Expect: fails, `layer quant is in arith mode`.
- Account: ACC1, Contract: V, Method: `analyze_layer`, Fields: `snapshot_id` = SID1, `layer` = `bogus`
- Expect: fails, `unknown layer`.
- (view) V `preview_layers(SID1)`: JSON with the arithmetic readings of the five layers.
- Result: ________

---

### B7. Run the two consensus layers
- Account: ACC1, Contract: V, Method: `analyze_layer`, Fields: `snapshot_id` = SID1, `layer` = `macro`
- Expect: success (a consensus round, 1-3 minutes). (view) V `get_layer_result(SID1, macro)`: a JSON with a stance-like reading, drivers, caution.
- Same with `layer` = `manipulation`. (view) V `get_layer_result(SID1, manipulation)`.
- Then run `analyze_layer` `macro` again.
- Expect: fails, `layer already analyzed; layer results are immutable`.
- Result: ________

---

### B8. Record the verdict
- Account: ACC1, Contract: V, Method: `analyze`, Fields: `snapshot_id` = SID1
- Expect: success (a consensus round).
- (view) V `get_status(SID1)` = `RECORDED`.
- (view) V `get_record(SID1)`: JSON with `stance` (bullish/bearish/neutral/inconclusive), `conviction` (0-100), `risk_level` (low/moderate/elevated/high), `submitter` and `analyst` both ACC1, `asserted_price_e8` = the snapshot price x 100000000.
- (view) V `get_layer_result(SID1, quant)`, `flow`, `risk`: an EMPTY answer (Studio shows nothing). Only consensus layers (macro, manipulation) are stored there; the arithmetic layers live inside `get_record(SID1)` under `layers`.
- Result: ________  (write the stance: ________)

---

### B9. Recorded results are immutable, slots and release
- Account: ACC1, Contract: V, Method: `analyze`, Fields: SID1
- Expect: fails, `already recorded; results are immutable`.
- Account: ACC1, Contract: V, Method: `release_snapshot`, Fields: SID1
- Expect: fails, `not in SUBMITTED state`.
- Account: ACC1, Contract: V, Method: `release_snapshot`, Fields: `snapshot_id` = `aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`
- Expect: fails, `unknown snapshot`.
- Result: ________

---

### B10. Republish to the ledger (anyone, at most 3 times)
- Account: ACC3, Contract: V, Method: `republish`, Fields: `snapshot_id` = SID1
- Expect: success. Repeat two more times (3 in total).
- A 4th time: fails, `republish limit reached`.
- (This only re-sends the same data; the ledger ignores the duplicate. The effect is checked in part C.)
- Result: ________

---

### B11. Release a snapshot nobody will analyze
- Account: ACC1, Contract: V, Method: `submit_snapshot`, Fields: S2 (rsi_1d 42) -> SID2 (read it with `get_ids_page(0, 10)`).
- Account: ACC3, Contract: V, Method: `release_snapshot`, Fields: SID2
- Expect: fails, `only the submitter may release a fresh snapshot`.
- Account: ACC1, Contract: V, Method: `release_snapshot`, Fields: SID2
- Expect: success. (view) `get_status(SID2)` = `RELEASED`.
- Account: ACC1, Contract: V, Method: `analyze`, Fields: SID2
- Expect: fails, `not in SUBMITTED state`.
- Result: ________

---

### B12. The per-sender open cap
- Account: ACC2, Contract: V, Method: `set_policy`: fails with `owner only` (already seen in A6, skip if done).
- Account: ACC1, Contract: V, Method: `set_policy`, Fields: `max_age_s` = 86400, `pause_hours` = 0, `max_open_per_sender` = 1
- Expect: success. (view) `get_policy()`: `max_open_per_sender` = 1.
- Account: ACC1, `submit_snapshot`, S3 (rsi_1d 43): success -> SID3.
- Account: ACC1, `submit_snapshot`, S4 (rsi_1d 44): fails, `too many open snapshots for this sender`.
- Account: ACC1, `release_snapshot`, SID3: success. Then `submit_snapshot` S4 succeeds -> SID4; `release_snapshot` SID4.
- Restore: `set_policy` with 86400, 0, 20.
- Result: ________

---

### B13. Pause stops new intake but not submitted work
- Account: ACC1, `submit_snapshot`, S5 (rsi_1d 45): success -> SID5.
- Account: ACC1, `set_policy`, Fields: `max_age_s` = 86400, `pause_hours` = 1, `max_open_per_sender` = 20
- Expect: success. (view) `get_policy()`: `paused_until_s` is about one hour in the future (unix seconds).
- Account: ACC1, `submit_snapshot`, S6 (rsi_1d 46): fails, `contract is paused`.
- Account: ACC1, `analyze_layer`, Fields: SID5, `macro`: SUCCESS even while paused.
- Account: ACC1, `set_policy`, Fields: 86400, 0, 20 (lifts the pause). (view) `paused_until_s` = 0.
- Account: ACC1, `release_snapshot`, SID5 (free the slot).
- Also: `set_policy` with `pause_hours` = 169 fails, `pause_hours out of bounds`; `max_age_s` = 100 fails, `max_age_s out of bounds` (the minimum is 300).
- Result: ________

---

### B14. The freshness rule is frozen per snapshot (optional, about 10 minutes)
- Account: ACC1, `submit_snapshot`, S7 (rsi_1d 47, FRESH): success -> SID7.
- Account: ACC1, `set_policy`, Fields: 300, 0, 20.
- Run `analyze_layer` macro, `analyze_layer` manipulation and `analyze` on SID7 (these take more than 5 minutes in total).
- Expect: all succeed although the snapshot is older than 300 s: it keeps the 86400 s rule it was submitted under.
- Then `submit_snapshot` with a snapshot generated more than 6 minutes ago: fails, `stale snapshot`.
- Restore: `set_policy` 86400, 0, 20.
- Result: ________

---

### B15. Layer modes
- Account: ACC3, `set_layer_mode`, Fields: `layer` = `quant`, `mode` = `consensus`: fails, `owner only`.
- Account: ACC1, `set_layer_mode`, Fields: `layer` = `bogus`, `mode` = `arith`: fails, `unknown layer`.
- Account: ACC1, `set_layer_mode`, Fields: `layer` = `quant`, `mode` = `x`: fails, `mode must be one of`.
- Account: ACC1, `submit_snapshot`, S8 (rsi_1d 48) -> SID8. Then `set_layer_mode` `quant` / `consensus`: success; (view) `get_layer_modes()`: quant = consensus; (view) `get_snapshot_modes(SID8)`: quant still `arith` (frozen at submit); `analyze_layer` SID8 `quant` fails, `arith mode`.
- Restore: `set_layer_mode` `quant` / `arith`. `release_snapshot` SID8.
- Result: ________

---

### B16. Two-step ownership
- Account: ACC1, `propose_owner`, Fields: `new_owner` = ACC2. (view) `get_policy()`: `pending_owner` = ACC2.
- Account: ACC3, `accept_ownership`: fails, `not the pending owner`.
- Account: ACC2, `accept_ownership`: success.
- Account: ACC1, `set_policy` 86400, 0, 20: fails, `owner only`.
- Give it back: Account: ACC2, `propose_owner`, `new_owner` = ACC1; Account: ACC1, `accept_ownership`. (view) `get_policy()`: `pending_owner` empty again.
- Result: ________

---

### B17. Re-pointing the ledger
- Account: ACC3, `set_ledger`, Fields: `ledger_address` = L: fails, `owner only`.
- Account: ACC1, `set_ledger`, Fields: `ledger_address` = L: success. (view) `get_ledger_history()`: now two entries (limit is 5 changes).
- Result: ________

---

## C. Ledger (L), with the verdict from B8

Wait until the verdict transaction of B8 is FINALIZED, then a few minutes more for the child message.

---

### C1. The verdict arrived
- (view) L `get_status(SID1)` = `REGISTERED`.
- (view) L `get_entry(SID1)`: JSON; `submitter` = ACC1 (lowercase), `stance`/`conviction`/`risk_level` equal the record from B8, `horizon_days` = 30, `bounty_ref` empty, `ref_ms` is the first full hour after `analyzed_at`, `target_ms` = `ref_ms` + 30 days, `resolve_not_before_s` = `target_ms`/1000 + 7200.
- (view) L `get_scorecard()`: `registered` 1, `resolved` 0, `unresolved` 1, `excluded` 0.
- (view) L `get_submitter_scorecard(ACC1 address)`: `registered` 1.
- Result: ________

---

### C2. Due list and too-early resolve
- (view) L `get_unresolved_due_page(0, 10, 1)`: empty list (time 1 is before everything).
- (view) L `get_unresolved_due_page(0, 10, 9999999999)`: contains SID1 (pretend it is the year 2286; this only tests the view).
- (view) L `get_unresolved_due_page(0, 10, -1)`: fails, `invalid now_s`.
- Account: ACC3, L `resolve`, Fields: `snapshot_id` = SID1: fails, `horizon not reached`.
- (view) L `get_resolution(SID1)`: empty.
- Result: ________

---

### C3. Rebroadcast and subscriber management
- Account: ACC3, L `rebroadcast`, Fields: SID1: success (at most 3 times per snapshot; a 4th fails `rebroadcast limit reached`).
- (view) L `get_subscriber_log()`: shows the subscription events.
- Account: ACC3, L `remove_subscriber`, Fields: `subscriber` = B: fails, `owner only`.
- Account: ACC1, L `add_subscriber`, Fields: `subscriber` = B: fails, `already subscribed`.
- Account: ACC1, L `register`, Fields: any: fails, `only the verdict contract may register` (the ledger accepts registrations only from V). Use: `snapshot_id` = `bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb`, `submitter` = ACC1, `bounty_ref` = empty, `stance` = `bullish`, `conviction` = 60, `risk_level` = `moderate`, `horizon_days` = 1, `analyzed_at` = `2026-10-01T12:30:00Z`, `observed_at` = `2026-10-01T12:20:00Z`, `asserted_price_e8` = 100000000.
- Result: ________

---

## D. Bounty (B)

Roles: ACC1 = client, ACC2 = analyst, ACC3 = stranger. Bounty ids are 0, 1, 2, 3 in creation order.

---

### D1. Create and cancel (money round trip)
- Account: ACC1, Contract: B, Method: `create_bounty`, Fields: `horizon_days` = 7, `commit_window_s` = 3600, `delivery_window_s` = 3600, `min_conviction` = 0, value = R.
- Expect: success. (view) `get_bounty_count()` = 1; `get_bounty(0)`: `status` OPEN, `client` = ACC1, `reward` = R; `get_solvency()`: `locked_total` = R, `ok` true; Studio balance of ACC1 dropped by R.
- Account: ACC2, `cancel_bounty`, Fields: `bounty_id` = `0`: fails, `only the client`.
- Account: ACC1, `cancel_bounty`, Fields: `bounty_id` = `0`: success; `get_bounty(0)`: `CANCELLED`; `get_claimable(ACC1 address, lowercase)` = R; `get_solvency()`: `locked_total` 0, `claimable_total` R.
- Account: ACC1, `withdraw`: success; ACC1 balance back; `get_claimable(ACC1)` = 0; `get_solvency()`: `balance` 0.
- Account: ACC1, `withdraw` again: fails, `nothing to withdraw`.
- Result: ________

---

### D2. A refused call returns the money (NOT an error any more)
Since the refund redesign the payable methods never revert on bad input: the transaction ends `SUCCESS`, the return value is empty (`create_bounty`) or `false` (`commit`), nothing is created, and the attached value is credited back to you.
For each line below, afterwards run (view) B `get_rejection` with `account` = the sender in lowercase, (view) B `get_bounty_count()` (must not change), (view) B `get_claimable` for the sender (must grow by the value you sent), and then `withdraw` from that account to take the money back.
- ACC1 `create_bounty` with `horizon_days` = 6 (others valid, value R): `get_rejection` = `horizon_days_out_of_bounds`.
- ACC1 `create_bounty` with `commit_window_s` = 100: `commit_window_s_out_of_bounds`.
- ACC1 `create_bounty` with `delivery_window_s` = 200000: `delivery_window_s_out_of_bounds`.
- ACC1 `create_bounty` with `min_conviction` = 101: `min_conviction_out_of_bounds`.
- ACC1 `create_bounty` with valid fields but value = 0: `reward_too_small` (nothing to refund).
- Result: ________

---

### D3. Create the three working bounties
- Account: ACC1, `create_bounty`, Fields: 7, 3600, 3600, 0, value = R. This is bounty `1` (delivery scenario).
- Repeat once: bounty `2` (wrong-horizon, then expiry).
- Repeat once: bounty `3` (never committed).
- Write the time now: `________` (bounty 3 can be expired after one hour; bounty 2 after 3 days, see part F).
- (view) `get_bounty_count()` = 4; `get_solvency()`: `locked_total` = 3R.
- Result: ________

---

### D4. The analyst prepares snapshots BEFORE committing
- Account: ACC2, Contract: V, `submit_snapshot`, Fields: SB1 -> SIDB1; and SB2 -> SIDB2. Read ids with `get_ids_page(0, 10)` (they are the ones submitted by ACC2: check `get_submitter`).
- Result: SIDB1 = `________`  SIDB2 = `________`

---

### D5. Commit rules (refusals are refunds: check `get_rejection` and `get_claimable` of the sender afterwards, then `withdraw`)
- Account: ACC1, B `commit`, Fields: `bounty_id` = `1`, value = R: transaction `SUCCESS`, returns `false`; `get_rejection(ACC1)` = `client_cannot_commit`.
- Account: ACC2, B `commit`, Fields: `bounty_id` = `1`, value = R minus 1 (or half of R): `false`; `get_rejection(ACC2)` = `bond_must_equal_reward`.
- Account: ACC2, B `commit`, Fields: `bounty_id` = `1`, value = R: `true`. `get_rejection(ACC2)` is empty again. `get_bounty(1)`: `status` COMMITTED, `analyst` = ACC2 (lowercase), `bond` = R, `deliver_deadline_s` = commit time + 3600. `get_solvency()`: `locked_total` 4R, `unaccounted` 0.
- Account: ACC3, B `commit`, Fields: `1`, value = R: `false`; `get_rejection(ACC3)` = `bounty_not_open`.
- Account: ACC3, B `commit`, Fields: `bounty_id` = `99`, value = R: `false`; `get_rejection(ACC3)` = `unknown_bounty`.
- Account: ACC1, B `cancel_bounty`, Fields: `1`: this one carries no value and still FAILS with `bounty is not open`.
- Result: ________

---

### D6. Deliver a verdict to bounty 1 (do this within 60 minutes of D5)
- Account: ACC2, Contract: V, `analyze_layer`, Fields: SIDB1, `macro`; then `manipulation`; then `analyze`, Fields: SIDB1.
- Wait for FINALIZED plus a few minutes. (view) L `get_status(SIDB1)` = `REGISTERED`; L `get_entry(SIDB1)`: `bounty_ref` = `1`, `horizon_days` = 7.
- (view) B `get_bounty(1)`:
  - if the verdict stance is bullish, bearish or neutral: `status` DELIVERED, `sid` = SIDB1, `stance` set, `resolve_deadline_s` set;
  - if the stance is inconclusive: `status` SETTLED, `result` abstain, `get_claimable(ACC2)` = R and `get_claimable(ACC1)` = R (settled at once).
- (view) B `get_ignored(SIDB1)` = empty.
- If the status is still COMMITTED after 15 minutes: read B `get_ignored(SIDB1)` and L `get_subscriber_log()` and send me both.
- Result: ________  (stance: ________, status: ________)

---

### D7. A verdict that must be ignored (bounty 2)
- Account: ACC2, B `commit`, Fields: `2`, value = R: success.
- Within 60 minutes, Account: ACC2, V: `analyze_layer` SIDB2 `macro`, `manipulation`, then `analyze` SIDB2. (SB2 has `horizon_days` 30 but the bounty wants 7.)
- After FINALIZED plus a few minutes: (view) B `get_ignored(SIDB2)` = `horizon_mismatch`; `get_bounty(2)`: still COMMITTED.
- Result: ________

---

### D8. Early expiry is refused; an uncommitted bounty expires
- Account: ACC3, B `expire`, Fields: `bounty_id` = `1`: fails, `not expirable`. Same for `2` now.
- Account: ACC3, B `expire`, Fields: `3` BEFORE one hour has passed: fails, `not expirable`.
- AFTER one hour from D3: Account: ACC3, B `expire`, Fields: `3`: success; `get_bounty(3)`: `EXPIRED_NO_COMMIT`; `get_claimable(ACC1)` = R.
- Account: ACC1, `withdraw`: ACC1 receives R. `get_solvency()` stays `ok`.
- Result: ________

---

## E. Resolve against the real price source, right now

The ledger accepts `register` only from the address it was deployed with and does not compare `analyzed_at` with the clock. So deploy a SECOND ledger whose "verdict contract" is ACC1 itself, and register entries analyzed four days ago with a one-day horizon: they are due immediately and the validators fetch real historical candles.

**Time values:** take the current UTC time minus 4 days, set minutes to 30, write it as `YYYY-MM-DDTHH:MM:SSZ`. Example for 28 Oct 2026: `analyzed_at` = `2026-10-24T12:30:00Z`, `observed_at` (10 minutes earlier) = `2026-10-24T12:20:00Z`.

---

### E1. Deploy the test ledger
- Account: ACC1
- Contract file: `eth_outcome_ledger.py`
- Constructor fields: `verdict_contract` = ACC1 address, `price_url_template` = `https://data-api.binance.vision/api/v3/klines?symbol=ETHUSDT&interval=1h&startTime={start_ms}&limit=1`, `flat_band_bps` = `300`, `max_price_deviation_bps` = `300`
- Expect: deployed. Write the address into L2.
- Result: ________

---

### E2. Register entry "bad": an absurd price
- Account: ACC1, Contract: L2, Method: `register`
- Fields, in order:
  - `snapshot_id` = `aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`
  - `submitter` = ACC1 address
  - `bounty_ref` = (empty; if the Studio form refuses an empty string, type `none`)
  - `stance` = `bullish`
  - `conviction` = `60`
  - `risk_level` = `moderate`
  - `horizon_days` = `1`
  - `analyzed_at` = (from the time values above)
  - `observed_at` = (10 minutes earlier)
  - `asserted_price_e8` = `100000000`
- Expect: success. (view) L2 `get_status(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)` = `REGISTERED`; `get_entry(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)`: `resolve_not_before_s` is in the past.
- Result: ________

---

### E3. Resolve it (real candles)
- Account: ACC3 (anyone), Contract: L2, Method: `resolve`, Fields: `snapshot_id` = `aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`
- Expect: success after a consensus round (validators fetch 3 candles from the real source). If it fails with `price source HTTP status 451`, the host is blocked for the validators: deploy another ledger with a different Binance-compatible host (same JSON format) and repeat. Any other error: send me the exact text.
- (view) L2 `get_status(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)` = `RESOLVED`.
- (view) L2 `get_resolution(aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)`: `result` = `excluded`, `evidence_ok` = false, `obs_low_e8` <= `obs_open_e8` <= `obs_high_e8`, `ref_open_e8` > 0, `end_open_e8` > 0.
- Write down `obs_high_e8` = `________`
- Result: ________

---

### E4. Register entry "top": price at the top of the observed hour
- Account: ACC1, L2 `register`: same fields as E2 except `snapshot_id` = `bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb` and `asserted_price_e8` = the `obs_high_e8` you wrote down.
- Then Account: ACC3, L2 `resolve`, Fields: `bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb`.
- Expect: (view) `get_resolution(bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb)`: `evidence_ok` true, `deviation_bps` 0, `result` hit, miss or abstain (not excluded).
- Result: ________

---

### E5. Register entry "over": 5 percent above the high
- Account: ACC1, L2 `register`: same fields except `snapshot_id` = `cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc` and `asserted_price_e8` = `obs_high_e8` x 1.05 (round down to an integer).
- Then Account: ACC3, L2 `resolve`, Fields: `cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc`.
- Expect: `evidence_ok` false, `result` excluded, `deviation_bps` about 500.
- Result: ________

---

### E6. Scorecards and immutability
- (view) L2 `get_scorecard()`: `registered` 3, `resolved` 3, `unresolved` 0, `excluded` 2.
- (view) L2 `get_submitter_scorecard(ACC1 address)`: the same counts.
- Account: ACC3, L2 `resolve`, Fields: `aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa` again: fails, `already resolved; resolutions are immutable`.
- Account: ACC3, L2 `register`, Fields: any valid set: fails, `only the verdict contract may register`.
- (view) L2 `get_unresolved_due_page(0, 10, 9999999999)`: empty.
- Result: ________

---

## F. Time-gated checks (come back later)

---

### F1. Expire a bounty that was committed but never delivered (bounty 2)
- When: more than 3 days after the end of its delivery window. Read `get_bounty(2)`: `deliver_deadline_s` (unix seconds) + 259200 is the earliest moment.
- Account: ACC3, B `expire`, Fields: `2`.
- Expect: `status` EXPIRED_NO_DELIVERY; `get_claimable(ACC1)` = R (reward back); `get_claimable(ACC2)` = 0; `get_solvency()`: `forfeited_total` = R, `ok` true (the analyst's bond is forfeited, nobody gets it).
- Result: ________

---

### F2. Resolve the real verdict of bounty 1 and settle the money
- When: after L `get_entry(SIDB1)` `resolve_not_before_s` (about 7 days and 3 hours after D6).
- Account: ACC3, L `resolve`, Fields: `snapshot_id` = SIDB1. Wait for FINALIZED plus a few minutes.
- Expect: (view) L `get_resolution(SIDB1)`: a result. (view) B `get_bounty(1)`: `status` SETTLED with the same `result`. Payout:
  - hit and bullish/bearish: `get_claimable(ACC2)` = 2R;
  - miss or excluded: `get_claimable(ACC1)` = 2R;
  - abstain or neutral: each side its own R.
- Then `withdraw` from the account that is owed money; balance increases; `get_solvency()`: `ok` true and `locked_total` 0.
- Result: ________

---

## Summary table (fill in)

- A (deploy and wiring): ________
- B1-B17 (verdict): ________
- C1-C3 (ledger): ________
- D1-D8 (bounty): ________
- E1-E6 (resolve with real candles): ________
- F1-F2 (time-gated): ________

Send me every step whose Result differs from Expect, with the exact error text and (for failed transactions) what Studio shows for the transaction.


---

## Notes from the first complete manual run (read before you start)
- The Value field in Studio is in GEN; the contract stores and shows wei (10 GEN = 10000000000000000000).
- `commit` takes the SHORT bounty number (for example `9`), never a snapshot id. A snapshot id gives `false` and the rejection reason `unknown_bounty` (and your bond is refunded).
- The delivery window is 60 minutes from the commit and only `analyze` has to fit in it: run `analyze_layer` (macro and manipulation) for the analyst's snapshot BEFORE committing, then commit, then `analyze` at once.
- The commit window is 60 minutes from creation: create the bounty, prepare the snapshot (`bounty_ref` = the bounty number) and commit within that hour.
- Studio prints no text for a view that returns an empty string (for example `get_resolution` before resolving, `get_ignored` when nothing was ignored, `get_layer_result` of an arithmetic layer). An empty list is shown as `[]`.
- A refused write shows `FINALIZED` or `ACCEPTED` with `Result: ERROR` and the reason in the validator rows. A refused VIEW shows a generic red toast.
- On the hosted Studio a refused payable call used to KEEP its Value (confirmed: 94 GEN ended up stuck in the first bounty deployment). The redesigned bounty contract credits it back instead; the old deployment keeps its stuck funds, so deploy a NEW bounty and subscribe it to the ledger before repeating part D.
- Time-gated checks: `expire` of a committed bounty with no delivery is possible 3 days after its `deliver_deadline_s` (`get_bounty`); `resolve` of a registered verdict is possible after `resolve_not_before_s` (`get_entry`).
