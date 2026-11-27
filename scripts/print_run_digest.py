"""Print the concise run digest last in a job log and job summary (RC-90, observation only).

    python -m scripts.print_run_digest report-output [--gold acceptance/gold/recall_v1.json]
                                       [--step-summary "$GITHUB_STEP_SUMMARY"]

The digest (``run_digest.txt``, written by main.py from the result and its
RunTrace) is printed as is. With ``--gold`` (recall tests) the v4 score of the
run's selection audit is appended: one line for the score and one short line
per gold item. With ``--step-summary`` the same text is appended to the job
summary file. A missing digest or audit is reported in one line; this script
never fails the job.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.recall_score import load_audit, load_gold, score  # noqa: E402
from src.weekly_report.run_digest import DIGEST_BEGIN, DIGEST_END  # noqa: E402


def score_lines(gold_path: str | Path, audit_path: str | Path) -> list[str]:
    result = score(load_gold(gold_path), load_audit(audit_path))
    lines = [
        f"recall_v4: accuracy={result['correct']}/{result['gold_groups']} missed={result['missed']}"
        f" wrong_section={result['wrong_section']} false_inclusions={result['false_inclusions']}"
        f" duplicates={result['duplicates']} included_events={result['included_events']}"
        f" unlabeled={len(result['unlabeled_included_events'])}"
    ]
    for row in result["rows"]:
        lines.append(f"  {row['gold_id']!s:<4} {'*' * row['stars']:<4} {row['expected']:<7} {row['outcome']:<15}"
                     f" x{row['included_events']} {row['title'][:40]}")
    return lines


def digest_text(directory: str | Path, gold: str | Path | None = None) -> str:
    directory = Path(directory)
    digest = directory / "run_digest.txt"
    if digest.is_file():
        text = digest.read_text(encoding="utf-8").rstrip("\n")
    else:
        text = f"{DIGEST_BEGIN}\nrun_digest=UNAVAILABLE (no run_digest.txt)\n{DIGEST_END}"
    if gold is not None:
        audit = directory / "selection_audit.json"
        try:
            extra = score_lines(gold, audit)
        except Exception as exc:  # noqa: BLE001 - observation only
            extra = [f"recall_v4=UNAVAILABLE failure_class={type(exc).__name__}"]
        lines = text.split("\n")
        if lines and lines[-1] == DIGEST_END:
            text = "\n".join(lines[:-1] + extra + [DIGEST_END])
        else:
            text = "\n".join(lines + extra)
    return text + "\n"


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("directory")
    parser.add_argument("--gold")
    parser.add_argument("--step-summary")
    args = parser.parse_args(list(argv) if argv is not None else None)
    text = digest_text(args.directory, args.gold)
    print(text, end="")
    if args.step_summary:
        with open(args.step_summary, "a", encoding="utf-8") as handle:
            handle.write("```\n" + text + "```\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
