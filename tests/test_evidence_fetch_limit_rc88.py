"""RC-88 (external review): the Evidence fetcher checks the Content-Type first and bounds the page size."""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from src.weekly_report import evidence_service
from src.weekly_report.contracts import EvidenceState
from src.weekly_report.evidence_service import EVIDENCE_FETCH_MAX_BYTES, EvidenceService, _default_fetcher
from tests.test_evidence_contract import _candidate, _MockHTTPOpener, _SameEventJudge

URL = "http://limit.test/article"
PUBLIC_DNS = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]


class _Response:
    def __init__(self, body: bytes, content_type: str, length: str | None = None):
        self.body, self.reads = body, []
        self.status = 200
        self.headers = {"Content-Type": content_type, **({"Content-Length": length} if length is not None else {})}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, amount=None):
        self.reads.append(amount)
        return self.body if amount is None else self.body[:amount]

    def geturl(self):
        return URL


def _fetch(response):
    with (
        patch.object(evidence_service.socket, "getaddrinfo", return_value=PUBLIC_DNS),
        patch.object(evidence_service, "build_opener", return_value=_MockHTTPOpener(response)),
    ):
        return _default_fetcher(URL, 5.0)


def test_a_non_textual_page_is_not_read():
    response = _Response(b"%PDF-1.7 ...", "application/pdf")
    fetched = _fetch(response)
    assert response.reads == [] and fetched.content == "" and fetched.content_type == "application/pdf"


@pytest.mark.parametrize(
    "response",
    [
        _Response(b"<html></html>", "text/html", length=str(EVIDENCE_FETCH_MAX_BYTES + 1)),
        _Response(b"x" * (EVIDENCE_FETCH_MAX_BYTES + 1), "text/html"),
    ],
)
def test_a_page_over_the_limit_is_an_acquisition_failure(response):
    with pytest.raises(evidence_service._EvidenceFetchTooLarge):
        _fetch(response)
    assert all(amount == EVIDENCE_FETCH_MAX_BYTES + 1 for amount in response.reads)


def test_the_service_rejects_an_oversized_page_at_fetch_transport():
    response = _Response(b"x" * (EVIDENCE_FETCH_MAX_BYTES + 1), "text/html")
    with (
        patch.object(evidence_service.socket, "getaddrinfo", return_value=PUBLIC_DNS),
        patch.object(evidence_service, "build_opener", return_value=_MockHTTPOpener(response)),
    ):
        result = EvidenceService(semantic_judge=_SameEventJudge()).evaluate(_candidate(url=URL))
    assert result.state is EvidenceState.REJECTED
    assert result.provenance["evidence_rejection_gate"] == "FETCH_TRANSPORT"
    assert result.provenance["transport_error"] == "_EvidenceFetchTooLarge"


def test_a_page_within_the_limit_is_read_whole():
    body = b"<html><body><article><p>Body.</p></article></body></html>"
    fetched = _fetch(_Response(body, "text/html; charset=utf-8", length=str(len(body))))
    assert fetched.content == body.decode()
