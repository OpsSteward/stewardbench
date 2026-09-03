"""Product-neutral adapter boundary and the deterministic fake HTTP variant.

No OpsSteward route is guessed here.  The fake adapter is the M3 executable
contract; a real OpsSteward variant can be registered only after supported wire
fixtures establish its request and completion shapes.
"""

from __future__ import annotations

import json
import os
import re
import socket
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib import error, request

from django.utils import timezone


MAX_CAPTURE_BYTES = 1_000_000
SENSITIVE_KEY = re.compile(r"(authorization|password|secret|token|cookie)", re.I)


class AdapterFailure(Exception):
    def __init__(
        self,
        error_class: str,
        detail: str,
        *,
        protocol_status: int | None = None,
        raw_response: str = "",
        raw_request: dict[str, Any] | None = None,
    ):
        super().__init__(detail)
        self.error_class = error_class
        self.detail = detail
        self.protocol_status = protocol_status
        self.raw_response = raw_response
        self.raw_request = raw_request or {}


class TargetTimeout(AdapterFailure):
    def __init__(self, detail: str, **kwargs):
        super().__init__("TARGET_TIMEOUT", detail, **kwargs)


class ConversationFailure(AdapterFailure):
    """Normalized turn failure with an explicit continuity signal.

    ``UNKNOWN`` is deliberately conservative: the coordinator must not submit a
    dependent turn unless the adapter can establish that the target session is
    still usable.
    """

    def __init__(self, *args, continuity: str = "UNKNOWN", **kwargs):
        super().__init__(*args, **kwargs)
        self.continuity = continuity if continuity in {"USABLE", "UNUSABLE", "UNKNOWN"} else "UNKNOWN"


@dataclass(frozen=True)
class Submission:
    adapter_key: str
    adapter_version: str
    started_at: datetime
    completed_at: datetime
    protocol_status: int
    raw_request: dict[str, Any]
    raw_response: str
    raw_answer: str
    evidence: dict[str, Any] | list[Any] | str | None
    response_metadata: dict[str, Any]
    target_correlation_id: str


@dataclass(frozen=True)
class ConversationSession:
    session_id: str
    session_metadata: dict[str, Any]
    raw_request: dict[str, Any]
    raw_response: str


@dataclass(frozen=True)
class RuntimeMetadata:
    state: str
    metadata: dict[str, Any] = field(default_factory=dict)
    raw_response: str = ""
    diagnostic: str = ""
    observed_at: datetime | None = None


@dataclass(frozen=True)
class HealthResult:
    status: str
    observed_at: datetime
    latency_ms: int
    diagnostic: str = ""


def credential_environment_name(reference: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]", "_", reference).upper()
    return f"STEWARD_BENCH_TARGET_CREDENTIAL_{normalized}"


def resolve_credential(reference: str) -> str | None:
    """Resolve only a symbolic external reference at call time, never persist it."""

    if not reference:
        return None
    value = os.environ.get(credential_environment_name(reference))
    if not value:
        raise AdapterFailure(
            "AUTHENTICATION_FAILED",
            f"Runtime credential reference {reference!r} is not configured.",
        )
    return value


def redact_text(value: str, secrets: tuple[str, ...]) -> str:
    redacted = value
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    return redacted


def redact_value(value: Any, secrets: tuple[str, ...]) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if SENSITIVE_KEY.search(str(key)) else redact_value(child, secrets)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item, secrets) for item in value]
    if isinstance(value, str):
        return redact_text(value, secrets)
    return value


