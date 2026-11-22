# Test results

Results of the runs described in [`TESTING_GUIDE.md`](TESTING_GUIDE.md). Only what was actually run is listed; open
and time-gated items are marked as such. The register of findings is [`TEST_REGISTER.md`](TEST_REGISTER.md).

## 1. Summary

| Level | Scope | Result | Status |
|---|---|---|---|
| 1a Static | `genvm-lint` on the three contracts | passed (verdict 24, ledger 16, bounty 16 methods) | PASS |
| 1b Direct mode | 463 contract tests + 60 client/UI tests | **523 passed** in 76.5 s | PASS |
| 1c Mutation, client/UI | 11 mutants | 11 killed, none survived | PASS |
| 1c Mutation, contracts | 139 mutants (verdict 68, ledger 35, bounty 36) | 139 killed, 0 survived | PASS |
| 2 gltest on Studio, final deployment | G1, G2, G4, G5, G6, G9 (one run) and G7 (one run) | **7 of 7 passed** | PASS |
| 2 gltest, G3 and G8 | not run on the final deployment | covered by runbook 3.3 and block 9; earlier runs passed | see 3.3 |
| 3 Studio runbook, blocks 1-7, 9, 10 | final deployment | all expected results matched | PASS |
| 3 Studio runbook, block 8 | directional verdicts for the win path | bullish bounty 8 and bearish bounty 9 delivered (see 4.4) | PASS |
| 3 Studio runbook, block 11 | time-gated: expiry without delivery, resolution, payout | 11.1 expiry with forfeited bond: PASS; 11.2 resolution and payout (bounties 0, 7, 8, 9): waiting | **PENDING** (11.1 done) |

<!-- BLOCK11-PENDING: when block 11 is done, change its row above to PASS/FAIL and fill section 5 -->

## 2. Level 1: static and direct mode

Environment: Linux, Python 3.12.3, pytest 9.2.0, genlayer-test 0.29.2, genlayer-py 0.16.3, genvm-linter 0.11.0,
GenVM SDK v0.2.16 (direct mode), run on 2026-11-20.

* `genvm-lint check` on each contract: `Lint passed (3 checks)`, `Validation passed`; methods: `eth_intelligence.py` 24
  (14 view, 10 write), `eth_outcome_ledger.py` 16 (11 view, 5 write), `eth_analyst_bounty.py` 16 (9 view, 7 write).
* `python -m pytest tests/direct tests/unit -q`: **523 passed in 76.48 s**. A second run just before packaging the repository: 523 passed in 31.10 s (SDK already cached).

| File | Tests |
|---|---:|
| tests/direct/test_eth_intelligence.py | 78 |
| tests/direct/test_layers.py | 53 |
| tests/direct/test_hardening.py | 25 |
| tests/direct/test_v5_identity.py | 30 |
| tests/direct/test_ledger.py | 105 |
| tests/direct/test_bounty.py | 79 |
| tests/direct/test_bounty_fuzz.py | 41 |
| tests/direct/test_review_findings.py | 50 |
| tests/direct/test_builder_integration.py | 2 |
| **direct total** | **463** |
| tests/unit/test_client_and_ui.py | 34 |
| tests/unit/test_client_hardening.py | 18 |
| tests/unit/test_client_layers.py | 8 |
| **client/UI total** | **60** |

* `python scripts/mutate_client.py`: C1-C11, all `KILLED`, `SURVIVORS: none`.
* `python scripts/mutate.py`: `SURVIVORS: none`: **139 of 139 mutants killed** (verdict 68, ledger 35, bounty 36), no mutation pattern missing from the source. The run was done in several segments (restarted from the first unprocessed mutant, order unchanged); each mutant ran exactly once.

Direct mode is CPython with a mocked LLM and mocked web. It is **not** validator consensus and not GenVM WASM; levels 2
and 3 close that gap.

## 3. Level 2: gltest on the hosted Studio

