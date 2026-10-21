"""Resumable external-I/O journal for long acceptance runs (test-only tooling).

A long run is interrupted by its environment (a killed process, a closed
session), not by the pipeline. Everything the pipeline decides is a pure
function of its external inputs, so the journal stores each external response
under the identity of its request:

* RSS, Google News link-resolution and publisher responses (and their
  failures), so a resumed run sees exactly the same candidates and Evidence;
* MaiAgent responses, keyed by the exact request body. Helper and Writer calls
  are stateless and self-contained (conversation = null), so the recorded
  response to a byte-identical request is a valid response to that request;
  every owner still validates it.

A restarted run re-executes all Python stages, replays recorded responses and
pays only for requests it has not seen. A ledger keeps the live usage of all
attempts, so a budget is a cap for the whole round, not per process. The
journal decides nothing; it never changes a request or a response.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError


class BudgetExhausted(BaseException):
    """Hard stop; deliberately not an Exception so no owner can swallow it."""


def _digest(*parts: bytes | str) -> str:
    sha = hashlib.sha256()
    for part in parts:
        data = part.encode("utf-8") if isinstance(part, str) else part
        sha.update(len(data).to_bytes(8, "big"))
        sha.update(data)
    return sha.hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def _encode_failure(exc: BaseException) -> dict[str, Any]:
    record: dict[str, Any] = {"type": type(exc).__name__, "message": str(exc)[:300]}
    for name in ("status_code", "code", "redirect_hop_count", "request_hostname", "failing_endpoint_hostname"):
        value = getattr(exc, name, None)
        if isinstance(value, (int, str)) and not isinstance(value, bool):
            record[name] = value
    return record


def _decode_failure(record: dict[str, Any], *, factories: dict[str, Callable[[dict[str, Any]], BaseException]]) -> BaseException:
    name = record["type"]
    if name in factories:
        return factories[name](record)
    if name in {"TimeoutError", "socket.timeout"}:
        return TimeoutError(record["message"])
    if name == "HTTPError":
        return HTTPError("", int(record.get("code", 0)), record["message"], None, None)
    if name == "URLError":
        return URLError(record["message"])
    # Same type name, so diagnostics that report the transport error type
    # (EvidenceService provenance) replay identically.
    return type(name, (OSError,), {})(record["message"])


class RunJournal:
    """Content-addressed store of external responses plus a cumulative ledger."""

    def __init__(self, directory: Path, *, limits: dict[str, int], seconds_limit: int) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.limits = dict(limits)
        self.seconds_limit = int(seconds_limit)
        self._ledger_path = self.directory / "ledger.json"
        if self._ledger_path.exists():
            self.ledger = json.loads(self._ledger_path.read_text(encoding="utf-8"))
        else:
            self.ledger = {"live": {}, "replayed": {}, "attempts": [], "prior_spend": {}}
        self.ledger["attempts"].append(
            {"started_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "pid": os.getpid(), "seconds": 0.0}
        )
        self._attempt = self.ledger["attempts"][-1]
        self._started = dt.datetime.now(dt.timezone.utc)
        self.factories: dict[str, Callable[[dict[str, Any]], BaseException]] = {}
        self._save()

    # -- ledger -----------------------------------------------------------
    def record_prior_spend(self, spend: dict[str, int], note: str) -> None:
        """Book live usage of an earlier attempt that kept no journal."""

        if self.ledger["prior_spend"]:
            return
        self.ledger["prior_spend"] = {"usage": dict(spend), "note": note}
        for budget, count in spend.items():
            if budget == "seconds":
                self.ledger["attempts"].insert(0, {"started_utc": "prior", "pid": None, "seconds": float(count)})
                continue
            self.ledger["live"][budget] = self.ledger["live"].get(budget, 0) + int(count)
        self._save()

    def elapsed_seconds(self) -> float:
        current = (dt.datetime.now(dt.timezone.utc) - self._started).total_seconds()
        earlier = sum(attempt["seconds"] for attempt in self.ledger["attempts"][:-1])
        return earlier + current

    def _save(self) -> None:
        self._attempt["seconds"] = round((dt.datetime.now(dt.timezone.utc) - self._started).total_seconds(), 1)
        _atomic_write(self._ledger_path, json.dumps(self.ledger, ensure_ascii=False, indent=1).encode("utf-8"))

    def _charge(self, budget: str, kind: str) -> None:
        if self.elapsed_seconds() > self.seconds_limit:
            raise BudgetExhausted(f"WALL_CLOCK_BUDGET_EXCEEDED ({self.seconds_limit}s cumulative)")
        used = self.ledger["live"].get(budget, 0)
        if used >= self.limits[budget]:
            raise BudgetExhausted(f"{budget.upper()}_BUDGET_EXCEEDED ({self.limits[budget]} cumulative)")
        self.ledger["live"][budget] = used + 1
        by_kind = self.ledger.setdefault("live_by_kind", {})
        by_kind[kind] = by_kind.get(kind, 0) + 1
        # Persist before the call: a call cut off by a kill still counts.
        self._save()

    def _count_replay(self, kind: str) -> None:
        self.ledger["replayed"][kind] = self.ledger["replayed"].get(kind, 0) + 1

    def flush(self) -> None:
        self._save()

    # -- records ----------------------------------------------------------
    def _path(self, kind: str, key: str) -> Path:
        return self.directory / kind / key[:2] / f"{key}.json"

    def _load(self, kind: str, key: str) -> dict[str, Any] | None:
        path = self._path(kind, key)
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def _store(self, kind: str, key: str, record: dict[str, Any]) -> None:
        _atomic_write(self._path(kind, key), json.dumps(record, ensure_ascii=False).encode("utf-8"))

    def call(
        self,
        kind: str,
        budget: str,
        key: str,
        live: Callable[[], Any],
        *,
        encode: Callable[[Any], dict[str, Any]],
        decode: Callable[[dict[str, Any]], Any],
        keep_response: Callable[[Any], bool] = lambda response: True,
        keep_failure: Callable[[BaseException], bool] = lambda exc: True,
    ) -> Any:
        """Replay a recorded outcome, or make the call live and record it.

        Only definitive outcomes are recorded; a transient one (``keep_*``
        false) is returned or raised but retried live on the next attempt.
        """
        stored = self._load(kind, key)
        if stored is not None:
            self._count_replay(kind)
            if "failure" in stored:
                raise _decode_failure(stored["failure"], factories=self.factories)
            return decode(stored["response"])
        self._charge(budget, kind)
        try:
            response = live()
        except Exception as exc:
            if keep_failure(exc):
                self._store(kind, key, {"failure": _encode_failure(exc)})
            raise
        if keep_response(response):
            self._store(kind, key, {"response": encode(response)})
        return response

    def seed(self, kind: str, key: str, record: dict[str, Any]) -> bool:
        if self._path(kind, key).exists():
            return False
        self._store(kind, key, record)
        return True


def request_key(*parts: bytes | str) -> str:
    return _digest(*parts)
