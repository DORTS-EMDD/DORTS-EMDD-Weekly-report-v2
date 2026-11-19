"""RC-72 (section A.53): Google News health gate rule and one 45-minute retry."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.weekly_report.google_news_rss_provider import GoogleNewsRssProvider, RssTransportResponse  # noqa: E402
from src.weekly_report.production_runner import (  # noqa: E402
    HEALTH_MIN_SUCCESS_COUNT,
    HEALTH_RETRY_WAIT_SECONDS,
    GoogleNewsHealthCheck,
)
from src.weekly_report.region_registry import RegionRegistry  # noqa: E402

OK = "ok"
LIMITED = "429"
CONNECTION = "connection"
SERVER_ERROR = "503"
UNPARSABLE = "unparsable"

_BODY = b"<rss><channel><item><title>t</title><link>https://example.test/a</link></item></channel></rss>"


class _Script:
    """A transport that answers each request from a per-request script."""

    def __init__(self, *outcomes: str) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    def __call__(self, url, timeout):
        outcome = self.outcomes[self.calls]
        self.calls += 1
        if outcome == OK:
            return RssTransportResponse(_BODY)
        if outcome == LIMITED:
            return RssTransportResponse(b"", status_code=429)
        if outcome == SERVER_ERROR:
            return RssTransportResponse(b"", status_code=503)
        if outcome == UNPARSABLE:
            return RssTransportResponse(b"not xml at all")
        raise ConnectionError("connection reset")


def _check(script: _Script) -> GoogleNewsHealthCheck:
    return GoogleNewsHealthCheck(RegionRegistry.from_file(), GoogleNewsRssProvider(script))


def test_the_rule_constants_are_the_user_decision():
    assert HEALTH_MIN_SUCCESS_COUNT == 4
    assert HEALTH_RETRY_WAIT_SECONDS == 45 * 60


def test_four_successes_and_two_rate_limits_pass_without_retry():
    script = _Script(OK, OK, LIMITED, OK, LIMITED, OK)
    waits: list[float] = []
    gate = _check(script).run_gated(sleep=waits.append)
    assert gate.passed
    assert len(gate.attempts) == 1
    assert gate.final.success_count == 4 and gate.final.failure_count == 2
    assert {p.technical_failure_class for p in gate.final.probes if p.technical_failure_class} == {"RATE_LIMIT"}
    assert waits == [] and script.calls == 6


def test_a_non_rate_limit_failure_is_a_fail_even_with_four_successes():
    one_connection_error = _Script(OK, OK, LIMITED, OK, CONNECTION, OK)
    assert _check(one_connection_error).run().status == "FAIL"
    for other in (CONNECTION, SERVER_ERROR, UNPARSABLE):
        result = _check(_Script(OK, OK, OK, OK, OK, other)).run()
        assert result.success_count == 5
        assert result.status == "FAIL", other


def test_a_miss_waits_45_minutes_then_reruns_all_six_and_fails_if_still_short():
    script = _Script(OK, OK, OK, LIMITED, LIMITED, LIMITED, OK, LIMITED, LIMITED, LIMITED, LIMITED, OK)
    waits: list[float] = []
    observed: list[tuple[int, str]] = []
    gate = _check(script).run_gated(sleep=waits.append, observe=lambda n, r: observed.append((n, r.status)))
    assert not gate.passed
    assert len(gate.attempts) == 2 and script.calls == 12
    assert waits == [2700]
    assert observed == [(1, "FAIL"), (2, "FAIL")]


def test_three_successes_retry_and_a_passing_second_attempt_passes():
    script = _Script(OK, OK, OK, LIMITED, LIMITED, LIMITED, OK, OK, OK, OK, OK, OK)
    waits: list[float] = []
    gate = _check(script).run_gated(sleep=waits.append)
    assert gate.passed
    assert [a.status for a in gate.attempts] == ["FAIL", "PASS"]
    assert waits == [HEALTH_RETRY_WAIT_SECONDS]
    assert script.calls == 12


def test_a_non_rate_limit_failure_also_retries_once_and_the_second_attempt_decides():
    script = _Script(OK, OK, OK, OK, OK, CONNECTION, OK, OK, OK, OK, LIMITED, OK)
    waits: list[float] = []
    gate = _check(script).run_gated(sleep=waits.append)
    assert [a.status for a in gate.attempts] == ["FAIL", "PASS"]
    assert waits == [2700]


def test_all_six_successes_pass_with_one_attempt():
    gate = _check(_Script(*[OK] * 6)).run_gated(sleep=lambda s: (_ for _ in ()).throw(AssertionError("no wait")))
    assert gate.passed and len(gate.attempts) == 1