Environment (operator machine): Windows, Python 3.12.10, pytest 9.1.1, genlayer-test 0.29.2, network `studionet`
(`https://studio.genlayer.com/api`), `--default-wait-retries 200`, run on 2026-11-20 against the final deployment
(addresses in section 4) through `ETH_VERDICT_ADDRESS`, `ETH_LEDGER_ADDRESS`, `ETH_BOUNTY_ADDRESS`.

Command 1 (`-k "g1 or g2 or g4 or g5 or g6 or g9"`): collected 8, 2 deselected, 6 selected.

| Test | Result |
|---|---|
| `test_g1_zero_price_is_rejected_at_submission` | PASSED |
| `test_g2_unresolved_due_page_view_works_on_a_real_node` | PASSED |
| `test_g4_stranger_cannot_analyze_foreign_snapshot` | PASSED |
| `test_g5_release_snapshot_frees_the_slot` | PASSED |
| `test_g6_bounty_cancel_and_withdraw_moves_value` | PASSED |
| `test_g9_refused_payable_call_refunds_the_value` | PASSED |

`6 passed, 2 deselected in 337.46s (0:05:37)`

Command 2 (`-k g7`): `test_g7_end_to_end_delivery_reaches_the_bounty` PASSED, `1 passed, 7 deselected in 299.89s (0:04:59)`.

Not run on the final deployment:

* **G3** (pause blocks new submissions, not submitted work) needs owner rights, and the gltest account is not the
  deployer of the final contracts. Verified by hand in runbook 3.3 (see section 4). G3 passed earlier on a freshly
  deployed stack (`TEST_REGISTER.md`, "Live evidence").
* **G8** (resolve on real candles) deploys its own ledger. Mirrored by runbook block 9 (section 4); G8 passed earlier
  with `data-api.binance.vision` (`TEST_REGISTER.md`).

## 4. Level 3: Studio runbook on the final deployment

### 4.1 Deployment under test

| Role | Address |
|---|---|
| verdict (`eth_intelligence.py`) | `0x75959426F363B8d7363EF7671e2c30B146be2E72` |
| ledger (`eth_outcome_ledger.py`) | `0xaDA9c28722974830078AFbFD912AEF48143f1d92` |
| bounty (`eth_analyst_bounty.py`) | `0xeFDC090Bd6Ec93d606A81f7012555732e2c7d1eF` |
| helper ledger L2 for block 9 (verdict role = ACC1) | `0x68E3DaFE84Ae15573E9D66E69460D2234F6480fd` |
| ACC1 (owner, client) | `0xd3e5F03720031D71A7c6766C39f36dD7ef3F28B8` |
| ACC2 (analyst) | `0x4E23B18f0ac1C47F06DB7f99Aed9783e31B29e3C` |
| ACC3 (stranger) | `0x662aA10611Ef5F8D874B9A3d54446d5e41D1d367` |

Ledger deployed with price source `https://data-api.binance.vision/api/v3/klines?symbol=ETHUSDT&interval=1h&startTime={start_ms}&limit=1`
and bands 300 / 300. Blocks 1-5 were run again from the start on these addresses after earlier rehearsal deployments
(see `docs/archive/REHEARSAL_DEPLOYMENTS.md`); nothing here relies on those.

Snapshot ids as recorded by the operator, with the block they were made in (the operator gave no block for the last two):

| # | Snapshot id | Block |
|---|---|---|
| 0 | `bac05937156188d1d23d0d352dc90b65e0be6f4c3db80cac35da5d3b64b4d55f` | 7 |
| 1 | `8249135e86c3b4c1a64672339696d3c145fbbd6ee56800c234ea7a04704f9afd` | 7 |
| 2 | `588db10e36239fed8a269c43010772e58ab188c642a5158fb4f2c6cfe3e3d094` | 2 |
| 3 | `cf0475cd0a9d9d778b0a780409aeb14d9348d4685bf967f576a5d71d47fbca45` | 3 |
| 4 | `75dd24b45a6d7b44e59103dfe974c809e622798cbf54784f9e2fda3e97e10765` | 3 |
| 5 | `460b36c2ff58558496b610f62bd68d5963b84e18f899efcc4d8a3e9d9fe980ec` | 3 |
| 6 | `294301e0cba9fc160df0d5a2d66fd685d283c4faa5d43112b0da00925eaeb1eb` | (blocks 3-4, to be labelled) |
| 7 | `7ddc5889d703b952e1a00b0b4601f64fb75ba63b7d7373f6ff90bd6c2b308f97` | (blocks 3-4, to be labelled) |

