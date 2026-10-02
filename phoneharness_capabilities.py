#!/usr/bin/env python3
"""Typed clipboard / text / app / system capability foundation (S4-M4).

Host-only typed evidence, operation descriptors, and URL safety over the
existing raw primitives and frozen governance. This module cannot authorize,
bind, dispatch, verify, retry, or mutate anything: RiskController remains the
sole Action Authorization Authority, GovernedInputTextRuntime remains the text
entry owner, and the Stage-2 app-launch capability remains the app launch
owner. Nothing here persists content.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any
from urllib.parse import urlsplit

from phoneharness_contracts import ObservationRef


CLIPBOARD_VERSION_SCHEMA = "phoneharness.clipboard-version.v1"
CLIPBOARD_EVIDENCE_SCHEMA = "phoneharness.clipboard-evidence.v1"
URL_RESOURCE_SCHEMA = "phoneharness.resource-url.v1"
MAX_URL_LENGTH = 2048
MAX_CONTENT_VALUE_LENGTH = 4096
MAX_STATE_VALUE_LENGTH = 128

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")


class CapabilityPolicyError(RuntimeError):
    """A typed capability contract was malformed or violated its policy."""


def _identifier(value: Any, field_name: str) -> str:
    normalized = str(value or "").strip()
    if _IDENTIFIER.fullmatch(normalized) is None:
        raise CapabilityPolicyError(f"{field_name} must be an opaque bounded identifier")
    return normalized


def _timestamp(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CapabilityPolicyError(f"{field_name} must be a non-negative integer")
    return value


# --------------------------------------------------------------------------
# Clipboard: version, evidence, operations, stable read
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ClipboardVersion:
    """Pasteboard change evidence bound to one device session context.

    changeCount resets on reboot and is not globally unique; equality is only
    meaningful inside the same device session, and equality never proves
    identical content.
    """

    change_count: int
    device_session_id: str
    observed_at_ms: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.change_count, bool) or not isinstance(self.change_count, int) or self.change_count < 0:
            raise CapabilityPolicyError("clipboard change_count must be a non-negative integer")
        object.__setattr__(self, "device_session_id", _identifier(self.device_session_id, "device_session_id"))
        object.__setattr__(self, "observed_at_ms", _timestamp(self.observed_at_ms, "observed_at_ms"))

    def is_comparable_to(self, other: "ClipboardVersion") -> bool:
        return (
            isinstance(other, ClipboardVersion)
            and other.device_session_id == self.device_session_id
        )

    def matches(self, other: "ClipboardVersion") -> bool:
        return self.is_comparable_to(other) and other.change_count == self.change_count

    def audit(self) -> dict[str, Any]:
        return {
            "change_count": self.change_count,
            "global_identity": False,
            "authorization": False,
            "proves_same_content": False,
        }


class ClipboardSensitivity(str, Enum):
    METADATA_ONLY = "METADATA_ONLY"
    CONTENT_READ = "CONTENT_READ"
    REDACTED = "REDACTED"


@dataclass(frozen=True)
class ClipboardEvidence:
    """Typed clipboard observation; content value only after an explicit read."""

    version: ClipboardVersion | None
    sensitivity: ClipboardSensitivity
    has_string: bool | None = None
    has_url: bool | None = None
    has_image: bool | None = None
    content_present: bool | None = None
    content_value: str | None = None
    observation_ref: ObservationRef | None = None
    source: str = "clipboard.metadata"
    observed_at_ms: int = 0

    def __post_init__(self) -> None:
        if self.version is not None and not isinstance(self.version, ClipboardVersion):
            raise CapabilityPolicyError("clipboard evidence requires a typed ClipboardVersion")
        object.__setattr__(self, "sensitivity", ClipboardSensitivity(self.sensitivity))
        for name in ("has_string", "has_url", "has_image", "content_present"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, bool):
                raise CapabilityPolicyError(f"clipboard {name} must be boolean or unknown")
        if self.content_value is not None:
            if self.sensitivity is not ClipboardSensitivity.CONTENT_READ:
                raise CapabilityPolicyError("clipboard content value requires an explicit content read")
            if not str(self.content_value) or len(self.content_value) > MAX_CONTENT_VALUE_LENGTH:
                raise CapabilityPolicyError("clipboard content value must be bounded non-empty text")
        elif self.sensitivity is ClipboardSensitivity.CONTENT_READ:
            raise CapabilityPolicyError("content-read clipboard evidence must carry its content value")
        if self.observation_ref is not None and not isinstance(self.observation_ref, ObservationRef):
            raise CapabilityPolicyError("clipboard evidence provenance must use ObservationRef")
        object.__setattr__(self, "source", _identifier(self.source, "clipboard source"))
        object.__setattr__(self, "observed_at_ms", _timestamp(self.observed_at_ms, "observed_at_ms"))

    def redacted(self) -> "ClipboardEvidence":
        return ClipboardEvidence(
            self.version, ClipboardSensitivity.REDACTED, self.has_string, self.has_url,
            self.has_image, self.content_present, None, self.observation_ref,
            self.source, self.observed_at_ms,
        )

    def audit(self) -> dict[str, Any]:
        return {
            "sensitivity": self.sensitivity.value,
            "content_persisted": False,
            "authorization": False,
            "secret_entry_authorization": False,
        }


class ClipboardOperationKind(str, Enum):
    READ_METADATA = "READ_METADATA"
    READ_CONTENT = "READ_CONTENT"
    WRITE_TEXT = "WRITE_TEXT"

    @property
    def mutation_capable(self) -> bool:
        return self is ClipboardOperationKind.WRITE_TEXT


class ClipboardReadStatus(str, Enum):
    READY_CONTENT = "READY_CONTENT"
    UNSTABLE_VERSION = "UNSTABLE_VERSION"
    METADATA_ONLY = "METADATA_ONLY"


@dataclass(frozen=True)
class ClipboardReadOutcome:
    """Result of a stable clipboard read: version before -> read -> version after."""

    status: ClipboardReadStatus
    evidence: ClipboardEvidence

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", ClipboardReadStatus(self.status))
        if not isinstance(self.evidence, ClipboardEvidence):
            raise CapabilityPolicyError("clipboard read outcome requires typed evidence")
        if self.status is ClipboardReadStatus.READY_CONTENT and self.evidence.sensitivity is not ClipboardSensitivity.CONTENT_READ:
            raise CapabilityPolicyError("ready content outcome requires content-read evidence")
        if self.status is ClipboardReadStatus.UNSTABLE_VERSION and self.evidence.content_value is not None:
            raise CapabilityPolicyError("unstable version outcome cannot expose content")


class ClipboardStableRead:
    """Version-before / read / version-after contract; never a freshness runtime."""

    @staticmethod
    def evaluate(
        version_before: ClipboardVersion,
        version_after: ClipboardVersion,
        evidence: ClipboardEvidence,
    ) -> ClipboardReadOutcome:
        if not isinstance(version_before, ClipboardVersion) or not isinstance(version_after, ClipboardVersion):
            raise CapabilityPolicyError("stable read requires typed clipboard versions")
        if not isinstance(evidence, ClipboardEvidence):
            raise CapabilityPolicyError("stable read requires typed clipboard evidence")
        if not version_after.is_comparable_to(version_before) or not version_after.matches(version_before):
            return ClipboardReadOutcome(ClipboardReadStatus.UNSTABLE_VERSION, evidence.redacted())
        if evidence.sensitivity is ClipboardSensitivity.CONTENT_READ:
            return ClipboardReadOutcome(ClipboardReadStatus.READY_CONTENT, evidence)
        return ClipboardReadOutcome(ClipboardReadStatus.METADATA_ONLY, evidence)

    @staticmethod
    def requires_reobservation(planned: ClipboardVersion | None, current: ClipboardVersion | None) -> bool:
        """A planned version is never auto-current; any mismatch forces re-observation."""

        if planned is None or current is None:
            return True
        if not current.is_comparable_to(planned):
            return True
        return not current.matches(planned)


# --------------------------------------------------------------------------
# Text operations
# --------------------------------------------------------------------------


class TextOperationCategory(str, Enum):
    OBSERVE = "OBSERVE"
    TRANSFORM = "TRANSFORM"
    ENTER = "ENTER"


@dataclass(frozen=True)
class TextOperationDescriptor:
    """Typed text-operation classification; never an execution authority."""

    descriptor_id: str
    category: TextOperationCategory
    governed_owner: str
    mutation_capable: bool
    capability_hint: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "descriptor_id", _identifier(self.descriptor_id, "descriptor_id"))
        object.__setattr__(self, "category", TextOperationCategory(self.category))
        object.__setattr__(self, "governed_owner", _identifier(self.governed_owner, "governed_owner"))
        if not isinstance(self.mutation_capable, bool):
            raise CapabilityPolicyError("text mutation capability must be boolean")
        if self.mutation_capable is not (self.category is TextOperationCategory.ENTER):
            raise CapabilityPolicyError("only ENTER text operations are mutation capable")
        if self.category is TextOperationCategory.ENTER:
            if self.governed_owner != "GovernedInputTextRuntime":
                raise CapabilityPolicyError("device text entry remains owned by GovernedInputTextRuntime")
        if self.capability_hint is not None:
            object.__setattr__(self, "capability_hint", _identifier(self.capability_hint, "capability_hint"))

    def audit(self) -> dict[str, Any]:
        return {
            "category": self.category.value,
            "authorization": False,
            "dispatched_is_verified": False,
        }


# --------------------------------------------------------------------------
# App resources and typed URLs
# --------------------------------------------------------------------------


class UrlPolicyClass(str, Enum):
    PUBLIC_WEB = "PUBLIC_WEB"
    USER_VISIBLE_HANDOFF = "USER_VISIBLE_HANDOFF"
    CUSTOM_APP = "CUSTOM_APP"
    SETTINGS_RESOURCE = "SETTINGS_RESOURCE"


@dataclass(frozen=True)
class UrlPolicy:
    """Capability-specific allowed-scheme policy; never a universal allowlist."""

    policy_class: UrlPolicyClass
    allowed_schemes: frozenset

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_class", UrlPolicyClass(self.policy_class))
        schemes = frozenset(str(item).strip().lower() for item in self.allowed_schemes)
        if not schemes or any(not item or not re.fullmatch(r"[a-z][a-z0-9+.-]*", item) for item in schemes):
            raise CapabilityPolicyError("url policy schemes must be valid lowercase schemes")
        object.__setattr__(self, "allowed_schemes", schemes)

    def allows(self, scheme: str) -> bool:
        return scheme.lower() in self.allowed_schemes


class ResourceUrlError(CapabilityPolicyError):
    """A resource URL failed typed validation; reason codes are stable."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = _identifier(reason, "url rejection reason")


