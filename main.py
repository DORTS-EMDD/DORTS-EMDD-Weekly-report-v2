"""Thin command-line entrypoint for the V2 production runner."""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from weekly_report.contracts import RegionMode  # noqa: E402
from weekly_report.production_runner import ProductionRunner  # noqa: E402
from weekly_report.debug_service import execution_trace  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one Weekly-report V2 production report")
    parser.add_argument("--period-start", type=date.fromisoformat)
    parser.add_argument("--period-end", type=date.fromisoformat)
    parser.add_argument(
        "--region-mode",
        choices=tuple(mode.value for mode in RegionMode),
        default=RegionMode.SELECTED.value,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="write the formal report as Markdown and PDF plus the run summary and selection audit",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    with execution_trace() as trace:
        code = _main(argv)
        trace.outcome(code in (0, 2), partial=code == 2)
        return code


def _main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        runner = ProductionRunner.from_environment()
        result = runner.run(
            region_mode=args.region_mode,
            period_start=args.period_start,
            period_end=args.period_end,
        )
    except Exception as exc:
        print(f"status=CONFIGURATION_FAILURE failure_class={type(exc).__name__} diagnostic=production configuration unavailable")
        return 1
    print(result.summary())
    if args.output_dir is not None and not _write_outputs(args.output_dir, result):
        return 1
    delivery = getattr(result, "delivery_result", None)
    if delivery is not None and delivery.status.value == "FAILED":
        # The report exists but was not delivered; automation must not look green.
        return 1
    if result.complete:
        return 0
    # Artifact produced with disclosed technical gaps: not a complete success.
    return 2 if result.successful else 1


def _write_outputs(directory: Path, result) -> bool:
    """Write the assembled report files; False when the PDF cannot be rendered."""

    from weekly_report.pdf_renderer import pdf_filename, render_report_pdf

    directory.mkdir(parents=True, exist_ok=True)
    (directory / "run_summary.txt").write_text(result.summary() + chr(10), encoding="utf-8")
    written = {"run_summary": "run_summary.txt"}
    audit = getattr(result, "selection_audit", None)
    if audit is not None:
        # Observer-only projection of every candidate's path (RC-31).
        (directory / "selection_audit.json").write_text(
            json.dumps(audit, ensure_ascii=False, indent=1, sort_keys=False) + chr(10), encoding="utf-8"
        )
        written["selection_audit"] = "selection_audit.json"
    pdf_ok = True
    artifact = result.final_report
    if artifact is not None:
        (directory / f"{artifact.report_id}.md").write_text(artifact.content, encoding="utf-8")
        written["report_markdown"] = f"{artifact.report_id}.md"
        try:
            (directory / pdf_filename(artifact)).write_bytes(render_report_pdf(artifact))
            written["report_pdf"] = pdf_filename(artifact)
        except Exception as exc:
            print(f"pdf=FAILED failure_class={type(exc).__name__}")
            pdf_ok = False
    _write_debug_artifacts(directory, result, written)
    return pdf_ok


def _write_debug_artifacts(directory: Path, result, written: dict[str, str]) -> None:
    """Section S: Developer Debug and Engineering Summary, observation only.

    Both come from the same result and RunTrace; a failure to build them is
    recorded in the file and never changes the run's outcome or exit code.
    """

    from weekly_report.debug_service import (
        DEBUG_ARTIFACT_VERSION,
        build_developer_debug,
        build_engineering_summary,
        debug_artifact_names,
    )

    try:
        debug_name, summary_name = debug_artifact_names(result.period_end)
    except Exception as exc:  # noqa: BLE001 - observation must not change the outcome
        print(f"debug_artifacts=UNAVAILABLE failure_class={type(exc).__name__}")
        return
    files = {**written, "developer_debug": debug_name, "engineering_summary": summary_name}
    for name, build in ((debug_name, build_developer_debug), (summary_name, build_engineering_summary)):
        try:
            content = build(result, files=files)
        except Exception as exc:  # noqa: BLE001 - observation must not change the outcome
            content = {"version": DEBUG_ARTIFACT_VERSION, "unavailable": type(exc).__name__}
        (directory / name).write_text(
            json.dumps(content, ensure_ascii=False, indent=1, sort_keys=False) + chr(10), encoding="utf-8"
        )


if __name__ == "__main__":
    raise SystemExit(main())
