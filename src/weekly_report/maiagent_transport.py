"""Neutral mechanical transport and configuration helpers for MaiAgent."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import os
from pathlib import Path
import socket
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


SHARED_MAIAGENT_CONFIG_KEYS = (
    "MAIAGENT_API_BASE",
    "MAIAGENT_API_KEY",
    "MAIAGENT_STRUCTURED_HELPER_CHATBOT_ID",
)


def load_shared_maiagent_values(
    environ: Mapping[str, str] | None = None,
    *,
    dotenv_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Merge the shared MaiAgent settings with process precedence.

    An explicitly empty process value remains empty after the dotenv merge and
    therefore fails closed in each typed provider configuration.
    """

    process_values = os.environ if environ is None else environ
    dotenv: Mapping[str, Any] = {}
    if not all(
        key in process_values and str(process_values[key]).strip()
        for key in SHARED_MAIAGENT_CONFIG_KEYS
    ):
        env_file = (
            Path(dotenv_path)
            if dotenv_path is not None
            else Path(__file__).resolve().parents[2] / ".env"
        )
        try:
            from dotenv import dotenv_values

            dotenv = dotenv_values(env_file)
        except (ImportError, OSError, UnicodeError, ValueError):
            dotenv = {}

    merged = {key: dotenv.get(key) for key in SHARED_MAIAGENT_CONFIG_KEYS}
    for key in SHARED_MAIAGENT_CONFIG_KEYS:
        if key in process_values:
            merged[key] = process_values[key]
    return merged


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ):
        return None


@dataclass(frozen=True, slots=True)
class MaiAgentHttpResponse:
    """HTTP status and body returned by one MaiAgent completion request."""

    status_code: int
    body: bytes


class MaiAgentJsonHttpTransport(Protocol):
    def __call__(
        self,
        endpoint: str,
        *,
        headers: Mapping[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> MaiAgentHttpResponse:
        """Make one request without redirects or retries."""


class UrllibMaiAgentJsonTransport:
    """One non-stream MaiAgent POST; redirects and retries are disabled."""

    def __call__(
        self,
        endpoint: str,
        *,
        headers: Mapping[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> MaiAgentHttpResponse:
        request = Request(endpoint, data=body, headers=dict(headers), method="POST")
        opener = build_opener(_NoRedirect)
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                return MaiAgentHttpResponse(response.status, response.read())
        except HTTPError as exc:
            # The caller needs only the status. Do not retain an error body.
            return MaiAgentHttpResponse(exc.code, b"")
        except TimeoutError:
            raise TimeoutError from None
        except URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise TimeoutError from None
            raise RuntimeError("MaiAgent transport failed") from None
        except OSError:
            raise RuntimeError("MaiAgent transport failed") from None


class MaiAgentResponseError(ValueError):
    """The proven outer-envelope-to-inner-JSON contract was not met."""


def parse_maiagent_response(response_body: bytes) -> dict[str, Any]:
    """Parse only outer JSON → top-level content string → inner JSON object."""

    if not isinstance(response_body, bytes) or not response_body:
        raise MaiAgentResponseError("MaiAgent response body is empty or invalid")
    try:
        envelope = json.loads(response_body)
    except (UnicodeDecodeError, TypeError, ValueError):
        raise MaiAgentResponseError("MaiAgent response envelope is invalid JSON") from None
    if not isinstance(envelope, dict):
        raise MaiAgentResponseError("MaiAgent response envelope must be an object")
    content = envelope.get("content")
    if not isinstance(content, str):
        raise MaiAgentResponseError("MaiAgent response has no top-level content string")
    try:
        proposal = json.loads(content)
    except (TypeError, ValueError):
        raise MaiAgentResponseError("MaiAgent content is invalid proposal JSON") from None
    if not isinstance(proposal, dict):
        raise MaiAgentResponseError("MaiAgent proposal must be an object")
    return proposal


__all__ = [
    "SHARED_MAIAGENT_CONFIG_KEYS",
    "MaiAgentHttpResponse",
    "MaiAgentJsonHttpTransport",
    "UrllibMaiAgentJsonTransport",
    "MaiAgentResponseError",
    "load_shared_maiagent_values",
    "parse_maiagent_response",
]