@dataclass(frozen=True)
class TypedResourceUrl:
    """A validated resource URL; the raw value stays ephemeral and non-authoritative."""

    raw: str
    scheme: str
    host: str
    path: str
    policy_class: UrlPolicyClass
    has_userinfo: bool = False
    has_query: bool = False
    has_fragment: bool = False
    redacted: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw", str(self.raw))
        object.__setattr__(self, "scheme", _identifier(self.scheme, "url scheme") if self.scheme else "")
        object.__setattr__(self, "policy_class", UrlPolicyClass(self.policy_class))
        if not self.redacted:
            raise CapabilityPolicyError("typed resource url requires its redacted diagnostic form")

    def audit(self) -> dict[str, Any]:
        return {
            "policy_class": self.policy_class.value,
            "url_is_authorization": False,
            "open_success_is_semantic_success": False,
            "raw_value_persisted": False,
        }


def validate_resource_url(raw: Any, policy: UrlPolicy) -> TypedResourceUrl:
    """Deterministic typed URL validation; rejects without ever executing."""

    if not isinstance(raw, str) or not raw.strip():
        raise ResourceUrlError("URL_EMPTY")
    # Cosmetic surrounding spaces are stripped deterministically; every other
    # control character (tab/newline/NUL/DEL) anywhere in the value is rejected.
    value = raw.strip(" ")
    if len(value) > MAX_URL_LENGTH:
        raise ResourceUrlError("URL_TOO_LONG")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise ResourceUrlError("URL_CONTROL_CHARACTER")
    parts = urlsplit(value)
    if not parts.scheme:
        raise ResourceUrlError("URL_NO_SCHEME")
    scheme = parts.scheme.lower()
    if not re.fullmatch(r"[a-z][a-z0-9+.-]*", scheme):
        raise ResourceUrlError("URL_UNPARSEABLE")
    if not policy.allows(scheme):
        raise ResourceUrlError("URL_DISALLOWED_SCHEME")
    normalized = value.replace(value[: len(parts.scheme)], scheme, 1)
    reparsed = urlsplit(normalized)
    if reparsed.scheme != scheme or (parts.netloc and not reparsed.netloc):
        raise ResourceUrlError("URL_UNPARSEABLE")
    if policy.policy_class in (UrlPolicyClass.PUBLIC_WEB, UrlPolicyClass.USER_VISIBLE_HANDOFF) and not reparsed.hostname:
        raise ResourceUrlError("URL_NO_HOST")
    redacted = f"{scheme}://"
    if reparsed.hostname:
        redacted += reparsed.hostname
    if reparsed.path:
        redacted += reparsed.path
    return TypedResourceUrl(
        raw,
        scheme,
        reparsed.hostname or "",
        reparsed.path or "",
        policy.policy_class,
        bool(parts.username or parts.password),
        bool(parts.query),
        bool(parts.fragment),
        redacted,
    )


