#!/usr/bin/env python3
"""Durable, privacy-bounded evidence stores for PhoneHarness Stage 3.

This module persists artifact descriptors, execution receipts, and trace
events. It is deliberately outside the Stage-2 execution path: stored data is
not authorization, a governed binding, an executor port, a verifier result, or
a replay instruction.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
from typing import Any, Iterable, Iterator, Mapping

from phoneharness_contracts import (
    ArtifactDescriptor,
    ArtifactLifetime,
    ArtifactRef,
    ContractValidationError,
    ObservationFreshness,
    ObservationRef,
    SensitivityClass,
)


STORE_SCHEMA_VERSION = 1
RECEIPT_SCHEMA_VERSION = "phoneharness.execution-receipt.v1"
TRACE_EVENT_SCHEMA_VERSION = "phoneharness.trace-event.v1"
MAX_METADATA_ITEMS = 24
MAX_METADATA_VALUE_LENGTH = 512
MAX_SAFE_MESSAGE_LENGTH = 256
MAX_LINKS_PER_RECORD = 32

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
_SECRET_VALUE_PATTERNS = (
    re.compile(r"(?i)^bearer\s+\S+"),
    re.compile(r"(?i)^(?:sk|ghp|github_pat|xox[baprs])-\S+"),
    re.compile(r"^eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$"),
    re.compile(r"^[0-9a-f]{32}$"),
)
_FORBIDDEN_FIELD_WORDS = frozenset(
    {
        "authorization",
        "authorizationheader",
        "authorized",
        "binding",
        "bindingid",
        "credential",
        "executorauthority",
        "executorport",
        "faceid",
        "otp",
        "passcode",
        "password",
        "privatekey",
        "rawsecret",
        "secret",
        "token",
    }
)


class StoreError(RuntimeError):
    """Base class for deterministic store failures."""


class StorePolicyError(StoreError):
    """A record violated the bounded or privacy-safe store contract."""


class StoreConflictError(StoreError):
    """An immutable identifier was reused with different content."""


class StoreSchemaError(StoreError):
    """The database schema is unknown, incomplete, or incompatible."""


class StoreClosedError(StoreError):
    """A caller attempted to use a closed store."""


class StoreWriterUnavailableError(StoreError):
    """The database already has a canonical writer owner."""


class UnknownArtifactError(StoreError):
    """An ArtifactRef cannot be resolved in its exact task/session scope."""


class UnknownReceiptError(StoreError):
    """A receipt identifier is unknown."""


class UnknownTraceEventError(StoreError):
    """A trace event identifier is unknown."""


class ReceiptResultStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    AUTHORIZED = "AUTHORIZED"
    DISPATCHED = "DISPATCHED"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    DENIED = "DENIED"
    BLOCKED = "BLOCKED"


class DispatchStatus(str, Enum):
    NOT_DISPATCHED = "NOT_DISPATCHED"
    DISPATCHED = "DISPATCHED"
    UNKNOWN = "UNKNOWN"


class SideEffectClass(str, Enum):
    READ_ONLY = "READ_ONLY"
    INTERACTION = "INTERACTION"
    EXTERNAL_SIDE_EFFECT = "EXTERNAL_SIDE_EFFECT"


def _identifier(value: Any, field_name: str) -> str:
    normalized = str(value or "").strip()
    if _IDENTIFIER.fullmatch(normalized) is None:
        raise StorePolicyError(f"{field_name} must be an opaque bounded identifier")
    return normalized


def _optional_identifier(value: Any, field_name: str) -> str | None:
    return None if value is None else _identifier(value, field_name)


def _timestamp(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise StorePolicyError(f"{field_name} must be a non-negative integer")
    return value


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _field_words(key: str) -> set[str]:
    components = {part.casefold() for part in re.split(r"[._:-]+", key) if part}
    components.add(re.sub(r"[^a-z0-9]", "", key.casefold()))
    return components


def _safe_text(value: Any, field_name: str, *, maximum: int) -> str:
    normalized = " ".join(str(value or "").split())
    if not normalized or len(normalized) > maximum:
        raise StorePolicyError(f"{field_name} must be non-empty bounded text")
    if any(pattern.search(normalized) for pattern in _SECRET_VALUE_PATTERNS):
        raise StorePolicyError(f"{field_name} resembles secret material")
    return normalized


def _metadata(
    value: Mapping[str, Any] | Iterable[tuple[str, Any]],
    field_name: str,
) -> tuple[tuple[str, str], ...]:
    items = value.items() if isinstance(value, Mapping) else value
    normalized: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw_key, raw_value in items:
        key = _identifier(raw_key, f"{field_name} key")
        if _field_words(key) & _FORBIDDEN_FIELD_WORDS:
            raise StorePolicyError(f"{field_name} cannot contain authority or secret fields")
        if key in seen:
            raise StorePolicyError(f"{field_name} cannot contain duplicate keys")
        seen.add(key)
        normalized.append(
            (key, _safe_text(raw_value, f"{field_name} value", maximum=MAX_METADATA_VALUE_LENGTH))
        )
    if len(normalized) > MAX_METADATA_ITEMS:
        raise StorePolicyError(f"{field_name} exceeds its bounded size")
    return tuple(sorted(normalized))


def _references(values: Iterable[str], field_name: str) -> tuple[str, ...]:
    normalized = tuple(_identifier(value, field_name) for value in values)
    if len(normalized) > MAX_LINKS_PER_RECORD or len(normalized) != len(set(normalized)):
        raise StorePolicyError(f"{field_name} must be bounded and unique")
    return normalized


def _artifact_refs(values: Iterable[ArtifactRef], field_name: str) -> tuple[ArtifactRef, ...]:
    normalized = tuple(values)
    if len(normalized) > MAX_LINKS_PER_RECORD or any(not isinstance(value, ArtifactRef) for value in normalized):
        raise StorePolicyError(f"{field_name} must contain bounded ArtifactRef values")
    if len({value.to_dict()["artifact_id"] for value in normalized}) != len(normalized):
        raise StorePolicyError(f"{field_name} must be unique")
    return normalized


def _observation_refs(values: Iterable[ObservationRef], field_name: str) -> tuple[ObservationRef, ...]:
    normalized = tuple(values)
    if len(normalized) > MAX_LINKS_PER_RECORD or any(not isinstance(value, ObservationRef) for value in normalized):
        raise StorePolicyError(f"{field_name} must contain bounded ObservationRef values")
    if len({value.observation_id for value in normalized}) != len(normalized):
        raise StorePolicyError(f"{field_name} must be unique")
    return normalized


def _artifact_ref_from_dict(payload: Mapping[str, Any]) -> ArtifactRef:
    required = {"schema_version", "artifact_id", "task_id", "session_id"}
    if not isinstance(payload, dict) or set(payload) != required:
        raise StoreSchemaError("stored ArtifactRef has an incompatible schema")
    try:
        return ArtifactRef(**payload)
    except (TypeError, ContractValidationError) as exc:
        raise StoreSchemaError("stored ArtifactRef is invalid") from exc


def _observation_ref_from_dict(payload: Mapping[str, Any]) -> ObservationRef:
    try:
        return ObservationRef.from_dict(dict(payload))
    except (TypeError, ContractValidationError) as exc:
        raise StoreSchemaError("stored ObservationRef is invalid") from exc


def _artifact_descriptor_from_dict(payload: Mapping[str, Any]) -> ArtifactDescriptor:
    required = {
        "schema_version",
        "ref",
        "artifact_kind",
        "producer",
        "created_at_ms",
        "sensitivity",
        "lifetime",
        "observation_ref",
        "content_digest",
        "opaque_locator",
        "metadata",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise StoreSchemaError("stored ArtifactDescriptor has an incompatible schema")
    try:
        return ArtifactDescriptor(
            ref=_artifact_ref_from_dict(payload["ref"]),
            artifact_kind=payload["artifact_kind"],
            producer=payload["producer"],
            created_at_ms=payload["created_at_ms"],
            sensitivity=SensitivityClass(payload["sensitivity"]),
            lifetime=ArtifactLifetime(payload["lifetime"]),
            observation_ref=(
                None
                if payload["observation_ref"] is None
                else _observation_ref_from_dict(payload["observation_ref"])
            ),
            content_digest=payload["content_digest"],
            opaque_locator=payload["opaque_locator"],
            metadata=payload["metadata"],
            schema_version=payload["schema_version"],
        )
    except (TypeError, ValueError, ContractValidationError) as exc:
        raise StoreSchemaError("stored ArtifactDescriptor is invalid") from exc


def _validate_artifact_descriptor(descriptor: ArtifactDescriptor) -> None:
    if not isinstance(descriptor, ArtifactDescriptor):
        raise StorePolicyError("artifact registration requires ArtifactDescriptor")
    _metadata(descriptor.metadata, "artifact metadata")
    if descriptor.opaque_locator is not None:
        _safe_text(descriptor.opaque_locator, "opaque_locator", maximum=128)


@dataclass(frozen=True)
class ExecutionReceipt:
    receipt_id: str
    task_id: str
    execution_id: str
    capability_id: str
    provider_id: str
    operation: str
    started_at_ms: int
    ended_at_ms: int
    result_status: ReceiptResultStatus
    side_effect_class: SideEffectClass
    dispatch_status: DispatchStatus
    step_id: str | None = None
    error_code: str | None = None
    error_class: str | None = None
    failure_signature: str | None = None
    safe_message: str | None = None
    verification_ref: str | None = None
    artifact_refs: tuple[ArtifactRef, ...] = ()
    observation_refs: tuple[ObservationRef, ...] = ()
    metadata: tuple[tuple[str, str], ...] = ()
    schema_version: str = RECEIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RECEIPT_SCHEMA_VERSION:
            raise StorePolicyError("unsupported ExecutionReceipt schema version")
        for name in ("receipt_id", "task_id", "execution_id", "capability_id", "provider_id", "operation"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        for name in ("step_id", "error_code", "error_class", "failure_signature", "verification_ref"):
            object.__setattr__(self, name, _optional_identifier(getattr(self, name), name))
        _timestamp(self.started_at_ms, "started_at_ms")
        _timestamp(self.ended_at_ms, "ended_at_ms")
        if self.ended_at_ms < self.started_at_ms:
            raise StorePolicyError("receipt end time cannot precede start time")
        try:
            object.__setattr__(self, "result_status", ReceiptResultStatus(self.result_status))
            object.__setattr__(self, "side_effect_class", SideEffectClass(self.side_effect_class))
            object.__setattr__(self, "dispatch_status", DispatchStatus(self.dispatch_status))
        except ValueError as exc:
            raise StorePolicyError("receipt contains an unsupported classification") from exc
        if self.result_status is ReceiptResultStatus.VERIFIED:
            if self.verification_ref is None or self.dispatch_status is not DispatchStatus.DISPATCHED:
                raise StorePolicyError("VERIFIED receipt evidence requires dispatch and a verifier reference")
        if self.result_status is ReceiptResultStatus.UNKNOWN_OUTCOME and self.dispatch_status is DispatchStatus.NOT_DISPATCHED:
            raise StorePolicyError("unknown outcome requires possible external dispatch")
        if self.safe_message is not None:
            object.__setattr__(
                self,
                "safe_message",
                _safe_text(self.safe_message, "safe_message", maximum=MAX_SAFE_MESSAGE_LENGTH),
            )
        object.__setattr__(self, "artifact_refs", _artifact_refs(self.artifact_refs, "artifact_refs"))
        object.__setattr__(self, "observation_refs", _observation_refs(self.observation_refs, "observation_refs"))
        if any(ref.task_id != self.task_id for ref in self.artifact_refs + self.observation_refs):
            raise StorePolicyError("receipt evidence references must share the task scope")
        object.__setattr__(self, "metadata", _metadata(self.metadata, "receipt metadata"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "receipt_id": self.receipt_id,
            "task_id": self.task_id,
            "step_id": self.step_id,
            "execution_id": self.execution_id,
            "capability_id": self.capability_id,
            "provider_id": self.provider_id,
            "operation": self.operation,
            "started_at_ms": self.started_at_ms,
            "ended_at_ms": self.ended_at_ms,
            "result_status": self.result_status.value,
            "error_code": self.error_code,
            "error_class": self.error_class,
            "failure_signature": self.failure_signature,
            "safe_message": self.safe_message,
            "side_effect_class": self.side_effect_class.value,
            "dispatch_status": self.dispatch_status.value,
            "verification_ref": self.verification_ref,
            "artifact_refs": [value.to_dict() for value in self.artifact_refs],
            "observation_refs": [value.to_dict() for value in self.observation_refs],
            "metadata": dict(self.metadata),
        }

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ExecutionReceipt":
        required = {
            "schema_version",
            "receipt_id",
            "task_id",
            "step_id",
            "execution_id",
            "capability_id",
            "provider_id",
            "operation",
            "started_at_ms",
            "ended_at_ms",
            "result_status",
            "error_code",
            "error_class",
            "failure_signature",
            "safe_message",
            "side_effect_class",
            "dispatch_status",
            "verification_ref",
            "artifact_refs",
            "observation_refs",
            "metadata",
        }
        if not isinstance(payload, dict) or set(payload) != required:
            raise StoreSchemaError("stored ExecutionReceipt has an incompatible schema")
        try:
            return cls(
                receipt_id=payload["receipt_id"],
                task_id=payload["task_id"],
                step_id=payload["step_id"],
                execution_id=payload["execution_id"],
                capability_id=payload["capability_id"],
                provider_id=payload["provider_id"],
                operation=payload["operation"],
                started_at_ms=payload["started_at_ms"],
                ended_at_ms=payload["ended_at_ms"],
                result_status=ReceiptResultStatus(payload["result_status"]),
                error_code=payload["error_code"],
                error_class=payload["error_class"],
                failure_signature=payload["failure_signature"],
                safe_message=payload["safe_message"],
                side_effect_class=SideEffectClass(payload["side_effect_class"]),
                dispatch_status=DispatchStatus(payload["dispatch_status"]),
                verification_ref=payload["verification_ref"],
                artifact_refs=tuple(_artifact_ref_from_dict(value) for value in payload["artifact_refs"]),
                observation_refs=tuple(
                    _observation_ref_from_dict(value) for value in payload["observation_refs"]
                ),
                metadata=payload["metadata"],
                schema_version=payload["schema_version"],
            )
        except (TypeError, ValueError, StorePolicyError) as exc:
            raise StoreSchemaError("stored ExecutionReceipt is invalid") from exc


@dataclass(frozen=True)
class TraceEvent:
    event_id: str
    task_id: str
    trace_id: str
    event_name: str
    observed_timestamp_ms: int
    parent_event_id: str | None = None
    step_id: str | None = None
    execution_id: str | None = None
    provider_id: str | None = None
    capability_id: str | None = None
    source_timestamp_ms: int | None = None
    receipt_refs: tuple[str, ...] = ()
    artifact_refs: tuple[ArtifactRef, ...] = ()
    observation_refs: tuple[ObservationRef, ...] = ()
    verifier_result: str | None = None
    error_code: str | None = None
    error_class: str | None = None
    failure_signature: str | None = None
    safe_message: str | None = None
    attributes: tuple[tuple[str, str], ...] = ()
    schema_version: str = TRACE_EVENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != TRACE_EVENT_SCHEMA_VERSION:
            raise StorePolicyError("unsupported TraceEvent schema version")
        for name in ("event_id", "task_id", "trace_id", "event_name"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        for name in (
            "parent_event_id",
            "step_id",
            "execution_id",
            "provider_id",
            "capability_id",
            "verifier_result",
            "error_code",
            "error_class",
            "failure_signature",
        ):
            object.__setattr__(self, name, _optional_identifier(getattr(self, name), name))
        _timestamp(self.observed_timestamp_ms, "observed_timestamp_ms")
        if self.source_timestamp_ms is not None:
            _timestamp(self.source_timestamp_ms, "source_timestamp_ms")
        object.__setattr__(self, "receipt_refs", _references(self.receipt_refs, "receipt_refs"))
        object.__setattr__(self, "artifact_refs", _artifact_refs(self.artifact_refs, "artifact_refs"))
        object.__setattr__(self, "observation_refs", _observation_refs(self.observation_refs, "observation_refs"))
        if any(ref.task_id != self.task_id for ref in self.artifact_refs + self.observation_refs):
            raise StorePolicyError("trace evidence references must share the task scope")
        if self.safe_message is not None:
            object.__setattr__(
                self,
                "safe_message",
                _safe_text(self.safe_message, "safe_message", maximum=MAX_SAFE_MESSAGE_LENGTH),
            )
        object.__setattr__(self, "attributes", _metadata(self.attributes, "trace attributes"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "parent_event_id": self.parent_event_id,
            "step_id": self.step_id,
            "execution_id": self.execution_id,
            "provider_id": self.provider_id,
            "capability_id": self.capability_id,
            "event_name": self.event_name,
            "source_timestamp_ms": self.source_timestamp_ms,
            "observed_timestamp_ms": self.observed_timestamp_ms,
            "receipt_refs": list(self.receipt_refs),
            "artifact_refs": [value.to_dict() for value in self.artifact_refs],
            "observation_refs": [value.to_dict() for value in self.observation_refs],
            "verifier_result": self.verifier_result,
            "error_code": self.error_code,
            "error_class": self.error_class,
            "failure_signature": self.failure_signature,
            "safe_message": self.safe_message,
            "attributes": dict(self.attributes),
        }

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TraceEvent":
        required = {
            "schema_version",
            "event_id",
            "task_id",
            "trace_id",
            "parent_event_id",
            "step_id",
            "execution_id",
            "provider_id",
            "capability_id",
            "event_name",
            "source_timestamp_ms",
            "observed_timestamp_ms",
            "receipt_refs",
            "artifact_refs",
            "observation_refs",
            "verifier_result",
            "error_code",
            "error_class",
            "failure_signature",
            "safe_message",
            "attributes",
        }
        if not isinstance(payload, dict) or set(payload) != required:
            raise StoreSchemaError("stored TraceEvent has an incompatible schema")
        try:
            return cls(
                event_id=payload["event_id"],
                task_id=payload["task_id"],
                trace_id=payload["trace_id"],
                parent_event_id=payload["parent_event_id"],
                step_id=payload["step_id"],
                execution_id=payload["execution_id"],
                provider_id=payload["provider_id"],
                capability_id=payload["capability_id"],
                event_name=payload["event_name"],
                source_timestamp_ms=payload["source_timestamp_ms"],
                observed_timestamp_ms=payload["observed_timestamp_ms"],
                receipt_refs=tuple(payload["receipt_refs"]),
                artifact_refs=tuple(_artifact_ref_from_dict(value) for value in payload["artifact_refs"]),
                observation_refs=tuple(
                    _observation_ref_from_dict(value) for value in payload["observation_refs"]
                ),
                verifier_result=payload["verifier_result"],
                error_code=payload["error_code"],
                error_class=payload["error_class"],
                failure_signature=payload["failure_signature"],
                safe_message=payload["safe_message"],
                attributes=payload["attributes"],
                schema_version=payload["schema_version"],
            )
        except (TypeError, ValueError, StorePolicyError) as exc:
            raise StoreSchemaError("stored TraceEvent is invalid") from exc


class PhoneHarnessStore:
    """Single-writer SQLite store for immutable runtime evidence.

    The process holds an exclusive advisory lock for the lifetime of the store
    and serializes its one SQLite connection with an RLock. No API in this
    class dispatches, authorizes, verifies, resumes, or replays an action.
    """

    REQUIRED_TABLES = frozenset({"artifacts", "receipts", "trace_events"})
    REQUIRED_COLUMNS = {
        "artifacts": (
            "artifact_id",
            "task_id",
            "session_id",
            "created_at_ms",
            "body_json",
            "body_sha256",
        ),
        "receipts": (
            "receipt_id",
            "task_id",
            "execution_id",
            "started_at_ms",
            "body_json",
            "body_sha256",
        ),
        "trace_events": (
            "event_id",
            "task_id",
            "trace_id",
            "observed_timestamp_ms",
            "body_json",
            "body_sha256",
        ),
    }

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self._mutex = threading.RLock()
        self._closed = False
        parent_existed = self.path.parent.exists()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not parent_existed:
            os.chmod(self.path.parent, 0o700)
        self._lock_path = self.path.with_suffix(self.path.suffix + ".writer.lock")
        self._lock_fd = os.open(self._lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(self._lock_fd)
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                raise StoreWriterUnavailableError("canonical store writer is already owned") from exc
            raise

        existed = self.path.exists()
        try:
            self._connection = sqlite3.connect(
                self.path,
                check_same_thread=False,
                isolation_level=None,
                timeout=5.0,
            )
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys=ON")
            self._connection.execute("PRAGMA synchronous=FULL")
            self._connection.execute("PRAGMA busy_timeout=5000")
            version = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
            if existed:
                if version != STORE_SCHEMA_VERSION:
                    raise StoreSchemaError(f"unsupported store schema version {version}")
                self._verify_schema()
            else:
                self._initialize_schema()
            journal_mode = str(self._connection.execute("PRAGMA journal_mode=DELETE").fetchone()[0]).casefold()
            if journal_mode != "delete":
                raise StoreSchemaError("store requires SQLite DELETE journal mode")
            os.chmod(self.path, 0o600)
        except Exception:
            if hasattr(self, "_connection"):
                self._connection.close()
            fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            os.close(self._lock_fd)
            self._closed = True
            raise

    @property
    def schema_version(self) -> int:
        with self._mutex:
            self._require_open()
            return int(self._connection.execute("PRAGMA user_version").fetchone()[0])

    @property
    def journal_mode(self) -> str:
        with self._mutex:
            self._require_open()
            return str(self._connection.execute("PRAGMA journal_mode").fetchone()[0]).upper()

    @property
    def writer_topology(self) -> str:
        return "SINGLE_PROCESS_SINGLE_CONNECTION_RLOCK_SERIALIZED"

    def close(self) -> None:
        with self._mutex:
            if self._closed:
                return
            self._connection.close()
            fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            os.close(self._lock_fd)
            self._closed = True

    def __enter__(self) -> "PhoneHarnessStore":
        self._require_open()
        return self

    def __exit__(self, _type: Any, _value: Any, _traceback: Any) -> None:
        self.close()

    def register_artifact(self, descriptor: ArtifactDescriptor) -> bool:
        _validate_artifact_descriptor(descriptor)
        if descriptor.lifetime is ArtifactLifetime.EPHEMERAL:
            raise StorePolicyError("EPHEMERAL artifact metadata is not eligible for durable registration")
        body = descriptor.to_json()
        with self._transaction():
            return self._insert_immutable(
                "artifacts",
                "artifact_id",
                descriptor.ref.artifact_id,
                body,
                {
                    "task_id": descriptor.ref.task_id,
                    "session_id": descriptor.ref.session_id,
                    "created_at_ms": descriptor.created_at_ms,
                },
            )

    def get_artifact(self, ref: ArtifactRef) -> ArtifactDescriptor:
        if not isinstance(ref, ArtifactRef):
            raise StorePolicyError("artifact lookup requires ArtifactRef")
        row = self._fetch_one("SELECT body_json, body_sha256 FROM artifacts WHERE artifact_id=?", (ref.artifact_id,))
        if row is None:
            raise UnknownArtifactError("artifact reference is unknown")
        descriptor = _artifact_descriptor_from_dict(self._verified_json(row))
        if descriptor.ref != ref:
            raise UnknownArtifactError("artifact reference scope does not match durable evidence")
        return descriptor

    def list_artifacts(self, task_id: str, *, session_id: str | None = None) -> tuple[ArtifactDescriptor, ...]:
        task = _identifier(task_id, "task_id")
        if session_id is None:
            rows = self._fetch_all(
                "SELECT body_json, body_sha256 FROM artifacts WHERE task_id=? ORDER BY created_at_ms, artifact_id",
                (task,),
            )
        else:
            session = _identifier(session_id, "session_id")
            rows = self._fetch_all(
                "SELECT body_json, body_sha256 FROM artifacts WHERE task_id=? AND session_id=? "
                "ORDER BY created_at_ms, artifact_id",
                (task, session),
            )
        return tuple(_artifact_descriptor_from_dict(self._verified_json(row)) for row in rows)

    def append_receipt(self, receipt: ExecutionReceipt) -> bool:
        if not isinstance(receipt, ExecutionReceipt):
            raise StorePolicyError("receipt append requires ExecutionReceipt")
        with self._transaction():
            return self._insert_receipt(receipt)

    def get_receipt(self, receipt_id: str) -> ExecutionReceipt:
        identifier = _identifier(receipt_id, "receipt_id")
        row = self._fetch_one("SELECT body_json, body_sha256 FROM receipts WHERE receipt_id=?", (identifier,))
        if row is None:
            raise UnknownReceiptError("receipt identifier is unknown")
        return ExecutionReceipt.from_dict(self._verified_json(row))

    def list_receipts(
        self,
        task_id: str,
        *,
        execution_id: str | None = None,
    ) -> tuple[ExecutionReceipt, ...]:
        task = _identifier(task_id, "task_id")
        if execution_id is None:
            rows = self._fetch_all(
                "SELECT body_json, body_sha256 FROM receipts WHERE task_id=? "
                "ORDER BY started_at_ms, receipt_id",
                (task,),
            )
        else:
            execution = _identifier(execution_id, "execution_id")
            rows = self._fetch_all(
                "SELECT body_json, body_sha256 FROM receipts WHERE task_id=? AND execution_id=? "
                "ORDER BY started_at_ms, receipt_id",
                (task, execution),
            )
        return tuple(ExecutionReceipt.from_dict(self._verified_json(row)) for row in rows)

    def append_trace_event(self, event: TraceEvent) -> bool:
        if not isinstance(event, TraceEvent):
            raise StorePolicyError("trace append requires TraceEvent")
        with self._transaction():
            return self._insert_trace_event(event)

    def get_trace_event(self, event_id: str) -> TraceEvent:
        identifier = _identifier(event_id, "event_id")
        row = self._fetch_one("SELECT body_json, body_sha256 FROM trace_events WHERE event_id=?", (identifier,))
        if row is None:
            raise UnknownTraceEventError("trace event identifier is unknown")
        return TraceEvent.from_dict(self._verified_json(row))

    def list_trace_events(
        self,
        task_id: str,
        *,
        trace_id: str | None = None,
    ) -> tuple[TraceEvent, ...]:
        task = _identifier(task_id, "task_id")
        if trace_id is None:
            rows = self._fetch_all(
                "SELECT body_json, body_sha256 FROM trace_events WHERE task_id=? "
                "ORDER BY observed_timestamp_ms, event_id",
                (task,),
            )
        else:
            trace = _identifier(trace_id, "trace_id")
            rows = self._fetch_all(
                "SELECT body_json, body_sha256 FROM trace_events WHERE task_id=? AND trace_id=? "
                "ORDER BY observed_timestamp_ms, event_id",
                (task, trace),
            )
        return tuple(TraceEvent.from_dict(self._verified_json(row)) for row in rows)

    def record_receipt_and_trace(self, receipt: ExecutionReceipt, event: TraceEvent) -> tuple[bool, bool]:
        if not isinstance(receipt, ExecutionReceipt) or not isinstance(event, TraceEvent):
            raise StorePolicyError("correlated write requires typed receipt and trace event")
        if receipt.task_id != event.task_id or receipt.receipt_id not in event.receipt_refs:
            raise StorePolicyError("correlated receipt and trace event must share task and reference identity")
        with self._transaction():
            receipt_created = self._insert_receipt(receipt)
            event_created = self._insert_trace_event(event)
            return receipt_created, event_created

    def record_artifact_and_trace(self, descriptor: ArtifactDescriptor, event: TraceEvent) -> tuple[bool, bool]:
        if not isinstance(descriptor, ArtifactDescriptor) or not isinstance(event, TraceEvent):
            raise StorePolicyError("correlated write requires typed artifact and trace event")
        _validate_artifact_descriptor(descriptor)
        if descriptor.lifetime is ArtifactLifetime.EPHEMERAL:
            raise StorePolicyError("EPHEMERAL artifact metadata is not eligible for durable registration")
        if descriptor.ref.task_id != event.task_id or descriptor.ref not in event.artifact_refs:
            raise StorePolicyError("correlated artifact and trace event must share task and reference identity")
        body = descriptor.to_json()
        with self._transaction():
            artifact_created = self._insert_immutable(
                "artifacts",
                "artifact_id",
                descriptor.ref.artifact_id,
                body,
                {
                    "task_id": descriptor.ref.task_id,
                    "session_id": descriptor.ref.session_id,
                    "created_at_ms": descriptor.created_at_ms,
                },
            )
            event_created = self._insert_trace_event(event)
            return artifact_created, event_created

    def _initialize_schema(self) -> None:
        self._connection.execute("PRAGMA journal_mode=DELETE")
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            statements = (
                """CREATE TABLE artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    session_id TEXT,
                    created_at_ms INTEGER NOT NULL,
                    body_json TEXT NOT NULL,
                    body_sha256 TEXT NOT NULL
                )""",
                "CREATE INDEX artifacts_task_idx ON artifacts(task_id, created_at_ms, artifact_id)",
                "CREATE INDEX artifacts_session_idx ON artifacts(task_id, session_id, created_at_ms, artifact_id)",
                """CREATE TABLE receipts (
                    receipt_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    execution_id TEXT NOT NULL,
                    started_at_ms INTEGER NOT NULL,
                    body_json TEXT NOT NULL,
                    body_sha256 TEXT NOT NULL
                )""",
                "CREATE INDEX receipts_task_idx ON receipts(task_id, started_at_ms, receipt_id)",
                "CREATE INDEX receipts_execution_idx ON receipts(task_id, execution_id, started_at_ms, receipt_id)",
                """CREATE TABLE trace_events (
                    event_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    observed_timestamp_ms INTEGER NOT NULL,
                    body_json TEXT NOT NULL,
                    body_sha256 TEXT NOT NULL
                )""",
                "CREATE INDEX trace_task_idx ON trace_events(task_id, observed_timestamp_ms, event_id)",
                "CREATE INDEX trace_id_idx ON trace_events(task_id, trace_id, observed_timestamp_ms, event_id)",
            )
            for statement in statements:
                self._connection.execute(statement)
            self._connection.execute(f"PRAGMA user_version={STORE_SCHEMA_VERSION}")
            self._connection.execute("COMMIT")
        except Exception:
            self._connection.execute("ROLLBACK")
            raise

    def _verify_schema(self) -> None:
        names = {
            str(row[0])
            for row in self._connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        if names != self.REQUIRED_TABLES:
            raise StoreSchemaError("store schema tables do not match the supported version")
        for table, expected_columns in self.REQUIRED_COLUMNS.items():
            actual_columns = tuple(
                str(row[1]) for row in self._connection.execute(f"PRAGMA table_info({table})").fetchall()
            )
            if actual_columns != expected_columns:
                raise StoreSchemaError(f"store table {table} has an incompatible layout")

    def _require_open(self) -> None:
        if self._closed:
            raise StoreClosedError("store is closed")

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        with self._mutex:
            self._require_open()
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
            else:
                self._connection.execute("COMMIT")

    def _fetch_one(self, sql: str, parameters: tuple[Any, ...]) -> sqlite3.Row | None:
        with self._mutex:
            self._require_open()
            return self._connection.execute(sql, parameters).fetchone()

    def _fetch_all(self, sql: str, parameters: tuple[Any, ...]) -> tuple[sqlite3.Row, ...]:
        with self._mutex:
            self._require_open()
            return tuple(self._connection.execute(sql, parameters).fetchall())

    def _insert_receipt(self, receipt: ExecutionReceipt) -> bool:
        return self._insert_immutable(
            "receipts",
            "receipt_id",
            receipt.receipt_id,
            receipt.to_json(),
            {
                "task_id": receipt.task_id,
                "execution_id": receipt.execution_id,
                "started_at_ms": receipt.started_at_ms,
            },
        )

    def _insert_trace_event(self, event: TraceEvent) -> bool:
        return self._insert_immutable(
            "trace_events",
            "event_id",
            event.event_id,
            event.to_json(),
            {
                "task_id": event.task_id,
                "trace_id": event.trace_id,
                "observed_timestamp_ms": event.observed_timestamp_ms,
            },
        )

    def _insert_immutable(
        self,
        table: str,
        identifier_column: str,
        identifier: str,
        body: str,
        columns: Mapping[str, Any],
    ) -> bool:
        existing = self._connection.execute(
            f"SELECT body_json, body_sha256 FROM {table} WHERE {identifier_column}=?",
            (identifier,),
        ).fetchone()
        body_sha256 = _digest(body)
        if existing is not None:
            if existing["body_json"] == body and existing["body_sha256"] == body_sha256:
                return False
            raise StoreConflictError(f"conflicting immutable {identifier_column}")
        names = [identifier_column, *columns.keys(), "body_json", "body_sha256"]
        placeholders = ",".join("?" for _ in names)
        self._connection.execute(
            f"INSERT INTO {table} ({','.join(names)}) VALUES ({placeholders})",
            (identifier, *columns.values(), body, body_sha256),
        )
        return True

    @staticmethod
    def _verified_json(row: sqlite3.Row) -> dict[str, Any]:
        body = str(row["body_json"])
        if _digest(body) != row["body_sha256"]:
            raise StoreSchemaError("stored record integrity digest does not match")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise StoreSchemaError("stored record is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise StoreSchemaError("stored record must be a JSON object")
        return payload


__all__ = [
    "DispatchStatus",
    "ExecutionReceipt",
    "PhoneHarnessStore",
    "ReceiptResultStatus",
    "SideEffectClass",
    "StoreClosedError",
    "StoreConflictError",
    "StorePolicyError",
    "StoreSchemaError",
    "StoreWriterUnavailableError",
    "TraceEvent",
    "UnknownArtifactError",
    "UnknownReceiptError",
    "UnknownTraceEventError",
]
