# Studio test plan (what the direct-mode suite CANNOT prove)
Use throw-away testnet accounts only. Record for each step: tx hash, final tx status (`status_name`), error text, receipt JSON. Fill the "Result" column and send it back; BLOCKED rows in `TEST_REGISTER.md` get closed from this.

## Deploy
**Redeploy BOTH contracts from the latest files** (first Studio run found that Studio sends address arguments as integers; both contracts now accept that). An address field takes your pasted `0x...` as usual. Ledger args: `verdict_contract` = VERDICT address, `price_url_template` = the URL below (keep `{start_ms}` literally), `flat_band_bps` = 300, `max_price_deviation_bps` = 300 (zeros are rejected).
1. `contracts/eth_intelligence.py` (no constructor args) → `VERDICT`. If Studio rejects the runner hash, note the exact error (U1) — do **not** just swap hashes blindly.
2. `contracts/eth_outcome_ledger.py` with args `(VERDICT, "https://data-api.binance.vision/api/v3/klines?symbol=ETHUSDT&interval=1h&startTime={start_ms}&limit=1", 300, 300)` → `LEDGER`.
3. From the deploying account: `VERDICT.set_ledger(LEDGER)`; then `VERDICT.get_policy()` → `ledger_set: true`.
4. Quick-test ledger: deploy `eth_outcome_ledger.py` again with args `(<your own account address>, <same template>, 300, 300)` → `LEDGER_T` (lets you call `register` yourself).
Generate a fresh snapshot (observed_at must be ≤24 h old): `python scripts/make_snapshot.py > snap.json` (change one value per run to get a new id).

## Steps
| # | Action | Expected | Proves / closes | Result |
|---|---|---|---|---|
| S01 | `VERDICT.get_policy()` | schema "1", max_age 86400, paused false | deploy sanity; Studio schema parsing | |
| S02 | `validate_snapshot(snap)` | 64-hex id, no revert | U2 (hashlib/json/datetime in real VM), U4 time format | |
| S03 | `submit_snapshot(snap)` | tx Accepted; `get_status(id)`=SUBMITTED; `get_snapshot(id)` canonical JSON | write path | |
| S04 | submit same snap again | error `duplicate snapshot` | dedupe on-chain | |
| S05 | `analyze(id)` | RECORDED + record, or Undetermined (note which, how many rounds/validators) | **real validator consensus**; U3, U5 | |
| S06 | `analyze(id)` again | error `already recorded` | immutability | |
| S07 | repeat S03+S05 for **≥10 different snapshots** (vary rsi_1d / etf / funding) | count RECORDED vs Undetermined/rotations | U5: calibrate tolerances | |
| S08 | after `analyze` tx is Finalized: `LEDGER.get_status(id)` | REGISTERED | U7 `emit(on='finalized')` delivery + sender check | |
| S09 | if S08 shows UNKNOWN: `VERDICT.republish(id)`, wait Finalized, recheck | REGISTERED | recovery path | |
| S10 | submit stale (observed_at 3 days old) / malformed JSON / >6000 B | errors `stale snapshot` / `malformed JSON` / `exceeds` | input defences on-chain | |
| S11 | `LEDGER_T.register(<64-hex>, <your address as 0x+40hex>, "bullish", 60, "moderate", 7, <analyzed_at: ISO 10 days ago>, <observed_at: 20 min earlier>, <asserted price e8, e.g. 300000000000 for 3000.00 — must be within 300 bps of the real open at the observation hour>)` | tx ok, REGISTERED; `get_scorecard()` registered=1 unresolved=1 | register shape; **U15 submitter format** | |
| S12 | `LEDGER_T.resolve(<id>)` | RESOLVED with `obs_open_e8`, `ref_open_e8`, `end_open_e8`, `deviation_bps`, `evidence_ok`, `return_bps`, `result` | **U4a/U4b: web access works, `.status`, no geo-block, validators agree on prices** | |
| S13 | compare `ref_open_e8/1e8` to the real 1h candle open at that hour on the source | equal | price correctness (not just agreement) | |
| S14 | `resolve` again; `resolve` on a not-yet-due entry | `already resolved` / `horizon not reached` | guards | |
| S15 | deploy a 3rd ledger with a dead URL template, register+resolve | tx fails/undetermined, status stays REGISTERED, no resolution | external failure never fabricates a result | |
| S16 | for S05 / S12 txs: poll `get_transaction().status_name` over time | ACCEPTED → … → FINALIZED; note elapsed time | finality labels; U9 window length | |
| S17 | (optional) `appeal_transaction` on an Accepted analyze; re-read record | record may change; client shows PROVISIONAL meanwhile | appeal behaviour, U8 | |
Tell me exactly what differs from "Expected"; do not paraphrase errors.

