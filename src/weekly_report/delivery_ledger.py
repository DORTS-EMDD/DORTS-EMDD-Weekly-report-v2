"""RC-55 (contract section A.39): the Delivery handoff ledger's model and storage.

``DeliveryService`` is the only owner of delivery decisions. This module holds
the period-file model, the transition table every write must satisfy, the
keyed recipient hashes and a mechanical compare-and-swap store. It decides
nothing: which recipient to claim, send or release is decided by Delivery.
"""

from __future__ import annotations

import base64
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import date
from enum import StrEnum
import hashlib
import hmac
import json
import re
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

LEDGER_VERSION = "delivery-ledger-v1"
KEY_VERSION = "v1"
REFERENCE_LENGTH = 16
MIN_SECRET_LENGTH = 32

_KEY = re.compile(r"[0-9a-f]{64}")
_REFERENCE = re.compile(rf"[0-9a-f]{{{REFERENCE_LENGTH}}}")
_RUN_ID = re.compile(r"[A-Za-z0-9]{1,64}")
_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}")
_AUDIT_VALUE = re.compile(r"[A-Za-z0-9_.@:+-]{1,128}")


class EntryState(StrEnum):
    ATTEMPTED = "ATTEMPTED"
    SENT = "SENT"
    NOT_SENT = "NOT_SENT"
    RELEASED = "RELEASED"


# Section A.39: an ATTEMPTED or SENT entry blocks every new claim.
BLOCKING_STATES = frozenset({EntryState.ATTEMPTED, EntryState.SENT})


class LedgerInvariantError(RuntimeError):
    """A ledger file or a requested transition breaks the section A.39 rules."""


class LedgerUnavailable(RuntimeError):
    """The store could not be read or written; a write's outcome may be unknown."""


class LedgerConflict(RuntimeError):
    """The store rejected a write made from a stale blob SHA."""


def recipient_key(secret: bytes, period_start: date, period_end: date, address: str) -> str:
    """HMAC-SHA256 of the period and the case-folded address; never stored with the address."""

    message = f"{KEY_VERSION}|{period_start.isoformat()}|{period_end.isoformat()}|{address.strip().casefold()}"
    return hmac.new(secret, message.encode("utf-8"), hashlib.sha256).hexdigest()


def key_id(secret: bytes) -> str:
    """A fingerprint of the HMAC key that reveals nothing about it."""

    return hmac.new(secret, b"delivery-ledger-key-id", hashlib.sha256).hexdigest()[:16]


def entry_reference(key: str) -> str:
    return key[:REFERENCE_LENGTH]


def claim_id_for(run_id: str, reference: str) -> str:
    if not _RUN_ID.fullmatch(run_id) or not _REFERENCE.fullmatch(reference):
        raise ValueError("claim IDs use an alphanumeric run ID and a 16-character entry reference")
    return f"{run_id}.{reference}"


def period_path(period_start: date, period_end: date) -> str:
    return f"periods/{period_start.isoformat()}_{period_end.isoformat()}.json"