@dataclass(frozen=True)
class AppResourceDescriptor:
    """Adapted app-resource reference over the existing destination taxonomy."""

    resource_id: str
    resource_kind: str
    destination_class: str
    bundle_id: str | None = None
    url: TypedResourceUrl | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "resource_id", _identifier(self.resource_id, "resource_id"))
        object.__setattr__(self, "resource_kind", _identifier(self.resource_kind, "resource_kind"))
        object.__setattr__(self, "destination_class", _identifier(self.destination_class, "destination_class"))
        if self.bundle_id is not None:
            object.__setattr__(self, "bundle_id", _identifier(self.bundle_id, "bundle_id"))
        if self.url is not None and not isinstance(self.url, TypedResourceUrl):
            raise CapabilityPolicyError("app resource url must be a typed resource url")
        if self.bundle_id is None and self.url is None:
            raise CapabilityPolicyError("app resource requires a bundle or a typed url")

    def audit(self) -> dict[str, Any]:
        return {
            "resource_kind": self.resource_kind,
            "second_app_launcher": False,
            "second_app_binding": False,
            "authorization": False,
        }


# --------------------------------------------------------------------------
# System state and operations
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SystemStateEvidence:
    """Typed observation of existing S4-M4-owned system state; readback-ready."""

    kind: str
    value: str
    observed_at_ms: int = 0
    observation_ref: ObservationRef | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _identifier(self.kind, "system state kind"))
        value = str(self.value or "").strip()
        if not value or len(value) > MAX_STATE_VALUE_LENGTH:
            raise CapabilityPolicyError("system state value must be bounded non-empty text")
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "observed_at_ms", _timestamp(self.observed_at_ms, "observed_at_ms"))
        if self.observation_ref is not None and not isinstance(self.observation_ref, ObservationRef):
            raise CapabilityPolicyError("system state provenance must use ObservationRef")

    def audit(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "authorization": False,
            "mutation": False,
        }


