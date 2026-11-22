# ETH Intelligence - GenLayer-native analytical protocol

**Three contracts, five layers, one rule: no verdict without GenLayer validator consensus, and no verdict shown as final until the protocol says so.**
No external LLM, no local consensus, no fallback verdict.

> **Status (checked 2026-11-20).** Direct-mode and client tests: **523 passed** (463 contract tests + 60 client/UI tests on a fake RPC); `genvm-lint` passes on all three contracts; mutation checks: **139 contract mutants** (68 verdict, 35 ledger, 36 bounty) and **11 client/UI mutants**, all killed, none survived. Direct mode is CPython with a mocked LLM and web: it is not validator consensus.
> **Live on the hosted Studio (`studionet`), final deployment (table below):** gltest G1, G2, G4, G5, G6, G9 and G7 **passed** on these exact contracts (7 of 7). The manual runbook (`docs/TESTING_GUIDE.md`, section 3) was run on them: blocks 1-10 matched every expected result, including a verdict delivered through the real chain (verdict -> ledger -> bounty, `emit(on='finalized')`), refused payable calls returning their value, and resolution on real Binance candles through `data-api.binance.vision` on a helper ledger (block 9; the default `api.binance.com` answered `HTTP status 451` to the hosted-Studio validators in an earlier run, so a new deployment should use `data-api.binance.vision`). **The main ledger of the final deployment was deployed with `api.binance.com` and bands 600/600, so whether it can resolve is decided by block 11.** G3 (pause) and G8 (live resolve) passed earlier on freshly deployed stacks and are mirrored by runbook 3.3 and block 9.
> **Still open (time-gated by contract rules):** the second half of runbook block 11, resolution of the delivered 7-day verdicts and the payout (a bullish and a bearish bounty were delivered in block 8 for it; the `expire` with a forfeited bond, 11.1, passed on the final deployment). <!-- BLOCK11-PENDING: replace this paragraph with the block 11 results; remove "Still open" if everything passed -->
> Also unverified live: fees, the Streamlit client against a live chain, tolerance calibration with many real validator runs. Details: `docs/TEST_RESULTS.md`, `docs/TEST_REGISTER.md`.

## Final deployment under test (hosted Studio)
| Contract | Address |
|---|---|
| verdict `contracts/eth_intelligence.py` | `0x75959426F363B8d7363EF7671e2c30B146be2E72` |
| ledger `contracts/eth_outcome_ledger.py` (price source `api.binance.com`, flat band and max price deviation 600/600 bps) | `0xaDA9c28722974830078AFbFD912AEF48143f1d92` |
| bounty `contracts/eth_analyst_bounty.py` | `0xeFDC090Bd6Ec93d606A81f7012555732e2c7d1eF` |

## What it does
1. **`EthIntelligence`** (verdict): submit a bounded snapshot (id = sha256 of canonical JSON that includes the submitter) -> `analyze(id)`: leader and validators each run the prompt; agreement is judged on a directional score (bullish = +conviction, bearish = -conviction, neutral = 0; scores within 40 of each other, `risk_level` within 1 step; `inconclusive` only matches `inconclusive`) and the leader's own result is what is recorded before the immutable record is written. All evidence **and provenance are submitter-asserted and unverified**. Only the submitter can analyze their snapshot; a snapshot that will never be recorded is freed with `release_snapshot` (anyone may release a stale one).
1b. **Layers** (quant, flow, macro, manipulation, risk): each has an arithmetic reading (ported from `engine/`) and an AI reading. Default: macro + manipulation get **their own validator consensus** (`analyze_layer`, one transaction each, run BEFORE `analyze`); quant, flow, risk are formulas. The owner can promote any layer with `set_layer_mode` (affects only future snapshots). Default cost: 3 consensus rounds per verdict.
2. **`EthOutcomeLedger`** (accountability): graded **forward-only** from the verdict's own time (no hindsight), with `registered` / `unresolved` / `excluded` always visible (no survivorship), scorecards per submitter. The asserted price must lie inside the observed hour's low-high range (widened by `max_price_deviation_bps`), otherwise the verdict is excluded from hit/miss. The verdict contract pushes each recorded verdict with `emit(on='finalized')`. After the horizon anyone calls `resolve(id)`: validators independently fetch three historical hourly candles (exact equality required) and the verdict is scored hit / miss / abstain / excluded. Subscribers (such as the bounty) receive the verdict and the resolution.
3. **`EthAnalystBounty`** (stake on a verdict): a client escrows a reward, one analyst commits with an equal bond, delivers a verdict from the verdict contract, and the ledger's outcome settles the money (`hit` on bullish/bearish pays the analyst reward + bond; `miss` or `excluded` pays the client; `abstain`, `neutral`, `inconclusive` return each side its own money). A refused payable call (bad arguments, wrong bond, closed window) never keeps the money: it is credited back to the sender. A bond that is never earned by a delivery is **forfeited** (stays in the contract; nobody profits from non-delivery). This is a prediction bounty: a single outcome cannot tell skill from luck.
4. **Clients** (`client/`, `app.py`) read only on-chain state and label every result **FINAL / PROVISIONAL / UNKNOWN**; Undetermined is shown as appealable, never as a final failure.
Analytical interpretation of supplied evidence: not a forecast, not verification of the data, not investment advice. Social layer removed. Local `engine/` metrics are diagnostics only.

