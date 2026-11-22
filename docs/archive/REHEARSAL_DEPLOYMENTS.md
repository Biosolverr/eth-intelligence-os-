# Rehearsal deployments (superseded)

Before the final clean run, two other stacks were deployed in the same Studio account while the runbook was being
rehearsed. They are **not** the deployment under test and no result in `TEST_RESULTS.md` relies on them.

| Stack | verdict | ledger | bounty |
|---|---|---|---|
| rehearsal 1 | `0x8d6D10A29Bf022B868d5E315b79c353d266d93b1` | `0xc15b3ffd7598B56eb45d888Ff71960750434424f` | `0xdb30E8e9AdA487de241Dea66fc8b97ad424e57Ed` |
| rehearsal 2 | `0x547Ec66CBb787666399B2173876942CD8C9470a9` | `0x1Da11D5ee125658Fb4f2836B6b0c5961b20aF4ee` | `0xDB92296A9d79CfEEC235dF768E3d424B036370a3` |

Why this file exists: transactions on the rehearsal stacks contain operator mistakes that a reader of the explorer
could otherwise mistake for test steps.

* On rehearsal 2, the verdict was briefly pointed (`set_ledger`) at addresses that belong to other stacks and then
  pointed back at its own ledger; the ledger of rehearsal 2 also had the bounty of rehearsal 1 added and removed as a
  subscriber. These came from running the runbook while the Studio contract list showed several deployments with
  similar `get_policy()` output.
* The lesson is part of the guide: the fingerprint check (`TESTING_GUIDE.md`, 3.0) and the rule "run every block on one
  deployment; after any mix-up, redeploy and start again".
