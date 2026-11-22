# Test register (v5: layers + P1/P2 hardening + bounty + round-3 review)
Modes: **DIRECT** = in-memory GenVM SDK under CPython with mocked LLM/web (NOT validator consensus, NOT GenVM WASM) · **FAKE** = client/UI against a fake RPC (NOT a chain) · **STATIC** = linter/AST · **MUTATION** = deliberate bugs.
Totals at last run (2026-11-20): `523 passed` (463 contract tests in direct mode + 60 client/UI tests on a fake RPC) · `genvm-lint` passes for all three contracts (verdict 24, ledger 16, bounty 16 methods) · mutation sets: **139/139 contract mutants** (`scripts/mutate.py`: verdict 68, ledger 35, bounty 36) and **11/11 client/UI mutants** (`scripts/mutate_client.py`) killed · **gltest on the hosted Studio, final deployment: G1, G2, G4, G5, G6, G7, G9 passed (7/7)**; G3 and G8 passed earlier on fresh stacks. Live results by block: `TEST_RESULTS.md`.
Reproduce: `TESTING_GUIDE.md` (all three levels), README → Verify.

| Area | Test ids | Expected | Actual | Mode | Status |
|---|---|---|---|---|---|
| Lint / schema, all three contracts | — | pass | passed (verdict 24, ledger 16, bounty 16 methods) | STATIC | PASS |
| Snapshot validation: ranges, types, bool, NaN, unknown keys, oversized, source cap, injection vectors, version/asset/horizon | t01–t09, t63, t64 | reject | rejected | DIRECT | PASS |
| Timestamps: stale / future / naive tz / offset normalisation / source-after-snapshot / stale-before-analyze | t10–t15 | per rule | as expected (t15 needs `set_tx_time`) | DIRECT | PASS |
| Duplicates, canonical identity | t16–t18 | duplicate reverts; same id | as expected | DIRECT | PASS |
| Authority: owner-only policy; no result backdoor (AST); analysis not sender-bound (squatting fix) | t19–t22, t58 | per rule | as expected | DIRECT/STATIC | PASS |
| Verdict flow: bullish / bearish / mixed(inconclusive+conflicts) / immutability / association | t30–t34 | recorded, bound to id | as expected | DIRECT (mock LLM) | PASS |
| Conviction cap from structure only; **provenance labels buy nothing** | t36, t37, t62 | cap 80/80, equal for raw/derived | as expected | DIRECT | PASS |
| Unexpected LLM output, unverifiable citations, retry, fenced JSON, hostile summary | t40–t44 | no result / inert | as expected | DIRECT | PASS |
| Validator rule: agree/disagree on stance, conviction, risk, free text, own failure, leader error, leader schema | t50–t57 | per rule | as expected | DIRECT | PASS |
| Paging bounded (verdict + ledger) | t65, l21 | ≤50 per call | as expected | DIRECT | PASS |
| Verdict→ledger emission: finalized-only, exactly once, none if unset/failed, republish guards, one-time wiring | l40–l43 | per rule | as expected **via recorder stub** | DIRECT (stub) | PASS (stub only) |
| Argument shape shared between contracts | l44 | accepted | accepted | DIRECT | PASS |
| Ledger register: sender check, idempotent re-delivery, input validation, constructor validation | l01–l05 | per rule | as expected | DIRECT | PASS |
| Ledger resolve: hit/miss/abstain, band edges, truncation, horizon, immutability, retry, scorecard | l10–l20, l22 | per rule | as expected | DIRECT (mock web) | PASS |
| External source failure: HTTP 4xx/5xx, bad JSON/shape/hour/price, zero price | l18, l19, l31 | never a resolution | as expected | DIRECT (mock web) | PASS |
| Price validator: exact match only, extra keys, leader error, validator failure | l30–l32 | per rule | as expected | DIRECT | PASS |
| Client: finality classification (13 statuses), provisional≠final, undetermined appealable, lookup failure ⇒ UNKNOWN, no hash ⇒ UNKNOWN, no verdict without on-chain state, id mismatch, `leader_only` never, no legacy import | t70–t77, t83–t87 | per rule | as expected | FAKE/STATIC | PASS |
| UI: unconfigured, send failure, FINAL, PROVISIONAL label, UNDETERMINED message | t80–t82, t88, t89 | per rule | as expected | FAKE (AppTest) | PASS |
| Layer arithmetic: reference values; missing inputs ⇒ inconclusive; manipulation triggers; risk build-up; **parity with original `engine/`** (suspicion index exact on 400 random cases; WDI reproduced from layer scores within 0.4 on 400 cases); fuzz 500 snapshots (bounds, ints, determinism, shape) | a01–a07 | per rule | as expected | DIRECT | PASS |
| AI layer output: normalisation, driver grounding/caps, caution layers ignore direction, 14 malformed forms rejected | n01–n06 | per rule | as expected | DIRECT | PASS |
| Layer equivalence: tolerance edges, inconclusive mismatch, **exhaustive proof that opposite stances are never equivalent**, rule with real error objects, `run_validator` on a layer tx | e01–e03, v01 | per rule | as expected | DIRECT | PASS |
| Layer flow: final needs consensus layers first; independent immutable layer records; failed layer does not discard others and is retryable; guards (unknown/arith/stale/paused/after RECORDED); record carries layers+modes+prior+tally; AI may disagree with arithmetic and it stays visible; binding per snapshot; preview; cap still bounds the verdict | f01–f12 | per rule | as expected | DIRECT (mock LLM) | PASS |
| Mode switch: owner-only, validation, promote adds a step, all 5 layers work in both modes, demote ignores a stored result, all-arith needs no layer tx | m01–m05 | per rule | as expected | DIRECT | PASS |
| Prompts: layer prompt minimised to its own groups; final prompt carries layers; exactly 3 LLM calls by default; prompts embed only canonical validated data; hostile layer text inert | p01–p03 | per rule | as expected | DIRECT (prompt spy) | PASS |
| Client orchestration: layers then final, stops at first failing layer with no verdict attempted, retry runs only missing layers, a layer counts only if stored on-chain, all-arith ⇒ final only, `leader_only` never; UI layer table and stop reason | t90–t97 | per rule | as expected | FAKE | PASS |
| **P1 regressions (ledger)**: grading window forward-only; unresolved entries visible; per-submitter scorecards; implausible asserted price excluded (boundary 300 vs 303 bps); submitter case normalised; deviation measured on the observation candle; three-candle validator rule; due-page bounded | l02, s01–s03, p01–p05, v01–v03 | per rule | as expected | DIRECT (mock web) | PASS |
| **P2 regressions (verdict)**: conviction bounded by caution layers (manipulation 100 ⇒ 95→50; risk 90 ⇒ 55; inconclusive caution ignored); per-sender open cap (default 20, slot freed on record, failed submit consumes none); republish cap; two-step ownership; pause auto-expires (and is bounded); ledger re-pointing with public capped history; layer modes frozen at submit (owner flip mid-flight has no effect) | c01–c05, s01–s05 (hardening), o01–o02, p01–p02 (hardening), r01, m04–m07 (layers) | per rule | as expected | DIRECT | PASS |
| Verdict→ledger emission carries submitter (not whoever triggered analysis), verdict time (not asserted observation time), asserted price scaled to e8 | l40–l46 | per rule | as expected **via recorder stub** | DIRECT (stub) | PASS (stub only) |
| **Client/UI P2**: weakest finality across layers+final; earlier-run layers ⇒ UNKNOWN; dry-run advisory (contract rejection stops, failing view does not); new id found among other senders' ids; UI locked without password/local flag; wrong/right password; non-pinned address refused until confirmed; scorecard tab warns about unresolved | t100–t112 | per rule | as expected | FAKE (AppTest) | PASS |
| **Address forms (found in the FIRST real Studio run)**: constructor/`set_ledger`/`propose_owner` accept int (what Studio's form sent), 0x-hex lower/checksum, 20 bytes, `Address`; invalid forms (bool, negative, >=2^160, short hex, garbage, None) revert `invalid address`; stored value really is the intended address | a01–a02 (ledger), a01–a03 (hardening) | per rule | as expected | DIRECT | PASS |
| Test sensitivity | `scripts/mutate.py`, `scripts/mutate_client.py` | every mutant caught | 139/139 contract + 11/11 client/UI killed (re-run in full after the round-3 fixes) | MUTATION | PASS |
| **Real validator agreement** (verdict and two consensus layers recorded) | S05-S06 | recorded | `analyze` / `analyze_layer` reached agreement on the final deployment (runbook 2.6-2.7, 7.5, G7) | LIVE | **PASS** |
| Disagreement / Undetermined / rotation statistics; tolerance calibration with many real runs | S07, SL10 | - | not run as a statistic (only single runs) | - | **NOT TESTED** |
| **Real web access, `.status`, geo-blocking, validators agreeing on prices** | S12 | resolution with real candles | block 9 and G8: `data-api.binance.vision` works, no HTTP 451, equal prices on all validators | LIVE | **PASS** |
| Independent comparison of `ref_open_e8` with the exchange candle (S13); dead-URL ledger (S15) | S13, S15 | - | not recorded / not run | - | **NOT TESTED** |
| **`emit(on='finalized')` delivery + sender == verdict contract** | S08-S09 | REGISTERED / DELIVERED | ledger `REGISTERED` after `analyze`; bounty `DELIVERED` through the real chain (runbook 5.1, 7.5, G7) | LIVE | **PASS** |
| hashlib/datetime/json inside real GenVM; runner-hash acceptance | S01-S03 | works | all three contracts deploy and every submit/analyze/register path runs | LIVE | **PASS** |
| Fees | - | - | not examined | - | **NOT TESTED** |
| Finality transitions (ACCEPTED then FINALIZED) | S16 | per rule | observed in the Studio transaction views | LIVE | **PASS** |
| Appeal behaviour | S17 | - | not run | - | **NOT TESTED** |
| Tolerance calibration with real LLMs (verdict and per layer) | S07, SL10 | — | not run | — | **NOT TESTED** |
| Float arithmetic of layers inside real GenVM | SL02 | reference readings | `preview_layers` equals the reference values (quant 25, flow 35, macro prior 10, manipulation caution 0, risk caution 30), runbook 2.5 | LIVE | **PASS** |
| Final reading layer txs that are only ACCEPTED | SL07 | - | not run | - | **NOT TESTED** |
| `Address.as_hex` format vs the ledger's submitter check; 3 price fetches per validator; 9-arg `emit` | SP01-SP04 | per rule | `register` arrives, `submitter` stored in lower case, resolve fetches three candles, 9 arguments delivered (5.1, 9.3, G7) | LIVE | **PASS** |
| Pause (intake blocked, submitted work continues), open cap, ownership transfer, ledger re-pointing, frozen freshness and layer modes on a real network | SH01-SH06 | per rule | as expected (runbook 3.2, 3.3, 4.1-4.4) | LIVE | **PASS** |
| Automatic expiry of a pause (the pause was lifted by hand in 3.3) | SH01 | - | not run | - | **NOT TESTED** |
| genlayer-js / browser frontend; engine on-chain port; keeper for `resolve` | — | — | not built | — | **NOT TESTED** |

## First real Studio run — log
| # | What happened | Cause | Status |
|---|---|---|---|
| S-1 | Ledger deploy ACCEPTED but result ERROR on all 5 validators: `AttributeError: 'int' object has no attribute 'as_bytes'` at `self.verdict_contract = verdict_contract` | Studio's form sent the `address` argument as a plain integer; the contract assumed an `Address` object. My direct-mode tests wrapped `Address(...)` themselves and so hid the problem | **Fixed** in both contracts (`_to_address` accepts int, str, bytes, Address; clear `invalid address` otherwise) in the ledger constructor, `set_ledger`, `propose_owner`; regression tests + mutants L29/V38/V39. Lesson: constructor/direct-mode arguments are NOT converted by the harness; tests must pass raw forms |
| S-2 | `Address.as_hex` format (U15) | source of SDK v0.2.16 shows EIP-55 checksum `0x` + 40 hex, matching the ledger's regex | Source-confirmed; real runtime still to be observed (SP02) |

## Round-2 review (hostile, by the master prompt) — status
| # | Sev | Finding | Status |
|---|---|---|---|
| P1-A | Critical (claim) | ledger graded from asserted `observed_at` ⇒ up to 96 % hindsight | **Fixed** (forward-only from `analyzed_at`); l02, V34/L14/L15 |
| P1-B | Critical (claim) | survivorship: only resolved entries counted | **Fixed** (`registered/unresolved`, due page); s01–s03, L16/L21/L22 |
| P1-C | Critical (claim) | scorecard polluted by any submitter; asserted price never checked | **Fixed** (per-submitter, excluded on deviation); p01–p05, L18–L25 |
| P2-D | Major | owner could flip layer modes after seeing results | **Fixed** (frozen per snapshot); m04, V22/V23 |
| P2-E | Major | caution layers had no deterministic effect | **Fixed** (layer cap); c01–c05, V24/V25 |
| P2-F | Major | UI showed final-tx finality only; dry-run could block submit | **Fixed**; t101–t106, C1–C6 |
| P2-G | Major | server signer open to every visitor; any contract address accepted | **Fixed** (lock + pin); t107–t110, C7–C9 |
| P2-H | Major | no spam limits; owner pause could freeze forever; ownership untransferable; ledger unrecoverable | **Fixed / bounded**: open cap, republish cap, expiring pause, two-step ownership, re-pointable ledger; residual: Sybil + hostile re-pausing |
| P3 | Minor/quality | model-written layer notes feed the final prompt; flat band ignores horizon + no base rates; conviction ungraded; arithmetic ignores many inputs (12 fields had zero effect); doc polish | **Open by decision** — to be handled with Studio data |
| meta | — | my own overclaims (ledger "strongest use" before checking hindsight/survivorship; "no verdict shown as final" before checking layered finality; mid-flight demotion presented as a feature) | Acknowledged; claims in README/ARCHITECTURE now match tested behaviour |

## Review findings and status (round 1)
| # | Sev | Finding | Status |
|---|---|---|---|
| F-A | Critical (trust claim) | `kind` provenance label was self-asserted yet raised conviction cap 75→100 | **Fixed**: labels `raw/derived` carry no weight; everything declared submitter-asserted; t62/t63, mutants V15/V21 |
| F-B | Major | Client/UI showed Accepted verdicts as final; Undetermined shown as terminal failure | **Fixed**: finality classification + labels; t71b, t83–t89, t88/t89 |
| F-C | Major | `get_ids()` unbounded | **Fixed**: `get_id_count` + `get_ids_page(≤50)`; t65, l21, V16/L12 |
| F-D | Major (risk) | Appeal on one tx recomputes later non-finalized txs of the same contract (shared fate) | **Accepted residual**, documented; factory-per-snapshot out of scope |
| F-E | Major | Ledger depends on unproven web access | **Fixed; live proof PASS** (block 9, G8) → S12 |
| F-F | Major | Docs/code mismatches on finality and trust | **Fixed**: ARCHITECTURE v2, this register |
| earlier | | id-squatting (t58), missing leader-error/leader-schema tests (mutants), harness `warp` limitation, SDK `latest` 404, shemas.py import, fabricated ingestion stub | Fixed / documented |
| new limitation | Info | direct mode cannot load two contracts ("only one contract is allowed") and swallows `emit` | worked around with recorder stub; real behaviour BLOCKED |

## Process notes (what the tests themselves taught)
* Two of my own tests were vacuous when first written (`or True`; prompt slices that picked the instruction text instead of the data). Found by re-reading and by mutation; fixed and made non-vacuous.
* A background mutation run was killed by a tool timeout and a `pkill` once killed its own shell; results were only trusted after re-running on a green baseline (40 + 11 mutants, none survived).
* Known limitations of the layer formulas: macro arithmetic covers only fear_greed and dxy; risk composition is new and unvalidated; thresholds are inherited heuristics, **not validated predictors**.

## Round-3 review (adversarial, code + logic) - status
| # | Sev | Finding | Status |
|---|---|---|---|
| F1 | High | `price.current` of 0 or below 1e-8 passed validation; the ledger needs `0 < asserted_price_e8 <= 1e15`, so `register` reverted AFTER the verdict was recorded: never graded, never settled, a bounty analyst lost the bond | **Fixed** (`price.current >= 0.01`); `TestF1PriceParity`, mutant R01; gltest G1 |
| F2 | High | an open slot was freed only by a successful `analyze`; a stale snapshot could never be analyzed and nothing cancelled it, so the sender was locked out forever | **Fixed** (`release_snapshot`); `TestF2Release`, R02/R03; G5 |
| F3 | Medium | any account could trigger `analyze`/`analyze_layer` on someone else's snapshot (choose when it is recorded; analysis before a bounty commit makes the bounty ignore it) | **Fixed** (submitter only); `TestF3SubmitterOnly`, R04, V03; G4 |
| F4 | High | the owner could pause past the whole bounty delivery window, or tighten `max_age` retroactively, and (as client) collect the analyst's bond | **Fixed**: pause stops intake only; `max_age` frozen per snapshot; a forfeited bond is not paid to anyone; `TestF4OwnerLevers`, R05/R06/R12/R15; G3 |
| F5 | Medium | the ledger owner could remove the bounty from the subscribers and turn a win into a refund | **Fixed** (subscribers at registration keep their promise); `TestF5SubscriberPromise`, R07 |
| F6 | Medium | `inconclusive` cost the analyst nothing but locked the client's reward for the whole horizon; a rejected verdict left no trace | **Fixed** (immediate settlement; `get_ignored`); `TestF6Abstain`, R11/R13/R14. The bounty remains a single-outcome bet (**open by design**) |
| F7 | Medium | evidence was compared with the hour OPEN only: honest intra-hour prices could be excluded and analysts were pushed to assert the open | **Fixed** (observed hour [low, high]); `TestF7CandleRange`, R08/R09, L25 |
| F8 | Low | a view relied on the transaction clock | **Fixed** (`now_s` parameter); `TestF8ViewClock`, R10; G2 |
| T1 | Process | the mutation re-run found three rules with no test in the verdict/ledger suites (V15 unknown source kind, V16 unbounded page, L08 hour check on start/end candles); the old "88/88" did not hold for this snapshot | **Fixed** (`TestCoverageGaps`, `TestF7CandleRange`); V35 re-anchored (it had become equivalent after F3) |
| L1 | Info | gltest findings that were test-code bugs, not contract bugs: consensus layers must run before `analyze`; `contract.account` is `None` by default; OpenBLAS memory error in a subprocess; a dropped RPC poll through a local proxy | **Fixed** in the tests (layer helper, default account, env + retries, read-only retry) |
| U17 | Limit | the hosted Studio rejects VIEW calls with a ~1.4 KB string argument (`validate_snapshot`, `snapshot_id_for`); the same payload works in a transaction | **Open** (use `get_id_count`/`get_ids_page`; validate locally) |

## Live evidence (hosted Studio, gltest) - log
Final deployment (2026-11-20): G1, G2, G4, G5, G6, G9 passed in one run (337 s) and G7 in a second run (300 s); details in `TEST_RESULTS.md`. The table below is the earlier log on freshly deployed stacks.
| # | Scenario | Result |
|---|---|---|
| G1 | zero price refused | PASS |
| G2 | due-page view with `now_s` | PASS |
| G3 | pause stops intake, not submitted work (layers + verdict finalize `MAJORITY_AGREE`) | PASS |
| G4 | stranger cannot analyze | PASS |
| G5 | `release_snapshot` | PASS |
| G6 | bounty value flow incl. `withdraw` | PASS |
| G7 | verdict -> ledger -> bounty delivery via `emit(on='finalized')` | PASS |
| G8 | resolution with real candles (dedicated ledger, past-dated entries, no waiting) | **PASS** with `data-api.binance.vision` (first attempt with `api.binance.com` FAILED: `price source HTTP status 451`, as predicted by U4b). Observed: bad $1 -> excluded (deviation 9995 bps); asserted = hour high -> evidence_ok, deviation 0, return -70 bps, flat -> bullish = miss; high +5 % -> excluded (deviation 500 bps) |
| SR02-SR04 | `expire` with a forfeited bond: **PASS** (final deployment, runbook 11.1: `EXPIRED_NO_DELIVERY`, reward back to the client, bond into `forfeited_total`, `unaccounted` 0). Still open: bounty win payout, resolution of a 7-day verdict, client live | **PARTLY PENDING** (runbook 11.2; 3-8 days by contract rules) <!-- BLOCK11-PENDING: replace with the observed results from TEST_RESULTS.md section 5 --> |
| U4b | High | the default price source `api.binance.com` returns HTTP 451 to the hosted-Studio validators; the ledger cannot resolve anything with it and the template is immutable | **Confirmed live; mitigated.** Deploy with `data-api.binance.vision` (official market-data-only host, same format): confirmed to work for the hosted-Studio validators by G8. The template stays immutable, so a source that breaks later still means a redeploy |

## Manual Studio walk-through (runbook parts A-D) - log
This section is the earlier walk-through on previous deployments. The run on the final deployment (blocks 1-10, block 11 pending) is in `TEST_RESULTS.md`; the runbook itself is `TESTING_GUIDE.md`, section 3.
| Area | Scenarios | Result |
|---|---|---|
| Wiring | deploy, `set_ledger`, `add_subscriber`, owner-only refusals | PASS |
| Verdict B1-B17 | submit/duplicate, stranger refusals, layers, verdict, immutability, republish limit, release, cap, pause, bounds, frozen freshness, frozen layer modes, ownership, ledger history | PASS (`validate_snapshot` view not exercised: U17) |
| Ledger C1-C3 | registered entry and timestamp arithmetic, scorecards, due view, early resolve refused, rebroadcast limit, subscribers, register refusal | PASS |
| Bounty D | create/cancel/withdraw/solvency, invalid creation, commit rules, `EXPIRED_NO_COMMIT` x4, real delivery (`DELIVERED`), `outside_delivery_window`, `horizon_mismatch`, early `expire` refused | PASS |
| U20 | excess balance in the bounty contract that matched the value sent with refused calls | **CLOSED**: after the fix a refused payable call is credited back (`get_rejection`, `unaccounted` = 0); verified on the final deployment by runbook 6.2-6.3 and gltest G9 |
| Time-gated | `EXPIRED_NO_DELIVERY` (forfeited bond): PASS (11.1). Win payout, main-chain `resolve` of 7-day verdicts: PENDING (runbook 11.2) <!-- BLOCK11-PENDING: fill from TEST_RESULTS.md section 5 --> |
Lessons recorded in the runbook: the bounty commit takes the SHORT bounty number, never a snapshot id; run the consensus layers BEFORE committing so only `analyze` has to fit the 60-minute delivery window; the Studio Value field is in GEN (the contract shows wei).

## Round-4 (manual Studio run) findings
| # | Sev | Finding | Status |
|---|---|---|---|
| M1 | High (money) | a REFUSED payable call keeps its value on the hosted Studio (confirmed: sender 25 to 24 GEN, contract 153 to 154 GEN; 94 GEN unaccounted after the session); the bounty has no owner who could return it, and `ok` only detects a shortfall | **Fixed in code**: `create_bounty` and `commit` credit the value back instead of reverting, `get_rejection`, `unaccounted`; direct tests + mutants B27-B31; live re-check pending (G9). The 94 GEN in the first deployment are unrecoverable |
| H1 | Process | the fixes had introduced 3 comments and 5 docstrings into contracts that the README promises are comment-free | **Fixed**; `TestContractHygiene` (comments, docstrings, non-ASCII) |
| T2 | Process | the money contract had only 5 mutants | **Fixed**: 36 (B01-B31, R11-R15), all killed |
| L2 | Info | a plain transfer to the bounty cannot be handled (the linter rejects `__receive__`) | **Open by decision**: such funds would show as `unaccounted` |
| C1 | High (reliability) | the verdict consensus rule (stance exact, conviction within 20, risk within 1 step) gave `UNDETERMINED` after three leader rotations in 2 of 9 live `analyze` runs (30-day snapshots) and needed rotations in 3 more; only 4 of 9 passed in the first round | **Changed**: directional-score equivalence (tolerance 40, risk within 1 step, inconclusive only with inconclusive); direct tests t57-t59, mutants V04-V04f. Live effect NOT yet measured (needs the redeployed verdict) |

