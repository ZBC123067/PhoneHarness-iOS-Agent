#!/usr/bin/env python3
"""Typed, non-authoritative Process / Service foundation for S4-M6-A1.

This Host-only module defines bounded evidence and operation descriptors. It
does not enumerate processes, inspect arbitrary PIDs, execute mutations,
authorize actions, create providers, or introduce a process/service monitor,
database, shell, freshness runtime, world model, memory system, or AI runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any

from phoneharness_contracts import ObservationFreshness, ObservationRef


PROCESS_IDENTITY_SCHEMA = "phoneharness.process-identity.v1"
PROCESS_INSTANCE_SCHEMA = "phoneharness.process-instance.v1"
PROCESS_SNAPSHOT_SCHEMA = "phoneharness.process-snapshot.v1"
SERVICE_IDENTITY_SCHEMA = "phoneharness.service-identity.v1"
SERVICE_STATE_SCHEMA = "phoneharness.service-state.v1"

MAX_PROCESS_NAME = 128
MAX_STATE_VALUE = 64
MAX_CPU_PERCENT = 100.0

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

AI_LEARNING_HOOK_RULE = (
    "S4-M6 evidence may be consumed by shared Stage-5 learning, but one "
    "observation cannot directly create permanent causal knowledge."
)
AI_CAPABILITY_SURFACE_NOTE = (
    "Capability metadata is discovery-only; availability is not authorization."
)


class ProcessServicePolicyError(ValueError):
    """A process/service contract is malformed or unsafe."""


def _identifier(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ProcessServicePolicyError(f"{field_name} must be a string identifier")
    normalized = value.strip()
    if _IDENTIFIER.fullmatch(normalized) is None:
        raise ProcessServicePolicyError(
            f"{field_name} must be an opaque bounded identifier"
        )
    return normalized


def _optional_identifier(value: Any, field_name: str) -> str | None:
    return None if value is None else _identifier(value, field_name)


def _bounded_text(value: Any, field_name: str, maximum: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProcessServicePolicyError(f"{field_name} must be bounded text")
    if _CONTROL.search(value):
        raise ProcessServicePolicyError(f"{field_name} must be bounded safe text")
    normalized = " ".join(value.split())
    if not normalized:
        return None
    if len(normalized) > maximum:
        raise ProcessServicePolicyError(f"{field_name} must be bounded safe text")
    return normalized


def _positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ProcessServicePolicyError(f"{field_name} must be a positive integer")
    return value


def _nonnegative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProcessServicePolicyError(
            f"{field_name} must be a non-negative integer"
        )
    return value


def _optional_digest(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProcessServicePolicyError(f"{field_name} must be a sha256 digest")
    normalized = value.strip().lower()
    if _DIGEST.fullmatch(normalized) is None:
        raise ProcessServicePolicyError(f"{field_name} must be a sha256 digest")
    return normalized


def _same_observation_scope(left: ObservationRef, right: ObservationRef) -> bool:
    """Compare provenance scope without requiring the same observation event."""

    return (
        left.producer == right.producer
        and left.task_id == right.task_id
        and left.session_id == right.session_id
    )


def _fresh_observation(
    observation_ref: ObservationRef | None,
    *,
    observed_at_ms: int,
    now_ms: int,
    max_age_ms: int,
) -> bool:
    if observation_ref is None:
        return False
    if now_ms < 0 or max_age_ms <= 0 or observed_at_ms < 0:
        raise ProcessServicePolicyError("freshness clock inputs are invalid")
    if observation_ref.freshness is not ObservationFreshness.FRESH:
        return False
    if now_ms < observed_at_ms or now_ms - observed_at_ms > max_age_ms:
        return False
    if (
        observation_ref.observed_at_ms is not None
        and observation_ref.observed_at_ms != observed_at_ms
    ):
        return False
    return True


class InstanceCertainty(str, Enum):
    STRONG = "STRONG"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


class InstanceIdentityStrength(str, Enum):
    NONE = "NONE"
    PID_ONLY = "PID_ONLY"
    PARTIAL = "PARTIAL"
    STRONG_PROVIDER_EVIDENCE = "STRONG_PROVIDER_EVIDENCE"


class ProcessInstanceDiscriminatorKind(str, Enum):
    START_TIME = "START_TIME"
    PID_VERSION = "PID_VERSION"
    UNIQUE_ID = "UNIQUE_ID"
    AUDIT_TOKEN_DERIVED_IDENTITY = "AUDIT_TOKEN_DERIVED_IDENTITY"
    PROVIDER_GENERATION_MARKER = "PROVIDER_GENERATION_MARKER"


@dataclass(frozen=True)
class ProcessInstanceDiscriminator:
    """Provider-abstract evidence distinguishing one process instance."""

    kind: ProcessInstanceDiscriminatorKind
    evidence_ref: str
    provider: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", ProcessInstanceDiscriminatorKind(self.kind))
        object.__setattr__(
            self,
            "evidence_ref",
            _identifier(self.evidence_ref, "instance discriminator evidence ref"),
        )
        object.__setattr__(
            self,
            "provider",
            _identifier(self.provider, "instance discriminator provider"),
        )


@dataclass(frozen=True)
class ProcessIdentity:
    """Logical process identity evidence, distinct from any process instance."""

    process_name: str | None = None
    bundle_id: str | None = None
    executable_digest: str | None = None
    provider: str = "process.provider"
    schema_version: str = PROCESS_IDENTITY_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != PROCESS_IDENTITY_SCHEMA:
            raise ProcessServicePolicyError("unsupported ProcessIdentity schema")
        object.__setattr__(
            self,
            "process_name",
            _bounded_text(self.process_name, "process_name", MAX_PROCESS_NAME),
        )
        if self.process_name and ("/" in self.process_name or "\\" in self.process_name):
            raise ProcessServicePolicyError("process_name cannot be a filesystem path")
        object.__setattr__(self, "bundle_id", _optional_identifier(self.bundle_id, "bundle_id"))
        object.__setattr__(
            self,
            "executable_digest",
            _optional_digest(self.executable_digest, "executable_digest"),
        )
        object.__setattr__(self, "provider", _identifier(self.provider, "process provider"))
        if not (self.process_name or self.bundle_id or self.executable_digest):
            raise ProcessServicePolicyError(
                "process identity requires at least one logical identity field"
            )

    def same_logical_identity_as(self, other: "ProcessIdentity") -> bool:
        return isinstance(other, ProcessIdentity) and self == other

    def safe_diagnostic(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "provider": self.provider,
            "process_name_present": self.process_name is not None,
            "bundle_id_present": self.bundle_id is not None,
            "executable_digest_present": self.executable_digest is not None,
            "pid_is_identity": False,
            "authorization": False,
        }


@dataclass(frozen=True)
class ProcessInstanceEvidence:
    """Evidence about a particular running process instance.

    STRONG requires a positive PID, an opaque generation/start marker, and an
    S4-M0 observation reference. Anything less remains PARTIAL rather than
    fabricating stable instance identity.
    """

    identity: ProcessIdentity
    pid: int | None = None
    generation_marker: str | None = None
    observation_ref: ObservationRef | None = None
    provider: str = "process.provider"
    observed_at_ms: int = 0
    instance_discriminators: tuple[ProcessInstanceDiscriminator, ...] = ()
    schema_version: str = PROCESS_INSTANCE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != PROCESS_INSTANCE_SCHEMA:
            raise ProcessServicePolicyError("unsupported ProcessInstanceEvidence schema")
        if not isinstance(self.identity, ProcessIdentity):
            raise ProcessServicePolicyError("process instance requires ProcessIdentity")
        if self.pid is not None:
            object.__setattr__(self, "pid", _positive_int(self.pid, "process pid"))
        object.__setattr__(
            self,
            "generation_marker",
            _optional_identifier(self.generation_marker, "generation marker"),
        )
        if self.observation_ref is not None and not isinstance(
            self.observation_ref, ObservationRef
        ):
            raise ProcessServicePolicyError("process provenance must use ObservationRef")
        object.__setattr__(
            self, "provider", _identifier(self.provider, "process instance provider")
        )
        object.__setattr__(
            self,
            "observed_at_ms",
            _nonnegative_int(self.observed_at_ms, "observed_at_ms"),
        )
        discriminators = tuple(self.instance_discriminators)
        if len(discriminators) > len(ProcessInstanceDiscriminatorKind):
            raise ProcessServicePolicyError("too many process instance discriminators")
        if any(
            not isinstance(value, ProcessInstanceDiscriminator)
            for value in discriminators
        ):
            raise ProcessServicePolicyError(
                "instance discriminators must use typed provider evidence"
            )
        kinds = [value.kind for value in discriminators]
        if len(kinds) != len(set(kinds)):
            raise ProcessServicePolicyError(
                "instance discriminator kinds must be unique"
            )
        if (
            self.generation_marker is not None
            and ProcessInstanceDiscriminatorKind.PROVIDER_GENERATION_MARKER in kinds
        ):
            raise ProcessServicePolicyError(
                "legacy generation marker duplicates typed provider evidence"
            )
        object.__setattr__(self, "instance_discriminators", discriminators)
        if self.observation_ref is not None:
            if self.observation_ref.producer != self.provider:
                raise ProcessServicePolicyError(
                    "process provider and observation provenance conflict"
                )
            if (
                self.observation_ref.observed_at_ms is not None
                and self.observation_ref.observed_at_ms != self.observed_at_ms
            ):
                raise ProcessServicePolicyError(
                    "process timestamp and observation provenance conflict"
                )

    @property
    def identity_strength(self) -> InstanceIdentityStrength:
        has_discriminator = bool(
            self.generation_marker or self.instance_discriminators
        )
        if self.pid is None and not has_discriminator and self.observation_ref is None:
            return InstanceIdentityStrength.NONE
        if self.pid is not None and not has_discriminator:
            return InstanceIdentityStrength.PID_ONLY
        if self.pid is not None and has_discriminator and self.observation_ref is not None:
            return InstanceIdentityStrength.STRONG_PROVIDER_EVIDENCE
        return InstanceIdentityStrength.PARTIAL

    @property
    def certainty(self) -> InstanceCertainty:
        if self.identity_strength is InstanceIdentityStrength.STRONG_PROVIDER_EVIDENCE:
            return InstanceCertainty.STRONG
        if self.identity_strength is InstanceIdentityStrength.NONE:
            return InstanceCertainty.UNKNOWN
        return InstanceCertainty.PARTIAL

    @property
    def discriminator_fingerprint(self) -> tuple[tuple[str, str, str], ...]:
        values = [
            (value.kind.value, value.evidence_ref, value.provider)
            for value in self.instance_discriminators
        ]
        if self.generation_marker is not None:
            values.append(
                (
                    ProcessInstanceDiscriminatorKind.PROVIDER_GENERATION_MARKER.value,
                    self.generation_marker,
                    self.provider,
                )
            )
        return tuple(sorted(values))

    def same_instance_as(self, other: "ProcessInstanceEvidence") -> bool:
        if not isinstance(other, ProcessInstanceEvidence):
            return False
        if self.certainty is not InstanceCertainty.STRONG:
            return False
        if other.certainty is not InstanceCertainty.STRONG:
            return False
        return (
            self.pid == other.pid
            and self.discriminator_fingerprint == other.discriminator_fingerprint
            and self.provider == other.provider
            and self.identity.same_logical_identity_as(other.identity)
            and _same_observation_scope(self.observation_ref, other.observation_ref)
        )

    def safe_diagnostic(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "certainty": self.certainty.value,
            "identity_strength": self.identity_strength.value,
            "pid_present": self.pid is not None,
            "generation_marker_present": self.generation_marker is not None,
            "instance_discriminator_count": len(self.discriminator_fingerprint),
            "instance_discriminator_kinds": [
                value[0] for value in self.discriminator_fingerprint
            ],
            "observation_ref_present": self.observation_ref is not None,
            "provider": self.provider,
            "PID_MATCH_ALONE_PROVES_SAME_PROCESS_INSTANCE": False,
            "STRONG_IDENTITY_IS_AUTHORIZATION": False,
            "authorization": False,
        }


class SnapshotCompleteness(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ProcessSnapshot:
    """One bounded process observation, never a continuous telemetry stream."""

    instance: ProcessInstanceEvidence
    observed_at_ms: int
    observation_ref: ObservationRef
    state: str | None = None
    cpu_observation: float | None = None
    memory_observation_bytes: int | None = None
    thread_count: int | None = None
    wakeup_observation: int | None = None
    foreground_relation: str | None = None
    schema_version: str = PROCESS_SNAPSHOT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != PROCESS_SNAPSHOT_SCHEMA:
            raise ProcessServicePolicyError("unsupported ProcessSnapshot schema")
        if not isinstance(self.instance, ProcessInstanceEvidence):
            raise ProcessServicePolicyError("process snapshot requires instance evidence")
        if not isinstance(self.observation_ref, ObservationRef):
            raise ProcessServicePolicyError("process snapshot requires ObservationRef")
        object.__setattr__(
            self,
            "observed_at_ms",
            _nonnegative_int(self.observed_at_ms, "observed_at_ms"),
        )
        if self.instance.observation_ref != self.observation_ref:
            raise ProcessServicePolicyError(
                "process snapshot and instance provenance must be identical"
            )
        if (
            self.observation_ref.observed_at_ms is not None
            and self.observation_ref.observed_at_ms != self.observed_at_ms
        ):
            raise ProcessServicePolicyError(
                "process snapshot timestamp and provenance conflict"
            )
        object.__setattr__(
            self, "state", _bounded_text(self.state, "process state", MAX_STATE_VALUE)
        )
        if self.cpu_observation is not None:
            cpu = self.cpu_observation
            if (
                isinstance(cpu, bool)
                or not isinstance(cpu, (int, float))
                or not 0.0 <= float(cpu) <= MAX_CPU_PERCENT
            ):
                raise ProcessServicePolicyError("cpu observation must be within 0..100")
            object.__setattr__(self, "cpu_observation", float(cpu))
        for field_name in (
            "memory_observation_bytes",
            "thread_count",
            "wakeup_observation",
        ):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, _nonnegative_int(value, field_name))
        object.__setattr__(
            self,
            "foreground_relation",
            _bounded_text(
                self.foreground_relation,
                "foreground relation",
                MAX_STATE_VALUE,
            ),
        )

    @property
    def observed_fields(self) -> tuple[str, ...]:
        fields: list[str] = []
        for field_name, public_name in (
            ("state", "state"),
            ("cpu_observation", "cpu"),
            ("memory_observation_bytes", "memory"),
            ("thread_count", "threads"),
            ("wakeup_observation", "wakeups"),
            ("foreground_relation", "foreground_relation"),
        ):
            if getattr(self, field_name) is not None:
                fields.append(public_name)
        return tuple(fields)

    @property
    def completeness(self) -> SnapshotCompleteness:
        count = len(self.observed_fields)
        if count == 0:
            return SnapshotCompleteness.UNKNOWN
        if count == 6:
            return SnapshotCompleteness.COMPLETE
        return SnapshotCompleteness.PARTIAL

    def semantic_facts(self) -> dict[str, Any]:
        return {
            "process_instance_observed": True,
            "identity_certainty": self.instance.certainty.value,
            "snapshot_completeness": self.completeness.value,
            "observed_fields": self.observed_fields,
            "resource_observation_present": bool(
                {"cpu", "memory", "wakeups"} & set(self.observed_fields)
            ),
            "requires_fresh_revalidation_before_mutation": True,
            "is_root_cause": False,
            "authorization": False,
        }

    def safe_diagnostic(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "instance": self.instance.safe_diagnostic(),
            "observed_fields": list(self.observed_fields),
            "completeness": self.completeness.value,
            "continuous_monitor": False,
            "missing_value_means_zero": False,
            "authorization": False,
        }


class ProcessOperationKind(str, Enum):
    OBSERVE = "OBSERVE"
    TERMINATE = "TERMINATE"
    SIGNAL = "SIGNAL"
    SUSPEND = "SUSPEND"
    RESUME = "RESUME"

    @property
    def mutation_capable(self) -> bool:
        return self is not ProcessOperationKind.OBSERVE

    @property
    def destructive(self) -> bool:
        return self is ProcessOperationKind.TERMINATE


class ProcessTargetClass(str, Enum):
    CONTROL_PLANE_SELF = "CONTROL_PLANE_SELF"
    SYSTEM_CRITICAL = "SYSTEM_CRITICAL"
    SECURITY_SENSITIVE = "SECURITY_SENSITIVE"
    UNKNOWN_TARGET = "UNKNOWN_TARGET"
    NORMAL_USER_PROCESS = "NORMAL_USER_PROCESS"


class ClassificationBasisKind(str, Enum):
    CONTROL_PLANE_REGISTRY = "CONTROL_PLANE_REGISTRY"
    SYSTEM_POLICY = "SYSTEM_POLICY"
    PROVIDER_ATTESTED = "PROVIDER_ATTESTED"


@dataclass(frozen=True)
class ProcessClassificationEvidence:
    """Typed evidence for a target class; arbitrary prose is not accepted."""

    subject_identity: ProcessIdentity
    basis_kind: ClassificationBasisKind
    evidence_ref: str
    provider: str

    def __post_init__(self) -> None:
        if not isinstance(self.subject_identity, ProcessIdentity):
            raise ProcessServicePolicyError(
                "classification evidence requires a typed subject identity"
            )
        object.__setattr__(self, "basis_kind", ClassificationBasisKind(self.basis_kind))
        object.__setattr__(
            self, "evidence_ref", _identifier(self.evidence_ref, "classification evidence ref")
        )
        object.__setattr__(
            self, "provider", _identifier(self.provider, "classification provider")
        )


@dataclass(frozen=True)
class ProcessTargetProtection:
    target: ProcessInstanceEvidence
    target_class: ProcessTargetClass
    classification_evidence: ProcessClassificationEvidence | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.target, ProcessInstanceEvidence):
            raise ProcessServicePolicyError("target protection requires process evidence")
        object.__setattr__(self, "target_class", ProcessTargetClass(self.target_class))
        if self.target_class is ProcessTargetClass.UNKNOWN_TARGET:
            if self.classification_evidence is not None:
                raise ProcessServicePolicyError("unknown targets cannot claim class evidence")
            return
        if not isinstance(self.classification_evidence, ProcessClassificationEvidence):
            raise ProcessServicePolicyError("known target class requires typed evidence")
        if not self.classification_evidence.subject_identity.same_logical_identity_as(
            self.target.identity
        ):
            raise ProcessServicePolicyError(
                "classification evidence is bound to a different process identity"
            )
        allowed_basis = {
            ProcessTargetClass.CONTROL_PLANE_SELF: {
                ClassificationBasisKind.CONTROL_PLANE_REGISTRY
            },
            ProcessTargetClass.SYSTEM_CRITICAL: {
                ClassificationBasisKind.SYSTEM_POLICY,
                ClassificationBasisKind.PROVIDER_ATTESTED,
            },
            ProcessTargetClass.SECURITY_SENSITIVE: {
                ClassificationBasisKind.SYSTEM_POLICY,
                ClassificationBasisKind.PROVIDER_ATTESTED,
            },
            ProcessTargetClass.NORMAL_USER_PROCESS: {
                ClassificationBasisKind.PROVIDER_ATTESTED
            },
        }
        if self.classification_evidence.basis_kind not in allowed_basis[self.target_class]:
            raise ProcessServicePolicyError("classification evidence cannot support target class")

    @property
    def mutation_candidate_allowed(self) -> bool:
        return self.target_class is ProcessTargetClass.NORMAL_USER_PROCESS

    @property
    def mutation_requires_user_confirmation(self) -> bool:
        return self.target_class is not ProcessTargetClass.NORMAL_USER_PROCESS

    @property
    def auto_mutatable(self) -> bool:
        return False

    def safe_diagnostic(self) -> dict[str, Any]:
        return {
            "target_class": self.target_class.value,
            "classification_evidence_present": self.classification_evidence is not None,
            "mutation_candidate_allowed": self.mutation_candidate_allowed,
            "auto_mutatable": False,
            "unknown_target_auto_safe": False,
            "authorization": False,
        }


def classify_process_target(
    instance: ProcessInstanceEvidence,
    *,
    claimed_class: ProcessTargetClass | None = None,
    evidence: ProcessClassificationEvidence | None = None,
) -> ProcessTargetProtection:
    if not isinstance(instance, ProcessInstanceEvidence):
        raise ProcessServicePolicyError("classification requires process evidence")
    if claimed_class is None or evidence is None:
        return ProcessTargetProtection(instance, ProcessTargetClass.UNKNOWN_TARGET)
    return ProcessTargetProtection(instance, claimed_class, evidence)


@dataclass(frozen=True)
class ProcessOperationDescriptor:
    """Non-executable process operation metadata."""

    descriptor_id: str
    kind: ProcessOperationKind
    target: ProcessInstanceEvidence
    requires_privilege: str | None = None
    readback_supported: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "descriptor_id", _identifier(self.descriptor_id, "descriptor_id"))
        object.__setattr__(self, "kind", ProcessOperationKind(self.kind))
        if not isinstance(self.target, ProcessInstanceEvidence):
            raise ProcessServicePolicyError("process operation requires instance evidence")
        if self.requires_privilege is not None:
            privilege = str(self.requires_privilege).strip().upper()
            if privilege not in {"NONE", "MOBILE", "ROOT", "PRIVATE_ENTITLEMENT"}:
                raise ProcessServicePolicyError("unsupported privilege requirement")
            object.__setattr__(self, "requires_privilege", privilege)
        if not isinstance(self.readback_supported, bool):
            raise ProcessServicePolicyError("readback support must be boolean")

    @property
    def prepared_operation_auto_executable(self) -> bool:
        return False

    def safe_diagnostic(self) -> dict[str, Any]:
        return {
            "descriptor_id": self.descriptor_id,
            "kind": self.kind.value,
            "mutation_capable": self.kind.mutation_capable,
            "prepared_operation_auto_executable": False,
            "provider_ack_is_semantic_success": False,
            "privilege_is_authorization": False,
            "authorization": False,
        }


def revalidate_process_target(
    prepared: ProcessInstanceEvidence,
    fresh_snapshot: ProcessSnapshot,
    *,
    now_ms: int,
    max_age_ms: int,
) -> bool:
    """Require the same strong instance and current S4-M0 freshness evidence."""

    if not isinstance(prepared, ProcessInstanceEvidence) or not isinstance(
        fresh_snapshot, ProcessSnapshot
    ):
        raise ProcessServicePolicyError("process revalidation requires typed evidence")
    return _fresh_observation(
        fresh_snapshot.observation_ref,
        observed_at_ms=fresh_snapshot.observed_at_ms,
        now_ms=now_ms,
        max_age_ms=max_age_ms,
    ) and prepared.same_instance_as(fresh_snapshot.instance)


@dataclass(frozen=True)
class ServiceIdentity:
    """Logical service definition identity, distinct from a current process."""

    label: str
    provider: str = "service.provider"
    definition_digest: str | None = None
    schema_version: str = SERVICE_IDENTITY_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != SERVICE_IDENTITY_SCHEMA:
            raise ProcessServicePolicyError("unsupported ServiceIdentity schema")
        object.__setattr__(self, "label", _identifier(self.label, "service label"))
        object.__setattr__(self, "provider", _identifier(self.provider, "service provider"))
        object.__setattr__(
            self,
            "definition_digest",
            _optional_digest(self.definition_digest, "service definition digest"),
        )

    def same_service_as(self, other: "ServiceIdentity") -> bool:
        return isinstance(other, ServiceIdentity) and self == other

    def safe_diagnostic(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "label": self.label,
            "provider": self.provider,
            "definition_digest_present": self.definition_digest is not None,
            "label_is_process_instance": False,
            "label_is_pid": False,
            "authorization": False,
        }


class ServiceStateKind(str, Enum):
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    UNKNOWN = "UNKNOWN"
    TRANSITIONING = "TRANSITIONING"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class ServiceStateEvidence:
    """One typed service-state observation with explicit S4-M0 provenance."""

    identity: ServiceIdentity
    state: ServiceStateKind
    observed_at_ms: int
    observation_ref: ObservationRef
    instance: ProcessInstanceEvidence | None = None
    schema_version: str = SERVICE_STATE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != SERVICE_STATE_SCHEMA:
            raise ProcessServicePolicyError("unsupported ServiceStateEvidence schema")
        if not isinstance(self.identity, ServiceIdentity):
            raise ProcessServicePolicyError("service state requires ServiceIdentity")
        object.__setattr__(self, "state", ServiceStateKind(self.state))
        object.__setattr__(
            self,
            "observed_at_ms",
            _nonnegative_int(self.observed_at_ms, "observed_at_ms"),
        )
        if not isinstance(self.observation_ref, ObservationRef):
            raise ProcessServicePolicyError("service state requires ObservationRef")
        if self.instance is not None and not isinstance(self.instance, ProcessInstanceEvidence):
            raise ProcessServicePolicyError("service instance must be process evidence")
        if self.state is ServiceStateKind.RUNNING and self.instance is None:
            raise ProcessServicePolicyError(
                "RUNNING service state requires current process instance evidence"
            )
        if (
            self.observation_ref.observed_at_ms is not None
            and self.observation_ref.observed_at_ms != self.observed_at_ms
        ):
            raise ProcessServicePolicyError(
                "service timestamp and observation provenance conflict"
            )
        if self.instance is not None and self.instance.observation_ref != self.observation_ref:
            raise ProcessServicePolicyError(
                "service state and process instance provenance must be identical"
            )

    def is_fresh(self, *, now_ms: int, max_age_ms: int) -> bool:
        return _fresh_observation(
            self.observation_ref,
            observed_at_ms=self.observed_at_ms,
            now_ms=now_ms,
            max_age_ms=max_age_ms,
        )

    def semantic_facts(self) -> dict[str, Any]:
        return {
            "service_identity_observed": True,
            "state": self.state.value,
            "current_instance_present": self.instance is not None,
            "unknown_is_stopped": False,
            "requires_fresh_revalidation_before_mutation": True,
            "authorization": False,
        }

    def safe_diagnostic(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "identity": self.identity.safe_diagnostic(),
            "state": self.state.value,
            "instance_present": self.instance is not None,
            "unknown_forced_to_stopped": False,
            "authorization": False,
        }


class ServiceOperationKind(str, Enum):
    OBSERVE = "OBSERVE"
    START = "START"
    STOP = "STOP"
    RESTART = "RESTART"

    @property
    def mutation_capable(self) -> bool:
        return self is not ServiceOperationKind.OBSERVE


@dataclass(frozen=True)
class ServiceOperationDescriptor:
    """Non-executable service operation metadata."""

    descriptor_id: str
    kind: ServiceOperationKind
    identity: ServiceIdentity
    requires_privilege: str | None = None
    readback_supported: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "descriptor_id", _identifier(self.descriptor_id, "descriptor_id"))
        object.__setattr__(self, "kind", ServiceOperationKind(self.kind))
        if not isinstance(self.identity, ServiceIdentity):
            raise ProcessServicePolicyError("service operation requires ServiceIdentity")
        if self.requires_privilege is not None:
            privilege = str(self.requires_privilege).strip().upper()
            if privilege not in {"NONE", "MOBILE", "ROOT", "PRIVATE_ENTITLEMENT"}:
                raise ProcessServicePolicyError("unsupported privilege requirement")
            object.__setattr__(self, "requires_privilege", privilege)
        if not isinstance(self.readback_supported, bool):
            raise ProcessServicePolicyError("readback support must be boolean")

    @property
    def prepared_operation_auto_executable(self) -> bool:
        return False

    def safe_diagnostic(self) -> dict[str, Any]:
        return {
            "descriptor_id": self.descriptor_id,
            "kind": self.kind.value,
            "mutation_capable": self.kind.mutation_capable,
            "prepared_operation_auto_executable": False,
            "provider_ack_is_semantic_success": False,
            "privilege_is_authorization": False,
            "authorization": False,
        }


def revalidate_service_target(
    prepared: ServiceStateEvidence,
    fresh_state: ServiceStateEvidence,
    *,
    now_ms: int,
    max_age_ms: int,
) -> bool:
    """Require the same logical service and fresh current state evidence."""

    if not isinstance(prepared, ServiceStateEvidence) or not isinstance(
        fresh_state, ServiceStateEvidence
    ):
        raise ProcessServicePolicyError("service revalidation requires typed evidence")
    if not fresh_state.is_fresh(now_ms=now_ms, max_age_ms=max_age_ms):
        return False
    if not prepared.identity.same_service_as(fresh_state.identity):
        return False
    if not _same_observation_scope(
        prepared.observation_ref, fresh_state.observation_ref
    ):
        return False
    if prepared.state is not fresh_state.state:
        return False
    if (prepared.instance is None) != (fresh_state.instance is None):
        return False
    if prepared.instance is not None:
        return prepared.instance.same_instance_as(fresh_state.instance)
    return True


def capability_definition_candidates() -> tuple[dict[str, Any], ...]:
    """Discovery-only candidates for the existing capability fabric."""

    process_risks = {
        ProcessOperationKind.OBSERVE: "read_only",
        ProcessOperationKind.TERMINATE: "destructive",
        ProcessOperationKind.SIGNAL: "user_visible_mutation",
        ProcessOperationKind.SUSPEND: "user_visible_mutation",
        ProcessOperationKind.RESUME: "user_visible_mutation",
    }
    service_risks = {
        ServiceOperationKind.OBSERVE: "read_only",
        ServiceOperationKind.START: "user_visible_mutation",
        ServiceOperationKind.STOP: "destructive",
        ServiceOperationKind.RESTART: "user_visible_mutation",
    }
    candidates: list[dict[str, Any]] = []
    for kind, risk_class in process_risks.items():
        candidates.append(
            {
                "capability_id": f"capability.process.{kind.value.lower()}.v1",
                "operation": kind.value,
                "target": "process_instance",
                "risk_class": risk_class,
                "descriptor_only": True,
                "compatibility_gate": None
                if kind is ProcessOperationKind.OBSERVE
                else "BOOTSTRAP_2_2_1_COMPAT_GATE",
            }
        )
    for kind, risk_class in service_risks.items():
        candidates.append(
            {
                "capability_id": f"capability.service.{kind.value.lower()}.v1",
                "operation": kind.value,
                "target": "service_identity",
                "risk_class": risk_class,
                "descriptor_only": True,
                "compatibility_gate": None
                if kind is ServiceOperationKind.OBSERVE
                else "BOOTSTRAP_2_2_1_COMPAT_GATE",
            }
        )
    return tuple(candidates)


def ai_native_contract() -> dict[str, Any]:
    """P21/P23 composition surface; descriptive and non-authoritative."""

    return {
        "AI_OBSERVATION_SURFACE": "typed process/service evidence",
        "AI_SEMANTIC_SURFACE": "bounded semantic facts",
        "AI_CAPABILITY_SURFACE": AI_CAPABILITY_SURFACE_NOTE,
        "AI_CONTEXT_INTEGRATION": "shared semantic context consumer/contributor",
        "AI_WORLD_MODEL_COMPOSITION": "descriptive runtime facts only",
        "AI_CROSS_MODULE_COMPOSITION": "app/log/crash/artifact references",
        "AI_POST_ACTION_VERIFICATION_SURFACE": "fresh observation required",
        "AI_LEARNING_HOOK": AI_LEARNING_HOOK_RULE,
        "AI_PRIVACY_BOUNDARY": "no secrets or unnecessary full paths",
        "AI_AUTHORITY_BOUNDARY": "RiskController remains sole authority",
        "SHARED_SEMANTIC_CONTEXT_CONNECTED": True,
        "SECOND_AI_RUNTIME_ADDED": False,
        "SECOND_WORLD_MODEL_ADDED": False,
        "SECOND_MEMORY_SYSTEM_ADDED": False,
        "authorization": False,
    }


def ai_learning_hook() -> dict[str, Any]:
    return {
        "hook": AI_LEARNING_HOOK_RULE,
        "S4_M6_WRITES_PERMANENT_CAUSAL_MEMORY": False,
        "ONE_PROCESS_SPIKE_CREATES_PERMANENT_RULE": False,
        "ONE_SERVICE_FAILURE_CREATES_PERMANENT_RULE": False,
        "authorization": False,
    }


__all__ = [
    "AI_LEARNING_HOOK_RULE",
    "ClassificationBasisKind",
    "InstanceCertainty",
    "InstanceIdentityStrength",
    "ProcessInstanceDiscriminator",
    "ProcessInstanceDiscriminatorKind",
    "ProcessClassificationEvidence",
    "ProcessIdentity",
    "ProcessInstanceEvidence",
    "ProcessOperationDescriptor",
    "ProcessOperationKind",
    "ProcessServicePolicyError",
    "ProcessSnapshot",
    "ProcessTargetClass",
    "ProcessTargetProtection",
    "ServiceIdentity",
    "ServiceOperationDescriptor",
    "ServiceOperationKind",
    "ServiceStateEvidence",
    "ServiceStateKind",
    "SnapshotCompleteness",
    "ai_learning_hook",
    "ai_native_contract",
    "capability_definition_candidates",
    "classify_process_target",
    "revalidate_process_target",
    "revalidate_service_target",
]
