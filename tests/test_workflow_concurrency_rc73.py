"""RC-73 (section A.54): the production concurrency group sits on the two jobs that need it."""

from __future__ import annotations

from pathlib import Path
import re

WORKFLOW = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "weekly-report.yml").read_text(
    encoding="utf-8"
)
GROUP = "concurrency:\n      group: weekly-report-production\n      cancel-in-progress: false"


def _job(name: str) -> str:
    start = WORKFLOW.index(f"\n  {name}:")
    following = re.search(r"\n  [a-z][a-z-]*:\n", WORKFLOW[start + 1 :])
    return WORKFLOW[start : start + 1 + following.start()] if following else WORKFLOW[start:]


def test_the_workflow_itself_declares_no_concurrency():
    assert not re.search(r"^concurrency:", WORKFLOW, flags=re.M)


def test_production_and_recall_test_share_one_group_without_cancelling():
    assert GROUP in _job("production")
    assert GROUP in _job("recall-test")


def test_no_other_job_queues_behind_them():
    for name in ("offline-regression", "recall-plan", "source-probe", "delivery-check"):
        assert "concurrency" not in _job(name), name
