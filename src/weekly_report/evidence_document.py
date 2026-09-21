"""Structural document facts for the V2 Evidence boundary.

This module owns document representation and structural assessment facts.  It
does not decide ``EVIDENCE_READY`` or ``EVIDENCE_REJECTED``.  In particular,
the tree is deliberately kept separate from EvidenceService so that a parser
signal cannot quietly become a second terminal-decision owner.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any, Iterable
from urllib.parse import urlsplit
from xml.etree import ElementTree

from lxml import html as lxml_html


class PrincipalDocumentStatus(StrEnum):
    STRUCTURAL_FAILURE_ESTABLISHED = "STRUCTURAL_FAILURE_ESTABLISHED"
    PRINCIPAL_DOCUMENT_ESTABLISHED = "PRINCIPAL_DOCUMENT_ESTABLISHED"
    PRINCIPAL_DOCUMENT_AMBIGUOUS = "PRINCIPAL_DOCUMENT_AMBIGUOUS"


@dataclass(slots=True)
class _Node:
    node_id: str
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    namespace: str = ""
    qualified_name: str = ""
    parent: "_Node | None" = None
    children: list["_Node"] = field(default_factory=list)
    text_parts: list[str] = field(default_factory=list)
    tail_text: str = ""

    def add_child(self, child: "_Node") -> None:
        child.parent = self
        self.children.append(child)


@dataclass(frozen=True, slots=True)
class DocumentSegment:
    segment_id: str
    text: str


@dataclass(frozen=True, slots=True)
class StructuralAssessment:
    """Immutable structural facts consumed by EvidenceService."""

    format: str
    parse_status: str
    principal_document_status: PrincipalDocumentStatus
    principal_document_identifier: str
    principal_segment_ids: tuple[str, ...]
    principal_body_segments: tuple[DocumentSegment, ...]
    document_level_headlines: tuple[str, ...]
    secondary_headlines: tuple[str, ...]
    canonical_values: tuple[str, ...]
    excluded_region_reasons: tuple[str, ...] = ()
    structural_conflict: bool = False
    unsupported_structure: bool = False
    reject_reason: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def body_text(self) -> str:
        return " ".join(segment.text for segment in self.principal_body_segments).strip()

    def as_provenance(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "parse_status": self.parse_status,
            "principal_document_status": self.principal_document_status.value,
            "principal_document_identifier": self.principal_document_identifier,
            "principal_segment_ids": list(self.principal_segment_ids),
            "excluded_region_reasons": list(self.excluded_region_reasons),
            "structural_conflict": self.structural_conflict,
            "unsupported_structure": self.unsupported_structure,
            **self.diagnostics,
        }


_EXCLUDED_TAGS = {
    "aside": "complementary_region",
    "footer": "footer_region",
    "nav": "navigation_region",
    "script": "non_content_script",
    "style": "non_content_style",
    "template": "non_content_template",
    "noscript": "non_content_noscript",
    "svg": "non_content_graphic",
}

_EXCLUDED_ROLES = {
    "banner": "banner_region",
    "complementary": "complementary_region",
    "contentinfo": "footer_region",
    "dialog": "interactive_dialog",
    "menu": "navigation_menu",
    "menubar": "navigation_menu",
    "navigation": "navigation_region",
    "search": "search_region",
    "tablist": "interactive_tabs",
    "toolbar": "interactive_toolbar",
}

_INTERACTIVE_TAGS = {"button", "input", "option", "select", "textarea"}
_HEADLINE_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_COLLECTION_ROLES = {"feed", "list", "listbox", "grid", "tree"}
_ARTICLE_ROLES = {"article", "document", "main"}
_COMMENT_ROLES = {"comment", "reply"}


def _clean(value: str) -> str:
    return " ".join(str(value or "").split())


def _role(node: _Node) -> str:
    return (node.attrs.get("role", "").split() or [""])[0].casefold()


def _tag_is(node: _Node, *tags: str) -> bool:
    return node.tag.casefold() in {item.casefold() for item in tags}


def _is_descendant(node: _Node, ancestor: _Node) -> bool:
    current = node.parent
    while current is not None:
        if current is ancestor:
            return True
        current = current.parent
    return False


def _ancestors(node: _Node) -> Iterable[_Node]:
    current = node.parent
    while current is not None:
        yield current
        current = current.parent


def _exclusion_reason(node: _Node) -> str | None:
    if node.tag.casefold() in _EXCLUDED_TAGS:
        return _EXCLUDED_TAGS[node.tag.casefold()]
    role = _role(node)
    return _EXCLUDED_ROLES.get(role)


def _is_excluded_region(node: _Node, boundary: _Node | None = None) -> str | None:
    current: _Node | None = node
    while current is not None and current is not boundary:
        reason = _exclusion_reason(current)
        if reason:
            return reason
        current = current.parent
    return None


def _is_collection_node(node: _Node) -> bool:
    if _role(node) in _COLLECTION_ROLES:
        return True
    return node.tag.casefold() in {"ol", "ul"}


def _is_article_node(node: _Node) -> bool:
    if node.tag.casefold() == "article" or _role(node) in _ARTICLE_ROLES:
        return True
    item_type = node.attrs.get("itemtype", "").casefold()
    return any(value in item_type for value in ("article", "newsarticle"))


def _is_comment_node(node: _Node) -> bool:
    if _role(node) in _COMMENT_ROLES:
        return True
    if node.attrs.get("itemprop", "").casefold() in _COMMENT_ROLES:
        return True
    return node.attrs.get("aria-label", "").casefold() in _COMMENT_ROLES


def _is_interactive_only_node(node: _Node) -> bool:
    return node.tag.casefold() in _INTERACTIVE_TAGS


def _has_text_outside_headlines(node: _Node) -> bool:
    """Return whether a structural unit owns non-headline text.

    This is deliberately a relationship/ownership fact.  It does not inspect
    visible words, match a Candidate, or treat a list-item count as authority.
    """

    def visit(current: _Node) -> bool:
        if current is not node and current.tag.casefold() in _HEADLINE_TAGS:
            return False
        if current is not node and _is_collection_node(current):
            return False
        if current.tag.casefold() not in _HEADLINE_TAGS and _direct_text(current):
            return True
        return any(visit(child) for child in current.children)

    return any(visit(child) for child in node.children)


def _is_explicit_collection_unit(node: _Node) -> bool:
    """Recognize a document-shaped unit under an explicit collection.

    Native ``li`` elements and ARIA list items are units only when their
    parent-child relationship is the collection relationship and the unit has
    both a headline and separately owned body text.  An explicitly article-
    typed unit may establish its shape through its article semantics.
    """

    if not (
        node.tag.casefold() == "li"
        or _role(node) == "listitem"
        or _is_article_node(node)
    ):
        return False
    has_headline = any(
        child.tag.casefold() in _HEADLINE_TAGS
        for child in _walk(node)
        if child is not node
    )
    return bool(has_headline and _has_text_outside_headlines(node))


def _lxml_to_tree(element: Any, parent: _Node, counter: list[int]) -> _Node:
    """Convert an lxml HTML tree without reimplementing HTML tree building."""

    raw_tag = str(element.tag)
    node = _Node(
        f"node-{counter[0]:04d}",
        raw_tag.casefold(),
        {str(key).casefold(): str(value or "") for key, value in element.attrib.items()},
        qualified_name=raw_tag,
    )
    counter[0] += 1
    parent.add_child(node)
    if element.text:
        node.text_parts.append(element.text)
    for child in element:
        if not isinstance(child.tag, str):
            continue
        child_node = _lxml_to_tree(child, node, counter)
        if child.tail:
            child_node.tail_text = child.tail
    return node


def _node_text(node: _Node) -> str:
    parts: list[str] = []

    def visit(current: _Node) -> None:
        parts.extend(current.text_parts)
        for child in current.children:
            visit(child)
            if child.tail_text:
                parts.append(child.tail_text)

    visit(node)
    return _clean(" ".join(parts))


def _walk(node: _Node) -> Iterable[_Node]:
    yield node
    for child in node.children:
        yield from _walk(child)


def _has_ancestor(node: _Node, predicate: Any, boundary: _Node | None = None) -> bool:
    current = node.parent
    while current is not None and current is not boundary:
        if predicate(current):
            return True
        current = current.parent
    return False


def _direct_text(node: _Node) -> str:
    return _clean(" ".join(node.text_parts))


def _collect_principal_body(
    boundary: _Node,
    excluded: list[str],
) -> tuple[str, bool, bool]:
    """Return body text, noninteractive-content flag, and body presence."""

    parts: list[str] = []
    has_noninteractive = False
    has_any = False

    def visit(node: _Node, inside_anchor: bool = False) -> None:
        nonlocal has_noninteractive, has_any
        reason = None if node is boundary else _exclusion_reason(node)
        if reason:
            excluded.append(f"{node.node_id}:{reason}")
            return
        if node is not boundary and _is_article_node(node):
            nested_in_principal = (
                _is_article_node(boundary)
                and _is_descendant(node, boundary)
            )
            if _is_comment_node(node) or nested_in_principal:
                excluded.append(f"{node.node_id}:subordinate_document")
                return
        if node is not boundary and _is_interactive_only_node(node):
            excluded.append(f"{node.node_id}:standalone_control")
            return
        is_heading = node.tag.casefold() in _HEADLINE_TAGS
        if not is_heading:
            own = _direct_text(node)
            if own:
                parts.append(own)
                has_any = True
                is_anchor = inside_anchor or node.tag.casefold() == "a"
                if not is_anchor and not _is_interactive_only_node(node):
                    has_noninteractive = True
        child_anchor = inside_anchor or node.tag.casefold() == "a"
        for child in node.children:
            visit(child, child_anchor)
            if not is_heading and child.tail_text:
                tail = _clean(child.tail_text)
                if tail:
                    parts.append(tail)
                    has_any = True
                    if not inside_anchor:
                        has_noninteractive = True

    visit(boundary)
    return _clean(" ".join(parts)), has_noninteractive, has_any


def _find_main_nodes(root: _Node) -> list[_Node]:
    return [
        node for node in _walk(root)
        if (node.tag.casefold() == "main" or _role(node) == "main")
        and _is_excluded_region(node) is None
    ]


def _find_body_nodes(root: _Node) -> list[_Node]:
    return [
        node for node in _walk(root)
        if node.tag.casefold() == "body" and _is_excluded_region(node) is None
    ]


def _find_article_roots(region: _Node) -> list[_Node]:
    result: list[_Node] = []
    for node in _walk(region):
        if node is region or not _is_article_node(node):
            continue
        if _is_excluded_region(node, region) is not None:
            continue
        if _has_ancestor(node, _is_article_node, region):
            continue
        result.append(node)
    return result


def _has_explicit_collection(region: _Node) -> bool:
    for node in _walk(region):
        if _is_collection_node(node):
            return True
    return False


def _collection_has_multiple_units(region: _Node) -> bool:
    for collection in (node for node in _walk(region) if _is_collection_node(node)):
        units = [
            child for child in collection.children
            if _is_explicit_collection_unit(child)
        ]
        if len(units) >= 2:
            return True
    return False


def _is_generic_document_shaped_div(node: _Node) -> bool:
    """Identify an untyped sibling whose ownership is structurally unresolved.

    This deliberately does not use the div count, visible words, Candidate
    matching, classes, URLs, or any publisher convention as authority.  The
    relevant fact is that an untyped direct child owns both a headline and
    non-headline text, while having no explicit article, section, or
    collection relationship.
    """

    return bool(
        node.tag.casefold() == "div"
        and not _role(node)
        and not _is_article_node(node)
        and any(
            child.tag.casefold() in _HEADLINE_TAGS
            for child in _walk(node)
            if child is not node
        )
        and _has_text_outside_headlines(node)
    )


def _has_unresolved_generic_sibling_units(boundary: _Node) -> bool:
    """Return whether generic sibling units leave principal ownership unresolved.

    A pair of direct generic div units is ambiguous because the markup proves
    neither one coherent document nor a collection of separate documents.
    Explicit article/section/list relationships are handled by their own
    structural rules and are intentionally not folded into this test.
    """

    units = [
        child
        for child in boundary.children
        if _is_excluded_region(child, boundary) is None
        and _is_generic_document_shaped_div(child)
    ]
    for index, unit in enumerate(units):
        if any(sibling is not unit for sibling in units[index + 1:]):
            return True
    return False


def _headlines_for(boundary: _Node, root: _Node) -> tuple[tuple[str, ...], tuple[str, ...]]:
    primary: list[str] = []
    secondary: list[str] = []
    # Metadata and <title> belong to the fetched resource, not to arbitrary
    # related cards.  They are therefore collected from document head only.
    for node in _walk(root):
        if node.tag.casefold() == "title":
            value = _node_text(node)
            if value:
                primary.append(value)
        if node.tag.casefold() == "meta":
            key = (node.attrs.get("property") or node.attrs.get("name") or "").casefold()
            value = _clean(node.attrs.get("content", ""))
            if value and key in {"og:title", "twitter:title"}:
                primary.append(value)
        if (
            node.tag.casefold() in _HEADLINE_TAGS
            and _is_descendant(node, boundary)
            and not _has_ancestor(node, _is_article_node, boundary)
        ):
            value = _node_text(node)
            if not value:
                continue
            if node.tag.casefold() == "h1":
                primary.append(value)
            else:
                secondary.append(value)
    # A unique <main> commonly follows a page-level document header.  That
    # header is associated with the unique principal region by the tree
    # relationship; unrelated H2-H6 cards remain secondary and are never
    # promoted.
    if boundary.tag.casefold() == "main" and boundary.parent is not None:
        for sibling in boundary.parent.children:
            if sibling is boundary or sibling.tag.casefold() != "h1":
                continue
            value = _node_text(sibling)
            if value:
                primary.append(value)
    return tuple(dict.fromkeys(primary)), tuple(dict.fromkeys(secondary))


def _has_ancestor_tag(node: _Node, tag: str) -> bool:
    return any(ancestor.tag.casefold() == tag.casefold() for ancestor in _ancestors(node))


def _headline_structure_conflict(
    boundary: _Node,
    root: _Node,
) -> tuple[bool, tuple[str, ...]]:
    """Return structural headline conflicts without comparing headline text."""

    has_head = any(node.tag.casefold() == "head" for node in _walk(root))
    title_nodes: list[_Node] = []
    metadata_nodes: dict[str, list[_Node]] = {"og:title": [], "twitter:title": []}
    principal_h1_nodes: list[_Node] = []
    detached_metadata = False

    for node in _walk(root):
        tag = node.tag.casefold()
        if tag == "title":
            associated = not has_head or _has_ancestor_tag(node, "head")
            if associated:
                title_nodes.append(node)
            else:
                detached_metadata = True
        elif tag == "meta":
            key = (node.attrs.get("property") or node.attrs.get("name") or "").casefold()
            if key not in metadata_nodes:
                continue
            associated = not has_head or _has_ancestor_tag(node, "head")
            if associated:
                metadata_nodes[key].append(node)
            else:
                detached_metadata = True
        elif (
            tag == "h1"
            and _is_descendant(node, boundary)
            and not _has_ancestor(node, _is_article_node, boundary)
        ):
            principal_h1_nodes.append(node)

    reasons: list[str] = []
    if len(title_nodes) > 1:
        reasons.append("duplicate_title_elements")
    for key, nodes in metadata_nodes.items():
        if len(nodes) > 1:
            reasons.append(f"duplicate_{key.replace(':', '_')}_metadata")
    if len(principal_h1_nodes) > 1:
        reasons.append("multiple_principal_h1")
    if detached_metadata:
        reasons.append("detached_headline_metadata")
    return bool(reasons), tuple(reasons)


def _canonical_values(root: _Node) -> tuple[str, ...]:
    values: list[str] = []
    for node in _walk(root):
        if node.tag.casefold() == "link" and "canonical" in node.attrs.get("rel", "").casefold():
            if node.attrs.get("href"):
                values.append(node.attrs["href"])
        if node.tag.casefold() == "meta":
            key = (node.attrs.get("property") or node.attrs.get("name") or "").casefold()
            if key in {"og:url", "twitter:url"} and node.attrs.get("content"):
                values.append(node.attrs["content"])
    return tuple(dict.fromkeys(values))


def _assessment(
    *,
    format_name: str,
    parse_status: str,
    status: PrincipalDocumentStatus,
    boundary: _Node | None,
    root: _Node,
    canonical_values: tuple[str, ...],
    excluded: list[str],
    structural_conflict: bool = False,
    unsupported_structure: bool = False,
    reject_reason: str = "",
    diagnostics: dict[str, Any] | None = None,
) -> StructuralAssessment:
    principal_id = boundary.node_id if boundary is not None else ""
    body_segments: tuple[DocumentSegment, ...] = ()
    primary: tuple[str, ...] = ()
    secondary: tuple[str, ...] = ()
    effective_status = status
    if boundary is not None and status is PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_ESTABLISHED:
        body, has_noninteractive, has_any = _collect_principal_body(boundary, excluded)
        primary, secondary = _headlines_for(boundary, root)
        if body and has_any and has_noninteractive:
            body_segments = (DocumentSegment("body-0001", body),)
        else:
            effective_status = PrincipalDocumentStatus.STRUCTURAL_FAILURE_ESTABLISHED
            body_segments = ()
            if has_any:
                reject_reason = reject_reason or "TITLE_ONLY"
            else:
                reject_reason = reject_reason or "CONTENT_UNAVAILABLE"
    if effective_status is not PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_ESTABLISHED:
        principal_id = "" if effective_status is not status else principal_id
    return StructuralAssessment(
        format=format_name,
        parse_status=parse_status,
        principal_document_status=effective_status,
        principal_document_identifier=principal_id,
        principal_segment_ids=tuple(segment.segment_id for segment in body_segments),
        principal_body_segments=body_segments,
        document_level_headlines=primary,
        secondary_headlines=secondary,
        canonical_values=canonical_values,
        excluded_region_reasons=tuple(dict.fromkeys(excluded)),
        structural_conflict=structural_conflict,
        unsupported_structure=unsupported_structure,
        reject_reason=reject_reason,
        diagnostics=diagnostics or {},
    )


def _assess_tree(
    root: _Node,
    *,
    format_name: str,
    parse_status: str,
    parse_diagnostics: list[str],
    canonical_values: tuple[str, ...],
    resource_url: str,
) -> StructuralAssessment:
    excluded: list[str] = [
        f"{node.node_id}:{reason}"
        for node in _walk(root)
        if node is not root
        for reason in [_exclusion_reason(node)]
        if reason
    ]
    mains = _find_main_nodes(root)
    if len(mains) > 1:
        return _assessment(
            format_name=format_name,
            parse_status=parse_status,
            status=PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_AMBIGUOUS,
            boundary=None,
            root=root,
            canonical_values=canonical_values,
            excluded=excluded,
            structural_conflict=True,
            reject_reason="SOURCE_PAGE_MISMATCH",
            diagnostics={"parse_diagnostics": parse_diagnostics},
        )

    region = mains[0] if mains else root
    articles = _find_article_roots(region)
    if _collection_has_multiple_units(region):
        return _assessment(
            format_name=format_name,
            parse_status=parse_status,
            status=PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_AMBIGUOUS,
            boundary=None,
            root=root,
            canonical_values=canonical_values,
            excluded=excluded,
            structural_conflict=True,
            reject_reason="SOURCE_PAGE_MISMATCH",
            diagnostics={"parse_diagnostics": parse_diagnostics, "collection": True},
        )

    if len(articles) > 1:
        return _assessment(
            format_name=format_name,
            parse_status=parse_status,
            status=PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_AMBIGUOUS,
            boundary=None,
            root=root,
            canonical_values=canonical_values,
            excluded=excluded,
            structural_conflict=True,
            reject_reason="SOURCE_PAGE_MISMATCH",
            diagnostics={"parse_diagnostics": parse_diagnostics},
        )

    boundary = articles[0] if articles else (region if region is not root else None)
    if boundary is None:
        parsed_url = urlsplit(resource_url)
        is_search_shell = bool(
            any(node.tag.casefold() == "nav" for node in _walk(root))
            and parsed_url.query.casefold().startswith(("q=", "query="))
            and "search" in parsed_url.path.casefold()
        )
        if is_search_shell:
            return _assessment(
                format_name=format_name,
                parse_status=parse_status,
                status=PrincipalDocumentStatus.STRUCTURAL_FAILURE_ESTABLISHED,
                boundary=None,
                root=root,
                canonical_values=canonical_values,
                excluded=excluded,
                unsupported_structure=True,
                reject_reason="SOURCE_PAGE_MISMATCH",
                diagnostics={
                    "parse_diagnostics": parse_diagnostics,
                    "structural_exclusions": bool(excluded),
                    "page_kind": "search_shell",
                },
            )
        body_nodes = _find_body_nodes(root)
        if len(body_nodes) > 1:
            return _assessment(
                format_name=format_name,
                parse_status=parse_status,
                status=PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_AMBIGUOUS,
                boundary=None,
                root=root,
                canonical_values=canonical_values,
                excluded=excluded,
                structural_conflict=True,
                reject_reason="SOURCE_PAGE_MISMATCH",
                diagnostics={
                    "parse_diagnostics": parse_diagnostics,
                    "competing_body_regions": True,
                },
            )
        if len(body_nodes) == 1:
            boundary = body_nodes[0]
    if boundary is None:
        # A document with no markup-owned principal boundary cannot prove that
        # it is one complete authoritative document in this Phase 1 boundary.
        parsed_url = urlsplit(resource_url)
        is_search_shell = bool(
            any(node.tag.casefold() == "nav" for node in _walk(root))
            and parsed_url.query.casefold().startswith(("q=", "query="))
            and "search" in parsed_url.path.casefold()
        )
        return _assessment(
            format_name=format_name,
            parse_status=parse_status,
            status=PrincipalDocumentStatus.STRUCTURAL_FAILURE_ESTABLISHED,
            boundary=None,
            root=root,
            canonical_values=canonical_values,
            excluded=excluded,
            unsupported_structure=True,
            reject_reason="SOURCE_PAGE_MISMATCH" if is_search_shell else "CONTENT_UNAVAILABLE",
            diagnostics={
                "parse_diagnostics": parse_diagnostics,
                "structural_exclusions": bool(excluded),
                **({"page_kind": "search_shell"} if is_search_shell else {}),
            },
        )

    # A root resource containing only global navigation plus a generic main
    # region is a landing page, not proof of an event document.  The URL is a
    # corroborating resource hint here; it is never sufficient by itself.
    parsed_url = urlsplit(resource_url)
    if (
        len(mains) == 1
        and not articles
        and (parsed_url.path or "/") in {"", "/"}
        and any(node.tag.casefold() == "nav" for node in _walk(root))
        and not any(node.tag.casefold() == "h1" and _is_descendant(node, boundary) for node in _walk(boundary))
    ):
        return _assessment(
            format_name=format_name,
            parse_status=parse_status,
            status=PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_AMBIGUOUS,
            boundary=None,
            root=root,
            canonical_values=canonical_values,
            excluded=excluded,
            structural_conflict=True,
            reject_reason="SOURCE_PAGE_MISMATCH",
            diagnostics={"parse_diagnostics": parse_diagnostics, "page_kind": "landing_page"},
        )

    if _has_unresolved_generic_sibling_units(boundary):
        return _assessment(
            format_name=format_name,
            parse_status=parse_status,
            status=PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_AMBIGUOUS,
            boundary=None,
            root=root,
            canonical_values=canonical_values,
            excluded=excluded,
            structural_conflict=True,
            reject_reason="SOURCE_PAGE_MISMATCH",
            diagnostics={
                "parse_diagnostics": parse_diagnostics,
                "unresolved_generic_sibling_units": True,
            },
        )

    # A page-level header is outside the selected boundary and is therefore
    # ignored; a header descendant of an article remains available to the
    # body/headline collector.  Sibling regions are not concatenated.
    for node in region.children:
        if node is not boundary and node is not region:
            reason = _exclusion_reason(node)
            if reason:
                excluded.append(f"{node.node_id}:{reason}")
            elif _node_text(node):
                excluded.append(f"{node.node_id}:outside_principal_boundary")

    headline_conflict, headline_conflict_reasons = _headline_structure_conflict(boundary, root)
    if headline_conflict:
        return _assessment(
            format_name=format_name,
            parse_status=parse_status,
            status=PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_AMBIGUOUS,
            boundary=None,
            root=root,
            canonical_values=canonical_values,
            excluded=excluded,
            structural_conflict=True,
            reject_reason="SOURCE_PAGE_MISMATCH",
            diagnostics={
                "parse_diagnostics": parse_diagnostics,
                "headline_conflict": True,
                "headline_conflict_reasons": list(headline_conflict_reasons),
            },
        )

    assessment = _assessment(
        format_name=format_name,
        parse_status=parse_status,
        status=PrincipalDocumentStatus.PRINCIPAL_DOCUMENT_ESTABLISHED,
        boundary=boundary,
        root=root,
        canonical_values=canonical_values,
        excluded=excluded,
        diagnostics={"parse_diagnostics": parse_diagnostics},
    )
    if not assessment.principal_body_segments:
        reason = assessment.reject_reason or "INSUFFICIENT_SUBSTANCE"
        return replace(assessment, reject_reason=reason)
    return assessment


def _split_expanded_name(value: str) -> tuple[str, str]:
    if value.startswith("{") and "}" in value:
        namespace, local = value[1:].split("}", 1)
        return namespace, local
    return "", value


def _xml_to_tree(element: ElementTree.Element, parent: _Node, counter: list[int]) -> _Node:
    raw_tag = str(element.tag)
    namespace, local_name = _split_expanded_name(raw_tag)
    node = _Node(
        f"node-{counter[0]:04d}",
        local_name.casefold(),
        {str(key): str(value) for key, value in element.attrib.items()},
        namespace=namespace,
        qualified_name=raw_tag,
    )
    counter[0] += 1
    parent.add_child(node)
    if element.text:
        node.text_parts.append(element.text)
    for child in list(element):
        _xml_to_tree(child, node, counter)
        if child.tail:
            node.text_parts.append(child.tail)
    return node


def _xml_representation_facts(root: _Node) -> dict[str, Any]:
    namespaces = sorted({node.namespace for node in _walk(root) if node.namespace})
    nodes = [
        {
            "node_id": node.node_id,
            "qualified_name": node.qualified_name or node.tag,
            "namespace": node.namespace,
            "attributes": dict(node.attrs),
        }
        for node in _walk(root)
        if node is not root and (node.namespace or node.attrs)
    ]
    relationships = []
    for node in _walk(root):
        for key, value in node.attrs.items():
            _, local_name = _split_expanded_name(key)
            if local_name.casefold() in {"about", "resource", "nodeid", "datatype", "parsetype"}:
                relationships.append(
                    {"node_id": node.node_id, "attribute": key, "value": value}
                )
    return {
        "xml_namespaces": namespaces,
        "xml_nodes": nodes,
        "xml_relationships": relationships,
    }


def _has_unsupported_rdf_graph(root: _Node) -> bool:
    root_node = root.children[0] if root.children else None
    if root_node is None or root_node.tag.casefold() != "rdf":
        return False
    for node in _walk(root):
        if node.tag.casefold() == "description":
            return True
        for key in node.attrs:
            _, local_name = _split_expanded_name(key)
            if local_name.casefold() in {"about", "resource", "nodeid", "datatype", "parsetype"}:
                return True
    return False


def _looks_like_feed(root: _Node, content_type: str) -> bool:
    media = str(content_type or "").split(";", 1)[0].strip().casefold()
    if media in {"application/rss+xml", "application/atom+xml"}:
        return True
    root_tag = root.children[0].tag if root.children else ""
    if root_tag in {"rss", "feed"}:
        return True
    if root_tag == "rdf":
        names = {node.tag for node in _walk(root)}
        if {"channel", "item"}.issubset(names):
            return True
    return False


def _assess_xml(content: str, content_type: str, resource_url: str) -> StructuralAssessment:
    try:
        element = ElementTree.fromstring(content)
    except ElementTree.ParseError:
        return StructuralAssessment(
            format="xml",
            parse_status="malformed",
            principal_document_status=PrincipalDocumentStatus.STRUCTURAL_FAILURE_ESTABLISHED,
            principal_document_identifier="",
            principal_segment_ids=(),
            principal_body_segments=(),
            document_level_headlines=(),
            secondary_headlines=(),
            canonical_values=(),
            unsupported_structure=True,
            reject_reason="CONTENT_UNAVAILABLE",
        )
    root = _Node("document", "#document")
    _xml_to_tree(element, root, [1])
    xml_facts = _xml_representation_facts(root)
    if _looks_like_feed(root, content_type):
        return StructuralAssessment(
            format="feed",
            parse_status="ok",
            principal_document_status=PrincipalDocumentStatus.STRUCTURAL_FAILURE_ESTABLISHED,
            principal_document_identifier="",
            principal_segment_ids=(),
            principal_body_segments=(),
            document_level_headlines=(),
            secondary_headlines=(),
            canonical_values=(),
            unsupported_structure=False,
            reject_reason="SOURCE_PAGE_MISMATCH",
            diagnostics={"page_kind": "discovery_feed", **xml_facts},
        )
    if _has_unsupported_rdf_graph(root):
        return StructuralAssessment(
            format="rdf",
            parse_status="ok",
            principal_document_status=PrincipalDocumentStatus.STRUCTURAL_FAILURE_ESTABLISHED,
            principal_document_identifier="",
            principal_segment_ids=(),
            principal_body_segments=(),
            document_level_headlines=(),
            secondary_headlines=(),
            canonical_values=(),
            unsupported_structure=True,
            reject_reason="SOURCE_PAGE_MISMATCH",
            diagnostics={"unsupported_structure_reason": "rdf_graph", **xml_facts},
        )
    assessment = _assess_tree(
        root,
        format_name="rdf" if (root.children and root.children[0].tag == "rdf") else "xml",
        parse_status="ok",
        parse_diagnostics=[],
        canonical_values=(),
        resource_url=resource_url,
    )
    return replace(assessment, diagnostics={**xml_facts, **assessment.diagnostics})


def assess_document(
    content: str,
    content_type: str,
    *,
    resource_url: str = "",
) -> StructuralAssessment:
    """Parse one acquired source and return structural facts only."""

    media = str(content_type or "").split(";", 1)[0].strip().casefold()
    source = str(content or "")
    if "xml" in media or "rdf" in media or source.lstrip().startswith("<?xml"):
        return _assess_xml(source, content_type, resource_url)
    if "<" not in source or ">" not in source:
        return StructuralAssessment(
            format="plain_text",
            parse_status="unsupported_without_boundary",
            principal_document_status=PrincipalDocumentStatus.STRUCTURAL_FAILURE_ESTABLISHED,
            principal_document_identifier="",
            principal_segment_ids=(),
            principal_body_segments=(),
            document_level_headlines=(),
            secondary_headlines=(),
            canonical_values=(),
            unsupported_structure=True,
            reject_reason="CONTENT_UNAVAILABLE",
        )
    parser = lxml_html.HTMLParser(recover=True, remove_comments=True)
    try:
        document = lxml_html.document_fromstring(source, parser=parser)
    except Exception as exc:  # pragma: no cover - defensive parser boundary
        return StructuralAssessment(
            format="html",
            parse_status="error",
            principal_document_status=PrincipalDocumentStatus.STRUCTURAL_FAILURE_ESTABLISHED,
            principal_document_identifier="",
            principal_segment_ids=(),
            principal_body_segments=(),
            document_level_headlines=(),
            secondary_headlines=(),
            canonical_values=(),
            unsupported_structure=True,
            reject_reason="CONTENT_UNAVAILABLE",
            diagnostics={"parse_error": type(exc).__name__},
        )
    root = _Node("document", "#document")
    _lxml_to_tree(document, root, [1])
    parse_diagnostics = [
        f"lxml:{entry.level_name.casefold()}:{entry.message}"
        for entry in parser.error_log
    ]
    return _assess_tree(
        root,
        format_name="html",
        parse_status="ok",
        parse_diagnostics=parse_diagnostics + [
            "metadata_present"
            for node in _walk(root)
            if node.tag.casefold() == "meta"
        ],
        canonical_values=_canonical_values(root),
        resource_url=resource_url,
    )
