# V2 Evidence Structural Document Contract

Status: authoritative subordinate implementation contract for the structural
Evidence capability.

This document is governed by `docs/ARCHITECTURE_CONTRACT.md`. It defines the
facts and boundaries required before EvidenceService may invoke the Semantic
Judge. It does not change the production pipeline or create another Domain
Owner. If this document conflicts with the Architecture Contract, the
Architecture Contract prevails.

## 1. Purpose

The structural Evidence capability performs this transformation:

```text
Fetched Source
→ parsed structural representation
→ principal-document assessment
→ principal-body segments or structural failure facts
```

It supplies structural facts and diagnostics to EvidenceService. It never
returns `EVIDENCE_READY`, `EVIDENCE_REJECTED`, Scope, Date, Category, E&M
Taxonomy, or Reportability decisions.

EvidenceService remains the sole authoritative owner of the two Evidence
terminal states.

## 2. Minimum internal representation

A structured source must be represented with stable node or region identities
and enough relationship information to preserve:

* parent, child, sibling, ancestor, and descendant relationships;
* document regions and their containment;
* ownership of visible text and headlines;
* interactive, navigation, and complementary regions;
* related, supporting, comment, or other non-principal document units;
* candidate regions that could own a principal document;
* source metadata and the parsed nodes or resource to which it applies; and
* parse errors, repairs, unsupported constructs, and incomplete input.

Text must remain traceable to its owning structural node or region until one
principal document has been established. For HTML and XHTML, flattened text,
tag counts, and global skip lists are insufficient structural
representations.

The representation is an internal Evidence fact model. Its node names and
storage classes are implementation details and do not create a pipeline
contract.

## 3. Structural format families

The capability handles format families separately:

* **HTML / XHTML:** parse into a queryable tree that preserves containment,
  attributes, landmarks, document metadata, and text ownership.
* **Plain text:** the fetched resource boundary may define one possible
  document only when acquisition facts indicate one complete plain-text
  document and the payload does not expose competing independent records or
  document units. Absence of HTML markup alone does not establish coherence.
  If a single coherent document cannot be established from the payload and
  acquisition facts, the assessment is ambiguous.
* **Non-feed XML / RDF:** preserve XML element, namespace, and graph or
  resource relationships. A non-feed XML or RDF notice may be accepted only
  when one principal document and its body are structurally established. It
  must not be silently parsed under HTML rules.
* **Discovery feeds:** RSS 2.0, RSS 1.0 / RDF syndication, Atom, and other
  structurally established syndication documents are deterministic structural
  failures for Authoritative Evidence. Individual feed entries are discovery
  material and are not principal source documents merely because they contain
  substantive summaries.

An unsupported format or unsupported structure is a valid conservative
Evidence rejection condition. It must not be repaired by treating metadata,
snippets, or flattened payload text as authoritative body content.

## 4. Principal document

`PRINCIPAL_DOCUMENT` means the single structural document unit whose body is
eligible to be supplied to the Semantic Judge.

Structural establishment proves only that the supplied text belongs to one
coherent source document rather than an unresolved mixture of independent
documents. It does not prove that the document describes the Candidate event.
Source-to-Candidate semantic equivalence remains on the existing Semantic
Judge path under EvidenceService ownership.

The principal document may be an article, official release, notice,
procurement record, technical bulletin, formal project release, or another
coherent substantive document. A particular HTML tag is not required.

## 5. Principal-document establishment

The assessment may use mutually consistent structural evidence, including:

* semantic containment and DOM relationships;
* a unique main-content region and its relationship to a document unit;
* article containment, including whether article units are nested, sibling,
  principal, complementary, or subordinate;
* ARIA landmarks and roles;
* structured metadata associated with the same resource and parsed document;
* containment of the document headline and body;
* canonical and document metadata as resource-association facts; and
* format-specific document or notice structure.

No one signal is authoritative in every document. A principal document is
established only when the available facts identify one coherent document
boundary, all proposed body segments belong to that boundary, competing
document units are excluded by structural relationship, and material
structural facts do not conflict.

An HTML `article`, `main`, H1, canonical URL, structured-data type, or URL path
may contribute evidence but does not automatically establish a principal
document. Candidate-title similarity, publisher-specific selectors,
class-name vocabulary, language rules, URL keyword scores, longest-text
selection, first-article selection, and article counts are forbidden as sole
proof.

When usable facts conflict and this contract provides no deterministic
resolution, the principal boundary is ambiguous.

## 6. Multiple article elements

`article_count >= 2` does not prove a listing or collection.

The parser must preserve whether article elements are:

* nested within a principal article;
* comments or replies subordinate to another document;
* contained in a complementary or otherwise excluded region;
* related or recommended documents outside the principal document; or
* sibling independent document units in a collection structure.

A main article with a related article remains eligible when the main document
and related unit are structurally separable. A nested article does not create
a second principal document merely because it uses the same tag. Multiple
sibling article cards prove a collection only when their relationships and
surrounding structure establish multiple independent document units and do
not establish one principal document.

## 7. Multiple main regions

