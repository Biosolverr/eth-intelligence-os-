# To fill after block 11 (and block 8)

Internal checklist, delete this file before publishing the repository. Every place below carries a marker in the text:
search for `BLOCK11-PENDING`, `BLOCK8-PENDING`, `LABEL-PENDING` and `_PENDING` (for example
`grep -rn "BLOCK11-PENDING\|BLOCK8-PENDING\|LABEL-PENDING\|_PENDING" docs README.md`).

## Data to bring back from Studio

Block 8 is closed (bounties 8 bullish and 9 bearish delivered). Block 11 (only 11.2 is left), in the order the times arrive:

* 11.1 (bounty 1, expiry with the forfeited bond): DONE and recorded in `TEST_RESULTS.md` section 5. Optional: the
  `get_solvency()` after ACC1's `withdraw` was not captured.
* 11.2a, bounty 0: from 2026-11-25 17:00 UTC (`resolve_not_before_s` 1795626000).
* 11.2b-d, bounties 7, 8, 9: from 2026-11-28 19:00 UTC (`resolve_not_before_s` 1795892400); send before the bounty's
  `resolve_deadline_s` (1797095139, 1797096878, 1797097712).
* For each: the time of `resolve`, `LEDGER.get_resolution` (`result`, `realized`, `return_bps`, `evidence_ok`),
  `get_bounty` (`status`, `result`), `get_claimable` before and after `withdraw`, final `get_solvency()`.
* The block labels of snapshots #6 and #7 in `TEST_RESULTS.md` section 4.1 (the operator list has none).

## Places to update

| File | Where | What to do |
|---|---|---|
| `docs/TEST_RESULTS.md` | section 1, row "block 11" | set PASS / FAIL |
| `docs/TEST_RESULTS.md` | section 4.2, row 11 | set the result and the evidence |
| `docs/TEST_RESULTS.md` | section 4.1, snapshot table (`LABEL-PENDING`) | add the block of #6 and #7 |
| `docs/TEST_RESULTS.md` | section 5 (`BLOCK11-PENDING`, `B11_*_PENDING`, five rows) | fill the "Observed" cells and the times |
| `docs/TEST_REGISTER.md` | rows `SR02-SR04` and `Time-gated` | replace PENDING with the observed result; if a finding appears, add it to the review tables |
| `README.md` | the "Status" paragraph, line "Still open" (`BLOCK11-PENDING`) | state the block 8 / 11 result, remove "Still open" if all passed |
| `docs/ARCHITECTURE.md` | section 6, "Still open on the live network" (`BLOCK11-PENDING`) | move the closed items to "Observed", keep only what is still open |
| `docs/TESTING_GUIDE.md` | block 11 | change only if the observed behaviour differs from the text (payout table, times) |

## Final steps

1. `grep -rn "PENDING" docs README.md` returns nothing.
2. Remove this file and `docs/archive/REHEARSAL_DEPLOYMENTS.md` if you do not want the rehearsal history published
   (`TEST_RESULTS.md` section 4.1 mentions it; remove that sentence too).
3. Re-run `python -m pytest tests/direct tests/unit -q` (expected 523 passed) after any code change.