## Layer steps (variant 2: macro + manipulation have their own consensus)
Flow per snapshot: `submit_snapshot` → `analyze_layer(id,"macro")` → `analyze_layer(id,"manipulation")` → `analyze(id)` (S05 now needs the two layer txs first; the verdict contract constructor is unchanged).
| # | Action | Expected | Proves / closes | Result |
|---|---|---|---|---|
| SL01 | `get_layer_modes()` | quant/flow/risk = arith; macro/manipulation = consensus | deploy sanity | |
| SL02 | `preview_layers(id)` for the sample snapshot (`scripts/make_snapshot.py`) | pending = [macro, manipulation]; arithmetic readings quant 25, flow 35, macro prior 10, manipulation caution 0, risk caution 30 | **U12: float/integer arithmetic inside real GenVM** | |
| SL03 | `analyze(id)` before the layers | error `layer macro not analyzed yet` | ordering guard | |
| SL04 | `analyze_layer(id,"macro")` | tx Accepted (or Undetermined — note it); `get_layer_result(id,"macro")` has score/caution/note and `arith_prior` | **real per-layer consensus**, U3 | |
| SL05 | `analyze_layer(id,"manipulation")` | same; unaffected by SL04 outcome | failure isolation | |
| SL06 | repeat `analyze_layer(id,"macro")`; `analyze_layer(id,"quant")` | `layer already analyzed` / `layer quant is in arith mode` | guards on-chain | |
| SL07 | `analyze(id)` | RECORDED; record has `layers`, `layer_modes`, `layer_tally`, 5 entries | final aggregation; **U13** (layer txs maybe only Accepted) | |
| SL08 | non-owner `set_layer_mode("flow","consensus")` | error `owner only`; owner succeeds | authority | |
| SL09 | new snapshot after promoting flow: `analyze` before `analyze_layer(id,"flow")` | error `layer flow not analyzed yet`; then works | extensibility switch | |
| SL10 | ≥10 snapshots: record per layer and for the final: RECORDED vs Undetermined, rotations, wall-clock | rates per layer | **U14 tolerance calibration; real cost/time of 3 rounds** | |
| SL11 | compare each AI layer score with its `arith_prior` | note how often/how far AI deviates | does AI add anything over the formula? (the whole point of variant 2) | |
Report SL02 numbers exactly: any difference from the listed values means arithmetic differs in the real VM.

## P1/P2 steps (ledger grading rules, authority, limits) — run after the S and SL steps
| # | Action | Expected | Proves / closes | Result |
|---|---|---|---|---|
| SP01 | on `LEDGER_T`, register with `analyzed_at` = X and `observed_at` = X − 23 h; read `get_entry` | `ref_ms` = first full hour AFTER X; window never starts before X | forward-only grading | |
| SP02 | register 3 entries (same submitter), resolve only one; `get_scorecard()` and `get_submitter_scorecard(<you>)` | registered 3, resolved 1, unresolved 2 | no survivorship; per-submitter view; **U15** | |
| SP03 | `get_unresolved_due_page(0, 50)` | lists the two unresolved due ids; resolved one absent | keeper tooling | |
| SP04 | register one with a wrong asserted price (e.g. 2000.00 when the real open was ~3000) and resolve | `evidence_ok=false`, `result=excluded`, `excluded` counter +1, no hit/miss counted | no pollution; 3-candle fetch works (**U16**) | |
| SH01 | `VERDICT.set_policy(86400, 1, 20)` then try `submit_snapshot`; wait >1 h (or check `paused_until_s`) and submit again | blocked, then allowed with no owner action | pause self-expires | |
| SH02 | `set_policy(86400, 0, 2)`; submit 3 distinct snapshots | third reverts `too many open snapshots`; after `analyze` a slot frees | per-sender cap | |
| SH03 | `propose_owner(B)`, `accept_ownership()` from B, then `set_policy` from old owner | old owner reverts `owner only` | two-step ownership | |
| SH04 | `set_ledger(X)` twice; `get_ledger_history()`; `republish(id)` ×4 | history has both; 4th republish reverts `republish limit reached` | re-pointing + caps | |
| SH05 | submit a snapshot, then `set_layer_mode("macro","arith")`; run `analyze_layer(id,"macro")` | still allowed (snapshot frozen with macro=consensus); `get_snapshot_modes(id)` unchanged | frozen modes | |
| SH06 | analyze a snapshot whose manipulation layer ends with caution ≥ 80 | `result.conviction_cap_layers` ≤ 60 and `conviction ≤ cap` | caution cap on a real model | |
| SH07 | UI: open the page without `ETH_UI_PASSWORD`/`ETH_UI_LOCAL_ONLY`; then with a wrong/right password; then another contract address | locked / locked / unlocked; non-pinned address needs the checkbox | UI access control | |
Anything that differs from "Expected" is a finding; send the exact text.

