"""Observation-only probe of canonical declarations under three rules (no MaiAgent calls).

For each page of a list (``candidate_id<TAB>evidence gate<TAB>url``, built from a
run's selection audit) it fetches the page with EvidenceService's own fetcher,
reads the page's canonical declarations with the production structural
assessment, and prints the source-provenance outcome of the canonical check
under three rules:

* ``D5``  - d5bfbaa: only the first declaration, which must be related;
* ``R86`` - RC-86: any related declaration fits unless an unrelated one is on
  another host (``www.`` only ignored, as ``_resource_key`` does);
* ``R86B`` - the RC-87 now in production (``_declared_canonical``):
  hosts that differ only by a leading ``www.``, ``m.``, ``mobile.`` or ``amp.``
  label are the same site.

The fetched URL stands in for the run's resolved URL: the audit keeps one
canonical URL per candidate, not the resolved URL or the declarations, so an
outcome here is an approximation of the live run (a page fetched from its
first, unrelated declaration may resolve elsewhere than Google News did).
It prints URLs and outcomes only, never page text, and decides nothing.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import sys
from urllib.parse import urljoin

from src.weekly_report import evidence_service
from src.weekly_report.evidence_document import assess_document


def _rules(values: tuple[str, ...], resolved: str, chain: tuple[str, ...]) -> dict[str, str]:
    declared = [
        url for url in (evidence_service._normalise_url(urljoin(resolved, value.strip())) for value in values) if url
    ]
    if not declared:
        return {"D5": "OK", "R86": "OK", "R86B": "OK", "declarations": "0"}
    related = [url for url in declared if evidence_service._canonical_is_related(url, resolved, chain)]
    d5 = "OK" if declared[0] in related else "CANONICAL_RESOURCE_MISMATCH"
    resolved_key = evidence_service._resource_key(resolved)
    strict_other = [
        url for url in declared
        if url not in related and resolved_key is not None and (evidence_service._resource_key(url) or (None, None))[1] != resolved_key[1]
    ]
    r86 = "CANONICAL_OTHER_SITE" if strict_other else ("OK" if related else "CANONICAL_RESOURCE_MISMATCH")
    r86b = evidence_service._declared_canonical(values, resolved, chain)[1] or "OK"
    return {"D5": d5, "R86": r86, "R86B": r86b, "declarations": str(len(declared))}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    rows = [line.split("\t") for line in Path(args[0]).read_text(encoding="utf-8").splitlines() if line.strip()]
    transitions: Counter[tuple[str, str, str]] = Counter()
    fetched_pages = 0
    for candidate_id, gate, url in rows:
        try:
            fetched = evidence_service._default_fetcher(url, 20.0)
        except Exception as exc:  # observation only
            print(f"CANONICAL_PROBE FETCH_ERROR {type(exc).__name__} gate={gate} {candidate_id[:13]} {url}")
            continue
        if fetched.status_code >= 400:
            print(f"CANONICAL_PROBE HTTP_{fetched.status_code} gate={gate} {candidate_id[:13]} {url}")
            continue
        fetched_pages += 1
        resolved = evidence_service._normalise_url(fetched.url) or url
        chain = tuple(fetched.redirect_chain or ())
        assessment = assess_document(
            fetched.content,
            fetched.content_type,
            resource_url=resolved,
            candidate_id="probe",
            resource_identity_checker=lambda value: evidence_service._canonical_is_related(value, resolved, chain),
        )
        outcome = _rules(assessment.canonical_values, resolved, chain)
        transitions[(outcome["D5"], outcome["R86"], outcome["R86B"])] += 1
        print(
            f"CANONICAL_PROBE gate={gate} D5={outcome['D5']} R86={outcome['R86']} R86B={outcome['R86B']} "
            f"declarations={outcome['declarations']} {candidate_id[:13]} {url} -> {resolved} "
            f"declared={list(assessment.canonical_values)[:4]}"
        )
    print(f"CANONICAL_PROBE_SUMMARY pages={len(rows)} fetched={fetched_pages}")
    for (d5, r86, r86b), count in sorted(transitions.items()):
        print(f"CANONICAL_PROBE_SUMMARY D5={d5} R86={r86} R86B={r86b} count={count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