<!-- LABEL-PENDING: add the missing block labels for snapshots 6 and 7 (operator knows which steps made them) -->

### 4.2 Results by block

"Values recorded" means the observed numbers are given below; "pass reported" means every refusal and success matched
the expected text and the run was accepted, without per-step numbers kept in this document.

| Block | Result | Evidence |
|---|---|---|
| 1 Wiring | PASS | pass reported; ledger `get_policy`, `set_ledger`, subscription and owner-only refusals as expected |
| 2 Verdict main path | PASS | pass reported; snapshot #2 recorded as the verdict used by block 5 |
| 3 Slots, release, pause | PASS | pass reported |
| 4 Frozen rules, owner, ledger | PASS | pass reported; ownership returned to ACC1; `set_ledger` pointed back at the same ledger |
| 5 Ledger (5.1-5.3) | PASS | pass reported; the duplicate `add_subscriber` was refused (`already subscribed`) as required |
| 6 Bounty money and refusals | PASS | values recorded in 4.3 |
| 7 Bounty delivery | PASS | pass reported; two bounties numbered 0 and 1 created in this block; `get_solvency` after the block: balance = `locked_total` = 8 GEN, `unaccounted` = 0 |
| 8 Payout attempts | PASS | values recorded in 4.4; the payout itself is checked in block 11 |
| 9 Resolve on real candles | PASS | values recorded in 4.5 |
| 10 gltest | PASS | section 3 |
| 11 Time-gated checks | **PENDING** (11.1 PASS) | section 5 |

### 4.3 Block 6 (values recorded)

Block 7 ran first, so the contract already held 8 GEN; totals below are therefore baseline-relative.

* 6.1: `create_bounty(7, 3600, 3600, 0)` with 2 GEN returned `2`; `get_bounty(2)`: `OPEN`, client ACC1, reward
  2000000000000000000; `get_solvency`: balance = `locked_total` = 10 GEN, `unaccounted` = 0, `ok` = true. ACC2 `cancel_bounty`:
  refused `unauthorized: only the client`. ACC1 cancel and `withdraw` succeeded; a second `withdraw` was refused
  `nothing to withdraw`. `get_solvency` returned to balance = `locked_total` = 8 GEN, `claimable_total` = 0.
* 6.2: the five refused creations (horizon 6, commit window 100, delivery window 200000, min conviction 101, value 0)
  left `get_bounty_count` unchanged and, after one `withdraw`, `get_solvency` = 8 GEN balance = `locked_total`,
  `claimable_total` = 0, `unaccounted` = 0, i.e. every refused value came back.
* 6.3: `get_rejection`: ACC1 `client_cannot_commit`, ACC2 `bond_must_equal_reward`, ACC3 `unknown_bounty`. After the
  withdrawals `get_solvency`: 8 GEN, `unaccounted` = 0.
* 6.4: bounty `4`: `created_at_s` 1795026136, `commit_deadline_s` 1795029736; the early `expire` was refused `not expirable`;
  the late `expire` set `EXPIRED_NO_COMMIT` with `settled_at_s` 1795030691 (after the deadline); ACC1 withdrew the reward.

### 4.4 Block 8 (values recorded)

Block 8 needs delivered verdicts with a directional stance (`bullish` / `bearish`); only those can win. The verdicts of block 7
and of the first round of this block were `neutral`, with the sample price 2995.4 that is far from the real market. They were
kept (they exercise the `excluded` path in block 11) and a bullish and a bearish round were added with a coherent input and a
price near the real market (`examples/input.bullish.json`, `examples/input.bearish.json`, price 1676.2 on 2026-11-21).

