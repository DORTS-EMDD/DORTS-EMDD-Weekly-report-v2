"""RC-55 live-check tooling (scripts/delivery_ledger_checks.py), offline.

A fake GitHub contents API with the provider's compare-and-swap rules (409 for
a stale SHA, 422 for a blind create over an existing file, 403 where the token
cannot write) shows that each check passes on a correct provider and fails on
a provider or token that would break RC-55. No network, no SMTP.
"""

from __future__ import annotations

import base64
import hashlib
import json
from urllib.parse import unquote, urlsplit

from scripts import delivery_ledger_checks as checks
from src.weekly_report.delivery_ledger import GitHubContentsLedgerStore
from tests.delivery_fakes import FakeLedgerStore, FakeSender

LEDGER = "DORTS-EMDD/weekly-report-delivery-ledger"
SECRET = b"k" * 40
TOKEN = "fake-token-value"


class FakeGitHub:
    def __init__(self, *, writable=(LEDGER,), compare_and_swap=True):
        self.files: dict[tuple[str, str], tuple[bytes, str]] = {}
        self.writable = set(writable)
        self.compare_and_swap = compare_and_swap
        self.requests: list[tuple[str, str]] = []

    def __call__(self, method, url, headers, body, timeout):
        assert headers["Authorization"] == f"Bearer {TOKEN}"
        parts = urlsplit(url).path.split("/")
        repository, path = f"{parts[2]}/{parts[3]}", unquote("/".join(parts[5:]))
        self.requests.append((method, repository))
        current = self.files.get((repository, path))
        if method == "GET":
            if current is None:
                return 404, b""
            return 200, json.dumps({"content": base64.b64encode(current[0]).decode(), "sha": current[1]}).encode()
        if repository not in self.writable:
            return 403, b""
        payload = json.loads(body)
        if self.compare_and_swap:
            if current is not None and "sha" not in payload:
                return 422, b""
            if (current[1] if current else None) != payload.get("sha"):
                return 409, b""
        content = base64.b64decode(payload["content"])
        sha = hashlib.sha1(content + str(len(self.files)).encode()).hexdigest()
        self.files[(repository, path)] = (content, sha)
        return 200, b"{}"


def _store(github):
    return GitHubContentsLedgerStore(LEDGER, TOKEN, transport=github)


def test_l1_passes_on_a_compare_and_swap_provider():
    results = checks.check_l1(_store(FakeGitHub()), SECRET, "123a1")
    assert all(results.values()), results


def test_l1_fails_on_a_provider_without_compare_and_swap():
    results = checks.check_l1(_store(FakeGitHub(compare_and_swap=False)), SECRET, "123a1")
    assert results["stale_write_rejected"] is False
    assert results["owner_sent_nothing_on_a_lost_race"] is False  # the owner would send on a lost race


def test_l2_passes_for_a_ledger_only_token_and_fails_for_an_over_scoped_one():
    github = FakeGitHub()
    checks.check_l1(_store(github), SECRET, "123a1")
    assert all(checks.check_l2(TOKEN, LEDGER, "checks/l1-123a1.json", transport=github).values())

    over_scoped = FakeGitHub(writable=(LEDGER, checks.APP_REPOSITORY))
    checks.check_l1(_store(over_scoped), SECRET, "123a1")
    results = checks.check_l2(TOKEN, LEDGER, "checks/l1-123a1.json", transport=over_scoped)
    assert results["application_repository_write_denied"] is False
    # The probe never changes the application repository.
    assert (checks.APP_REPOSITORY, "README.md") not in over_scoped.files


def test_l3_sends_one_message_claims_first_and_the_second_run_is_duplicate(capsys):
    store, sender = FakeLedgerStore(), FakeSender()
    recipient = "sender-account@example.test"
    results = checks.check_l3(store, SECRET, sender, recipient, "123a1")
    assert all(results.values()), results
    assert sender.delivered == [recipient]
    # A rerun of the check sends nothing more.
    again = checks.check_l3(store, SECRET, sender, recipient, "124a1")
    assert all(again.values()), again
    assert sender.delivered == [recipient]
    assert recipient not in capsys.readouterr().out


def test_l3_fails_when_the_handoff_fails_and_does_not_retry(capsys):
    store, sender = FakeLedgerStore(), FakeSender({"sender-account@example.test": "data_reject"})
    results = checks.check_l3(store, SECRET, sender, "sender-account@example.test", "123a1")
    assert results["first_run_sent_or_already_verified"] is False
    assert sender.attempted == ["sender-account@example.test"]
    assert "SENDMAIL:SMTPDataError:554" in capsys.readouterr().out


def test_missing_configuration_fails_without_printing_values(monkeypatch, capsys):
    for name in ("DELIVERY_LEDGER_REPOSITORY", "DELIVERY_LEDGER_TOKEN", "DELIVERY_LEDGER_KEY", "GITHUB_STEP_SUMMARY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DELIVERY_LEDGER_TOKEN", TOKEN)
    assert checks.main(["l1-l2"]) == 1
    output = capsys.readouterr().out
    assert "failure_class=CheckConfigurationError" in output
    assert TOKEN not in output
    assert checks.main(["unknown"]) == 2
