# Category V4 Final Seal Checkpoint

This is the formal governance checkpoint for the completed Category V4 Final
Seal batch. The evaluation harness remains the authority for acceptance; this
document records the frozen result and does not add a runtime decision owner.

```text
CATEGORY_V4_FINAL_SEALED = YES
ACCEPTANCE_VERSION = category-v4-final-seal-v2
FINAL_SEAL_ROUNDS = 3
GROUPS_PER_ROUND = 53
TOTAL_LIVE_CALLS = 159

ROUND_1 = PASS (53/53)
ROUND_2 = PASS (53/53)
ROUND_3 = PASS (53/53)

TOTAL_HTTP_200 = 159
TOTAL_CLASSIFIER_ACCEPTED = 159
TOTAL_CLASSIFIER_INVALID = 0
TOTAL_EXACT_CATEGORY_MATCHES = 159
TOTAL_CATEGORY_STATE_MISMATCHES = 0
TOTAL_PRIMARY_CATEGORY_MISMATCHES = 0
TOTAL_RESOLUTION_REASON_MISMATCHES = 0

CONFIGURATION_FINGERPRINT = 9f93fda69106a7fe0a43c4c87550ceed022735687e0603377db38d4dc6a6ae86
DEPLOYMENT_FINGERPRINT = 3e6de75b29724801efd67b1acca89dc8301754f26fdd1b44de72ea2833ad8b08
DEPLOYMENT_SNAPSHOT_CONTRACT_VERSION = category-deployment-snapshot-v1

AUTHORITATIVE_ASSESSOR = assess_final_seal_batch
LIVE_ACCEPTANCE_RERUN = NO
REPLACEMENT_ROUNDS = NO
AUTOMATIC_RETRY = NO
ROUND_4 = NO
```

The three complete round reports were assessed offline by
`assess_final_seal_batch`. Historically these reports were captured as root
`.env.category-*` files. Their current canonical local paths are
`docs/category-v4-final-seal/category-final-seal-round{1,2,3}.json`; all five
evidence files remain `IGNORED_LOCAL` and are not part of this checkpoint
commit. The operator harness is
`scripts/RUN_FINAL_SEAL_ASSESSMENT.ps1`.

The Category `Classifier` remains the sole Category decision owner. MaiAgent
remains proposal-only; this checkpoint introduces no Writer path, fallback,
retry, rescue, backfill, duplicated Category logic, or second source of truth.
No Golden, production semantic, test, or upstream sealed-phase changes are
part of this checkpoint. Existing unrelated dirty worktree state is preserved.