class SystemOperationKind(str, Enum):
    OBSERVE_ONLY = "OBSERVE_ONLY"
    LOW_RISK_MUTATION = "LOW_RISK_MUTATION"
    USER_VISIBLE_MUTATION = "USER_VISIBLE_MUTATION"
    PRIVILEGED_MUTATION = "PRIVILEGED_MUTATION"
    DESTRUCTIVE_OR_RECOVERY = "DESTRUCTIVE_OR_RECOVERY"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True)
class SystemOperationDescriptor:
    """Capability classification metadata; RiskController remains the only authority."""

    descriptor_id: str
    kind: SystemOperationKind
    readback_supported: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "descriptor_id", _identifier(self.descriptor_id, "descriptor_id"))
        object.__setattr__(self, "kind", SystemOperationKind(self.kind))
        if not isinstance(self.readback_supported, bool):
            raise CapabilityPolicyError("readback support must be boolean")

    def audit(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "classification_only": True,
            "authorization": False,
            "independent_execution_authority": False,
        }


def capability_definition_candidates() -> tuple[dict[str, Any], ...]:
    """Declarative candidates for the EXISTING capability catalog; no new registry.

    Private app/system methods carry their compatibility requirement explicitly:
    symbol presence is not target-device reliability proof.
    """

    return (
        {
            "capability_id": "capability.clipboard.read_metadata.v1",
            "kind": "mcp",
            "risk_class": "read_only",
            "surface": "get_clipboard_metadata",
            "compatibility_gate": None,
        },
        {
            "capability_id": "capability.clipboard.read_content.v1",
            "kind": "mcp",
            "risk_class": "read_only",
            "surface": "get_clipboard",
            "compatibility_gate": None,
        },
        {
            "capability_id": "capability.clipboard.write_text.v1",
            "kind": "mcp",
            "risk_class": "interaction",
            "surface": "set_clipboard",
            "compatibility_gate": None,
        },
        {
            "capability_id": "capability.text_input.v1",
            "kind": "governed_runtime",
            "risk_class": "interaction",
            "surface": "GovernedInputTextRuntime",
            "compatibility_gate": None,
        },
        {
            "capability_id": "capability.app.launch.v1",
            "kind": "governed_runtime",
            "risk_class": "interaction",
            "surface": "INSTALLED_APP_LAUNCH_CAPABILITY_DEFINITION",
            "compatibility_gate": "BOOTSTRAP_2_2_1_COMPAT_GATE",
        },
        {
            "capability_id": "capability.app.open_resource.v1",
            "kind": "mcp",
            "risk_class": "interaction",
            "surface": "open_url",
            "compatibility_gate": "BOOTSTRAP_2_2_1_COMPAT_GATE",
        },
        {
            "capability_id": "capability.system.brightness.v1",
            "kind": "mcp",
            "risk_class": "interaction",
            "surface": "set_brightness/get_brightness",
            "compatibility_gate": None,
        },
        {
            "capability_id": "capability.system.volume.v1",
            "kind": "mcp",
            "risk_class": "interaction",
            "surface": "set_volume/get_volume",
            "compatibility_gate": None,
        },
        {
            "capability_id": "capability.system.device_info.v1",
            "kind": "mcp",
            "risk_class": "read_only",
            "surface": "get_device_info",
            "compatibility_gate": None,
        },
    )


__all__ = [
    "AppResourceDescriptor",
    "ClipboardEvidence",
    "ClipboardOperationKind",
    "ClipboardReadOutcome",
    "ClipboardReadStatus",
    "ClipboardSensitivity",
    "ClipboardStableRead",
    "ClipboardVersion",
    "CapabilityPolicyError",
    "ResourceUrlError",
    "SystemOperationDescriptor",
    "SystemOperationKind",
    "SystemStateEvidence",
    "TextOperationCategory",
    "TextOperationDescriptor",
    "TypedResourceUrl",
    "UrlPolicy",
    "UrlPolicyClass",
    "capability_definition_candidates",
    "validate_resource_url",
]