Multiple competing main or principal regions must never be concatenated
blindly. If one principal document cannot be established from deterministic,
non-semantic structural relationships, the assessment is
`PRINCIPAL_DOCUMENT_AMBIGUOUS`.

The first region, longest region, region with the greatest text volume, or
region most similar to the Candidate title must not be selected as authority.

## 8. Related, recommended, comment, and shell content

Principal-body segments must exclude content structurally outside the selected
principal document, including related or recommended documents, comments and
replies, sidebars, navigation, site footer content, pagination, and standalone
interactive controls.

Exclusion is based on ownership, containment, standards-based region roles,
and document relationships. It must not depend on phrases such as “Related
News”, “Read More”, “Contact”, or “Privacy”, nor on class-name dictionaries
such as `related`, `card`, `story`, or `news-item`.

If excluded and principal content cannot be separated reliably, the principal
boundary is ambiguous. The implementation must not concatenate the regions
and ask the Semantic Judge to choose the event document.

## 9. Headers inside the principal document

A page or site header and a header owned by the selected principal document
are different structural regions. A global “skip all header elements” rule is
invalid.

A header contained by and associated with the principal document may own its
headline, lead, publication facts, or other substantive document content.
Those facts remain available to the appropriate headline or body extraction
step. Navigation or controls nested inside that header remain excluded by
their own structural relationship.

## 10. Inline interactive content

Meaningful inline anchor text inside principal prose is source text and must
remain in the principal body in document order. For example, the anchor text
in this sentence is retained:

```html
The authority awarded <a>the signalling contract</a> after evaluation.
```

Links, buttons, and other controls do not establish substantive body when
they are the resource's only usable content. The distinction must be derived
from whether text participates in principal prose and whether non-control
principal body exists, not from the visible language of the control.

## 11. Document-level headlines

The Semantic Judge receives only headlines structurally associated with the
selected principal document. Potential sources include the document title,
OG or Twitter title, and the principal H1, subject to resource association and
conflict checks.

H2-H6 values do not automatically become `document_level_headlines`. They may
remain structural facts or section headings. A page-level title or metadata
headline that conflicts with the selected document boundary cannot be trusted
blindly; unresolved ownership or identity conflicts make the boundary
ambiguous.

## 12. Principal-body segments

Every segment supplied to the Semantic Judge must:

* belong to the same selected principal document;
* have a deterministic identifier unique within the request;
* preserve stable visible text and document order;
* remain immutable from request creation through span validation;
* use Unicode code-point-compatible offsets; and
* be retained exactly for validation and diagnostics.

The representation may support more than one segment, but every segment must
share one principal-document identity. Unrelated documents must never be
concatenated into one segment or request.

Arbitrary truncation is not permitted on a path that can create
`EVIDENCE_READY`. If an implementation limit prevents complete, valid
principal-body representation, the structure is unsupported or ambiguous and
EvidenceService rejects conservatively.

## 13. Structural assessment and ambiguity

The structural capability returns one of these internal assessments:

```text
STRUCTURAL_FAILURE_ESTABLISHED
PRINCIPAL_DOCUMENT_ESTABLISHED
PRINCIPAL_DOCUMENT_AMBIGUOUS
```

These values are Evidence facts, not pipeline states or Domain Owners.

* `STRUCTURAL_FAILURE_ESTABLISHED` means a deterministic Evidence structural
  requirement failed, such as a discovery feed, unusable format, confirmed
  shell or collection without a principal document, title-only resource, or
  missing usable body. EvidenceService rejects without invoking the Semantic
  Judge.
* `PRINCIPAL_DOCUMENT_ESTABLISHED` means one principal document and its usable
  immutable body segments were established. The Candidate is eligible for the
  existing single Semantic Judge path.
* `PRINCIPAL_DOCUMENT_AMBIGUOUS` means principal ownership, boundary, metadata
  association, or exclusion of competing documents could not be established.
  EvidenceService rejects without invoking the Semantic Judge.

Ambiguity creates no rescue, fallback, alternate extraction lane, downstream
repair, or Semantic Judge page-type decision.

## 14. Clear collections and listings

The capability need not recognize every possible listing. A clear collection
or listing may be established when standards-based structure and document
relationships prove multiple independent document units or a collection
resource and no unique principal document is established.

Tag counts, heading counts, section counts, list-item counts, repeated visual
layout, and class names do not prove a collection by themselves. Conversely:

```text
failure to prove listing != proof of event document
failure to prove event document != requirement to label listing
```

When neither a collection nor a single principal document is proven, the
correct assessment is `PRINCIPAL_DOCUMENT_AMBIGUOUS`.

## 15. URL role

URL parsing supplies resource identity, redirect and canonical relationship
facts, and possible collection hints. Generic public path vocabulary is not
universal page-kind proof.

Words such as `news`, `latest`, `category`, `tag`, `archive`, and `search`
must not grow into a publisher, language, or locale dictionary. A lexical
path segment, its position, or a query name alone cannot establish a homepage,
collection, listing, search shell, or event document. Locale prefixes such as
`/en/`, `/fr/`, or `/de/` receive no special-case list or removal rule.

