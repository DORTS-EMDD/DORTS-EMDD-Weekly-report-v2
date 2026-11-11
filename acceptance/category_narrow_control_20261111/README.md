# Category narrow live control — 2026-11-11

This is an acceptance-only control, not a production report and not a Final
Seal. It used the documented read-only MaiAgent chatbot retrieval endpoint for
the configured Structured Helper, then bound the returned instance identity to
the runtime configuration by exact in-memory equality.

## Frozen plan

The plan was written before the first semantic call:

```text
CONTROL_SET = G100, G101, G93, G66
ROUNDS = 3
PLANNED_LOGICAL_CATEGORY_CALLS = 12
HARD_CAP = 24 total semantic attempts, including transport retries
CONFIGURATION_FINGERPRINT = 695988ff08b5aa792c68abc6dc4ad243aea88f01fe6b2b7caa10ca174006d749
DEPLOYMENT_FINGERPRINT = ab75a4fb9e278c8f93ee60fff8a1deaa9e0a2ef3a9db9086af09a43e8746bbe7
SAME_RUNTIME_HELPER_BINDING = PROVEN
```

G100 and G101 are the locked boundaries. G93 is the adjacent pre-opening test
control that guards against technical-category pollution. G66 is the adjacent
operating timetable control that guards against universal technology
precedence. These are existing Golden controls; no new expected outcome was
invented.

## Result

```text
ACTUAL_LOGICAL_CATEGORY_CALLS = 12
TRANSPORT_ATTEMPTS = 12
TRANSPORT_RETRIES = 0
EVIDENCE_CHAIN = COMPLETE for all 12 rows
```

| Control | Round 1 | Round 2 | Round 3 | Interpretation |
| --- | --- | --- | --- | --- |
| G100 | PASS | PASS | PASS | Locked pre-opening signalling outcome held |
| G101 | FAIL | PASS | FAIL | Inconsistent live boundary; not a stable PASS |
| G93 | PASS | PASS | PASS | Adjacent pre-opening exclusion held |
| G66 | PASS | PASS | PASS | Operational-change boundary held |

G101 used the same request and provider-request identity in all three rounds.
The two failing rounds retained the same unresolved proposal; the passing round
retained the expected `TECHNICAL_DEVELOPMENT` proposal. The evidence therefore
proves current live inconsistency under a contract-valid, same-runtime
deployment, not an input drift or deployment mismatch.

All round reports retain request identity, provider request/response hashes,
parsed proposal, validated `CategoryResult`, configuration/deployment/runtime
fingerprints, and per-row chain hashes. No API key, authorization header, raw
chatbot ID, or raw role content is included in the committed artifacts. The
full snapshot remains local-only under the repository's ignored
`docs/category-v4-final-seal/` evidence path.

No Category guidance, production behavior, schema semantics, Golden outcome,
EventIdentity behavior, Writer call, or production report changed in this
control.

`summary.json` is the machine-readable result; `round1.json` through
`round3.json` are the retained observer-only round evidence.
