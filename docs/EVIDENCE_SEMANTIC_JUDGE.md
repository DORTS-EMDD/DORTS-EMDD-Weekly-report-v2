# V2 Evidence Semantic Judge Contract

Status: authoritative implementation contract for the Evidence semantic
matching helper.

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

MaiAgent remains a formal-report writer. Validator remains a downstream
report-validation owner. Neither may repair, reinterpret, or recreate an
Evidence decision.

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

Span offsets use Unicode code-point indexing with an inclusive `start` and an
exclusive `end`. EvidenceService retains the exact input segments so it can
validate every returned span without refetching or normalizing the text after
the judge call.

The body segments must exclude navigation, footer, aside, script, style,
interactive controls, and other non-principal page shell content according to
the Evidence parser's structural extraction rules. Language-specific
boilerplate dictionaries are not part of this contract.

## Output schema

The Semantic Judge returns one object with this schema:

```json
{
  "relation": "SAME_EVENT | DIFFERENT_EVENT | UNCERTAIN",
  "support_spans": [
    {
      "segment_id": "...",
      "start": 0,
      "end": 0
    }
  ],
  "conflict_spans": [
    {
      "segment_id": "...",
      "start": 0,
      "end": 0
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

`support_spans` and `conflict_spans` contain only body segment references.
`explanation` is diagnostic text and has no decision authority. No score,
confidence value, or threshold is part of the authoritative schema.

## Span validation rules

EvidenceService accepts a judge response only after validating all of the
following:

* The response is an object with the required fields and valid enum value.
* Every span has an existing `segment_id`.
* `start` and `end` are integers, `0 <= start < end`, and `end` does not
  exceed the referenced segment length.
* The span text is obtained from the exact immutable input segment using the
  returned offsets.
* No support span points only to a document headline or Candidate title.

Unknown fields, missing fields, invalid types, invalid segment references, and
invalid boundaries make the response invalid. EvidenceService never repairs
or guesses a malformed span.

## SAME_EVENT acceptance preconditions

`SAME_EVENT` is a usable semantic signal only when:

1. All deterministic pre-judge Evidence gates passed.
2. The relation is exactly `SAME_EVENT`.
3. At least one valid `support_span` points to supplied principal body text.
4. The support text is present in the immutable judge input.
5. The Candidate title is not the sole support.

After these checks, EvidenceService may decide `EVIDENCE_READY` only when its
other Evidence requirements also pass. The judge response itself never
creates `EVIDENCE_READY`.

## DIFFERENT_EVENT behavior

`DIFFERENT_EVENT` proves that Source-to-Candidate Match has not been
established. EvidenceService rejects the Candidate, normally with
`SOURCE_PAGE_MISMATCH`, and records the validated conflict spans for
diagnostics.

## UNCERTAIN behavior

`UNCERTAIN` is not a match. EvidenceService rejects conservatively because
Source-to-Candidate Match remains unproven. It must not promote the Candidate
through a deterministic overlap rule, a fallback, a rescue lane, or a
downstream consumer.

## Invalid, timeout, and transport failure behavior

An invalid response, invalid schema, invalid support span, timeout, or
semantic provider transport failure is a failed Evidence decision.
EvidenceService rejects conservatively and records the failure type. It does not
reinterpret the error as `UNCERTAIN` and then accept it, and it does not
search for or fetch another source as a semantic fallback.

## Retry policy

Phase 1 makes at most one Semantic Judge call per Candidate. There is no retry
for `UNCERTAIN`, `DIFFERENT_EVENT`, malformed responses, invalid spans,
timeouts, or provider transport failures. Repeating a call until a desired
relation appears is forbidden.

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

This contract does not select a concrete model or provider. A production
deployment must use a configured and recorded:

```text
model_identifier
prompt_version
schema_version
```

Changing any of these is an observable semantic implementation change. The
judge must not be silently bound to the MaiAgent report-writing configuration.

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