class FakeHTTPAdapter:
    """M3 fake-target adapter with a deliberately small JSON wire contract."""

    key = "fake-http"
    version = "1"

    def _url(self, endpoint: str, suffix: str) -> str:
        return f"{endpoint.rstrip('/')}{suffix}"

    def _read_body(self, response, *, secrets: tuple[str, ...]) -> str:
        body = response.read(MAX_CAPTURE_BYTES + 1)
        if len(body) > MAX_CAPTURE_BYTES:
            raise AdapterFailure("MALFORMED_RESPONSE", "Target response exceeded the M3 capture limit.")
        charset = response.headers.get_content_charset() or "utf-8"
        return redact_text(body.decode(charset, errors="replace"), secrets)

    def submit_question(
        self,
        *,
        endpoint: str,
        credential: str | None,
        request_id: str,
        question: str,
        timeout_seconds: int,
    ) -> Submission:
        payload = {"request_id": request_id, "question": question}
        serialized = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        safe_request = {
            "method": "POST",
            "path": "/question",
            "headers": {"Content-Type": "application/json", "X-StewardBench-Request-ID": request_id},
            "body": payload,
        }
        headers = {
            "Content-Type": "application/json",
            "X-StewardBench-Request-ID": request_id,
        }
        if credential:
            headers["Authorization"] = "Bearer " + credential
        req = request.Request(
            self._url(endpoint, "/question"),
            data=serialized,
            headers=headers,
            method="POST",
        )
        started_at = timezone.now()
        try:
            with request.urlopen(req, timeout=timeout_seconds) as response:  # noqa: S310 - configured target
                raw_response = self._read_body(response, secrets=(credential or "",))
                status = response.status
                content_type = response.headers.get_content_type()
        except error.HTTPError as exc:
            raw_response = ""
            try:
                raw_response = redact_text(exc.read(MAX_CAPTURE_BYTES).decode("utf-8", errors="replace"), (credential or "",))
            except Exception:
                pass
            kind = "AUTHENTICATION_FAILED" if exc.code in {401, 403} else "HTTP_ERROR"
            raise AdapterFailure(
                kind,
                f"Target returned HTTP {exc.code}.",
                protocol_status=exc.code,
                raw_response=raw_response,
                raw_request=safe_request,
            ) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise TargetTimeout("Target did not return a complete answer before the deadline.", raw_request=safe_request) from exc
        except error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, (TimeoutError, socket.timeout)):
                raise TargetTimeout("Target did not return a complete answer before the deadline.", raw_request=safe_request) from exc
            raise AdapterFailure("CONNECTION_FAILED", "Target connection failed.", raw_request=safe_request) from exc
        except AdapterFailure:
            raise
        except OSError as exc:
            raise AdapterFailure("CONNECTION_FAILED", "Target connection failed.", raw_request=safe_request) from exc

        completed_at = timezone.now()
        if content_type != "application/json":
            raise AdapterFailure(
                "MALFORMED_RESPONSE",
                "Target returned a response with an unsupported content type.",
                protocol_status=status,
                raw_response=raw_response,
                raw_request=safe_request,
            )
        try:
            payload = json.loads(raw_response)
        except json.JSONDecodeError as exc:
            raise AdapterFailure(
                "MALFORMED_RESPONSE",
                "Target returned malformed JSON.",
                protocol_status=status,
                raw_response=raw_response,
                raw_request=safe_request,
            ) from exc
        if not isinstance(payload, dict) or payload.get("complete") is not True or not isinstance(payload.get("answer"), str):
            raise AdapterFailure(
                "MALFORMED_RESPONSE",
                "Target response did not contain a complete answer envelope.",
                protocol_status=status,
                raw_response=raw_response,
                raw_request=safe_request,
            )
        safe_payload = redact_value(payload, (credential or "",))
        return Submission(
            adapter_key=self.key,
            adapter_version=self.version,
            started_at=started_at,
            completed_at=completed_at,
            protocol_status=status,
            raw_request=safe_request,
            raw_response=raw_response,
            raw_answer=safe_payload["answer"],
            evidence=safe_payload.get("evidence"),
            response_metadata=safe_payload.get("metadata") if isinstance(safe_payload.get("metadata"), dict) else {},
            target_correlation_id=str(safe_payload.get("correlation_id", "")),
        )

    def _conversation_failure(
        self,
        *,
        error_class: str,
        detail: str,
        protocol_status: int | None,
        raw_response: str,
        raw_request: dict[str, Any],
    ) -> ConversationFailure:
        continuity = "UNKNOWN"
        try:
            body = json.loads(raw_response)
            if isinstance(body, dict):
                continuity = str(body.get("session_continuity", "UNKNOWN"))
        except (TypeError, json.JSONDecodeError):
            pass
        return ConversationFailure(
            error_class,
            detail,
            protocol_status=protocol_status,
            raw_response=raw_response,
            raw_request=raw_request,
            continuity=continuity,
        )

    def open_conversation(self, *, endpoint: str, credential: str | None, timeout_seconds: int) -> ConversationSession:
        payload = {"conversation_requested": True}
        safe_request = {"method": "POST", "path": "/conversations", "headers": {"Content-Type": "application/json"}, "body": payload}
        headers = {"Content-Type": "application/json"}
        if credential:
            headers["Authorization"] = "Bearer " + credential
        req = request.Request(
            self._url(endpoint, "/conversations"),
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=timeout_seconds) as response:  # noqa: S310 - configured target
                raw_response = self._read_body(response, secrets=(credential or "",))
                status = response.status
                content_type = response.headers.get_content_type()
        except error.HTTPError as exc:
            raw_response = redact_text(exc.read(MAX_CAPTURE_BYTES).decode("utf-8", errors="replace"), (credential or "",))
            raise self._conversation_failure(
                error_class="SESSION_FAILED",
                detail=f"Target returned HTTP {exc.code} while opening a conversation.",
                protocol_status=exc.code,
                raw_response=raw_response,
                raw_request=safe_request,
            ) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise ConversationFailure("SESSION_FAILED", "Target timed out while opening a conversation.", raw_request=safe_request, continuity="UNUSABLE") from exc
        except (error.URLError, OSError) as exc:
            raise ConversationFailure("SESSION_FAILED", "Target connection failed while opening a conversation.", raw_request=safe_request, continuity="UNUSABLE") from exc
        if content_type != "application/json":
            raise ConversationFailure("SESSION_FAILED", "Conversation creation returned an unsupported content type.", protocol_status=status, raw_response=raw_response, raw_request=safe_request, continuity="UNUSABLE")
        try:
            body = json.loads(raw_response)
        except json.JSONDecodeError as exc:
            raise ConversationFailure("SESSION_FAILED", "Conversation creation returned malformed JSON.", protocol_status=status, raw_response=raw_response, raw_request=safe_request, continuity="UNUSABLE") from exc
        if not isinstance(body, dict) or not isinstance(body.get("session_id"), str) or not body["session_id"]:
            raise ConversationFailure("SESSION_FAILED", "Conversation creation did not return a non-secret session identity.", protocol_status=status, raw_response=raw_response, raw_request=safe_request, continuity="UNUSABLE")
        safe_body = redact_value(body, (credential or "",))
        return ConversationSession(
            session_id=safe_body["session_id"],
            session_metadata=safe_body.get("metadata") if isinstance(safe_body.get("metadata"), dict) else {},
            raw_request=safe_request,
            raw_response=raw_response,
        )

    def submit_conversation_turn(
        self,
        *,
        endpoint: str,
        credential: str | None,
        request_id: str,
        session_id: str,
        turn_ordinal: int,
        question: str,
        timeout_seconds: int,
    ) -> Submission:
        payload = {
            "request_id": request_id,
            "session_id": session_id,
            "turn_ordinal": turn_ordinal,
            "question": question,
        }
        safe_request = {
            "method": "POST",
            "path": f"/conversations/{session_id}/turns",
            "headers": {"Content-Type": "application/json", "X-StewardBench-Request-ID": request_id},
            "body": payload,
        }
        headers = dict(safe_request["headers"])
        if credential:
            headers["Authorization"] = "Bearer " + credential
        req = request.Request(
            self._url(endpoint, f"/conversations/{session_id}/turns"),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        started_at = timezone.now()
        try:
            with request.urlopen(req, timeout=timeout_seconds) as response:  # noqa: S310 - configured target
                raw_response = self._read_body(response, secrets=(credential or "",))
                status = response.status
                content_type = response.headers.get_content_type()
        except error.HTTPError as exc:
            raw_response = redact_text(exc.read(MAX_CAPTURE_BYTES).decode("utf-8", errors="replace"), (credential or "",))
            raise self._conversation_failure(
                error_class="SESSION_FAILED" if exc.code in {404, 409, 410} else "HTTP_ERROR",
                detail=f"Target returned HTTP {exc.code} for a conversation turn.",
                protocol_status=exc.code,
                raw_response=raw_response,
                raw_request=safe_request,
            ) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise ConversationFailure("TARGET_TIMEOUT", "Target did not return a complete conversation answer before the deadline.", raw_request=safe_request, continuity="UNKNOWN") from exc
        except error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, (TimeoutError, socket.timeout)):
                raise ConversationFailure("TARGET_TIMEOUT", "Target did not return a complete conversation answer before the deadline.", raw_request=safe_request, continuity="UNKNOWN") from exc
            raise ConversationFailure("CONNECTION_FAILED", "Target connection failed for a conversation turn.", raw_request=safe_request, continuity="UNKNOWN") from exc
        except OSError as exc:
            raise ConversationFailure("CONNECTION_FAILED", "Target connection failed for a conversation turn.", raw_request=safe_request, continuity="UNKNOWN") from exc
        completed_at = timezone.now()
        if content_type != "application/json":
            raise ConversationFailure("MALFORMED_RESPONSE", "Conversation turn returned an unsupported content type.", protocol_status=status, raw_response=raw_response, raw_request=safe_request, continuity="UNKNOWN")
        try:
            body = json.loads(raw_response)
        except json.JSONDecodeError as exc:
            raise ConversationFailure("MALFORMED_RESPONSE", "Conversation turn returned malformed JSON.", protocol_status=status, raw_response=raw_response, raw_request=safe_request, continuity="UNKNOWN") from exc
        if not isinstance(body, dict) or body.get("complete") is not True or not isinstance(body.get("answer"), str):
            raise ConversationFailure("MALFORMED_RESPONSE", "Conversation turn did not contain a complete answer envelope.", protocol_status=status, raw_response=raw_response, raw_request=safe_request, continuity="UNKNOWN")
        safe_body = redact_value(body, (credential or "",))
        return Submission(
            adapter_key=self.key,
            adapter_version=self.version,
            started_at=started_at,
            completed_at=completed_at,
            protocol_status=status,
            raw_request=safe_request,
            raw_response=raw_response,
            raw_answer=safe_body["answer"],
            evidence=safe_body.get("evidence"),
            response_metadata=safe_body.get("metadata") if isinstance(safe_body.get("metadata"), dict) else {},
            target_correlation_id=str(safe_body.get("correlation_id", "")),
        )

    def close_conversation(self, *, endpoint: str, credential: str | None, session_id: str, timeout_seconds: int):
        headers = {"Authorization": "Bearer " + credential} if credential else {}
        req = request.Request(self._url(endpoint, f"/conversations/{session_id}"), headers=headers, method="DELETE")
        try:
            with request.urlopen(req, timeout=timeout_seconds) as response:  # noqa: S310 - configured target
                self._read_body(response, secrets=(credential or "",))
                if response.status not in {200, 204}:
                    raise ConversationFailure("SESSION_FAILED", "Target did not close the conversation session.", continuity="USABLE")
        except (error.HTTPError, error.URLError, OSError, TimeoutError, socket.timeout) as exc:
            raise ConversationFailure("SESSION_FAILED", "Target could not close the conversation session.", continuity="USABLE") from exc

    def health_check(self, *, endpoint: str, credential: str | None, timeout_seconds: int) -> HealthResult:
        headers = {"Authorization": "Bearer " + credential} if credential else {}
        req = request.Request(self._url(endpoint, "/health"), headers=headers, method="GET")
        started = timezone.now()
        try:
            with request.urlopen(req, timeout=timeout_seconds) as response:  # noqa: S310 - configured target
                self._read_body(response, secrets=(credential or "",))
                if response.status != 200:
                    return HealthResult("DEGRADED", timezone.now(), 0, "Target health endpoint is degraded.")
        except error.HTTPError as exc:
            status = "AUTHENTICATION_FAILED" if exc.code in {401, 403} else "UNREACHABLE"
            return HealthResult(status, timezone.now(), 0, f"Target health endpoint returned HTTP {exc.code}.")
        except (error.URLError, OSError, TimeoutError, socket.timeout):
            return HealthResult("UNREACHABLE", timezone.now(), 0, "Target health endpoint is unavailable.")
        completed = timezone.now()
        return HealthResult(
            "REACHABLE",
            completed,
            max(0, int((completed - started).total_seconds() * 1000)),
        )

    def runtime_metadata(
        self,
        *,
        endpoint: str,
        credential: str | None,
        timeout_seconds: int,
    ) -> RuntimeMetadata:
        headers = {}
        if credential:
            headers["Authorization"] = "Bearer " + credential
        req = request.Request(self._url(endpoint, "/metadata"), headers=headers, method="GET")
        try:
            with request.urlopen(req, timeout=timeout_seconds) as response:  # noqa: S310 - configured target
                raw_response = self._read_body(response, secrets=(credential or "",))
        except error.HTTPError as exc:
            if exc.code in {404, 401, 403, 501}:
                return RuntimeMetadata(
                    state="UNAVAILABLE",
                    diagnostic=f"Runtime metadata endpoint returned HTTP {exc.code}.",
                    observed_at=timezone.now(),
                )
            return RuntimeMetadata(
                state="UNAVAILABLE",
                diagnostic="Runtime metadata endpoint is unavailable.",
                observed_at=timezone.now(),
            )
        except (error.URLError, OSError, TimeoutError, socket.timeout):
            return RuntimeMetadata(
                state="UNAVAILABLE",
                diagnostic="Runtime metadata endpoint is unavailable.",
                observed_at=timezone.now(),
            )
        try:
            metadata = json.loads(raw_response)
        except json.JSONDecodeError:
            return RuntimeMetadata(
                state="MALFORMED",
                raw_response=raw_response,
                diagnostic="Runtime metadata endpoint returned malformed JSON.",
                observed_at=timezone.now(),
            )
        if not isinstance(metadata, dict) or not isinstance(metadata.get("product"), str):
            return RuntimeMetadata(
                state="MALFORMED",
                raw_response=raw_response,
                diagnostic="Runtime metadata endpoint did not provide a product identity.",
                observed_at=timezone.now(),
            )
        return RuntimeMetadata(
            state="AVAILABLE",
            metadata=redact_value(metadata, (credential or "",)),
            raw_response=raw_response,
            observed_at=timezone.now(),
        )


def adapter_for(key: str):
    # ``fixture`` remains an internal M0–M2 fixture spelling for a smooth M3
    # migration; it maps to the one normalized fake contract.
    if key in {"fake-http", "fixture"}:
        return FakeHTTPAdapter()
    raise AdapterFailure("UNSUPPORTED_BEHAVIOR", f"No supported M3 adapter is configured for {key!r}.")