## Layout
`contracts/` verdict + ledger + bounty (ASCII-only, no comments or docstrings, only the required `Depends` header line; the design rationale lives in `docs/ARCHITECTURE.md`) - `client/` snapshot builder + genlayer-py client - `app.py` Streamlit client - `core.py`+`engine/` deterministic diagnostics (no verdict) - `legacy/` old agents/consensus/backtest (import-guarded, obsolete) - `tests/` (`direct/`, `unit/`, `integration/` = gltest) - `docs/` (ARCHITECTURE, TESTING_GUIDE, TEST_RESULTS, TEST_REGISTER; older runbooks in `docs/archive/`) - `scripts/` (`mutate.py`, `mutate_client.py`, `make_snapshot.py`) - `input.json` (sample input used by `make_snapshot.py` and the UI) - `examples/`.

## Verify
```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
for f in contracts/*.py; do genvm-lint check $f; done
# direct mode needs a GenVM SDK tarball; `latest` (v0.3.0-rc7) has none -> seed v0.2.16:
python -c "from gltest.direct.sdk_loader import download_artifacts as d; d('v0.2.16')"
python -m pytest tests/direct tests/unit -q    # 523 tests; direct mode != validator consensus
python scripts/mutate.py                       # 139 deliberate contract bugs must all be caught (~50 min)
python scripts/mutate_client.py                # 11 deliberate client/UI bugs must all be caught
```
Live tests (need a GenLayer node; without one they skip): `gltest tests/integration/test_review_findings_gltest.py -v -s -rs --network studionet --default-wait-retries 200`. To run them on existing deployments set `ETH_VERDICT_ADDRESS`, `ETH_LEDGER_ADDRESS`, `ETH_BOUNTY_ADDRESS`. Run G3 and G7 separately (`-k g3`, `-k g7`), they take about 5-7 minutes each. Full instructions for all three test levels: `docs/TESTING_GUIDE.md`.

## Deploy & test in Studio
Deploy order: verdict (no args) -> ledger(verdict_addr, price_url_template, flat_band_bps, max_price_deviation_bps) -> `verdict.set_ledger(ledger)` -> bounty(ledger_addr) -> `ledger.add_subscriber(bounty_addr)` (ledger owner). Follow `docs/TESTING_GUIDE.md` (section 3, the Studio runbook).
UI/client (not yet exercised live): `export ETH_INTEL_CONTRACT=0x<verdict> ETH_LEDGER_CONTRACT=0x<ledger> GENLAYER_PRIVATE_KEY=0x<testnet key> ETH_UI_LOCAL_ONLY=1` -> `streamlit run app.py --server.address 127.0.0.1`.
**Security:** the server key signs for EVERY visitor of the page. On any shared host set `ETH_UI_PASSWORD` instead of `ETH_UI_LOCAL_ONLY`, use a throw-away testnet key, or use a browser wallet (genlayer-js). Protocol actions stay locked without one of the two; a non-pinned contract address needs explicit confirmation.
**Known Studio quirk:** the hosted Studio rejects a view call whose string argument is large (about 1.4 KB): `gen_call failed: RLP string ends with N superfluous bytes`. The client's `validate_snapshot` view takes the whole snapshot, so on that Studio validate locally instead; writes with the same payload work.

## Open by decision (P3, with Studio data)
model-written layer notes still feed the final prompt - one flat band for all horizons (no base rates yet) - `conviction` not graded - arithmetic layers ignore many snapshot fields (ported engine) - a hostile owner can re-pause intake repeatedly (needs a multisig owner) - the bounty is a single-outcome bet, not a skill measure - the bounty owner-free design trusts the ledger and the verdict contract it was pointed at.

## Not done / planned
genlayer-js browser frontend - tolerance calibration with real validator LLMs - fee handling in the Python client - a keeper that calls `resolve` - on-chain port of `engine/` - validator-fetched input evidence - isolation of appeals (factory) - contract upgrade path.
[README.md](https://github.com/user-attachments/files/35237543/README.md)
