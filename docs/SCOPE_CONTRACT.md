# V2 Scope Contract

Status: authoritative subordinate implementation contract for Candidate-stage
Scope classification.

This document is governed by `docs/ARCHITECTURE_CONTRACT.md`. It resolves the
Scope rules left intentionally broad in the Architecture Contract without
adding a Domain Owner, pipeline stage, workflow lane, or eligible mode family.
If the two documents conflict, the Architecture Contract prevails.

## 1. Purpose and authoritative owner

`Scope Classifier` is the sole authoritative owner of:

```text
IN_SCOPE
OUT_OF_SCOPE
```

Scope diagnostics explain that decision but have no independent authority.
The Scope Classifier does not decide Evidence, Date, Event Identity, Category,
E&M Taxonomy, or Reportability.

## 2. Candidate-stage sequence

The locked Candidate sequence remains:

```text
DISCOVERED
→ EVIDENCE_READY
→ IN_SCOPE
→ DATE_VALID
→ GROUPED
```

The Scope Classifier is invoked only for `EVIDENCE_READY` Candidates:

```text
Evidence != EVIDENCE_READY
→ Scope = NOT_EVALUATED
→ Date = NOT_EVALUATED
```

`NOT_EVALUATED` is a pipeline observation that the Scope owner was not
invoked. It is not a third Scope outcome.

When Scope returns `OUT_OF_SCOPE`, Temporal is not invoked:

```text
Evidence = EVIDENCE_READY
Scope != IN_SCOPE
→ Date = NOT_EVALUATED
```

Only `EVIDENCE_READY + IN_SCOPE` reaches the Temporal Rule. Only
`EVIDENCE_READY + IN_SCOPE + DATE_VALID` may reach Event Identity.

## 3. Allowed authoritative facts

Scope may consume only supplied facts associated with the established
principal source document:

* substantive principal content from `EVIDENCE_READY`;
* factual same-resource metadata and provenance associated with that
  principal document;
* Candidate identity and title as comparison context only; and
* canonical source identity as provenance only.

The Candidate title may help identify which action the Candidate represents,
but it cannot substitute for missing principal-content proof. The canonical
URL establishes source identity, not transport mode.

Scope must not refetch, search, select an alternative source, reopen rejected
Evidence, reconstruct principal content, or change the canonical source.

## 4. Forbidden Scope authority

The following facts must not independently or collectively manufacture
`IN_SCOPE` when authoritative event-level mode support is absent:

```text
publisher identity
operator identity alone
website or domain identity
discovery intent
search query
search snippet
Search Language Profile vocabulary
search-engine metadata
URL vocabulary
generic rail vocabulary
external facts
new web searches
alternative-source fetches
rejected Evidence
future Event grouping
```

No country-specific, operator-specific, publisher-specific, URL-specific, or
language-specific downstream exception is permitted.

## 5. Exhaustive eligible mode families

The positive mode-family list is exhaustive:

```text
Metro
MRT
Subway
Light Rail
Tram
Urban Rail
AGT
Monorail
People Mover
```

Cross-language, spelling, abbreviation, and semantic equivalents may map to
these existing families. Such mappings do not create additional mode
families. Literal English keyword presence is neither necessary nor
sufficient.

`IN_SCOPE` requires authoritative event-level support tying the Candidate's
substantive action or event to at least one eligible family. Merely mentioning
an eligible family somewhere in a mixed document is insufficient.

## 6. Boundary-mode rules

### 6.1 Streetcar

`streetcar` may be treated as a semantic equivalent of `Tram` when
authoritative source facts establish that transport mode. The word alone is
not proof when its event association is unclear.

### 6.2 Commuter, suburban, and regional rail

These labels are not independently eligible mode families and do not
establish `IN_SCOPE` by themselves.

```text
commuter rail without independent Metro/MRT/etc. support
→ OUT_OF_SCOPE
```

If authoritative source facts independently establish that the Candidate
event belongs to an eligible family, a commuter, suburban, or regional
service label does not automatically exclude it.

```text
service described as commuter rail
+ authoritative facts explicitly establish Metro/MRT
→ MAY be IN_SCOPE
```

No country or operator exception applies.

### 6.3 Airport rail

`airport rail` describes service purpose, not formal mode. Scope follows the
underlying mode:

```text
airport Metro or MRT
→ MAY be IN_SCOPE

airport AGT or People Mover
→ MAY be IN_SCOPE

conventional or mainline airport express
→ OUT_OF_SCOPE
```

The words `airport rail` alone cannot decide Scope.

### 6.4 Mainline urban service

Urban geography, urban passengers, or service within a city does not
transform conventional or mainline railway into an eligible family.
Authoritative event facts must independently establish one of the listed
eligible families.

### 6.5 Funicular and cable railway

Funicular and cable railway are not currently eligible formal mode families:

```text
OUT_OF_SCOPE
```

Discovery vocabulary in `docs/SEARCH_LANGUAGE_PROFILES.md` does not alter
this rule. Adding either family requires a future legitimate Architecture
Contract change.

### 6.6 Maglev