def period_label(period_start: date, period_end: date) -> str:
    return f"{period_start.isoformat()}..{period_end.isoformat()}"


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    state: EntryState
    claim_id: str
    claimed_at: str
    history: tuple[Mapping[str, str], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", EntryState(self.state))
        if not isinstance(self.claim_id, str) or "." not in self.claim_id:
            raise LedgerInvariantError("ledger entry requires a claim ID")
        run_id, _, reference = self.claim_id.partition(".")
        if not _RUN_ID.fullmatch(run_id) or not _REFERENCE.fullmatch(reference):
            raise LedgerInvariantError("ledger entry claim ID is malformed")
        if not isinstance(self.claimed_at, str) or not self.claimed_at:
            raise LedgerInvariantError("ledger entry requires claimed_at")
        history = tuple(dict(item) for item in self.history)
        if any(not all(isinstance(key, str) and isinstance(value, str) for key, value in item.items()) for item in history):
            raise LedgerInvariantError("ledger entry history must hold strings")
        object.__setattr__(self, "history", history)

    def as_mapping(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "claim_id": self.claim_id,
            "claimed_at": self.claimed_at,
            "history": [dict(item) for item in self.history],
        }


@dataclass(frozen=True, slots=True)
class PeriodLedger:
    """One period file: keyed entries only, never an address."""

    period_start: date
    period_end: date
    key_id: str
    entries: Mapping[str, LedgerEntry] = field(default_factory=dict)

    def __post_init__(self) -> None:
        entries = dict(self.entries)
        if any(not _KEY.fullmatch(key) or not isinstance(entry, LedgerEntry) for key, entry in entries.items()):
            raise LedgerInvariantError("ledger entries are keyed by full recipient keys")
        for key, entry in entries.items():
            if entry.claim_id.partition(".")[2] != entry_reference(key):
                raise LedgerInvariantError("ledger entry claim does not name its own entry")
        object.__setattr__(self, "entries", entries)

    def entry(self, key: str) -> LedgerEntry | None:
        return self.entries.get(key)

    def with_entry(self, key: str, entry: LedgerEntry) -> "PeriodLedger":
        return replace(self, entries={**self.entries, key: entry})

    def keys_for_reference(self, reference: str) -> tuple[str, ...]:
        return tuple(key for key in self.entries if entry_reference(key) == reference)

    def to_json(self) -> str:
        return json.dumps(
            {
                "ledger_version": LEDGER_VERSION,
                "period": period_label(self.period_start, self.period_end),
                "key_id": self.key_id,
                "entries": {key: self.entries[key].as_mapping() for key in sorted(self.entries)},
            },
            ensure_ascii=False,
            indent=1,
            sort_keys=True,
        ) + "\n"

    @classmethod
    def from_json(cls, text: str, period_start: date, period_end: date) -> "PeriodLedger":
        try:
            data = json.loads(text)
        except (TypeError, ValueError) as exc:
            raise LedgerInvariantError("ledger file is not JSON") from exc
        if (
            not isinstance(data, Mapping)
            or data.get("ledger_version") != LEDGER_VERSION
            or data.get("period") != period_label(period_start, period_end)
            or not isinstance(data.get("key_id"), str)
            or not isinstance(data.get("entries"), Mapping)
        ):
            raise LedgerInvariantError("ledger file does not match this period's format")
        entries = {}
        for key, raw in data["entries"].items():
            if not isinstance(raw, Mapping) or set(raw) != {"state", "claim_id", "claimed_at", "history"}:
                raise LedgerInvariantError("ledger entry has the wrong fields")
            try:
                entries[key] = LedgerEntry(raw["state"], raw["claim_id"], raw["claimed_at"], tuple(raw["history"]))
            except (TypeError, ValueError) as exc:
                raise LedgerInvariantError("ledger entry is malformed") from exc
        return cls(period_start, period_end, data["key_id"], entries)


def check_transition(current: LedgerEntry | None, new_state: EntryState, claim_id: str) -> None:
    """Section A.39's transition table; anything else is an invariant failure.

    Holder checks (only the claim's own execution writes SENT or NOT_SENT, and
    a release names that exact claim) are made by matching ``claim_id``.
    """

    new_state = EntryState(new_state)
    if new_state is EntryState.ATTEMPTED:
        if current is None or current.state in {EntryState.NOT_SENT, EntryState.RELEASED}:
            return
    elif current is not None and current.state is EntryState.ATTEMPTED and current.claim_id == claim_id:
        return
    raise LedgerInvariantError(
        f"transition {getattr(getattr(current, 'state', None), 'value', None)} -> {new_state.value} is not allowed"
    )


def audit_fields(values: Mapping[str, object]) -> dict[str, str]:
    """Only safe audit tokens (run IDs, attempt numbers, actor logins) reach the history."""

    return {
        key: value
        for key, value in values.items()
        if isinstance(key, str) and isinstance(value, str) and _AUDIT_VALUE.fullmatch(value)
    }


class LedgerStore(Protocol):
    def read(self, path: str) -> tuple[str | None, str | None]:
        """Return the file's text and blob SHA, or (None, None) when it does not exist."""

    def write(self, path: str, content: str, sha: str | None, message: str) -> None:
        """Write by compare-and-swap; raise LedgerConflict on a stale SHA."""


HttpTransport = Callable[[str, str, Mapping[str, str], bytes | None, float], tuple[int, bytes]]


def _urllib_transport(method: str, url: str, headers: Mapping[str, str], body: bytes | None, timeout: float) -> tuple[int, bytes]:
    request = Request(url, data=body, headers=dict(headers), method=method)
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https API origin
            return response.status, response.read()
    except HTTPError as exc:
        return exc.code, b""


class GitHubContentsLedgerStore:
    """Compare-and-swap file storage in the private ledger repository (contents API).

    A write names the blob SHA it replaces; GitHub rejects a stale SHA with
    409. Mechanical only: no delivery decision is made here.
    """

    API = "https://api.github.com"

    def __init__(
        self,
        repository: str,
        token: str,
        *,
        branch: str = "main",
        timeout_seconds: float = 30.0,
        transport: HttpTransport | None = None,
    ) -> None:
        if not isinstance(repository, str) or not _REPOSITORY.fullmatch(repository):
            raise ValueError("ledger repository must be owner/name")
        if not isinstance(token, str) or not token.strip() or any(ch in token for ch in "\r\n "):
            raise ValueError("ledger token is required")
        if not isinstance(branch, str) or not re.fullmatch(r"[A-Za-z0-9_./-]{1,100}", branch):
            raise ValueError("ledger branch is invalid")
        self._repository = repository
        self._token = token
        self._branch = branch
        self._timeout = timeout_seconds
        self._transport = transport or _urllib_transport

    def __repr__(self) -> str:
        return f"GitHubContentsLedgerStore(repository={self._repository!r}, branch={self._branch!r})"

    def _url(self, path: str) -> str:
        return f"{self.API}/repos/{self._repository}/contents/{quote(path)}"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        }

    def _call(self, method: str, url: str, body: bytes | None) -> tuple[int, bytes]:
        try:
            return self._transport(method, url, self._headers(), body, self._timeout)
        except (OSError, URLError, TimeoutError) as exc:
            raise LedgerUnavailable(type(exc).__name__) from None

    def read(self, path: str) -> tuple[str | None, str | None]:
        status, body = self._call("GET", f"{self._url(path)}?ref={quote(self._branch)}", None)
        if status == 404:
            return None, None
        if status != 200:
            raise LedgerUnavailable(f"HTTP_{status}")
        try:
            data = json.loads(body)
            text = base64.b64decode(data["content"]).decode("utf-8")
            sha = data["sha"]
        except (KeyError, TypeError, ValueError) as exc:
            raise LedgerUnavailable("UNPARSEABLE_RESPONSE") from exc
        if not isinstance(sha, str) or not sha:
            raise LedgerUnavailable("UNPARSEABLE_RESPONSE")
        return text, sha

    def write(self, path: str, content: str, sha: str | None, message: str) -> None:
        payload: dict[str, str] = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "branch": self._branch,
        }
        if sha is not None:
            payload["sha"] = sha
        status, _ = self._call("PUT", self._url(path), json.dumps(payload).encode("utf-8"))
        if status in (200, 201):
            return
        if status in (409, 422):
            # 409: the SHA is stale; 422: a file exists although no SHA was given.
            raise LedgerConflict(f"HTTP_{status}")
        raise LedgerUnavailable(f"HTTP_{status}")


__all__ = [
    "BLOCKING_STATES",
    "EntryState",
    "GitHubContentsLedgerStore",
    "LedgerConflict",
    "LedgerEntry",
    "LedgerInvariantError",
    "LedgerStore",
    "LedgerUnavailable",
    "MIN_SECRET_LENGTH",
    "PeriodLedger",
    "audit_fields",
    "check_transition",
    "claim_id_for",
    "entry_reference",
    "key_id",
    "period_label",
    "period_path",
    "recipient_key",
]