URL facts may directly reject invalid or unresolved resource identity and
invalid provenance. Page-kind rejection requires corroborating source
structure or a format-level deterministic condition; URL naming alone has no
page-kind authority.

## 16. URL, DOM, and metadata conflicts

Parsed document relationships and resource-associated standards metadata are
stronger page-structure evidence than lexical URL hints. None may override a
material conflict silently.

Therefore:

* `/category/metro` with one otherwise valid principal article is not rejected
  only because of the path name;
* `/article/event` containing a multi-document collection is not accepted
  only because of the path name; and
* structured metadata declaring `Article` does not establish a principal
  document when the parsed source provides no stable principal body.

When URL, DOM, ARIA, structured data, or document metadata provide conflicting
principal-boundary facts and no rule in this contract resolves the conflict,
the result is `PRINCIPAL_DOCUMENT_AMBIGUOUS` and EvidenceService rejects.

## 17. Structured data and ARIA

Standards-based signals such as ARIA landmarks and roles, schema.org
`Article` or `NewsArticle`, `mainEntity`, and `articleBody` may contribute
structural evidence.

They are not source-trust certification, event-match evidence, or automatic
principal-document proof. Each signal must be associated with the same
fetched resource and reconciled with the parsed tree and body ownership.
Detached, duplicated, malformed, or conflicting metadata cannot be trusted
blindly. Unresolved conflicts make the principal boundary ambiguous.

## 18. Parser capability

The parser used by the implementation must provide:

* a queryable tree or equivalent relationship model;
* parent-child and sibling containment;
* text and headline ownership;
* document-region and standards-metadata association; and
* observable parse diagnostics and unsupported-structure reporting.

This contract does not mandate a specific parser library and does not require
continued use of raw `HTMLParser`. The implementation phase may select the
smallest mature parser that satisfies these capabilities.

This contract does not authorize an opaque full-text extraction score engine,
an opaque page-kind score, or an extractor whose hidden ranking becomes an
authoritative Evidence decision.

## 19. EvidenceService boundary

The internal responsibility flow is:

```text
Evidence Transport
→ acquisition facts

Evidence Document capability
→ structural representation, assessment, principal-body facts, diagnostics

EvidenceService
→ applies Evidence gates
→ invokes the Semantic Judge at most once when structurally eligible
→ creates EVIDENCE_READY or EVIDENCE_REJECTED
```

Transport and document capabilities are helpers under EvidenceService
ownership. They are not independent Domain Owners and must not create an
Evidence terminal state. Suggested filenames or class boundaries are
non-authoritative implementation details.

The Semantic Judge does not choose a principal document, classify page kind,
select among multiple documents, repair structural extraction, or create a
terminal Evidence state.

## 20. Structural diagnostics

The Evidence trace must make structural outcomes explainable. At minimum it
records, where applicable:

```text
format
parse_status
principal_document_status
principal_document_identifier
principal_segment_ids
excluded_region_reasons
structural_conflict
unsupported_structure
```

Diagnostics are observational facts. They do not control eligibility outside
EvidenceService and do not make Debug Service an owner. Raw full HTML is not a
required diagnostic artifact and must not be exposed merely to satisfy this
contract.

## 21. Testing contract

Tests must remain separated by purpose:

* **Domain invariant tests** verify owner and Evidence behavior independent of
  a parser implementation.
* **Parser implementation tests** verify concrete tree construction,
  association, exclusion, segment stability, and diagnostics.
* **Adversarial structural fixtures** verify conflicting or unusual but valid
  containment without turning one fixture's markup into a universal rule.

Domain-level invariants include:

* title or search snippet alone cannot become Evidence;
* a discovery feed cannot become Authoritative Evidence;
* principal-boundary ambiguity cannot reach the Semantic Judge;
* multi-document concatenation cannot reach the Semantic Judge;
* related, comment, navigation, and other non-principal content is excluded;
* inline anchor text inside principal prose is preserved;
* multiple article elements do not automatically mean listing;
* multiple sections do not automatically mean listing;
* H2-H6 are not automatically document-level headlines; and
* the Semantic Judge is called at most once per Candidate.

Tests must not encode arbitrary URL vocabulary, tag counts, class names,
language phrases, or individual publishers as universal Domain truth. Passing
unit tests does not replace review of principal-document invariants.

## 22. Golden Corpus

Golden Corpus v1 expected outcomes remain unchanged. Current structural HTML,
XML, or RDF behavior belongs in implementation tests unless a Golden case
explicitly contains and governs that structural contract.

Golden answers derive from the Architecture Contract and locked Domain Rules,
not from current production implementation.

## 23. Forbidden designs

The structural Evidence implementation must not introduce:

* publisher-specific selector tables or parsers;
* class-name keyword dictionaries;
* country, language, or locale page-kind dictionaries;
* Candidate-title matching to choose the principal body;
* longest-body or first-article selection as authority;
* article-count, section-count, heading-count, or list-item-count listing
  authority;
* opaque page-kind scores or thresholds;
* a second Evidence owner;
* Semantic Judge page-kind classification or principal selection;
* semantic retry, a fallback Evidence lane, rescue, or backfill;
* downstream repair or reinterpretation of structural rejection; or
* Debug-driven production decisions.
