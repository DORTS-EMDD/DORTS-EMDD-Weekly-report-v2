"""Thin Streamlit shell over the shared V2 production runner."""

from __future__ import annotations

from datetime import date, timedelta
import json
from pathlib import Path
import sys
from typing import Callable

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from weekly_report.contracts import RegionMode  # noqa: E402
from weekly_report.production_runner import ProductionRunner  # noqa: E402


def render_app(runner_factory: Callable[[], ProductionRunner] = ProductionRunner.from_environment) -> None:
    """Render controls and display only the typed runner result."""

    import streamlit as st

    st.title("Weekly-report V2")
    today = date.today()
    default_end = today - timedelta(days=today.weekday() + 1)
    default_start = default_end - timedelta(days=6)
    st.caption("V2 production execution")
    region_mode = st.selectbox(
        "Region mode", tuple(mode.value for mode in RegionMode), index=0
    )
    period_start = st.date_input("Start date", value=default_start)
    period_end = st.date_input("End date", value=default_end)

    if not st.button("Run report"):
        return
    if period_end < period_start:
        st.error("End date must not precede start date.")
        return
    try:
        result = runner_factory().run(
            region_mode=region_mode,
            period_start=period_start,
            period_end=period_end,
        )
    except Exception:
        st.error("Production configuration or execution failed.")
        return

    st.write(f"Status: {result.status.value}")
    st.write(f"Period: {result.period_start.isoformat()} to {result.period_end.isoformat()}")
    st.write("Stage counts", dict(result.stage_counts))
    if result.final_report is not None:
        st.subheader("Formal report")
        st.markdown(result.final_report.content)
        st.download_button(
            "Download report",
            data=result.final_report.content,
            file_name=f"weekly-report-{result.period_start.isoformat()}.md",
            mime="text/markdown",
        )
    if getattr(result, "selection_audit", None) is not None:
        st.download_button(
            "Download selection audit",
            data=json.dumps(result.selection_audit, ensure_ascii=False, indent=1),
            file_name=f"selection-audit-{result.period_start.isoformat()}.json",
            mime="application/json",
        )
    if not result.successful:
        st.error(
            f"{result.failure_stage or 'application'}: "
            f"{result.failure_class or 'UNKNOWN'}; {result.diagnostic or 'failed'}"
        )


if __name__ == "__main__":
    render_app()
