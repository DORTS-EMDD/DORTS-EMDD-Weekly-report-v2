# V2 Evidence Semantic Judge Contract

Status: authoritative target implementation contract for the Evidence semantic
matching helper. Span ownership is locked as `PYTHON_CANONICAL_COORDINATE_OWNER`.
Baseline `fa4eb23d3b0c78fd5e3c18bf1661ed90a1c41517` still implements the previous
offset-bearing proposal schema; this documentation checkpoint does not migrate
production code or claim offline/live implementation acceptance.

## Purpose

`EvidenceService` must establish that authoritative principal source content
describes the Candidate event. Page ownership, URL provenance, a matching
headline, and shared words do not establish event equivalence by themselves.

The Semantic Judge supplies one constrained semantic signal for the
Source-to-Candidate Match decision. It handles cross-language paraphrase and
event distinctions that cannot be established by deterministic document
structure alone. It does not own the Evidence decision.

## Owner boundary

`EvidenceService` is the only authoritative owner of:

```text
EVIDENCE_READY
EVIDENCE_REJECTED
```

The Semantic Judge is a helper called by EvidenceService. Its relation is an
input signal only. EvidenceService validates that signal, combines it with
the already completed structural acquisition checks, and decides the final
Evidence state.

The MaiAgent Generic Stateless Structured Helper supplies only the relation
and source-text proposals through the existing `SemanticJudge` seam. Its
task-specific schema and instructions are supplied per request; the permanent
Helper role remains neutral. The separate MaiAgent Writer remains a
formal-report writer, and Validator remains a downstream report-validation
owner. Neither may repair, reinterpret, or recreate an Evidence decision.

## Deterministic pre-judge reject gates

EvidenceService may reject without invoking the Semantic Judge when any
structural Evidence requirement fails:

* URL is unresolved or resource provenance is invalid.
* The response is unusable or non-textual.
* The document is a discovery feed.
* The resolved resource is a homepage, listing page, category page, or search
  shell.
* Only a title, metadata description, search snippet, or repeated headline is
  available.
* No principal substantive body is available.

These gates only create deterministic rejection paths. After they pass, every
Candidate uses the single semantic-judgment path. No positive `EVIDENCE_READY`
bypass is allowed for an exact H1, exact HTML title, URL, token overlap,
numeric overlap, keyword match, fuzzy lexical match, edit distance, embedding
threshold, or opaque similarity score.

## Input schema

EvidenceService supplies exactly this comparison input:

```json
{
  "candidate_id": "...",
  "candidate_title": "...",
  "document_level_headlines": ["..."],
  "principal_body_segments": [
    {
      "segment_id": "...",
      "text": "..."
    }
  ]
}
```

`candidate_id` identifies the Candidate being evaluated. The Candidate title
and document-level headlines are comparison context. `principal_body_segments`
are the source material that can support the event claim.

Search snippets, publisher names, search queries, URL strings, external
search results, and facts not present in this input are not semantic evidence
for the judge.

## Principal body segment contract

EvidenceService creates segment IDs deterministically from the extracted
principal body and supplies the exact segment text used for the call. A
`segment_id` is immutable for that input and unique within the request.

Canonical spans use Python Unicode code-point indexing with an inclusive
`start` and an exclusive `end`. EvidenceService retains the exact input
segments and derives every accepted span from the selected exact quote without
refetching or normalizing the text after the judge call. The Helper references
an existing segment ID; it does not create segment identities or calculate
coordinates.

The body segments must exclude navigation, footer, aside, script, style,
interactive controls, and other non-principal page shell content according to
the Evidence parser's structural extraction rules. Language-specific
boilerplate dictionaries are not part of this contract.

## Provider proposal schema

The Semantic Judge returns one untrusted object with exactly this schema:

```json
{
  "relation": "SAME_EVENT | DIFFERENT_EVENT | UNCERTAIN",
  "support_evidence": [
    {
      "segment_id": "...",
      "exact_quote": "..."
    }
  ],
  "conflict_evidence": [
    {
      "segment_id": "...",
      "exact_quote": "..."
    }
  ],
  "explanation": "..."
}
```

`relation` is an enum with exactly three values:

```text
SAME_EVENT
DIFFERENT_EVENT
UNCERTAIN
```