`maglev` is technology or system information, not Scope authority by itself.
The underlying mode must independently qualify:

```text
urban maglev explicitly established as eligible Urban Rail
→ MAY be IN_SCOPE

intercity or high-speed maglev
→ OUT_OF_SCOPE
```

### 6.7 Hybrid Metro and mainline systems

If authoritative Evidence clearly ties the Candidate action to the eligible
Metro or urban-rail portion, the Candidate is `IN_SCOPE`.

If the action cannot be reliably isolated from the mainline portion:

```text
OUT_OF_SCOPE
diagnostic = SCOPE_NOT_ESTABLISHED
```

Event Identity must not repair this ambiguity later.

## 7. Mixed-mode content

Mention of an excluded mode does not automatically reject a Candidate, and
mention of an eligible mode does not automatically accept it. The substantive
Candidate action must be traceably tied to an eligible system.

For content discussing both Metro and conventional railway:

* action clearly applies to Metro: `IN_SCOPE`;
* action clearly applies only to conventional railway: `OUT_OF_SCOPE`; or
* action cannot be resolved from supplied authoritative facts:
  `OUT_OF_SCOPE` with `SCOPE_NOT_ESTABLISHED`.

There is no `AMBIGUOUS_SCOPE` workflow state, deferred Event-level repair, or
downstream rescue.

## 8. Scope diagnostics

The authoritative outcomes remain only `IN_SCOPE` and `OUT_OF_SCOPE`.
Non-authoritative diagnostic vocabulary includes at minimum:

```text
EXCLUDED_TRANSPORT_MODE
NON_URBAN_RAIL
SCOPE_NOT_ESTABLISHED
```

`EXCLUDED_TRANSPORT_MODE` indicates that the Candidate action is established
as belonging to an excluded mode. `NON_URBAN_RAIL` indicates established
conventional, mainline, intercity, high-speed, bus, aviation, tourism, or
other non-eligible context. `SCOPE_NOT_ESTABLISHED` indicates that supplied
authoritative facts do not reliably tie the Candidate action to an eligible
family.

Diagnostics are trace facts. They do not create retry eligibility, workflow
branches, or Debug authority.

## 9. Optional semantic helper

The Scope Classifier may use one constrained semantic helper for
cross-language or contextual interpretation when deterministic supplied facts
are insufficient to interpret the mode relationship. The helper is
non-authoritative; the Scope Classifier remains final owner.

Allowed helper input is limited to:

* Candidate identity or title as context;
* supplied authoritative principal content; and
* same-document factual metadata.

Allowed helper output is:

```text
IN_SCOPE_SUPPORT
OUT_OF_SCOPE_SUPPORT
UNCERTAIN
```

Any support must cite validated spans from supplied content. The helper must
not search, fetch, use external facts, infer from publisher reputation, or
decide Date, Event Identity, Category, E&M Taxonomy, Reportability, or the
final Scope state.

`UNCERTAIN`, malformed output, invalid spans, timeout, and provider failure
cannot be repaired by keywords, retried until a desired answer appears, or
rescued downstream. When eligible mode support remains unestablished, the
Scope Classifier returns `OUT_OF_SCOPE` with `SCOPE_NOT_ESTABLISHED`.

## 10. Search and Evidence boundaries

`docs/SEARCH_LANGUAGE_PROFILES.md` serves Search and Discovery only. Its
terms must not be consumed as authoritative Scope proof. Cross-language Scope
understanding, when needed, operates on authoritative Evidence content under
Scope Classifier ownership rather than on query vocabulary.

Evidence Phase 1 remains frozen. Scope must not change
`EVIDENCE_READY`/`EVIDENCE_REJECTED`, principal-document boundaries, body
segments, or source provenance. Evidence readiness does not imply
`IN_SCOPE`; it only permits the Scope Classifier to evaluate supplied facts.

## 11. Golden expansion requirements

The next Golden Expansion phase must add fixed, non-live cases covering at
least:

```text
streetcar → Tram equivalence
commuter rail without eligible-mode proof
commuter rail with explicit eligible Metro/MRT proof
airport Metro
airport AGT/People Mover
conventional airport express
funicular
urban-rail maglev
intercity/high-speed maglev
mixed Metro + conventional rail, resolvable
mixed Metro + conventional rail, unresolved
urban-rail operator with non-urban-rail event
cross-language eligible urban-rail terminology
```

This document does not modify Golden. Existing G14 remains compatible: its
authoritative substantive content establishes a conventional intercity
railway event and supplies no eligible-mode support, so Scope is
`OUT_OF_SCOPE` and Date remains `NOT_EVALUATED`.

## 12. Forbidden designs

Implementation must stop for architecture review if it would require:

* a second Scope owner or third authoritative Scope state;
* Scope fallback, rescue, backfill, or retry-until-positive behavior;
* country-, operator-, publisher-, language-, URL-, CLI-, or UI-specific
  Domain rules;
* Search vocabulary or generic rail keywords as Scope proof;
* downstream refetch or Evidence reconstruction;
* Event Identity repairing Scope; or
* Debug controlling eligibility.
