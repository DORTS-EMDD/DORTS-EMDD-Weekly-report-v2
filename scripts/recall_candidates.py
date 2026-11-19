"""Print every candidate of one run from selection_audit.json (observation only).

One line per candidate: title, publisher, terminal stage, terminal reason and
the Category when the candidate's Event reached one. Reads the audit the run
already wrote; it recomputes no decision.
"""

from __future__ import annotations

import base64
import gzip
import json
from pathlib import Path
import sys

# The selection audit, gzip-compressed and base64-encoded, one chunk per log
# line, so a reader without artifact access can rebuild the exact file from the
# job log (scripts/recall_score.py and scripts/event_identity_replay.py read it).
AUDIT_LINE_PREFIX = "AUDIT_B64 "
AUDIT_CHUNK = 2000


def candidate_lines(audit: dict) -> list[str]:
    lines = []
    for entry in audit.get("candidates", ()):
        category = ((entry.get("event") or {}).get("category") or {}).get("primary_category")
        lines.append(
            " | ".join(
                (
                    "CANDIDATE",
                    str(entry.get("terminal_stage")),
                    str(entry.get("terminal_reason")),
                    f"category={category or '-'}",
                    f"publisher={entry.get('publisher') or '-'}",
                    f"title={entry.get('discovery_title') or '-'}",
                )
            )
        )
    return lines


def audit_lines(raw: bytes) -> list[str]:
    encoded = base64.b64encode(gzip.compress(raw, mtime=0)).decode("ascii")
    return [AUDIT_LINE_PREFIX + encoded[i:i + AUDIT_CHUNK] for i in range(0, len(encoded), AUDIT_CHUNK)]


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else Path("report-output/selection_audit.json")
    if not path.is_file():
        print(f"recall_candidates=UNAVAILABLE no {path}")
        return 0
    audit = json.loads(path.read_text(encoding="utf-8"))
    print(
        f"candidate_count={audit.get('candidate_count')} event_count={audit.get('event_count')} "
        f"final_report_event_count={audit.get('final_report_event_count')}"
    )
    print("terminal_reason_distribution=" + json.dumps(audit.get("terminal_reason_distribution"), ensure_ascii=False))
    for line in candidate_lines(audit):
        print(line)
    print("===== SELECTION AUDIT (gzip+base64; rebuild with scripts/recall_score.py) =====")
    for line in audit_lines(path.read_bytes()):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