`support_evidence` and `conflict_evidence` contain only locators for supplied
principal-body text. Their separate names preserve the semantic roles of
support and conflict while distinguishing untrusted quote proposals from
accepted numeric spans. Each locator has exactly `segment_id` and
`exact_quote`, both strings; `exact_quote` must be non-empty unchanged source
surface text. No occurrence ordinal, prefix/suffix locator, numeric offset, or
cross-segment locator is part of this contract.

`explanation` remains a string, including an empty string as allowed by the
existing validator. It is diagnostic text and has no decision authority; it
cannot substitute for support or select an occurrence. No score, confidence
value, or threshold is part of the authoritative schema.

Provider `support_spans`, `conflict_spans`, `start`, and `end` are prohibited
in the proposal, including nested, compatibility, or ignored-hint forms.
Missing or extra fields invalidate the complete response. Valid numeric offsets
do not make an old-schema proposal acceptable. The adapter returns the parsed
proposal unchanged; it does not validate domain semantics or localize quotes.

## Exact quote validation and canonical span derivation

EvidenceService owns exactly one canonical coordinate rule, in its existing
pure validator `semantic_judge.py::validate_semantic_judge_response` and a pure
mechanical locator within that validation boundary. For every locator in both
evidence arrays:

1. Validate the complete response fields, relation enum, array types, and
   explanation string, and the exact locator fields/types.
2. Require an existing supplied `segment_id` and a non-empty `exact_quote`.
3. Search only that immutable named segment for all occurrences of the quote
   exactly as supplied, including overlapping occurrences. Quote characters are
   never removed, rewritten, or added.
4. Zero occurrences invalidate the complete response. Under the RC-3 revision
   (`EXACT_TEXT_ALL_OCCURRENCES`, ARCHITECTURE_CONTRACT §A.1) every occurrence
   is recorded and none is selected; first, last, nearest, longest, title
   context, explanation, provider hints, and a second model cannot select an
   occurrence.
5. For each occurrence, derive `start = occurrence_index` and
   `end = start + len(exact_quote)` using Python Unicode indexing. Require
   integer, boolean-excluded bounds `0 <= start < end <= len(segment.text)`
   and verify `segment.text[start:end] == exact_quote` exactly.
6. Construct the canonical immutable `BodySpan(segment_id, start, end)` under
   EvidenceService authority. Accept the complete response only after every
   support and conflict locator and the relation-specific requirements pass.

No trimming, whitespace repair, case folding, Unicode normalization,
translation, aliasing, fuzzy/approximate matching, offset guessing, or
cross-segment synthetic quote reconstruction is allowed. Leading or trailing
whitespace must match unchanged; mismatches are rejected. The non-empty quote
rule does not add a new blanket nonblank-text requirement to the existing
Judge schema; the selected text must still serve its semantic evidentiary role.
Repeated identical text is supported at every occurrence in the named
segment. Preserve array order and
the existing handling of duplicate entries; no new semantic merging or
deduplication is introduced.

Unknown fields, missing fields, invalid types, unknown segments, empty quotes,
absent exact matches, or invalid canonical bounds invalidate the complete
response. One invalid conflict locator also invalidates a `SAME_EVENT`
proposal; there is no partial acceptance or subset salvage. Failures use the
existing `InvalidSemanticJudgeResponse`,
`response_validation_result = invalid`, and conservative Evidence rejection.

Only Python derives coordinates for the Judge task. The provider, adapter,
EvidenceService consumer, postprocessor, and Debug must not implement parallel
coordinate resolution. There is no "trust valid provider offsets, recompute
invalid ones" branch. The pure validator is not another Domain owner.

Exact quote grounding establishes where the selected text exists, not whether
it semantically proves the proposed relation. The Helper remains responsible
for proposing a source-supported event comparison and choosing the relevant
support/conflict text. Acceptance relies on that bounded semantic proposal
after the complete Python contract passes. No keyword judge, second model,
title-overlap gate, or hidden semantic re-evaluation is added. Candidate title
and document headlines remain comparison context only, never the sole support.

## Accepted internal response and provenance

The validated response keeps the existing internal interface:

```text
ValidatedSemanticJudgeResponse:
    relation: SemanticRelation
    support_spans: tuple[BodySpan, ...]
    conflict_spans: tuple[BodySpan, ...]
    explanation: str

BodySpan:
    segment_id: str
    start: int
    end: int
```

