# V2 Temporal Contract

Status: authoritative subordinate implementation contract for Candidate-stage
report-period eligibility.

This document is governed by `docs/ARCHITECTURE_CONTRACT.md`. It resolves the
Temporal rules left intentionally broad in the Architecture Contract without
adding a Domain Owner, pipeline stage, workflow lane, or alternate eligibility
date. If the two documents conflict, the Architecture Contract prevails.

## 1. Purpose and authoritative owner

`Temporal Rule` is the sole authoritative owner of:

```text
DATE_VALID = true
DATE_VALID = false
```

and the associated Temporal diagnostic. Temporal does not decide Evidence,
Scope, Event Identity, Category, E&M Taxonomy, or Reportability.

## 2. Candidate-stage sequence

Temporal is invoked only after both upstream decisions pass:

```text
Evidence != EVIDENCE_READY
→ Scope = NOT_EVALUATED
→ Date = NOT_EVALUATED

Evidence = EVIDENCE_READY
Scope != IN_SCOPE
→ Date = NOT_EVALUATED

Evidence = EVIDENCE_READY
Scope = IN_SCOPE
→ Temporal Rule evaluates Date
```

`NOT_EVALUATED` is a pipeline observation that Temporal was not invoked. It
is not a third Temporal outcome. Only
`EVIDENCE_READY + IN_SCOPE + DATE_VALID` may proceed to Event Identity.

## 3. Controlling date

Formal report-period eligibility uses the authoritative source publication or
notice calendar date associated with the established principal source
document.

Event occurrence, service opening, contract execution, procurement deadline,
fetch, crawl, and discovery dates are not alternate controlling dates.

## 4. Additive factual interface from Evidence

Temporal requires source-associated factual observations established during
Evidence acquisition and structural processing. The additive interface must
be able to represent, for every observed candidate controlling-date fact:

```text
raw_date_value
date_kind
principal_document_association
source_node_or_field_provenance
explicit_timezone_or_offset_if_present
competing_authoritative_date_facts
```

`date_kind` identifies the factual concept, including as applicable:

```text
ORIGINAL_PUBLICATION
NOTICE_ISSUED
NOTICE_PUBLISHED
MODIFIED
EVENT_DATE
DEADLINE
OTHER
```

These are factual observations only. EvidenceService and its structural
capability do not decide `DATE_VALID`, `OUT_OF_RANGE`, or period eligibility.
Supplying a fact does not declare it controlling; the Temporal Rule applies
the precedence in this contract.

This interface is an additive documentation requirement for future
implementation. It does not change Evidence Phase 1 decisions, authorize an
Evidence refetch, or modify current production code in this phase.

## 5. Authoritative date provenance

A controlling date must be associated with the established principal source
document and represent one of these source publication concepts:

```text
ORIGINAL_PUBLICATION
NOTICE_ISSUED
NOTICE_PUBLISHED
```

The association and source field or node provenance must be observable.
Discovery metadata alone is not authoritative. The following must not
independently establish `DATE_VALID`:

```text
CanonicalCandidate.published_at
RSS or feed timestamp
Google News timestamp
DDGS or search metadata date
search-result timestamp
```

Such values may remain discovery or comparison facts, but Temporal must not
promote them into source publication facts without authoritative
same-principal-document provenance.

## 6. Source-type controlling-date precedence

Use the original source-associated publication fact appropriate to the
principal document:

| Source type | Controlling factual concept |
| --- | --- |
| News or article | Original source-associated publication date |
| Official press release | Original release publication date |
| Technical bulletin | Original bulletin publication date |
| Formal project release | Original source publication date |
| Government/operator notice | Formal notice issuance or publication date |
| Procurement/tender/award notice | Formal notice issuance or publication date |

When a notice supplies both an issuance date and a publication date as
distinct authoritative concepts, the source's formal publication date
controls publication eligibility; when no separate publication date exists,
the formal issuance date controls. Temporal must retain which concept was
used.

For procurement, Temporal must not substitute bid deadline, contract
effective date, award execution date, event occurrence date, or service
opening date for notice publication eligibility.

## 7. Modified and update dates

Modified or update metadata does not replace original publication:

```text
dateModified
page updated date
CMS modified timestamp
crawl timestamp
fetch timestamp
```

These facts must not move an old publication into the current reporting
period. If a genuinely new, independently dated notice or publication exists,
it enters the normal Candidate and Evidence pipeline as that source. Temporal
must not manufacture a new publication from an old page update.

## 8. Calendar-date semantics

Eligibility uses the calendar date expressed by the authoritative source
publication or notice fact. Temporal preserves the date component as
expressed in that source fact; it does not convert every worldwide timestamp
to Taipei time, UTC, GitHub runner time, or machine-local time and then
recalculate the calendar date.

Example:

```text
source fact = 2026-09-11T23:30:00-05:00
controlling calendar date = 2026-09-11
```

It must not become `2026-09-12` because another timezone crosses midnight.

For an explicitly supplied offset-free timestamp:

```text
source fact = 2026-09-12T10:00:00
controlling calendar date = 2026-09-12
```

Temporal must not invent a timezone. A source date without a time is used as
the date expressed.

## 9. Timezone responsibility

