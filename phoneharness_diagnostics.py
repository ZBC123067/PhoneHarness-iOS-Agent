#!/usr/bin/env python3
"""Typed file, log, and crash evidence foundation for S4-M5.

This Host layer adapts the existing bounded device providers into typed,
privacy-safe evidence. It does not authorize, dispatch, persist, retry, read a
device, or create a second artifact, trace, freshness, shell, process, package,
or software-management runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import posixpath
import re
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit

from phoneharness_contracts import ArtifactRef, ObservationRef


MAX_PATH_BYTES = 4096
MAX_SAFE_BASENAME = 128
MAX_FILE_SIZE = (1 << 63) - 1
MAX_LOG_SECONDS = 60
DEFAULT_LOG_SECONDS = 5
MAX_LOG_LINES = 5000
DEFAULT_LOG_LINES = 500
MAX_LOG_FILTER = 128
MAX_LOG_MESSAGE = 2048
MAX_CRASH_REPORT_BYTES = 1024 * 1024
MAX_CRASH_FIELD = 512
MAX_CRASH_STACK_ITEMS = 8
MAX_CRASH_MODULES = 32
MAX_CORRELATION_WINDOW_MS = 86_400_000

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_SAFE_BASENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ +()@-]{0,127}$")
_URL = re.compile(r"(?i)\b(?:https?|ftp)://[^\s'\"<>]+")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(authorization|x-mcp-token|mcp[_ -]?token|password|passwd|passcode|otp"
    r"|token|access[_ -]?token|refresh[_ -]?token|api[_ -]?key|apikey)\b"
    r"\s*[:=]\s*(?:bearer\s+)?[^\s,;]+"
)
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_AUTH_VALUE = re.compile(r"(?i)\b(authorization)\b\s*[:=]\s*\S+(?:\s+\S+)?")


class DiagnosticPolicyError(RuntimeError):
    """Typed S4-M5 contract validation failure."""


def _identifier(value: Any, field_name: str) -> str:
    normalized = str(value or "").strip()
    if _IDENTIFIER.fullmatch(normalized) is None:
        raise DiagnosticPolicyError(f"{field_name} must be an opaque bounded identifier")
    return normalized


def _optional_identifier(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _identifier(value, field_name)


def _nonnegative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DiagnosticPolicyError(f"{field_name} must be a non-negative integer")
    return value


def _bounded_text(value: Any, field_name: str, *, maximum: int = MAX_CRASH_FIELD) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    if len(normalized) > maximum or _CONTROL.search(normalized):
        raise DiagnosticPolicyError(f"{field_name} must be bounded safe text")
    return normalized


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest_text(value: str) -> str:
    return _digest_bytes(value.encode("utf-8"))


def _require_digest(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if _DIGEST.fullmatch(normalized) is None:
        raise DiagnosticPolicyError(f"{field_name} must be lowercase SHA-256")
    return normalized


def _required_digest(value: Any, field_name: str) -> str:
    normalized = _require_digest(value, field_name)
    if normalized is None:
        raise DiagnosticPolicyError(f"{field_name} is required")
    return normalized


def _safe_pairs(values: Mapping[str, Any] | Sequence[tuple[str, Any]] | None) -> tuple[tuple[str, str], ...]:
    if values is None:
        return ()
    items = values.items() if isinstance(values, Mapping) else values
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw_key, raw_value in items:
        key = _identifier(raw_key, "metadata key")
        value = _bounded_text(raw_value, "metadata value", maximum=256)
        if value is None or key in seen:
            raise DiagnosticPolicyError("metadata must have unique non-empty values")
        seen.add(key)
        result.append((key, value))
    if len(result) > 32:
        raise DiagnosticPolicyError("metadata must remain bounded")
    return tuple(result)


# ---------------------------------------------------------------------------
# File evidence
# ---------------------------------------------------------------------------


class FileScope(str, Enum):
    CRASH_REPORT = "CRASH_REPORT"
    TEMPORARY = "TEMPORARY"
    APP_CONTAINER = "APP_CONTAINER"
    DEVICE_FILE = "DEVICE_FILE"
    UNKNOWN = "UNKNOWN"


class ProviderResolutionStatus(str, Enum):
    LEXICAL_ONLY = "LEXICAL_ONLY"
    PROVIDER_RESOLVED = "PROVIDER_RESOLVED"
    UNAVAILABLE = "UNAVAILABLE"


def validate_file_path(path: Any) -> str:
    """Validate and lexically normalize an absolute POSIX path.

    This intentionally does not call realpath, stat, lstat, or follow links.
    """

    if not isinstance(path, str) or not path:
        raise DiagnosticPolicyError("file path must be non-empty text")
    if len(path.encode("utf-8")) > MAX_PATH_BYTES:
        raise DiagnosticPolicyError("file path exceeds the typed contract bound")
    if _CONTROL.search(path):
        raise DiagnosticPolicyError("file path contains a control character")
    if not path.startswith("/"):
        raise DiagnosticPolicyError("file path must be absolute")
    if any(component == ".." for component in path.split("/")):
        raise DiagnosticPolicyError("file path traversal is not allowed")
    normalized = posixpath.normpath(path)
    if not normalized.startswith("/") or normalized in ("", "."):
        raise DiagnosticPolicyError("file path could not be normalized safely")
    return normalized


@dataclass(frozen=True)
class FileResourceRef:
    provider: str
    scope: FileScope
    path: str = field(repr=False)
    resolution_status: ProviderResolutionStatus = ProviderResolutionStatus.LEXICAL_ONLY

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", _identifier(self.provider, "file provider"))
        object.__setattr__(self, "scope", FileScope(self.scope))
        object.__setattr__(self, "path", validate_file_path(self.path))
        object.__setattr__(self, "resolution_status", ProviderResolutionStatus(self.resolution_status))

    @property
    def path_digest(self) -> str:
        return _digest_text(self.path)

    @property
    def safe_basename(self) -> str | None:
        if self.path == "/":
            return None
        basename = posixpath.basename(self.path)
        return basename if _SAFE_BASENAME.fullmatch(basename) else None

    def safe_diagnostic(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "scope": self.scope.value,
            "root_alias": f"<{self.scope.value.lower()}>",
            "basename": self.safe_basename,
            "path_digest": self.path_digest,
            "resolution_status": self.resolution_status.value,
            "full_path_included": False,
            "authorization": False,
            "symlink_safe": False,
        }


class FileOperationKind(str, Enum):
    LIST = "LIST"
    READ_METADATA = "READ_METADATA"
    READ_CONTENT = "READ_CONTENT"
    CREATE = "CREATE"
    WRITE = "WRITE"
    APPEND = "APPEND"
    MOVE_OR_RENAME = "MOVE_OR_RENAME"
    DELETE = "DELETE"

    @property
    def mutation_capable(self) -> bool:
        return self in {
            FileOperationKind.CREATE,
            FileOperationKind.WRITE,
            FileOperationKind.APPEND,
            FileOperationKind.MOVE_OR_RENAME,
            FileOperationKind.DELETE,
        }

    @property
    def destructive(self) -> bool:
        return self is FileOperationKind.DELETE

    def audit(self) -> dict[str, Any]:
        return {
            "kind": self.value,
            "mutation_capable": self.mutation_capable,
            "destructive": self.destructive,
            "authorization": False,
        }


_FILE_TYPES = frozenset({"file", "directory", "symlink", "fifo", "socket", "char_device", "block_device", "unknown"})
_ENCODINGS = frozenset({"utf8", "base64", "binary", "unknown"})


@dataclass(frozen=True)
class FileEvidence:
    resource: FileResourceRef
    size: int
    mtime_ms: int
    file_type: str
    mode: str | None = None
    encoding: str = "unknown"
    truncated: bool = False
    content_digest: str | None = None
    observation_ref: ObservationRef | None = None
    artifact_ref: ArtifactRef | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.resource, FileResourceRef):
            raise DiagnosticPolicyError("file evidence requires FileResourceRef")
        size = _nonnegative_int(self.size, "file size")
        if size > MAX_FILE_SIZE:
            raise DiagnosticPolicyError("file size exceeds the typed contract bound")
        object.__setattr__(self, "mtime_ms", _nonnegative_int(self.mtime_ms, "file mtime"))
        file_type = str(self.file_type).strip().lower()
        if file_type not in _FILE_TYPES:
            raise DiagnosticPolicyError("unsupported file type")
        object.__setattr__(self, "file_type", file_type)
        if self.mode is not None and re.fullmatch(r"[0-7]{3,4}", str(self.mode)) is None:
            raise DiagnosticPolicyError("file mode must be an octal diagnostic string")
        encoding = str(self.encoding).strip().lower()
        if encoding not in _ENCODINGS:
            raise DiagnosticPolicyError("unsupported file encoding")
        object.__setattr__(self, "encoding", encoding)
        if not isinstance(self.truncated, bool):
            raise DiagnosticPolicyError("file truncation state must be boolean")
        object.__setattr__(self, "content_digest", _require_digest(self.content_digest, "file content digest"))
        if self.observation_ref is not None and not isinstance(self.observation_ref, ObservationRef):
            raise DiagnosticPolicyError("file evidence provenance must use ObservationRef")
        if self.artifact_ref is not None and not isinstance(self.artifact_ref, ArtifactRef):
            raise DiagnosticPolicyError("file evidence artifact must use ArtifactRef")
        if self.observation_ref is not None and self.artifact_ref is not None:
            if self.observation_ref.task_id != self.artifact_ref.task_id:
                raise DiagnosticPolicyError("file observation and artifact task scopes must match")

    def safe_diagnostic(self) -> dict[str, Any]:
        return {
            "resource": self.resource.safe_diagnostic(),
            "size": self.size,
            "mtime_ms": self.mtime_ms,
            "file_type": self.file_type,
            "mode": self.mode,
            "encoding": self.encoding,
            "truncated": self.truncated,
            "content_digest": self.content_digest,
            "observation_ref": self.observation_ref.to_dict() if self.observation_ref else None,
            "artifact_ref": self.artifact_ref.to_dict() if self.artifact_ref else None,
            "plaintext_content_included": False,
            "authorization": False,
        }


class FileReadStatus(str, Enum):
    STABLE = "STABLE"
    UNSTABLE = "UNSTABLE"


def evaluate_stable_file_read(before: FileEvidence, after: FileEvidence) -> FileReadStatus:
    """Compare bounded before/after metadata without claiming atomic identity."""

    if not isinstance(before, FileEvidence) or not isinstance(after, FileEvidence):
        raise DiagnosticPolicyError("stable file read requires typed FileEvidence")
    comparable = (
        before.resource.provider == after.resource.provider
        and before.resource.scope is after.resource.scope
        and before.resource.path_digest == after.resource.path_digest
    )
    stable_metadata = (
        before.size == after.size
        and before.mtime_ms == after.mtime_ms
        and before.file_type == after.file_type
        and before.mode == after.mode
        and before.content_digest == after.content_digest
    )
    return FileReadStatus.STABLE if comparable and stable_metadata else FileReadStatus.UNSTABLE


def bounded_file_read_request(resource: FileResourceRef, max_bytes: int) -> dict[str, Any]:
    if not isinstance(resource, FileResourceRef):
        raise DiagnosticPolicyError("bounded read requires FileResourceRef")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not 1 <= max_bytes <= 4 * 1024 * 1024:
        raise DiagnosticPolicyError("bounded file read max_bytes must be between 1 and 4 MiB")
    return {"provider": "read_file", "path": resource.path, "max_bytes": max_bytes, "bounded": True}


# ---------------------------------------------------------------------------
# Unified log evidence
# ---------------------------------------------------------------------------


class LogParseStatus(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


def _redact_url(match: re.Match[str]) -> str:
    raw = match.group(0)
    trailing = ""
    while raw and raw[-1] in ").,;":
        trailing = raw[-1] + trailing
        raw = raw[:-1]
    try:
        parts = urlsplit(raw)
        host = parts.hostname or ""
        if parts.port is not None:
            host = f"{host}:{parts.port}"
        query = "<redacted-query>" if parts.query else ""
        fragment = "<redacted-fragment>" if parts.fragment else ""
        return urlunsplit((parts.scheme, host, parts.path, query, fragment)) + trailing
    except (ValueError, UnicodeError):
        return "<redacted-url>" + trailing


def redact_log_message(message: Any) -> str:
    text = str(message or "")
    text = _URL.sub(_redact_url, text)
    text = _AUTH_VALUE.sub(lambda match: f"{match.group(1)}=<redacted>", text)
    text = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=<redacted>", text)
    text = _BEARER.sub("Bearer <redacted>", text)
    if len(text) > MAX_LOG_MESSAGE:
        text = text[:MAX_LOG_MESSAGE]
    return text


@dataclass(frozen=True)
class LogWindowSpec:
    requested_seconds: int = DEFAULT_LOG_SECONDS
    requested_max_lines: int = DEFAULT_LOG_LINES
    process_filter: str | None = None
    level_filter: str = "all"

    def __post_init__(self) -> None:
        for field_name in ("requested_seconds", "requested_max_lines"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise DiagnosticPolicyError(f"{field_name} must be a positive integer")
        if self.process_filter is not None:
            process = _bounded_text(self.process_filter, "process filter", maximum=MAX_LOG_FILTER)
            if process is None:
                raise DiagnosticPolicyError("process filter cannot be empty")
            object.__setattr__(self, "process_filter", process)
        level = str(self.level_filter or "all").strip().lower()
        if level not in {"all", "debug", "info", "default", "error", "fault"}:
            raise DiagnosticPolicyError("unsupported log level filter")
        object.__setattr__(self, "level_filter", level)

    @property
    def effective_seconds(self) -> int:
        return min(self.requested_seconds, MAX_LOG_SECONDS)

    @property
    def effective_max_lines(self) -> int:
        return min(self.requested_max_lines, MAX_LOG_LINES)

    @property
    def timeout_seconds(self) -> int:
        return self.effective_seconds + 10

    def provider_arguments(self) -> dict[str, Any]:
        return {
            "last_seconds": self.effective_seconds,
            "max_lines": self.effective_max_lines,
            "process": self.process_filter,
            "level": self.level_filter,
            "timeout_seconds": self.timeout_seconds,
        }

    def audit(self) -> dict[str, Any]:
        return {
            "bounded": True,
            "unbounded_stream": False,
            "unbounded_accumulation": False,
            "authorization": False,
        }


@dataclass(frozen=True)
class LogEntry:
    timestamp: str | None
    process_name: str | None
    pid: int | None
    subsystem: str | None
    category: str | None
    severity: str
    safe_message: str
    provider: str
    raw_digest: str
    parse_status: LogParseStatus

    def __post_init__(self) -> None:
        for name in ("timestamp", "process_name", "subsystem", "category"):
            object.__setattr__(self, name, _bounded_text(getattr(self, name), name, maximum=256))
        if self.pid is not None:
            object.__setattr__(self, "pid", _nonnegative_int(self.pid, "log pid"))
        severity = str(self.severity or "unknown").strip().lower()
        if severity not in {"debug", "info", "default", "error", "fault", "unknown"}:
            severity = "unknown"
        object.__setattr__(self, "severity", severity)
        object.__setattr__(self, "safe_message", redact_log_message(self.safe_message))
        object.__setattr__(self, "provider", _identifier(self.provider, "log provider"))
        object.__setattr__(self, "raw_digest", _required_digest(self.raw_digest, "raw log digest"))
        object.__setattr__(self, "parse_status", LogParseStatus(self.parse_status))

    @classmethod
    def from_provider(cls, raw: Any, *, provider: str = "mcp-logreader") -> "LogEntry":
        if isinstance(raw, Mapping):
            canonical = json.dumps(dict(raw), sort_keys=True, separators=(",", ":"), default=str)
            message = raw.get("message", "")
            timestamp = raw.get("date", raw.get("timestamp"))
            process = raw.get("process")
            pid_value = raw.get("pid")
            pid = pid_value if isinstance(pid_value, int) and not isinstance(pid_value, bool) and pid_value >= 0 else None
            subsystem = raw.get("subsystem")
            category = raw.get("category")
            level = raw.get("level", "unknown")
            recognized = [timestamp, process, pid, subsystem, category, message]
            status = LogParseStatus.COMPLETE if message and timestamp and process else (
                LogParseStatus.PARTIAL if any(value not in (None, "") for value in recognized) else LogParseStatus.UNKNOWN
            )
        else:
            canonical = str(raw or "")
            message = canonical
            timestamp = process = subsystem = category = None
            pid = None
            level = "unknown"
            status = LogParseStatus.PARTIAL if canonical else LogParseStatus.UNKNOWN
        return cls(
            timestamp, process, pid, subsystem, category, str(level),
            redact_log_message(message), provider, _digest_text(canonical), status,
        )

    def safe_diagnostic(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "process_name": self.process_name,
            "pid": self.pid,
            "subsystem": self.subsystem,
            "category": self.category,
            "severity": self.severity,
            "safe_message": self.safe_message,
            "provider": self.provider,
            "raw_digest": self.raw_digest,
            "parse_status": self.parse_status.value,
            "raw_line_included": False,
            "authorization": False,
        }


@dataclass(frozen=True)
class LogWindowEvidence:
    spec: LogWindowSpec
    entries: tuple[LogEntry, ...]
    provider: str
    capture_started_ms: int
    capture_ended_ms: int
    truncated: bool = False
    observation_ref: ObservationRef | None = None
    artifact_refs: tuple[ArtifactRef, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.spec, LogWindowSpec):
            raise DiagnosticPolicyError("log evidence requires LogWindowSpec")
        entries = tuple(self.entries)
        if any(not isinstance(entry, LogEntry) for entry in entries):
            raise DiagnosticPolicyError("log evidence entries must be typed LogEntry values")
        if len(entries) > self.spec.effective_max_lines:
            raise DiagnosticPolicyError("log evidence exceeds the bounded line count")
        object.__setattr__(self, "entries", entries)
        object.__setattr__(self, "provider", _identifier(self.provider, "log window provider"))
        start = _nonnegative_int(self.capture_started_ms, "capture start")
        end = _nonnegative_int(self.capture_ended_ms, "capture end")
        if end < start:
            raise DiagnosticPolicyError("log capture end cannot precede start")
        if not isinstance(self.truncated, bool):
            raise DiagnosticPolicyError("log truncation state must be boolean")
        if self.observation_ref is not None and not isinstance(self.observation_ref, ObservationRef):
            raise DiagnosticPolicyError("log evidence provenance must use ObservationRef")
        refs = tuple(self.artifact_refs)
        if any(not isinstance(ref, ArtifactRef) for ref in refs):
            raise DiagnosticPolicyError("log artifact references must use ArtifactRef")
        if self.observation_ref is not None and any(ref.task_id != self.observation_ref.task_id for ref in refs):
            raise DiagnosticPolicyError("log observation and artifact task scopes must match")
        object.__setattr__(self, "artifact_refs", refs)

    def safe_diagnostic(self) -> dict[str, Any]:
        return {
            "requested_seconds": self.spec.requested_seconds,
            "effective_seconds": self.spec.effective_seconds,
            "requested_max_lines": self.spec.requested_max_lines,
            "effective_max_lines": self.spec.effective_max_lines,
            "entry_count": len(self.entries),
            "entries": [entry.safe_diagnostic() for entry in self.entries],
            "provider": self.provider,
            "capture_started_ms": self.capture_started_ms,
            "capture_ended_ms": self.capture_ended_ms,
            "truncated": self.truncated,
            "raw_lines_auto_persisted": False,
            "authorization": False,
        }


# ---------------------------------------------------------------------------
# Crash evidence
# ---------------------------------------------------------------------------


class CrashParseStatus(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


class IncidentType(str, Enum):
    APP_CRASH = "APP_CRASH"
    SPRINGBOARD_CRASH = "SPRINGBOARD_CRASH"
    DAEMON_CRASH = "DAEMON_CRASH"
    WATCHDOG = "WATCHDOG"
    JETSAM = "JETSAM"
    HANG = "HANG"
    LAUNCH_FAILURE = "LAUNCH_FAILURE"
    PANIC = "PANIC"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class CrashIdentity:
    incident_id: str | None
    report_digest: str
    metadata_digest: str

    def __post_init__(self) -> None:
        incident = _bounded_text(self.incident_id, "incident identifier", maximum=128)
        object.__setattr__(self, "incident_id", incident)
        object.__setattr__(self, "report_digest", _required_digest(self.report_digest, "crash report digest"))
        object.__setattr__(self, "metadata_digest", _required_digest(self.metadata_digest, "crash metadata digest"))

    @property
    def stable_key(self) -> str:
        if self.incident_id:
            return f"incident:{_digest_text(self.incident_id.lower())}"
        return f"report:{self.report_digest}:{self.metadata_digest}"

    def audit(self) -> dict[str, Any]:
        return {
            "stable_key": self.stable_key,
            "incident_identifier_present": self.incident_id is not None,
            "filename_is_identity": False,
            "authorization": False,
        }


def bounded_crash_read_request(resource: FileResourceRef, max_bytes: int = MAX_CRASH_REPORT_BYTES) -> dict[str, Any]:
    if not isinstance(resource, FileResourceRef) or resource.scope is not FileScope.CRASH_REPORT:
        raise DiagnosticPolicyError("governed crash read requires a crash-report FileResourceRef")
    request = bounded_file_read_request(resource, max_bytes)
    request["legacy_read_crash_log"] = False
    request["governed_crash_read"] = True
    return request


def _first(mapping: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in mapping and mapping[name] not in (None, ""):
            return mapping[name]
    return None


def _line_value(text: str, *labels: str) -> str | None:
    label_group = "|".join(re.escape(label) for label in labels)
    match = re.search(rf"(?im)^(?:{label_group})\s*:\s*(.+?)\s*$", text)
    return match.group(1).strip() if match else None


def _classify_incident(
    *, process: str | None, exception_type: str | None, signal: str | None,
    termination_reason: str | None, process_context: str | None,
) -> IncidentType:
    """Classify from structured report fields only.

    Free report text (stack lines, module names, user strings) is deliberately
    excluded: a module named "WatchdogSomething" or the word "hang" inside
    user content must never determine the incident type.
    """

    structured = " ".join(
        value for value in (exception_type, signal, termination_reason, process_context) if value
    ).lower()
    process_lower = (process or "").lower()
    if "panicstring" in structured or structured.startswith("panic"):
        return IncidentType.PANIC
    if "jetsam" in structured or "memory pressure" in structured or "memorystatus" in structured:
        return IncidentType.JETSAM
    if "watchdog" in structured or "0x8badf00d" in structured:
        return IncidentType.WATCHDOG
    if "launch failure" in structured or "failed to launch" in structured:
        return IncidentType.LAUNCH_FAILURE
    if "hang" in structured or "spin" in structured:
        return IncidentType.HANG
    if process_lower == "springboard" and any((exception_type, signal, termination_reason)):
        return IncidentType.SPRINGBOARD_CRASH
    if (process_context or "").lower() == "daemon" and any((exception_type, signal, termination_reason)):
        return IncidentType.DAEMON_CRASH
    if process and any((exception_type, signal, termination_reason)):
        return IncidentType.APP_CRASH
    return IncidentType.UNKNOWN


def _stack_and_modules(text: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    stack: list[str] = []
    modules: list[str] = []
    in_binary_images = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("binary images"):
            in_binary_images = True
            continue
        if in_binary_images:
            path_match = re.search(r"(/[^\s]+)$", stripped)
            if path_match:
                name = posixpath.basename(path_match.group(1))
                if name and name not in modules:
                    modules.append(name[:128])
            elif not stripped:
                in_binary_images = False
            if len(modules) >= MAX_CRASH_MODULES:
                in_binary_images = False
            continue
        frame_match = re.match(r"^\d+\s+([^\s]+)", stripped)
        if frame_match and len(stack) < MAX_CRASH_STACK_ITEMS:
            module = frame_match.group(1)[:128]
            if module:
                stack.append(module)
    return tuple(stack), tuple(modules)


@dataclass(frozen=True)
class CrashEvidence:
    identity: CrashIdentity
    incident_type: IncidentType
    parse_status: CrashParseStatus
    source_ref: FileResourceRef
    report_digest: str
    safe_summary: str
    timestamp: str | None = None
    process_name: str | None = None
    bundle_id: str | None = None
    pid: int | None = None
    os_version: str | None = None
    device_model: str | None = None
    exception_type: str | None = None
    signal: str | None = None
    termination_reason: str | None = None
    watchdog_observed: bool = False
    jetsam_observed: bool = False
    stack_summary: tuple[str, ...] = ()
    binary_modules: tuple[str, ...] = ()
    environment_provenance: tuple[tuple[str, str], ...] = ()
    observation_ref: ObservationRef | None = None
    artifact_ref: ArtifactRef | None = None
    acquisition_truncated: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.identity, CrashIdentity):
            raise DiagnosticPolicyError("crash evidence requires CrashIdentity")
        object.__setattr__(self, "incident_type", IncidentType(self.incident_type))
        object.__setattr__(self, "parse_status", CrashParseStatus(self.parse_status))
        if not isinstance(self.source_ref, FileResourceRef) or self.source_ref.scope is not FileScope.CRASH_REPORT:
            raise DiagnosticPolicyError("crash evidence source must be a crash-report FileResourceRef")
        object.__setattr__(self, "report_digest", _required_digest(self.report_digest, "crash evidence digest"))
        object.__setattr__(self, "safe_summary", _bounded_text(self.safe_summary, "crash safe summary") or "Crash report fields unavailable")
        for name in (
            "timestamp", "process_name", "bundle_id", "os_version", "device_model",
            "exception_type", "signal", "termination_reason",
        ):
            object.__setattr__(self, name, _bounded_text(getattr(self, name), name))
        if self.pid is not None:
            object.__setattr__(self, "pid", _nonnegative_int(self.pid, "crash pid"))
        for name in ("watchdog_observed", "jetsam_observed", "acquisition_truncated"):
            if not isinstance(getattr(self, name), bool):
                raise DiagnosticPolicyError(f"{name} must be boolean")
        stack = tuple(_bounded_text(value, "stack module", maximum=128) for value in self.stack_summary)
        modules = tuple(_bounded_text(value, "binary module", maximum=128) for value in self.binary_modules)
        if any(value is None for value in stack + modules):
            raise DiagnosticPolicyError("crash module summaries cannot be empty")
        object.__setattr__(self, "stack_summary", stack[:MAX_CRASH_STACK_ITEMS])
        object.__setattr__(self, "binary_modules", modules[:MAX_CRASH_MODULES])
        object.__setattr__(self, "environment_provenance", _safe_pairs(self.environment_provenance))
        if self.observation_ref is not None and not isinstance(self.observation_ref, ObservationRef):
            raise DiagnosticPolicyError("crash provenance must use ObservationRef")
        if self.artifact_ref is not None and not isinstance(self.artifact_ref, ArtifactRef):
            raise DiagnosticPolicyError("crash artifact must use ArtifactRef")
        if self.observation_ref is not None and self.artifact_ref is not None:
            if self.observation_ref.task_id != self.artifact_ref.task_id:
                raise DiagnosticPolicyError("crash observation and artifact task scopes must match")

    def safe_diagnostic(self) -> dict[str, Any]:
        return {
            "identity": self.identity.audit(),
            "incident_type": self.incident_type.value,
            "parse_status": self.parse_status.value,
            "source": self.source_ref.safe_diagnostic(),
            "report_digest": self.report_digest,
            "safe_summary": self.safe_summary,
            "timestamp": self.timestamp,
            "process_name": self.process_name,
            "bundle_id": self.bundle_id,
            "pid": self.pid,
            "os_version": self.os_version,
            "device_model": self.device_model,
            "exception_type": self.exception_type,
            "signal": self.signal,
            "termination_reason": self.termination_reason,
            "watchdog_observed": self.watchdog_observed,
            "jetsam_observed": self.jetsam_observed,
            "stack_summary": list(self.stack_summary),
            "binary_modules": list(self.binary_modules),
            "environment_provenance": dict(self.environment_provenance),
            "acquisition_truncated": self.acquisition_truncated,
            "full_raw_report_included": False,
            "crash_report_is_root_cause": False,
            "incident_type_is_root_cause": False,
            "signal_is_root_cause": False,
            "module_presence_is_root_cause": False,
            "environment_provenance_is_root_cause": False,
            "injection_present_proves_causation": False,
            "authorization": False,
        }


def parse_crash_report(
    report: str | bytes,
    *,
    source_ref: FileResourceRef,
    observation_ref: ObservationRef | None = None,
    artifact_ref: ArtifactRef | None = None,
    environment_provenance: Mapping[str, Any] | Sequence[tuple[str, Any]] | None = None,
) -> CrashEvidence:
    if not isinstance(source_ref, FileResourceRef) or source_ref.scope is not FileScope.CRASH_REPORT:
        raise DiagnosticPolicyError("crash parser requires a crash-report FileResourceRef")
    raw = report.encode("utf-8") if isinstance(report, str) else bytes(report)
    truncated = len(raw) > MAX_CRASH_REPORT_BYTES
    bounded = raw[:MAX_CRASH_REPORT_BYTES]
    text = bounded.decode("utf-8", errors="replace")
    digest = _digest_bytes(bounded)

    structured: dict[str, Any] = {}
    stripped = text.strip()
    if stripped.startswith("{"):
        # .ips reports may carry multiple JSON documents (single-line header +
        # multi-line body). Scalar fields are merged across every parseable
        # form so modern structured payloads are not missed.
        lines = stripped.splitlines()
        merged: dict[str, Any] = {}
        candidates = [stripped] + [line.strip() for line in lines[:8] if line.strip().startswith("{")]
        remainder = "\n".join(lines[1:]).strip()
        if remainder.startswith("{"):
            candidates.append(remainder)
        for candidate in candidates:
            try:
                value = json.loads(candidate)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(value, dict):
                continue
            for key, value_item in value.items():
                if key not in merged and not isinstance(value_item, (dict, list)):
                    merged[key] = value_item
        exception_object = None
        if remainder.startswith("{"):
            try:
                remainder_value = json.loads(remainder)
            except (json.JSONDecodeError, TypeError):
                remainder_value = None
            if isinstance(remainder_value, dict) and isinstance(remainder_value.get("exception"), dict):
                exception_object = remainder_value["exception"]
        structured = merged
        if isinstance(exception_object, dict):
            if isinstance(exception_object.get("type"), str):
                structured["exceptionType"] = exception_object["type"]
            if isinstance(exception_object.get("signal"), str):
                structured["exceptionSignal"] = exception_object["signal"]

    incident_id = _first(structured, "incident", "incident_id", "incidentId") or _line_value(
        text, "Incident Identifier", "Incident ID"
    )
    process = _first(structured, "procName", "process", "process_name")
    pid_value = _first(structured, "pid", "process_id")
    pid = pid_value if isinstance(pid_value, int) and not isinstance(pid_value, bool) and pid_value >= 0 else None
    if process is None:
        process_line = _line_value(text, "Process")
        if process_line:
            match = re.match(r"(.+?)\s*\[(\d+)\]", process_line)
            if match:
                process = match.group(1).strip()
                pid = int(match.group(2))
            else:
                process = process_line
    timestamp = _first(structured, "timestamp", "captureTime", "date") or _line_value(text, "Date/Time", "Timestamp")
    bundle_id = _first(structured, "bundleID", "bundle_id", "bundleIdentifier") or _line_value(text, "Identifier")
    os_version = _first(structured, "osVersion", "os_version") or _line_value(text, "OS Version")
    device_model = _first(structured, "modelCode", "device_model", "model") or _line_value(text, "Hardware Model", "Device Model")
    exception_type = _first(structured, "exceptionType", "exception_type") or _line_value(text, "Exception Type")
    signal = _first(structured, "signal", "exceptionSignal") or _line_value(text, "Signal")
    termination_reason = _first(structured, "terminationReason", "termination_reason") or _line_value(text, "Termination Reason")
    process_context = _first(structured, "processType", "process_type", "processRole") or _line_value(
        text, "Process Type", "Process Role"
    )

    safe_fields: dict[str, str | None] = {}
    for key, value in {
        "incident_id": incident_id,
        "process": process,
        "timestamp": timestamp,
        "bundle_id": bundle_id,
        "os_version": os_version,
        "device_model": device_model,
        "exception_type": exception_type,
        "signal": signal,
        "termination_reason": termination_reason,
        "process_context": process_context,
    }.items():
        try:
            safe_fields[key] = _bounded_text(value, key)
        except DiagnosticPolicyError:
            safe_fields[key] = None

    incident_type = _classify_incident(
        process=safe_fields["process"], exception_type=safe_fields["exception_type"],
        signal=safe_fields["signal"], termination_reason=safe_fields["termination_reason"],
        process_context=safe_fields["process_context"],
    )
    stack, modules = _stack_and_modules(text)
    recognized_count = sum(value is not None for value in safe_fields.values()) + (1 if pid is not None else 0)
    parse_status = CrashParseStatus.COMPLETE if (
        safe_fields["incident_id"] and safe_fields["process"] and
        any(safe_fields[name] for name in ("exception_type", "signal", "termination_reason"))
    ) else (CrashParseStatus.PARTIAL if recognized_count or stack or modules else CrashParseStatus.UNKNOWN)
    metadata_seed = "|".join(
        str(value or "") for value in (
            safe_fields["process"], safe_fields["bundle_id"], safe_fields["timestamp"], pid,
        )
    )
    identity = CrashIdentity(safe_fields["incident_id"], digest, _digest_text(metadata_seed))
    summary_parts = [incident_type.value]
    if safe_fields["process"]:
        summary_parts.append(f"process={safe_fields['process']}")
    if safe_fields["exception_type"]:
        summary_parts.append(f"exception={safe_fields['exception_type']}")
    if safe_fields["signal"]:
        summary_parts.append(f"signal={safe_fields['signal']}")
    safe_summary = "; ".join(summary_parts)
    lower_text = text.lower()
    return CrashEvidence(
        identity=identity,
        incident_type=incident_type,
        parse_status=parse_status,
        source_ref=source_ref,
        report_digest=digest,
        safe_summary=safe_summary,
        timestamp=safe_fields["timestamp"],
        process_name=safe_fields["process"],
        bundle_id=safe_fields["bundle_id"],
        pid=pid,
        os_version=safe_fields["os_version"],
        device_model=safe_fields["device_model"],
        exception_type=safe_fields["exception_type"],
        signal=safe_fields["signal"],
        termination_reason=safe_fields["termination_reason"],
        watchdog_observed=incident_type is IncidentType.WATCHDOG,
        jetsam_observed=incident_type is IncidentType.JETSAM,
        stack_summary=stack,
        binary_modules=modules,
        environment_provenance=_safe_pairs(environment_provenance),
        observation_ref=observation_ref,
        artifact_ref=artifact_ref,
        acquisition_truncated=truncated,
    )


# ---------------------------------------------------------------------------
# Diagnostic correlation over existing references
# ---------------------------------------------------------------------------


class CorrelationReason(str, Enum):
    TIME_WINDOW_MATCH = "TIME_WINDOW_MATCH"
    PROCESS_ID_MATCH = "PROCESS_ID_MATCH"
    BUNDLE_ID_MATCH = "BUNDLE_ID_MATCH"
    TRACE_REFERENCE_MATCH = "TRACE_REFERENCE_MATCH"
    OBSERVATION_REFERENCE_MATCH = "OBSERVATION_REFERENCE_MATCH"
    ARTIFACT_REFERENCE_MATCH = "ARTIFACT_REFERENCE_MATCH"


@dataclass(frozen=True)
class DiagnosticCorrelation:
    correlation_id: str
    reasons: tuple[CorrelationReason, ...]
    task_id: str | None = None
    session_id: str | None = None
    trace_id: str | None = None
    bundle_id: str | None = None
    pid: int | None = None
    window_start_ms: int | None = None
    window_end_ms: int | None = None
    file_evidence: tuple[FileEvidence, ...] = ()
    log_evidence: tuple[LogWindowEvidence, ...] = ()
    crash_evidence: tuple[CrashEvidence, ...] = ()
    observation_refs: tuple[ObservationRef, ...] = ()
    artifact_refs: tuple[ArtifactRef, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "correlation_id", _identifier(self.correlation_id, "correlation_id"))
        reasons = tuple(CorrelationReason(reason) for reason in self.reasons)
        if not reasons or len(reasons) != len(set(reasons)):
            raise DiagnosticPolicyError("diagnostic correlation requires unique matching reasons")
        object.__setattr__(self, "reasons", reasons)
        if len(self.file_evidence) + len(self.log_evidence) + len(self.crash_evidence) == 0:
            raise DiagnosticPolicyError("diagnostic correlation requires typed evidence")
        for name in ("task_id", "session_id", "trace_id", "bundle_id"):
            object.__setattr__(self, name, _optional_identifier(getattr(self, name), name))
        if self.pid is not None:
            object.__setattr__(self, "pid", _nonnegative_int(self.pid, "correlation pid"))
        if (self.window_start_ms is None) != (self.window_end_ms is None):
            raise DiagnosticPolicyError("correlation time window requires both boundaries")
        if self.window_start_ms is not None:
            start = _nonnegative_int(self.window_start_ms, "correlation start")
            end = _nonnegative_int(self.window_end_ms, "correlation end")
            if end < start:
                raise DiagnosticPolicyError("correlation time window is reversed")
            if end - start > MAX_CORRELATION_WINDOW_MS:
                raise DiagnosticPolicyError("correlation time window exceeds the bounded maximum")
        supporting = {
            CorrelationReason.PROCESS_ID_MATCH: self.pid is not None,
            CorrelationReason.BUNDLE_ID_MATCH: self.bundle_id is not None,
            CorrelationReason.TRACE_REFERENCE_MATCH: self.trace_id is not None,
            CorrelationReason.TIME_WINDOW_MATCH: self.window_start_ms is not None,
            CorrelationReason.OBSERVATION_REFERENCE_MATCH: bool(self.observation_refs),
            CorrelationReason.ARTIFACT_REFERENCE_MATCH: bool(self.artifact_refs),
        }
        unevidenced = [reason.value for reason in reasons if not supporting[reason]]
        if unevidenced:
            raise DiagnosticPolicyError(
                "correlation reasons without supporting evidence: " + ",".join(unevidenced)
            )
        for field_name, expected_type in (
            ("file_evidence", FileEvidence),
            ("log_evidence", LogWindowEvidence),
            ("crash_evidence", CrashEvidence),
            ("observation_refs", ObservationRef),
            ("artifact_refs", ArtifactRef),
        ):
            values = tuple(getattr(self, field_name))
            if any(not isinstance(value, expected_type) for value in values):
                raise DiagnosticPolicyError(f"{field_name} contains an untyped value")
            object.__setattr__(self, field_name, values)
        if not (self.file_evidence or self.log_evidence or self.crash_evidence):
            raise DiagnosticPolicyError("diagnostic correlation requires typed evidence")
        scoped_refs = self.observation_refs + self.artifact_refs
        if self.task_id is not None and any(ref.task_id != self.task_id for ref in scoped_refs):
            raise DiagnosticPolicyError("diagnostic correlation task scope mismatch")

    def safe_diagnostic(self) -> dict[str, Any]:
        return {
            "correlation_id": self.correlation_id,
            "reasons": [reason.value for reason in self.reasons],
            "task_id": self.task_id,
            "session_id": self.session_id,
            "trace_id": self.trace_id,
            "bundle_id": self.bundle_id,
            "pid": self.pid,
            "window_start_ms": self.window_start_ms,
            "window_end_ms": self.window_end_ms,
            "file_evidence_count": len(self.file_evidence),
            "log_evidence_count": len(self.log_evidence),
            "crash_evidence_count": len(self.crash_evidence),
            "observation_refs": [ref.to_dict() for ref in self.observation_refs],
            "artifact_refs": [ref.to_dict() for ref in self.artifact_refs],
            "causation": False,
            "authorization": False,
            "root_cause": False,
            "high_correlation_auto_root_cause": False,
        }
