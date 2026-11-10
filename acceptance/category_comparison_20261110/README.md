# Category comparison evidence — 2026-11-10

This is an observer-only, read-only evidence package for the Lyon
G100-equivalent and Incheon G101-equivalent Category failures in production
run `862b4757138643f8a3ad603504e7e0bf`.

The package deliberately does not contain a live Helper response, a Category
request body, a source-body substitute, a platform chatbot ID, or credentials.
The retained production audit preserves Evidence hashes and bounded metadata,
but not enough content to prove an exact historical request or deterministic
request reconstruction. The production result therefore cannot be localized
to request construction, Helper semantics, or platform configuration.

The strongest proven finding is an acceptance-integrity gap: the acceptance
harness validates a supplied deployment snapshot separately from the runtime
configuration and does not establish same-Helper-instance binding. The
historical 159-call seal remains valid for its own frozen configuration, but
does not apply to the current configuration and did not include G100/G101.

Read `category_comparison_evidence.json` for the complete event-level chain,
hashes, validation results, deployment comparison, architecture review and
the single next boundary.

No production code, prompt, schema, Golden expected outcome, EventIdentity
behavior, Scope behavior, or acceptance harness was modified by this package.