Temporal owns deterministic parsing of timezone information. It must:

* preserve explicit numeric offsets;
* preserve an explicit named timezone when present;
* retain timezone facts for provenance and diagnostics; and
* use the source-expressed calendar date without silent regional conversion.

Temporal must not infer timezone from machine locale, GitHub Actions,
country, publisher, URL, domain, Search Language Profile, or operator.

## 10. Reporting-period boundaries

`period_start` and `period_end` are inclusive calendar dates. Formal
eligibility is:

```text
period_start
<= source_publication_or_notice_calendar_date
<= period_end
```

Both boundaries are inclusive. Comparison is between calendar dates and must
not be implemented through host-local midnight assumptions.

## 11. Missing, unusable, and conflicting dates

When no authoritative source-associated controlling date exists:

```text
DATE_VALID = false
diagnostic = DATE_MISSING or DATE_PROVENANCE_INVALID
```

`DATE_MISSING` applies when no candidate controlling-date fact is supplied.
`DATE_PROVENANCE_INVALID` applies when dates exist but none has valid
same-principal-document publication/notice provenance, including a
discovery-only date.

When the authoritative raw value cannot be parsed deterministically:

```text
DATE_VALID = false
diagnostic = DATE_UNPARSEABLE
```

The following are not controlling-date conflicts:

```text
publication date vs modified date
→ publication controls

publication date vs event date
→ publication controls
```

A true conflict exists when multiple authoritative, same-kind,
source-associated publication or notice facts for the same principal document
disagree and deterministic structural/source association cannot resolve
them:

```text
DATE_VALID = false
diagnostic = DATE_CONFLICT
```

Temporal must not guess, choose the first or latest value, or ask a downstream
owner to repair the conflict.

## 12. Temporal diagnostics

Non-authoritative diagnostic vocabulary includes at minimum:

```text
OUT_OF_RANGE
DATE_MISSING
DATE_UNPARSEABLE
DATE_CONFLICT
DATE_PROVENANCE_INVALID
```

`OUT_OF_RANGE` means a valid authoritative controlling calendar date is
strictly before `period_start` or strictly after `period_end`. Diagnostics
explain the boolean result and are recorded in RunTrace; they do not create
workflow lanes, retry eligibility, or Debug authority.

## 13. Event-date prohibition

Event date cannot rescue an out-of-range or unusable publication/notice date:

```text
old article + event occurred this week
→ DATE_VALID = false

old procurement page + deadline this week
→ DATE_VALID = false

old page + recent generic modified timestamp
→ DATE_VALID = false

old technical article + current deployment discussed
→ DATE_VALID = false
```

If a genuinely new publication or notice exists, it enters normally as its
own Candidate and source. Temporal does not search for it or select it.

## 14. Search, Evidence, and downstream boundaries

`docs/SEARCH_LANGUAGE_PROFILES.md` serves Search and Discovery only. Its
configuration and vocabulary have no Date authority and must not be consumed
as Temporal proof.

Temporal must not refetch, search, select another source, reopen rejected
Evidence, reconstruct principal content, change the canonical source, or
change `EVIDENCE_READY`/`EVIDENCE_REJECTED`.

Event Identity, Classifier, E&M Taxonomy, Selector, Writer, Validator,
Report Service, Delivery, Debug, CLI, and Streamlit must not reinterpret or
repair Temporal results.

## 15. Golden compatibility and expansion requirements

Existing G15's expected Domain boundary remains conceptually compatible: an
authoritative source publication date of `2026-09-01` is before its inclusive
`2026-09-12` through `2026-09-18` period, so `DATE_VALID = false` with
`OUT_OF_RANGE`, and downstream fields remain `NOT_EVALUATED`.

However, the current G15 fixture exposes that date only through Candidate
`published_at`; this contract prohibits treating that field alone as
authoritative. The next Golden Expansion must add explicit fixed
source-associated date facts and provenance to G15 before it is used as an
executable Temporal acceptance fixture. This is a fixture-interface gap, not
a change to G15's expected Domain outcome and not permission to modify Golden
in this phase.

The same factual-interface requirement applies to G03, G17, and any other
existing fixture whose `date_valid` expectation currently relies only on
Candidate `published_at`. Their current expected dates need not change when
the authoritative source-associated date agrees, but the next Golden phase
must add the missing fixed provenance before those fixtures assert executable
Temporal acceptance.

The next Golden Expansion must also add fixed, non-live cases covering at
least:

```text
exact period_start
exact period_end
one day before start
one day after end
explicit offset crossing another timezone midnight
timezone-less source timestamp
date-only source
missing authoritative date
discovery-only date
publication vs modified date
publication vs Event date
conflicting publication facts
procurement deadline vs notice publication date
```

## 16. Forbidden designs

Implementation must stop for architecture review if it would require:

* a second Temporal owner or third authoritative Temporal state;
* Temporal fallback, rescue, backfill, or alternate eligibility dates;
* country-, publisher-, language-, URL-, CLI-, or UI-specific date rules;
* Search or feed metadata as authoritative Date proof;
* host-local or runner-local timezone inference;
* downstream refetch or Evidence reconstruction;
* Selector or another downstream owner repairing Temporal; or
* Debug controlling eligibility.
