# Testing guide

How to reproduce every check of the three contracts (`EthIntelligence` = verdict, `EthOutcomeLedger` = ledger,
`EthAnalystBounty` = bounty) at three levels. Results of the runs that were actually performed are in
[`TEST_RESULTS.md`](TEST_RESULTS.md); the longer register of findings and open points is
[`TEST_REGISTER.md`](TEST_REGISTER.md).

| Level | What it proves | Needs | Time | Section |
|---|---|---|---|---|
| 1a Static (`genvm-lint`) | each contract loads as a GenVM contract, schema is valid | Python 3.12 | seconds | [1](#1-level-1-static-checks-and-direct-mode) |
| 1b Direct mode (523 tests) | contract and client logic under CPython with a mocked LLM and mocked web. **Not** validator consensus, **not** GenVM WASM | GenVM SDK v0.2.16 tarball | about 80 s | [1](#1-level-1-static-checks-and-direct-mode) |
| 1c Mutation sets | the tests catch deliberate bugs (139 contract mutants, 11 client/UI mutants) | as 1b | 50 min + 1 min | [1](#1-level-1-static-checks-and-direct-mode) |
| 2 gltest on Studio | a real node: child transactions, value transfer, real validators with LLM and web access | funded Studio accounts | 5 min + 5 min | [2](#2-level-2-gltest-on-a-live-node) |
| 3 Studio runbook | everything by hand, on the exact deployments handed to a reviewer | three funded accounts | about 6 h of work plus 3-8 days of waiting | [3](#3-level-3-manual-studio-runbook) |

Direct mode cannot load two contracts at once and swallows `emit`, so the cross-contract chain
(verdict -> ledger -> bounty) is only proven at levels 2 and 3.

---

## 0. Prerequisites

* Python 3.12, a virtual environment, and the pinned tooling:
  ```bash
  python3.12 -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
  pip install -r requirements.txt                        # genlayer-py 0.16.x, genlayer-test 0.29.x, genvm-linter, pytest
  ```
* Direct mode needs a GenVM SDK tarball. `latest` ships none, so seed `v0.2.16` once:
  ```bash
  python -c "from gltest.direct.sdk_loader import download_artifacts as d; d('v0.2.16')"
  ```
* For levels 2 and 3: a GenLayer Studio (the hosted `studionet` was used), three accounts with funds
  (ACC1 owner and client, ACC2 analyst, ACC3 stranger), and a stable internet connection.
  Use throw-away testnet keys only.
* `scripts/studio_snapshot.py` copies a fresh snapshot to the clipboard with the Windows `clip` command. On other
  systems it saves `snap_<n>.json` and prints "open the file and copy its single line".

---

## 1. Level 1: static checks and direct mode

Run from the repository root.

```bash
# 1a static
for f in contracts/*.py; do genvm-lint check $f; done
# expected for each file: "Lint passed (3 checks)" and "Validation passed"
#   eth_analyst_bounty.py   16 methods (9 view, 7 write)
#   eth_intelligence.py     24 methods (14 view, 10 write)
#   eth_outcome_ledger.py   16 methods (11 view, 5 write)

# 1b direct mode: contracts (463 tests) and client/UI on a fake RPC (60 tests)
python -m pytest tests/direct tests/unit -q
# expected: 523 passed

# 1c mutation sets: every mutant MUST be caught
python scripts/mutate_client.py     # 11 mutants,  expected last line: SURVIVORS: none
python scripts/mutate.py            # 139 mutants (verdict 68, ledger 35, bounty 36), about 50 min, SURVIVORS: none
```

Tests per file (direct 463, client/UI 60):

| File | Tests | Area |
|---|---:|---|
| `tests/direct/test_eth_intelligence.py` | 78 | verdict: validation, freshness, analysis, validator rule |
| `tests/direct/test_layers.py` | 53 | five layers, arithmetic and AI modes, equivalence |
| `tests/direct/test_hardening.py` | 25 | open cap, pause, ownership, ledger re-pointing, frozen modes |
| `tests/direct/test_v5_identity.py` | 30 | snapshot identity and canonical form |
| `tests/direct/test_ledger.py` | 105 | register, resolve, candle rules, scorecards, subscribers |
| `tests/direct/test_bounty.py` | 79 | money flow, commit/deliver/settle/expire rules |
| `tests/direct/test_bounty_fuzz.py` | 41 | solvency invariants under random sequences |
| `tests/direct/test_review_findings.py` | 50 | regressions for the review findings F1-F8 |
| `tests/direct/test_builder_integration.py` | 2 | snapshot builder |
| `tests/unit/test_client_and_ui.py` | 34 | client finality classification, UI (Streamlit AppTest) |
| `tests/unit/test_client_hardening.py` | 18 | dry-run, locking, pinned address |
| `tests/unit/test_client_layers.py` | 8 | layer orchestration |

---

## 2. Level 2: gltest on a live node

`tests/integration/` holds the scenarios that direct mode cannot prove. Without a reachable node every test is
skipped, not failed.

| Id | Scenario | Proves |
|---|---|---|
| G1 | a snapshot with price 0 is refused at submission | no orphan verdict that can never be graded |
| G2 | `get_unresolved_due_page(offset, limit, now_s)` | the due-list view works on a real node |
| G3 | pause blocks new submissions, not work already submitted | owner pause stops intake only |
| G4 | a stranger cannot `analyze` someone else's snapshot | submitter-only analysis |
| G5 | `release_snapshot` frees the per-sender slot | no permanent lock-out |
| G6 | bounty create, cancel, `withdraw` moves real value | value flow and solvency |
| G7 | verdict -> ledger -> bounty delivery through `emit(on='finalized')` | the real cross-contract chain |
| G8 | `resolve` against real Binance candles (own ledger, past-dated entries) | live price source, validator agreement, candle-range rule |
| G9 | a refused payable call credits the value back | no value is kept on refusal |

Environment variables read by the tests:

| Variable | Meaning |
|---|---|
| `ETH_VERDICT_ADDRESS`, `ETH_LEDGER_ADDRESS`, `ETH_BOUNTY_ADDRESS` | run G1-G7, G9 **on existing, already wired deployments**. If any of the three is missing, the tests deploy a fresh, wired stack themselves (and G3 then works, because the test account is the owner) |
| `ETH_PRICE_TEMPLATE` | price URL template for self-deployed ledgers. Default `https://data-api.binance.vision/api/v3/klines?symbol=ETHUSDT&interval=1h&startTime={start_ms}&limit=1` |

Run (Windows `cmd`; on bash use `export NAME=value`):

```bat
set ETH_VERDICT_ADDRESS=0x<VERDICT>
set ETH_LEDGER_ADDRESS=0x<LEDGER>
set ETH_BOUNTY_ADDRESS=0x<BOUNTY>
gltest tests/integration/test_review_findings_gltest.py -v -s -rs --network studionet --default-wait-retries 200 -k "g1 or g2 or g4 or g5 or g6 or g9"
gltest tests/integration/test_review_findings_gltest.py -v -s -rs --network studionet --default-wait-retries 200 -k g7
```

Expected: every selected test `PASSED` (about 5.5 minutes for the first command, 5 minutes for G7).

Notes:

* G3 needs owner rights, which only the account that deployed the contracts has. On existing deployments it is not
  run; do the pause check by hand (block 3.3). To run it, unset the three variables so the test deploys its own stack
  and run `-k g3` separately.
* G8 is a separate file (`tests/integration/test_resolve_live.py`). It deploys a dedicated ledger whose "verdict
  contract" is the test account, so it needs no existing deployment. It is mirrored by block 9 of the runbook.
* Run G3, G7 and G8 one at a time (`-k g3`, `-k g7`); each waits for FINALIZED child transactions.
* The warning `gltest.config.yaml not found, using default config` is harmless.
* Each gltest run creates its own snapshots and bounties on the deployments it uses, so counters
  (`get_id_count`, `registered`, `get_bounty_count`, `get_solvency`) grow. Compare increments in later runbook blocks.

---

## 3. Level 3: manual Studio runbook

Goal: every behaviour that matters is visible on **the three contracts handed to the reviewer**. Rule of the run: if a
bug is found or a contract changes after deployment, redeploy and repeat every block on the new addresses.

### 3.0 Setup

Deploy in this order, from the files in `contracts/`:

1. verdict `eth_intelligence.py` (no constructor arguments) -> `VERDICT`
2. ledger `eth_outcome_ledger.py` with `(VERDICT, "https://data-api.binance.vision/api/v3/klines?symbol=ETHUSDT&interval=1h&startTime={start_ms}&limit=1", 300, 300)` -> `LEDGER`
   (the default host `api.binance.com` answers `HTTP status 451` to the hosted-Studio validators; the template is
   immutable, so a wrong choice means a redeploy)
3. bounty `eth_analyst_bounty.py` with `(LEDGER)` -> `BOUNTY`

Accounts used below:

| Role | Label | Note |
|---|---|---|
| owner, client | ACC1 | deploys everything; address also needed in lower case for `get_claimable` / `get_rejection` |
| analyst | ACC2 | commits bounties, runs the analysis |
| stranger | ACC3 | everything that must be refused |

**Fingerprint check (do this once, before block 1).** Studio shows several deployments in one list and their
`get_policy()` outputs look alike. Confirm you are on the right contracts:

* `LEDGER.get_policy().verdict_contract` equals `VERDICT`
* `BOUNTY.get_config().ledger` equals `LEDGER`
* the contract address in the Studio header is the one you intend to call, for every call below

These two fields are fixed at deployment, so a mismatch means you are looking at a different deployment.

### 3.1 Conventions and pitfalls

* **Value.** Enter `2` in the Value field (GEN). The contract works in wei: 2 GEN = `2000000000000000000`.
* **Snapshots.** Run in a plain `cmd` in the repository root. The command copies the snapshot to the clipboard; paste
  with Ctrl+V into `snapshot_json` and copy nothing in between (screenshots replace the clipboard too). Create each
  snapshot right before use: it is valid for 24 hours from its `observed_at`. A different number gives a different id.
  ```bat
  python scripts\studio_snapshot.py 41
  python scripts\studio_snapshot.py 51 --horizon 7 --bounty-ref 3
  ```
  Check the printed `horizon_days=... bounty_ref=...` line against the step. If a leftover command line is in the
  window, press Esc first: pasting a new command after old text runs both as one line.
* **Reading Studio.** A refused write shows `Result: ERROR`, the reason is in the validator rows (`[EXPECTED] ...`). A
  refused view shows a red notification. A view that returns an empty string draws nothing; an empty list shows `[]`.
* **Refused payable bounty calls are not red.** `create_bounty` and `commit` with bad arguments finish `SUCCESS` with an
  empty result (or `false` for `commit`): nothing is created, the value is credited to the sender's `get_claimable`,
  and the reason is in `get_rejection(account)` (use the lower-case address). Collect with `withdraw`.
* **Bounty numbers** (`commit`, `cancel_bounty`, `expire`, `get_bounty`) are the short numbers returned by
  `create_bounty` (`0`, `1`, ...), never a snapshot id. They depend on what already ran, so use the number you got.
* **Snapshot ids** come from the `submit_snapshot` response or `get_ids_page(offset=0, limit=50)`.
* **`withdraw` pays the whole `claimable` of the caller's address**; you cannot pick one bounty. Note `get_claimable`
  before and after, and compare the difference.
* **Totals.** `get_solvency()` is contract-wide. Where a step says "locked_total +2 GEN", compare with the value before
  the step. The absolute numbers in the original single-contract walk-through only hold on an empty contract.
* **Statuses.** The verdict contract reports `SUBMITTED / RECORDED / RELEASED`; the ledger reports `REGISTERED / RESOLVED`.
* **UNDETERMINED.** If `analyze` ends `UNDETERMINED` (red, several leader changes), the verdict is not recorded and the
  snapshot stays `SUBMITTED`. Call `analyze` again and count the attempts. Change nothing in the contract for this.
* **Size limit of views.** The hosted Studio rejects a view call with a string argument of about 1.4 KB
  (`validate_snapshot`, `snapshot_id_for`); use `get_id_count` / `get_ids_page` instead.
* **Address arguments.** Studio sends address fields as plain integers; the contracts accept int, hex string, bytes
  and `Address`. Paste `0x...` as usual.

### 3.2 Block map

| Block | Checks | Time | Depends on |
|---|---|---|---|
| 1 Wiring | contracts are linked correctly, owner rights | 15 min | nothing (first) |
| 2 Verdict main path | submit, layers, verdict, immutability, republish | 50 min | 1 |
| 3 Slots, release, pause | open cap, `release_snapshot`, pause, policy bounds | 30 min | 1 |
| 4 Frozen rules, owner, ledger | freshness and layer modes frozen at submit, two-step ownership, `set_ledger` | 45 min | 1 |
| 5 Ledger | registration, timestamps, counters, due list, subscribers | 20 min | 2 (needs recorded SID1) |
| 6 Bounty money and refusals | create, cancel, `withdraw`, refunds on refusal, expiry with no commit | 25 min + 60 min wait | 1 |
| 7 Bounty delivery | real delivery verdict -> ledger -> bounty, ignore reason | 50 min | 1 |
| 8 Bounty payout attempts | a directional verdict (`bullish`/`bearish`) for the win path | 30 min per round | 1 |
| 9 Resolve on real candles | outcome from real prices, price-range rule | 35 min | ACC1 only |
| 10 gltest on final addresses | automatic scenarios on the same contracts | 40 min | 1 |
| 11 Time-gated checks | `expire` with forfeited bond, resolution and payout | 3-8 days of waiting | 7 and 8 |

Order that saves time: 1, then 7 and 8 at once (they start the long timers), then 2, 3, 4, 5, 6, 9, 10, and 11 last.
Blocks 2, 3, 4 are independent of each other but use ACC1 one after another.

### Block 1. Wiring (about 15 min)

**1.1 Ledger (view).** `LEDGER.get_policy()`: `verdict_contract` = `VERDICT`, `price_url_template` = the URL used at
deployment, `flat_band_bps` = 300, `max_price_deviation_bps` = 300, `owner` = ACC1, `subscribers` = 0. Any difference
means redeploy.

**1.2 Link verdict to ledger.** ACC1, `VERDICT.set_ledger(ledger_address=LEDGER)`: `SUCCESS`. Then view
`get_ledger_history()` contains `LEDGER`; `get_policy()`: `ledger_set` = true, `max_age_s` = 86400,
`max_open_per_sender` = 20, `paused_until_s` = 0, `pending_owner` empty.

**1.3 Bounty (view).** `BOUNTY.get_config()`: `ledger` = `LEDGER`, `min_horizon_days` = 7, `max_horizon_days` = 90,
`min_reward` = 1, `min_delivery_window_s` = 3600, `max_delivery_window_s` = 172800, `arrival_grace_s` = 259200,
`resolve_grace_s` = 1209600. `get_solvency()`: all amounts 0, `ok` = true. `get_bounty_count()` = 0.

**1.4 Subscribe the bounty.** ACC1, `LEDGER.add_subscriber(subscriber=BOUNTY)`: `SUCCESS`. View `get_subscribers()` is
a list with the bounty address (letter case may differ).

**1.5 A stranger cannot manage.** ACC2, `LEDGER.add_subscriber(<any address>)`: refused `unauthorized: owner only`.
ACC2, `VERDICT.set_policy(max_age_s=86400, pause_hours=0, max_open_per_sender=20)`: refused `unauthorized: owner only`.

### Block 2. Verdict main path (about 50 min)

Produces SID1, which block 5 needs.

**2.1 Initial state (view).** `get_id_count()` (0 on a fresh verdict; otherwise note the value and compare increments).
`get_layer_modes()`: `macro` and `manipulation` = `consensus`; `flow`, `quant`, `risk` = `arith`.

**2.2 Submit S1.** `python scripts\studio_snapshot.py 41`; ACC1, `submit_snapshot` (paste). Expected `SUCCESS` with a
64-hex id: record it as **SID1**. View: `get_ids_page` lists SID1; `get_status(SID1)` = `SUBMITTED`;
`get_submitter(SID1)` = ACC1; `get_snapshot_modes(SID1)` equals 2.1. Keep `snap_41.json`.

**2.3 Duplicate.** `type snap_41.json | clip`, ACC1, `submit_snapshot` (paste): refused, text starts
`duplicate snapshot`. (Do not regenerate with the same number: the id depends on the time.)

**2.4 A stranger cannot start analysis.** ACC3, `analyze(SID1)` and `analyze_layer(SID1, macro)`: both refused
`unauthorized: only the submitter`. `get_status(SID1)` is still `SUBMITTED`.

**2.5 The verdict needs the layers (ACC1).** `analyze(SID1)`: refused `layer macro not analyzed yet (run analyze_layer)`.
`analyze_layer(SID1, quant)`: refused `layer quant is in arith mode`. `analyze_layer(SID1, bogus)`: refused
`unknown layer`. View `preview_layers(SID1)`: five layer readings, `macro` and `manipulation` with `pending` = true.

**2.6 Consensus layers (ACC1).** `analyze_layer(SID1, macro)`: `SUCCESS`; view `get_layer_result(SID1, macro)` has
`score`, `caution`, `drivers`. Same for `manipulation`. A repeat `analyze_layer(SID1, macro)`: refused
`layer already analyzed; layer results are immutable`.

**2.7 Record the verdict (ACC1).** `analyze(SID1)`: `SUCCESS` (consensus, 1-5 minutes, leader changes possible).
View: `get_status(SID1)` = `RECORDED`; `get_record(SID1)` has `stance`, `conviction`, `risk_level`, `submitter` and
`analyst` both ACC1, `asserted_price_e8` = 299540000000 (from the sample snapshot), all five layers in `layers`.
`get_layer_result` for `quant`, `flow`, `risk` is empty (their values are inside `get_record`). Note stance,
conviction, risk level and the number of `analyze` attempts.

**2.8 Immutability (ACC1).** `analyze(SID1)`: refused `already recorded; results are immutable`.
`release_snapshot(SID1)`: refused `snapshot is not in SUBMITTED state`. `release_snapshot(aaaa...a)` (64 letters `a`):
refused `unknown snapshot`.

**2.9 Re-send to the ledger (ACC3).** `republish(SID1)` three times: `SUCCESS`; the fourth: refused
`republish limit reached`.

### Block 3. Slots, release, pause (about 30 min)

**3.1 Release.** `studio_snapshot.py 42`, ACC1 `submit_snapshot` -> SID2. ACC3 `release_snapshot(SID2)`: refused
`unauthorized: only the submitter may release a fresh snapshot`. ACC1 `release_snapshot(SID2)`: `SUCCESS`;
`get_status(SID2)` = `RELEASED`. ACC1 `analyze(SID2)`: refused `snapshot is not in SUBMITTED state`.

**3.2 Open-snapshot cap (ACC1).** `set_policy(86400, 0, 1)`: `SUCCESS`, `get_policy().max_open_per_sender` = 1.
`studio_snapshot.py 43` + `submit_snapshot`: `SUCCESS` -> SID3. `studio_snapshot.py 44` + `submit_snapshot`: refused
`too many open snapshots for this sender`. `release_snapshot(SID3)`: `SUCCESS`. Submit 44 again: `SUCCESS` -> SID4, then
`release_snapshot(SID4)`. Restore `set_policy(86400, 0, 20)`; `max_open_per_sender` = 20.

**3.3 Pause stops only new submissions (ACC1).** `studio_snapshot.py 45` + `submit_snapshot` -> SID5.
`set_policy(86400, 1, 20)`: `SUCCESS`; `get_policy().paused_until_s` is about one hour ahead of the current Unix time.
`studio_snapshot.py 46` + `submit_snapshot`: refused `contract is paused`. `analyze_layer(SID5, macro)`: `SUCCESS`
(work already submitted continues). **Lift the pause at once:** `set_policy(86400, 0, 20)`; `paused_until_s` = 0. Then
`release_snapshot(SID5)`.

**3.4 Policy bounds (ACC1).** `set_policy(86400, 169, 20)`: refused `pause_hours out of bounds`.
`set_policy(100, 0, 20)`: refused `max_age_s out of bounds`. `get_policy()` is unchanged.

### Block 4. Frozen rules, owner, ledger (about 45 min)

**4.1 Freshness is frozen at submit (ACC1).** `studio_snapshot.py 47` + `submit_snapshot` -> SID7. Right after,
`studio_snapshot.py 48` creates `snap_48.json`; do not paste it yet, note the time. `set_policy(300, 0, 20)`: `SUCCESS`.
For SID7 run `analyze_layer(macro)`, `analyze_layer(manipulation)`, `analyze`: all `SUCCESS`, although the snapshot is
older than 300 s (it kept the 86400 s rule). More than 6 minutes after `snap_48.json` was created: `type snap_48.json |
clip` + `submit_snapshot`: refused `stale snapshot: age ...s exceeds 300s`. Restore `set_policy(86400, 0, 20)`. Do not
submit other snapshots while the policy is 300 s.

**4.2 Layer modes (ACC1 unless stated).** ACC3 `set_layer_mode(quant, consensus)`: refused `unauthorized: owner only`.
`set_layer_mode(bogus, arith)`: refused `unknown layer`. `set_layer_mode(quant, x)`: refused, text starts
`mode must be one of`. `studio_snapshot.py 49` + `submit_snapshot` -> SID8. `set_layer_mode(quant, consensus)`:
`SUCCESS`; `get_layer_modes().quant` = `consensus`; `get_snapshot_modes(SID8).quant` is still `arith` (frozen at
submit). `analyze_layer(SID8, quant)`: refused `layer quant is in arith mode`. Restore `set_layer_mode(quant, arith)`,
check `get_layer_modes()`, then `release_snapshot(SID8)`.
(If SID8 is released before the `analyze_layer` check, that call is refused with `snapshot is not in SUBMITTED state`
instead; keep the order above.)

**4.3 Two-step ownership.** ACC1 `propose_owner(ACC2)`; `get_policy()`: `pending_owner` = ACC2, `owner` still ACC1.
ACC3 `accept_ownership`: refused `unauthorized: not the pending owner`. ACC2 `accept_ownership`: `SUCCESS`; `owner` =
ACC2. ACC1 `set_policy(86400, 0, 20)`: refused `unauthorized: owner only`. **Give ownership back:** ACC2
`propose_owner(ACC1)`, ACC1 `accept_ownership`; `owner` = ACC1 and `pending_owner` empty.

**4.4 Ledger link.** ACC3 `set_ledger(LEDGER)`: refused `unauthorized: owner only`. ACC1 `set_ledger(LEDGER)`: `SUCCESS`
(the same ledger as in 1.2). `get_ledger_history()` now has two entries; the limit is 5 changes in total, do not
repeat the step. Never point `set_ledger` at an address that is not your ledger: the verdict would stop registering
verdicts until it is pointed back.

### Block 5. Ledger (about 20 min, after block 2)

Contract `LEDGER`. Do not call `remove_subscriber` as ACC1 (only ACC3, expecting a refusal): the bounty would be
unsubscribed and blocks 6-8 and 11 would break.

**5.1 The verdict arrived (view).** `get_status(SID1)` = `REGISTERED` (if empty, wait two minutes). `get_entry(SID1)`:
`stance`, `conviction`, `risk_level` equal the record from 2.7, `horizon_days` = 30, `bounty_ref` empty, `submitter` =
ACC1 in lower case, `asserted_price_e8` = 299540000000. Time arithmetic: `ref_ms` = start of the first full hour after
`analyzed_at`; `target_ms` = `ref_ms` + 30 days (2592000000 ms); `resolve_not_before_s` = `target_ms`/1000 + 7200;
`obs_ms` = start of the hour of `observed_at`. `get_scorecard()`: `registered` >= 1, `resolved` = 0.
`get_submitter_scorecard(ACC1)`: `registered` >= 1.

**5.2 Due list and early resolve.** `get_unresolved_due_page(0, 10, now_s=1)`: `[]`. With `now_s=9999999999`: contains
SID1. With `now_s=-1`: red notification (`invalid now_s`). ACC3 `resolve(SID1)`: refused `horizon not reached`.
`get_resolution(SID1)`: empty.

**5.3 Re-broadcast and subscribers.** ACC3 `rebroadcast(SID1)` three times: `SUCCESS`; the fourth: refused
`rebroadcast limit reached`. `rebroadcast(aaaa...a)`: refused `unknown snapshot`. View `get_subscribers()`: the bounty;
`get_subscriber_log()`: an `add:...` entry for it. ACC3 `remove_subscriber(BOUNTY)`: refused `unauthorized: owner only`.
ACC1 `add_subscriber(BOUNTY)`: refused `already subscribed`. ACC3 `register(snapshot_id=bbbb...b, submitter=ACC1,
bounty_ref=none, stance=bullish, conviction=60, risk_level=moderate, horizon_days=1, analyzed_at=2026-10-01T12:30:00Z,
observed_at=2026-10-01T12:20:00Z, asserted_price_e8=100000000)`: refused
`unauthorized: only the verdict contract may register`.

### Block 6. Bounty money and refusals (about 25 min + 60 min wait)

Contract `BOUNTY`. Start 6.4 early. Record `get_solvency()` before 6.1 as the baseline.

**6.1 Create, cancel, withdraw.** ACC1 `create_bounty(horizon_days=7, commit_window_s=3600, delivery_window_s=3600,
min_conviction=0)`, Value 2: `SUCCESS`, the response is the number (N_a). `get_bounty(N_a)`: `OPEN`, `client` = ACC1
in lower case, `reward` = 2000000000000000000; `get_solvency()`: `locked_total` = baseline + 2 GEN, `ok` = true.
ACC2 `cancel_bounty(N_a)`: refused `unauthorized: only the client`. ACC1 `cancel_bounty(N_a)`: `SUCCESS`; `CANCELLED`;
`get_claimable(ACC1)` = 2 GEN; `locked_total` back to baseline. ACC1 `withdraw`: `SUCCESS`; `get_claimable(ACC1)` = 0;
`claimable_total` = 0. A second `withdraw`: refused `nothing to withdraw`.

**6.2 Refused payable calls return the money (ACC1).** `create_bounty`, Value 2, one field changed at a time (rest:
7 / 3600 / 3600 / 0). Each call finishes `SUCCESS` with an empty result. After each: `get_rejection(ACC1)` = the reason;
`get_bounty_count()` unchanged; `get_claimable(ACC1)` grew by 2 GEN.
* `horizon_days=6`: `horizon_days_out_of_bounds`
* `commit_window_s=100`: `commit_window_s_out_of_bounds`
* `delivery_window_s=200000`: `delivery_window_s_out_of_bounds`
* `min_conviction=101`: `min_conviction_out_of_bounds`
* all valid but Value 0: `reward_too_small` (nothing to return)

One `withdraw` collects the money. `get_solvency()`: `unaccounted` = 0, totals back to baseline.

**6.3 Commit refusals.** ACC1 `create_bounty(7, 3600, 3600, 0)`, Value 2 -> N_b. ACC1 `commit(N_b)`, Value 2: result
`false`, `get_rejection(ACC1)` = `client_cannot_commit`. ACC2 `commit(N_b)`, Value 1: `false`, `get_rejection(ACC2)` =
`bond_must_equal_reward`. ACC3 `commit(99)`, Value 2: `false`, `get_rejection(ACC3)` = `unknown_bounty`. ACC1
`cancel_bounty(N_b)`: `SUCCESS`. Expected claimables before withdrawing: ACC1 4 GEN (reward back plus the refused
commit), ACC2 1 GEN, ACC3 2 GEN; each calls `withdraw`. `get_solvency()`: `unaccounted` = 0, totals at baseline.

**6.4 Expiry with no commit.** ACC1 `create_bounty(7, 3600, 3600, 0)`, Value 2 -> N_c; note the time. At once ACC3
`expire(N_c)`: refused `not expirable`. After `commit_deadline_s` (one hour or more): ACC3 `expire(N_c)`: `SUCCESS`,
`status` = `EXPIRED_NO_COMMIT`, `get_claimable(ACC1)` = 2 GEN; ACC1 `withdraw`.

### Block 7. Bounty delivery (about 50 min, hard windows)

Contracts `BOUNTY` and `VERDICT`. The commit must happen within 60 minutes of creation and `analyze` within 60 minutes
of the commit. Start the long timers of block 11 as early as possible; needs a stable internet connection.

**7.1 Two bounties (ACC1).** `create_bounty(7, 3600, 3600, 0)`, Value 2, twice: N_d (delivery) and N_e (foreign
horizon, then expiry). Note the time. `get_solvency()`: `locked_total` = baseline + 4 GEN, `unaccounted` = 0.

**7.2 Snapshots (ACC2, verdict).** `studio_snapshot.py 51 --horizon 7 --bounty-ref <N_d>`; check the line
`horizon_days=7, bounty_ref='<N_d>'`; `submit_snapshot` -> **SIDA**. `studio_snapshot.py 52 --horizon 30 --bounty-ref
<N_e>`; check `horizon_days=30`; `submit_snapshot` -> **SIDB**.

**7.3 Layers before the commit (ACC2, verdict).** For SIDA and for SIDB: `analyze_layer(macro)` then
`analyze_layer(manipulation)`. Four calls, all `SUCCESS`. Only `analyze` then has to fit the delivery window.

**7.4 Commit (ACC2 unless stated).** `commit(N_d)`, Value 2: `SUCCESS`, `true`. `get_bounty(N_d)`: `COMMITTED`, `analyst`
= ACC2 in lower case, `bond` = 2 GEN, `deliver_deadline_s` = commit time + 3600; note the commit time. ACC3
`commit(N_d)`, Value 2: `false`, `get_rejection(ACC3)` = `bounty_not_open`. ACC1 `cancel_bounty(N_d)`: refused
`bounty is not open`. ACC2 `commit(N_e)`, Value 2: `true`; note the time. ACC3 `withdraw` (money from the refused
commit). `get_solvency()`: `unaccounted` = 0.

**7.5 Delivery to N_d (ACC2, verdict, within 60 min of the commit).** `analyze(SIDA)`; wait for FINALIZED plus 2-3
minutes. View: `LEDGER.get_status(SIDA)` = `REGISTERED`; `LEDGER.get_entry(SIDA)`: `bounty_ref` = N_d, `horizon_days` = 7;
`BOUNTY.get_bounty(N_d)`: `DELIVERED`, `sid` = SIDA (if the stance is `inconclusive`: `SETTLED`, `result` = `abstain`,
each side gets its own money in `get_claimable`); `BOUNTY.get_ignored(SIDA)`: empty. If the status is still
`COMMITTED` after 15 minutes: read `get_ignored(SIDA)` and `LEDGER.get_subscriber_log()`. Record the stance, the
status and `LEDGER.get_entry(SIDA).resolve_not_before_s`.

**7.6 A verdict with a foreign horizon is ignored (N_e, within 60 min of its commit).** ACC2 `analyze(SIDB)`. After
FINALIZED plus 2-3 minutes: `get_ignored(SIDB)` = `horizon_mismatch`; `get_bounty(N_e)` is still `COMMITTED`.

**7.7 Too early to expire (ACC3).** `expire(N_d)` and `expire(N_e)`: both refused `not expirable`. `get_solvency()`:
`locked_total` = baseline + 8 GEN (two rewards plus two bonds).

### Block 8. Payout attempts (about 30 min per round)

Only a directional stance (`bullish`/`bearish`) can win, and the validators decide it. **The delivered bounty of block 7
already satisfies this block if its stance is directional.** If it came out `neutral`, prepare the next round like this:

* **Ready-made inputs.** `examples/input.bullish.json` and `examples/input.bearish.json` (price 1676.2, the real market of
  2026-11-21): copy one over `input.json` for the round and update `price.current` to the current real price first; restore
  your own `input.json` afterwards.
* **A coherent input.** The sample `input.json` mixes bearish macro with bullish technicals, and on the final deployment it
  produced `neutral` in blocks 7 and 8. Make every group lean one way before `studio_snapshot.py`. For a bullish round:
  price `ret_7d` 4 and `ret_30d` 6, derivs `oi_d1_pct` 1.5, `oi_w_pct` 4, `liq_side` `shorts`, macro `fear_greed` 68,
  `dxy_weekly_pct` -0.6, `spx_drawdown_pct` -0.5, `equity_breadth_pct` 62, `fed_status` `easing`; mirror them for a
  bearish round.
* **A realistic price.** Set `price.current` to the real ETH price (for example from
  `https://data-api.binance.vision/api/v3/ticker/price?symbol=ETHUSDT`). At resolution the asserted price must lie within
  the allowed deviation (3 %) of the real candle of the observation hour; otherwise the result is `excluded` and the
  client takes the money whatever the stance. The sample price 2995.4 is far from the real market.
* **The market decides the win.** A `hit` also needs the real price to move in the stance's direction by at least the flat
  band (3 %) over the horizon. Run one bullish and one bearish round at the same time: one of them is likely to win, the
  other shows the `miss` path.

One round: ACC1 `create_bounty(7, 3600, 3600, 0)`, Value 2 -> N_f. ACC2: `studio_snapshot.py 60 --horizon 7
--bounty-ref <N_f>`, `submit_snapshot` (verdict), `analyze_layer(macro)`, `analyze_layer(manipulation)`. ACC2 on the
bounty: `commit(N_f)`, Value 2 (the short number, not a snapshot id); at once `analyze` on the verdict. After FINALIZED
plus 2-3 minutes: `get_bounty(N_f)`: `DELIVERED` and a stance. Keep a directional one for block 11; a neutral one is a
valid delivery (it settles `hit` with 2 GEN each, `miss` or `excluded` with 4 GEN to the client), run the next round
with the coherent input above.

### Block 9. Resolve on real candles (about 35 min, only ACC1 needed)

A self-contained block: it deploys a **helper ledger L2** in which the "verdict contract" is the account ACC1, so
entries can be registered by hand with past dates and resolved at once on real, historical candles.

**9.1 Deploy L2.** ACC1, `eth_outcome_ledger.py` with `(verdict_contract=ACC1,
"https://data-api.binance.vision/api/v3/klines?symbol=ETHUSDT&interval=1h&startTime={start_ms}&limit=1", 300, 300)`.
Record the address. `get_policy()`: `verdict_contract` = ACC1, bands 300/300, `subscribers` = 0.

**9.2 "bad" entry with an absurd price.** Pick `analyzed_at` = four days before today, at minute 30 of some hour
(example for 20 November: `2026-11-16T12:30:00Z`) and `observed_at` ten minutes earlier (`...12:20:00Z`). ACC1
`L2.register(snapshot_id=aaaa...a, submitter=ACC1, bounty_ref=none, stance=bullish, conviction=60,
risk_level=moderate, horizon_days=1, analyzed_at, observed_at, asserted_price_e8=100000000)`: `SUCCESS`.
`get_status(aaaa...a)` = `REGISTERED`; `get_entry`: `resolve_not_before_s` in the past (`analyzed_at` rounded up to the
next hour, +1 day, +7200 s).

**9.3 Resolve "bad" (ACC3 on L2).** `resolve(aaaa...a)`: `SUCCESS` after a consensus round (2-4 minutes). If it is
refused with `price source HTTP status 451`, that host is closed to the validators: redeploy L2 with another host of
the same format. View: `get_status` = `RESOLVED`; `get_resolution`: `result` = `excluded`, `evidence_ok` = false,
`obs_low_e8` <= `obs_open_e8` <= `obs_high_e8`, `ref_open_e8` and `end_open_e8` > 0, `deviation_bps` about 9995. Record
`obs_high_e8`.

**9.4 Price at the hour high.** ACC1 `L2.register` with the same fields but `snapshot_id=bbbb...b` and
`asserted_price_e8` = the recorded `obs_high_e8`; ACC3 `resolve(bbbb...b)`. Expected: `evidence_ok` = true,
`deviation_bps` = 0, `result` in `hit` / `miss` / `abstain` (not `excluded`); the realised direction follows
`return_bps` against the 300 bps band (`flat` when |return| < 300, so a bullish stance is a `miss`). Record `result`,
`realized`, `return_bps`.

**9.5 Price 5 % above the high.** `snapshot_id=cccc...c`, `asserted_price_e8` = `obs_high_e8` x 1.05 rounded down;
register, then ACC3 `resolve`. Expected `evidence_ok` = false, `result` = `excluded`, `deviation_bps` about 500.

**9.6 Counters and immutability.** `L2.get_scorecard()`: `registered` 3, `resolved` 3, `unresolved` 0, `excluded` 2.
ACC3 `resolve(aaaa...a)` again: refused `already resolved; resolutions are immutable`.

### Block 10. gltest on the final addresses (about 40 min, after block 1)

Run section 2 with the three environment variables set to `VERDICT`, `LEDGER`, `BOUNTY`; G3 is not part of this
block (see section 2). Expected: all selected tests `PASSED`. Counters and `get_solvency()` grow; compare increments.

### Block 11. Time-gated checks (3-8 days of waiting; minutes of work)

Needs blocks 7 and 8. Write down the times when you start them. Read `get_bounty` of the delivered bounty first and note
`resolve_deadline_s` (= analysis time + horizon + 1 hour + 14 days). Send the resolution before it: once it has passed,
anyone can call `expire` on a still-`DELIVERED` bounty, which ends `EXPIRED_NO_RESOLUTION` and simply returns each side
its own money, so the win path would be lost. A resolution that arrives before anybody expires the bounty still settles
normally.

**11.1 Expiry without delivery (the bounty N_e from block 7, or any block-8 bounty that got no delivery).**
When: `deliver_deadline_s` (from `get_bounty`, Unix seconds) + 259200 s (3 days). ACC3 `expire(N_e)`: `SUCCESS`,
`status` = `EXPIRED_NO_DELIVERY`. `get_claimable(ACC1)` grew by 2 GEN (the reward); ACC2's did not; `get_solvency()`:
`forfeited_total` grew by 2 GEN (the bond burned), `ok` = true. ACC1 `withdraw`.

**11.2 Resolution and payout (the delivered bounty N_d, and the directional one from block 8).**
When: after `resolve_not_before_s` from `LEDGER.get_entry` (about 7 days and 2 hours after the analysis). ACC3,
`LEDGER.resolve(snapshot_id)`; wait for FINALIZED plus a few minutes. Expected: `LEDGER.get_resolution` has a result;
`BOUNTY.get_bounty`: `SETTLED` with the same `result`. Payout:
* `hit` with stance `bullish` or `bearish`: `get_claimable(ACC2)` = 4 GEN (reward and bond);
* `miss` or `excluded`, whatever the stance: `get_claimable(ACC1)` = 4 GEN. `excluded` is what the ledger returns when the
  asserted price is farther than the allowed deviation from the real candle of the observation hour, so a snapshot with a
  price far from the real market always ends here;
* `abstain` (stance `inconclusive`) or a `hit` with a `neutral` stance: each side gets its own 2 GEN.

The party that is owed money calls `withdraw`; its balance grows; `get_solvency()`: the settled bounty's funds are no
longer locked and `ok` = true.

---

## 4. Recording results

For every step write `OK` or the difference, with the step number and the exact text Studio returned (copy errors
verbatim, do not paraphrase). Fill [`TEST_RESULTS.md`](TEST_RESULTS.md); open findings go to
[`TEST_REGISTER.md`](TEST_REGISTER.md).

## 5. Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| `resolve` fails with `price source HTTP status 451` | default `api.binance.com` host is blocked for validators | redeploy the ledger with `data-api.binance.vision` |
| `analyze` is red, several leader changes, snapshot still `SUBMITTED` | `UNDETERMINED` (validators disagreed) | call `analyze` again, count the attempts |
| `layer macro not analyzed yet` | layers were not run first | `analyze_layer` for `macro` and `manipulation`, then `analyze` |
| step results look like another deployment | a different contract is selected in Studio | run the fingerprint check (3.0) |
| `get_policy` shows `ledger_set` but nothing reaches the ledger | the verdict points at another ledger | `get_ledger_history()`: last entry must be `LEDGER`; fix with `set_ledger` (limit 5 changes) |
| `gen_call failed: RLP string ends with N superfluous bytes` | view with a large string argument | use `get_ids_page`, validate snapshots locally |
| `get_claimable` differs from the step | an earlier block left a balance | note the value before the step and compare the increase |
| pasted command runs two commands | old text left in the `cmd` line | press Esc, paste again |