| Bounty | Snapshot id | Stance, conviction, risk | Asserted price (e8) | Delivered | `resolve_not_before_s` | `resolve_deadline_s` |
|---|---|---|---:|---|---:|---:|
| 0 (block 7) | `bac05937156188d1d23d0d352dc90b65e0be6f4c3db80cac35da5d3b64b4d55f` | `neutral`, 45, `moderate` | 299540000000 | `DELIVERED` | 1795626000 (2026-11-25 17:00 UTC) | 1796829377 |
| 7 (block 8, round 1) | `69df13fa4494bbbc436b0c3e0c7ff2507f17f8040e0134a5ba240a2daab33bbb` | `neutral`, 45, `elevated` | 299540000000 | `DELIVERED` | 1795892400 (2026-11-28 19:00 UTC) | 1797095139 |
| 8 (block 8, bullish round) | `4a726d2c70a0c386c950a8daade28b6a9c51e2023ac5ad5acb3ae2008b477373` | `bullish`, 45, `moderate` | 167620000000 | `DELIVERED` | 1795892400 | 1797096878 |
| 9 (block 8, bearish round) | `e28c3ff28c29dac5fd4ed89f84980f292328332d770c4b624c79147de2d071b8` | `bearish`, 65, `elevated` | 167620000000 | `DELIVERED` | 1795892400 | 1797097712 |

Bounties 8 and 9 share the candles: reference = open of 2026-11-21 17:00 UTC (`ref_ms` 1795280400000), end = open of
2026-11-28 17:00 UTC (`target_ms` 1795885200000), flat band 3 %. Expected in block 11 if the evidence check passes: price up
by at least 3 %: bounty 8 `hit` (analyst 4 GEN), bounty 9 `miss` (client 4 GEN); down by at least 3 %: the reverse; inside the
band: both `miss` (a directional stance against a flat market), client 4 GEN each. Bounties 0 and 7 are expected `excluded`
(client 4 GEN): the asserted price 2995.4 is far from the real market.

### 4.5 Block 9 (values recorded, helper ledger L2)

Entries were registered by ACC1 (acting as the verdict contract of L2) with `analyzed_at` = `2026-11-16T12:30:00Z`,
`observed_at` = `2026-11-16T12:20:00Z`, `horizon_days` = 1, stance `bullish`. Resulting entry (all three snapshots):
`obs_ms` = 1794830400000 (2026-11-16 12:00 UTC), `ref_ms` = 1794834000000 (13:00), `target_ms` = 1794920400000 (2026-11-17
13:00), `resolve_not_before_s` = 1794927600 (2026-11-17 15:00 UTC, in the past). Source: `data-api.binance.vision`, no HTTP 451.

Real candles fetched by the validators (equal on all validators): observation hour open 180614000000, high 180640000000,
low 178711000000 (e8); reference open 180010000000; end open 182348000000; return 129 bps; flat band 300; realised `flat`.

| Step | Asserted price (e8) | Expected | Observed |
|---|---:|---|---|
| 9.3 `aaaa...a` | 100000000 | `excluded`, deviation about 9995 | `excluded`, `evidence_ok` false, `deviation_bps` 9994 |
| 9.4 `bbbb...b` | 180640000000 (= high) | evidence ok, deviation 0 | `evidence_ok` true, `deviation_bps` 0, `result` `miss` (bullish vs flat) |
| 9.5 `cccc...c` | 189672000000 (= high x 1.05) | `excluded`, deviation about 500 | `excluded`, `evidence_ok` false, `deviation_bps` 500 |
| 9.6 | | registered 3, resolved 3, unresolved 0, excluded 2 | `registered` 3, `resolved` 3, `unresolved` 0, `excluded` 2, `bullish:miss` 1 |
| 9.6 repeat `resolve(aaaa...a)` | | refused `already resolved; resolutions are immutable` | as expected |

## 5. Block 11: time-gated checks (pending)

<!-- BLOCK11-PENDING: fill every "Observed" cell from the operator's results, then update the summary table in section 1, TEST_REGISTER.md (SR02-SR04, Time-gated), the README status paragraph and ARCHITECTURE.md section 6 "Still open on the live network" -->