EvidenceService constructs or consumes these Python-produced spans and projects
them into the existing `validated_support_spans` and `validated_conflict_spans`
provenance arrays. Their `segment_id/start/end` keys and segment-relative
coordinate meaning remain intact. This preserves the accepted result and
observational interfaces without passing raw quote locators downstream.

## SAME_EVENT acceptance preconditions

`SAME_EVENT` is a usable semantic signal only when:

1. All deterministic pre-judge Evidence gates passed.
2. The relation is exactly `SAME_EVENT`.
3. At least one `support_evidence` locator resolves to a valid canonical
   `support_span` in supplied principal body text.
4. The support text is present in the immutable judge input.
5. The Candidate title is not the sole support.

After these checks, EvidenceService may decide `EVIDENCE_READY` only when its
other Evidence requirements also pass. The judge response itself never
creates `EVIDENCE_READY`.

`conflict_evidence` may be empty. The schema migration does not introduce a
new conflict-array veto or change the existing relation acceptance meaning.
Any supplied conflict locator must pass the same complete validation contract.

## DIFFERENT_EVENT behavior

`DIFFERENT_EVENT` is a proposal that the principal body describes a different
event. It does not establish Source-to-Candidate Match. EvidenceService rejects
the Candidate with the existing `SOURCE_PAGE_MISMATCH` behavior and records
any validated support/conflict spans for diagnostics.

Both `support_evidence` and `conflict_evidence` may be empty, as allowed by the
current validator. No new minimum conflict/support cardinality or proof-of-
difference gate is introduced to facilitate the wire migration. Any supplied
locator must be valid; explanation alone never admits the Candidate.

## UNCERTAIN behavior

`UNCERTAIN` is not a match. EvidenceService rejects conservatively because
Source-to-Candidate Match remains unproven. It must not promote the Candidate
through a deterministic overlap rule, a fallback, a rescue lane, or a
downstream consumer.

Both evidence arrays may be empty and signify that no exact support/conflict
quote was proposed, not that the Candidate is eligible. Non-empty arrays must
validate completely and still cannot promote `UNCERTAIN` to `SAME_EVENT`.

## Invalid, timeout, and transport failure behavior

An invalid parseable response, invalid schema, or invalid support/conflict
locator or canonical span is a failed Evidence decision: EvidenceService
rejects conservatively and records the failure type. Under RC-6
(ARCHITECTURE_CONTRACT §A.1) a timeout, connection failure, HTTP 429/5xx or
unparseable response that persists after the single shared transport retry is
a typed `SemanticProviderTechnicalFailure`: the Candidate becomes a disclosed
`TechnicalGap`, never `EVIDENCE_REJECTED`. EvidenceService never reinterprets
an error as `UNCERTAIN` and never searches for or fetches another source.

## Retry policy

There is one Semantic Judge proposal per Candidate. The only retry is the
shared RC-6 transport retry, at most once with the identical request, and only
when no parseable response was received. There is no retry for `UNCERTAIN`,
`DIFFERENT_EVENT`, parseable invalid responses, or invalid spans. Repeating a
call until a desired relation appears is forbidden.

Transport acquisition concerns and semantic judgment concerns remain separate;
neither creates a second Evidence owner.

## Forbidden capabilities

The Semantic Judge must not:

* search or fetch;
* use external facts or hidden source material;
* decide Source Resolved or resource provenance;
* decide Scope, Date, Category, E&M Taxonomy, or Reportability;
* create `EVIDENCE_READY` or `EVIDENCE_REJECTED`;
* mutate a Candidate or source content;
* invoke rescue, fallback, or backfill behavior;
* use language-specific, country-specific, or publisher-specific rules;
* use token-overlap thresholds, edit distance, fuzzy prefixes, numeric
  similarity gates, embedding thresholds, or opaque similarity scores as
  authoritative decisions;
* become part of MaiAgent's report-writing role.

## Cross-language policy

The same input and output contract applies across languages and publishers.
Cross-language paraphrase may be accepted only when the judge returns
`SAME_EVENT` with valid principal-body support spans. Exact lexical overlap is
not required, and lexical overlap alone is not sufficient. If the semantic
relationship cannot be established, EvidenceService rejects with no language-
specific exception.

## Model, prompt, and schema versioning

The production proposal transport remains the existing MaiAgent Generic
Stateless Structured Helper selected by Architecture Contract §P. This
adjudication makes no model or deployment-setting change. The adapter continues
using the single shared `MAIAGENT_STRUCTURED_HELPER_CHATBOT_ID`, separate from
the Writer identity. A production deployment must use a configured and recorded:

```text
model_identifier
prompt_version
schema_version
```

Changing any of these is an observable semantic implementation change. The
judge must not be silently bound to the MaiAgent report-writing configuration.

The migration keeps task identity `evidence_source_candidate_match` and bumps
the task prompt from `evidence-source-candidate-match-v1` to
`evidence-source-candidate-match-v2`, and the response schema from
`evidence-semantic-judge-response-v1` to `evidence-semantic-judge-response-v2`.
The prompt must retain bounded semantic relation/quote selection, unchanged
source text and segment references, cross-language semantics, no external
knowledge, and no retry/fallback/rescue/repair, while explicitly forbidding
numeric offset calculation. Task rules stay in the per-call request, not in
the permanent neutral Helper platform role.

For every invocation, RunTrace records at least:

```text
judge_input_hash
model_identifier
prompt_version
schema_version
raw_relation
validated_support_spans
validated_conflict_spans
response_validation_result
latency
error_type
EvidenceService_final_decision
```

Debug records and RunTrace facts are observational only. They do not
participate in the Evidence decision and cannot create a second source of
truth.

## Migration boundary and acceptance work

This target replaces the raw proposal schema, not the accepted Evidence schema.
The baseline inspection establishes the following minimum implementation scope:

* `semantic_judge.py`: migrate exact raw fields and both locator arrays; derive
  canonical spans in the existing pure validator; preserve relation enum,
  explanation type, accepted `ValidatedSemanticJudgeResponse` and `BodySpan`.
* `maiagent_semantic_judge_provider.py`: migrate task schema/instructions and
  prompt/schema versions together; keep the proposal-only adapter, shared
  transport, configuration, and one-call failure behavior.
* `evidence_service.py`: the existing validator invocation, final relation/state
  gate, and numeric provenance projection can retain their current interfaces.
  Change this consumer only if necessary to preserve those invariants; it must
  not derive quotes a second time or add new Evidence states or diagnostics.
* Tests: migrate injected Judge responses in
  `tests/test_semantic_judge_contract.py`,
  `tests/test_maiagent_semantic_judge_provider.py`,
  `tests/test_evidence_contract.py`,
  `tests/test_evidence_temporal_integration.py`, and the Judge fixtures inside
  `tests/test_evidence_metadata.py` and
  `tests/test_maiagent_evidence_metadata_provider.py`. The latter fixture edits
  change only injected Judge wire responses, not the sealed Metadata contract,
  implementation, or expected results.

Later focused coverage must include unique/zero/multiple and overlapping exact
occurrences; leading/trailing whitespace, case and Unicode exactness; unknown
segments and cross-segment reconstruction; old offset-schema rejection; complete
response rejection without partial evidence; all three relations and their
unchanged cardinalities; cross-language support without lexical overlap;
canonical accepted spans/provenance; and no retry, fallback, rescue, repair,
positive deterministic bypass, or second coordinate derivation path.

Repository references show `BodySpan` and `PrincipalBodySegment` are also used
by the sealed Metadata seam. Their existing shapes must remain unchanged.
`SemanticJudgeInput`, its exact input hash, `EvidenceResult`, source-date facts,
identity facts, and the accepted provenance key/coordinate formats require no
schema migration. Version values change observably; existing historical trace
records retain their original versions and meaning and are not rewritten.

No persisted/public raw Judge proposal schema or Golden provider-response
corpus is identified in the inspected repository. Golden expected domain
outcomes and accepted Evidence fixtures need no change. Event Identity,
Category, Taxonomy, Reportability, Ordering, Formal Metadata, Writer, and
Delivery consume accepted Evidence and receive no new fields or responsibilities.
For equivalent valid semantic text selections, downstream domain behavior is
preserved. A missing quote fails the contract deliberately; a repeated quote is
recorded at every occurrence (RC-3);
this is not a claim that every old offset-bearing response has an equivalent
accepted quote proposal. No downstream consumer recalculates coordinates.

The contract checkpoint changes only this document and the architecture
adjudication in §H. Implementation and tests are subsequent work; focused and
full offline acceptance plus architecture inspection must precede any separately
authorized live Judge acceptance. This adjudication makes zero provider calls
and does not modify `.env` or MaiAgent platform settings.