## Round-3 steps (bounty + review fixes) - automated in `tests/integration/test_review_findings_gltest.py`
Run: `gltest tests/integration/test_review_findings_gltest.py -v -s -rs --network studionet --default-wait-retries 200` (G3 and G7 separately: `-k g3`, `-k g7`, about 7 minutes each). The module skips itself when no node is reachable. `contract_file_path` is relative to `contracts/`. Layers run first (`analyze_layer`, one tx each), then `analyze`.
| # | Action | Expected | Proves / closes | Result (hosted studionet) |
|---|---|---|---|---|
| G1 | submit a snapshot with `price.current = 0` | tx fails `out of range` | F1: no orphan verdicts | PASS |
| G2 | `ledger.get_unresolved_due_page(0, 10, now_s)` | returns a list | F8: no clock inside a view | PASS |
| G3 | submit; pause (`set_policy(86400, 1, 20)`); submit again; run layers + `analyze` on the first | second submit fails `paused`; layers and `analyze` succeed | F4: pause stops intake only | PASS |
| G4 | another account calls `analyze` on my snapshot | fails `only the submitter`; status stays `SUBMITTED` | F3 | PASS |
| G5 | submit; `release_snapshot`; then `analyze` | status `RELEASED`; `analyze` fails `not in SUBMITTED state` | F2 | PASS |
| G6 | `create_bounty` (value), `get_solvency`, `cancel_bounty`, `withdraw` | claimable = reward, then 0; `balance` back to the start; solvency ok | value flow, `emit_transfer` | PASS |
| G7 | client creates a bounty; analyst submits, commits (bond), runs layers + `analyze`; wait for FINALIZED children | ledger `REGISTERED`; bounty `DELIVERED` or `SETTLED` | verdict -> ledger -> bounty delivery, sender check | PASS |
Resolution against the real price source: **G8** (`tests/integration/test_resolve_live.py`, **PASSED on the hosted studionet** with `data-api.binance.vision`; with `api.binance.com` it failed `HTTP status 451`). It deploys a dedicated ledger whose "verdict contract" is the test account and registers entries "analyzed" four days ago with a 1-day horizon, so they are due at once and the validators fetch real historical candles: (1) asserted price $1 -> `excluded` with real candle fields; (2) asserted price = the observed hour's high -> `evidence_ok`, deviation 0; (3) 5 % above the high -> `excluded`, deviation about 500 bps; scorecard 3 registered / 3 resolved / 2 excluded. Observed: entry 1 deviation 9995 bps -> excluded; entry 2 deviation 0, `evidence_ok`, return -70 bps against a flat band of 300 -> realized flat, bullish verdict = miss; entry 3 deviation exactly 500 bps -> excluded. It does NOT cover the verdict -> ledger link (G7) or bounty settlement.
Time-gated, not automatable in minutes: **SR02** bounty settlement and `withdraw` of a win (horizon >= 7 days); **SR03** `expire` of a bounty with no delivery (delivery window + 3 days), expect `forfeited_total` = bond and client claimable = reward; **SR04** the client against the live chain (`validate_snapshot` is affected by U17; validate locally).

## Manual run results (hosted studionet, parts A-D of `STUDIO_RUNBOOK.md`)
All expected refusals and successes matched (details and numbers in `docs/ARCHITECTURE.md`, section 6, and `docs/TEST_REGISTER.md`). Still to do by hand, time-gated: **F1** `expire` of committed-but-undelivered bounties (earliest 5, 6 and 7 November, 2026, UTC; see the table in the runbook notes) expecting `EXPIRED_NO_DELIVERY` and `forfeited_total` growing by the bonds; **F2** `resolve` of the two registered 7-day verdicts (from 10 and 11 November, 12:00 UTC) and the resulting bounty settlement (a neutral verdict returns each side its own money; a payout needs a bullish or bearish verdict); **X3** the experiment for U20 (does a refused payable call keep its value).

**G9** (`tests/integration/test_review_findings_gltest.py`, written, NOT yet run): after redeploying the bounty and subscribing it to the ledger, a refused `create_bounty` with value must end `SUCCESS`, store `horizon_days_out_of_bounds` in `get_rejection`, raise `get_claimable` by the value, leave `unaccounted` unchanged and be withdrawable.
