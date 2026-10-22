"""Relaunch an interrupted journal-backed acceptance run (test-only tooling).

The worker runs without a console (DETACHED_PROCESS), so console close or
Ctrl+C events cannot reach it. If it still ends abnormally (any non-zero exit
code), it is started again with the same arguments; its RunJournal replays
everything already obtained and its ledger keeps the budgets cumulative, so a
relaunch never resets a cap. A worker that exits 0 has finished or stopped at
a budget and is not relaunched.

Usage: pythonw scripts/run_supervisor.py --log LOG --max-attempts N -- <worker args>
"""

from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
from pathlib import Path


def _log(path: Path, message: str) -> None:
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{stamp} {message}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--max-attempts", type=int, default=6)
    parser.add_argument("worker", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    worker = args.worker[1:] if args.worker[:1] == ["--"] else args.worker
    python = Path(sys.executable).with_name("python.exe")
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    for attempt in range(1, args.max_attempts + 1):
        out = args.log.with_name(f"worker{attempt}_stdout.txt")
        err = args.log.with_name(f"worker{attempt}_stderr.txt")
        with out.open("wb") as stdout, err.open("wb") as stderr:
            process = subprocess.Popen(
                [str(python), *worker], stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, creationflags=flags
            )
            _log(args.log, f"attempt {attempt} started pid={process.pid}")
            code = process.wait()
        _log(args.log, f"attempt {attempt} exited code={code} (0x{code & 0xFFFFFFFF:08X})")
        if code == 0:
            _log(args.log, "DONE")
            return 0
    _log(args.log, "GAVE_UP max attempts reached")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