| Step | Bounty / snapshot | Earliest time | Expected | Observed |
|---|---|---|---|---|
| 11.1 `expire` without delivery | block-7 bounty 1 with the foreign-horizon verdict (never delivered) | its `deliver_deadline_s` 1795014853 + 259200 s = 1795274053 (2026-11-21 15:14 UTC) | `EXPIRED_NO_DELIVERY`; ACC1 `claimable` +2 GEN (reward); ACC2 none; `forfeited_total` +2 GEN; `ok` true | **PASS** (recorded). Before: `COMMITTED`, analyst ACC2, bond 2 GEN; `get_claimable` ACC1 and ACC2 = 0; `get_solvency`: balance = `locked_total` = 20.002 GEN, `claimable_total` 0, `forfeited_total` 0. `expire` by ACC3: `SUCCESS`, `settled_at_s` 1795280470 (2026-11-21 17:01 UTC), `EXPIRED_NO_DELIVERY`. After: `get_claimable` ACC1 = 2 GEN, ACC2 = 0; `get_solvency`: balance 20.002 GEN, `locked_total` 16.002 GEN (-4), `claimable_total` 2 GEN, `forfeited_total` 2 GEN, `unaccounted` 0, `ok` true. ACC1 `withdraw`: `SUCCESS` (reported; the solvency after the withdrawal was not captured) |
| 11.2a `resolve` bounty 0 | snapshot `bac05937...` | 2026-11-25 17:00 UTC | `excluded` (asserted 2995.4); `SETTLED`; ACC1 `claimable` +4 GEN | B11_2A_PENDING |
| 11.2b `resolve` bounty 7 | snapshot `69df13fa...` | 2026-11-28 19:00 UTC | `excluded`; `SETTLED`; ACC1 +4 GEN | B11_2B_PENDING |
| 11.2c `resolve` bounty 8 (bullish) | snapshot `4a726d2c...` | 2026-11-28 19:00 UTC | `hit` and ACC2 +4 GEN if the price rose 3 % or more, else `miss` and ACC1 +4 GEN | B11_2C_PENDING |
| 11.2d `resolve` bounty 9 (bearish) | snapshot `e28c3ff2...` | 2026-11-28 19:00 UTC | `hit` and ACC2 +4 GEN if the price fell 3 % or more, else `miss` and ACC1 +4 GEN | B11_2D_PENDING |

Note on the totals: `get_solvency` holds 20.002 GEN, 0.002 GEN more than the four 4-GEN bounties of the runbook and the open ones of blocks 7 and 8; the difference is most likely the small bounty left by gltest G7 (delivered, not yet resolved). `unaccounted` is 0, so nothing is lost.

Times and values to record: the `deliver_deadline_s` and `resolve_not_before_s` actually read, the transaction times, the
`result` / `realized` / `return_bps` / `evidence_ok` returned by the ledger, the `get_claimable` of ACC1 and ACC2 before and
after `withdraw`, and the final `get_solvency()`. `resolve` must be sent before the bounty's `resolve_deadline_s`.

## 6. Deviations from the runbook and what was learned

| # | Observation | Handling |
|---|---|---|
| 1 | The runbook's absolute `get_solvency` / `get_bounty_count` numbers only hold on an empty contract; running block 7 before block 6 (the recommended order) shifts them (for example `locked_total` 10 GEN instead of 2 GEN in 6.1). | Not a contract difference. The guide now states increments over a baseline. |
| 2 | Refused payable calls (`create_bounty`, `commit`) finish `SUCCESS` and are not red. The reason is in `get_rejection`. | Documented in the guide (3.1). |
| 3 | In 4.2 the refusal text for `analyze_layer(quant)` on a frozen snapshot depends on the order: after `release_snapshot` the contract answers `snapshot is not in SUBMITTED state` instead of `layer quant is in arith mode`. | Documented in the guide (4.2). Both refusals are correct. |
| 4 | The Studio contract list shows several deployments with identical-looking `get_policy()` output; one session mixed up two deployments. | Fingerprint check added to the guide (3.0); the final run was repeated from block 1 on one deployment. |
| 5 | Studio logs of one transaction were no longer available when the results were collected (6.4 late `expire`). | The final state read through `get_bounty` is recorded above. |
