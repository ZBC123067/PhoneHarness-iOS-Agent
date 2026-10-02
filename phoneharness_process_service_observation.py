#!/usr/bin/env python3
"""Sanitized read-only Process / Service observation adapter for S4-M6-A3.

This module converts already-acquired, bounded provider facts into the frozen
S4-M6-A1/A2 contracts.  It deliberately contains no device transport,
command execution, process mutation, service mutation, authorization, or
provider-selection behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import Any

from phoneharness_contracts import ObservationFreshness, ObservationRef
from phoneharness_process_service import (
    InstanceIdentityStrength,
    ProcessIdentity,
    ProcessInstanceDiscriminator,
    ProcessInstanceDiscriminatorKind,
    ProcessInstanceEvidence,
    ProcessSnapshot,
    ServiceIdentity,
    ServiceStateEvidence,
    ServiceStateKind,
)


PROVIDER_OBSERVATION_SCHEMA = "phoneharness.process-service-provider-observation.v1"


class ProviderAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    PARTIAL = "PARTIAL"
    UNSTABLE = "UNSTABLE"
    NOT_TESTED = "NOT_TESTED"


class ResourceMetricStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    UNRELIABLE = "UNRELIABLE"


class ProviderServiceState(str, Enum):
    RUNNING = "RUNNING"
    NOT_RUNNING = "NOT_RUNNING"
    TRANSITIONING = "TRANSITIONING"
    UNKNOWN = "UNKNOWN"


class ProviderFusionDisposition(str, Enum):
    COMPOSED = "COMPOSED"
    PARTIAL = "PARTIAL"
    CONFLICT = "CONFLICT"
    UNAVAILABLE = "UNAVAILABLE"


class ObservationProviderRole(str, Enum):
    DISCOVERY = "DISCOVERY"
    APP_LIFECYCLE_EVIDENCE = "APP_LIFECYCLE_EVIDENCE"
    TARGETED_ENRICHMENT = "TARGETED_ENRICHMENT"


class MetricSemanticKind(str, Enum):
    SNAPSHOT_GAUGE = "SNAPSHOT_GAUGE"
    CUMULATIVE_COUNTER = "CUMULATIVE_COUNTER"
    DERIVED_RATE = "DERIVED_RATE"


class MetricCompleteness(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


class ProcessResourceMetric(str, Enum):
    MEMORY_RESIDENT_BYTES = "MEMORY_RESIDENT_BYTES"
    MEMORY_PHYS_FOOTPRINT_BYTES = "MEMORY_PHYS_FOOTPRINT_BYTES"
    THREAD_COUNT = "THREAD_COUNT"
    CPU_USER_TIME_NS = "CPU_USER_TIME_NS"
    CPU_SYSTEM_TIME_NS = "CPU_SYSTEM_TIME_NS"
    INTERRUPT_WAKEUPS = "INTERRUPT_WAKEUPS"
    PACKAGE_IDLE_WAKEUPS = "PACKAGE_IDLE_WAKEUPS"
    CPU_USER_TIME_RATE_NS_PER_SECOND = "CPU_USER_TIME_RATE_NS_PER_SECOND"
    CPU_SYSTEM_TIME_RATE_NS_PER_SECOND = "CPU_SYSTEM_TIME_RATE_NS_PER_SECOND"
    INTERRUPT_WAKEUPS_PER_SECOND = "INTERRUPT_WAKEUPS_PER_SECOND"
    PACKAGE_IDLE_WAKEUPS_PER_SECOND = "PACKAGE_IDLE_WAKEUPS_PER_SECOND"


class TargetRevalidationDisposition(str, Enum):
    MATCH_STRONG = "MATCH_STRONG"
    MATCH_PARTIAL = "MATCH_PARTIAL"
    STALE = "STALE"
    CONFLICT = "CONFLICT"
    TARGET_GONE = "TARGET_GONE"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class ProviderRoleDescriptor:
    provider: str
    role: ObservationProviderRole
    supports_general_enumeration: bool

    def __post_init__(self) -> None:
        if not isinstance(self.provider, str) or not self.provider.strip():
            raise ValueError("provider role requires a bounded provider identifier")
        object.__setattr__(self, "provider", self.provider.strip())
        object.__setattr__(self, "role", ObservationProviderRole(self.role))
        if not isinstance(self.supports_general_enumeration, bool):
            raise ValueError("provider enumeration support must be boolean")
        if (
            self.role is ObservationProviderRole.TARGETED_ENRICHMENT
            and self.supports_general_enumeration
        ):
            raise ValueError("targeted enrichment cannot claim general enumeration")

    def safe_semantic_record(self) -> dict[str, Any]:
        return {
            "schema_version": PROVIDER_OBSERVATION_SCHEMA,
            "provider": self.provider,
            "provider_role": self.role.value,
            "supports_general_enumeration": self.supports_general_enumeration,
            "app_lifecycle_authority": False,
            "authorization": False,
        }


_METRIC_CONTRACT: dict[
    ProcessResourceMetric,
    tuple[MetricSemanticKind, str],
] = {
    ProcessResourceMetric.MEMORY_RESIDENT_BYTES: (
        MetricSemanticKind.SNAPSHOT_GAUGE,
        "bytes",
    ),
    ProcessResourceMetric.MEMORY_PHYS_FOOTPRINT_BYTES: (
        MetricSemanticKind.SNAPSHOT_GAUGE,
        "bytes",
    ),
    ProcessResourceMetric.THREAD_COUNT: (
        MetricSemanticKind.SNAPSHOT_GAUGE,
        "threads",
    ),
    ProcessResourceMetric.CPU_USER_TIME_NS: (
        MetricSemanticKind.CUMULATIVE_COUNTER,
        "nanoseconds",
    ),
    ProcessResourceMetric.CPU_SYSTEM_TIME_NS: (
        MetricSemanticKind.CUMULATIVE_COUNTER,
        "nanoseconds",
    ),
    ProcessResourceMetric.INTERRUPT_WAKEUPS: (
        MetricSemanticKind.CUMULATIVE_COUNTER,
        "wakeups",
    ),
    ProcessResourceMetric.PACKAGE_IDLE_WAKEUPS: (
        MetricSemanticKind.CUMULATIVE_COUNTER,
        "wakeups",
    ),
    ProcessResourceMetric.CPU_USER_TIME_RATE_NS_PER_SECOND: (
        MetricSemanticKind.DERIVED_RATE,
        "nanoseconds_per_second",
    ),
    ProcessResourceMetric.CPU_SYSTEM_TIME_RATE_NS_PER_SECOND: (
        MetricSemanticKind.DERIVED_RATE,
        "nanoseconds_per_second",
    ),
    ProcessResourceMetric.INTERRUPT_WAKEUPS_PER_SECOND: (
        MetricSemanticKind.DERIVED_RATE,
        "wakeups_per_second",
    ),
    ProcessResourceMetric.PACKAGE_IDLE_WAKEUPS_PER_SECOND: (
        MetricSemanticKind.DERIVED_RATE,
        "wakeups_per_second",
    ),
}


@dataclass(frozen=True)
class NormalizedResourceMetric:
    metric: ProcessResourceMetric
    value: int | float
    semantic_kind: MetricSemanticKind
    unit: str
    provider: str
    observed_at_ms: int
    completeness: MetricCompleteness

    def __post_init__(self) -> None:
        object.__setattr__(self, "metric", ProcessResourceMetric(self.metric))
        object.__setattr__(
            self,
            "semantic_kind",
            MetricSemanticKind(self.semantic_kind),
        )
        object.__setattr__(
            self,
            "completeness",
            MetricCompleteness(self.completeness),
        )
        expected_kind, expected_unit = _METRIC_CONTRACT[self.metric]
        if self.semantic_kind is not expected_kind or self.unit != expected_unit:
            raise ValueError("resource metric semantics do not match metric identity")
        if (
            isinstance(self.value, bool)
            or not isinstance(self.value, (int, float))
            or not math.isfinite(float(self.value))
            or self.value < 0
        ):
            raise ValueError("resource metric value must be finite and non-negative")
        if not isinstance(self.provider, str) or not self.provider.strip():
            raise ValueError("resource metric requires provider provenance")
        object.__setattr__(self, "provider", self.provider.strip())
        if (
            isinstance(self.observed_at_ms, bool)
            or not isinstance(self.observed_at_ms, int)
            or self.observed_at_ms < 0
        ):
            raise ValueError("resource metric timestamp must be non-negative")

    def safe_semantic_record(self) -> dict[str, Any]:
        return {
            "schema_version": PROVIDER_OBSERVATION_SCHEMA,
            "metric": self.metric.value,
            "semantic_kind": self.semantic_kind.value,
            "unit": self.unit,
            "provider": self.provider,
            "observed_at_ms": self.observed_at_ms,
            "completeness": self.completeness.value,
            "authorization": False,
        }


@dataclass(frozen=True)
class CandidateInstanceDiscriminator:
    """Provider evidence that is observed but not automatically trusted.

    A candidate becomes canonical strong instance evidence only after its
    provider semantics and stability have been proven.  Merely exposing a
    Darwin field or repeating the same value does not prove that contract.
    """

    kind: ProcessInstanceDiscriminatorKind
    evidence_ref: str
    provider: str
    stability_proven: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", ProcessInstanceDiscriminatorKind(self.kind))
        if not isinstance(self.stability_proven, bool):
            raise ValueError("stability_proven must be boolean")
        # Reuse the frozen A2 validation without promoting the candidate.
        ProcessInstanceDiscriminator(self.kind, self.evidence_ref, self.provider)

    def accepted_evidence(self) -> ProcessInstanceDiscriminator | None:
        if not self.stability_proven:
            return None
        return ProcessInstanceDiscriminator(
            self.kind,
            self.evidence_ref,
            self.provider,
        )


@dataclass(frozen=True)
class SanitizedProcessObservation:
    process_name: str | None
    provider: str
    observation_id: str
    task_id: str
    session_id: str
    generation: int
    observed_at_ms: int
    pid: int | None = None
    bundle_id: str | None = None
    executable_digest: str | None = None
    candidate_discriminators: tuple[CandidateInstanceDiscriminator, ...] = ()
    state: str | None = None
    cpu_observation: float | None = None
    memory_observation_bytes: int | None = None
    thread_count: int | None = None
    wakeup_observation: int | None = None
    foreground_relation: str | None = None
    freshness: ObservationFreshness = ObservationFreshness.FRESH

    def __post_init__(self) -> None:
        object.__setattr__(self, "freshness", ObservationFreshness(self.freshness))
        candidates = tuple(self.candidate_discriminators)
        if any(not isinstance(value, CandidateInstanceDiscriminator) for value in candidates):
            raise ValueError("candidate discriminators must be typed")
        kinds = [value.kind for value in candidates]
        if len(kinds) != len(set(kinds)):
            raise ValueError("candidate discriminator kinds must be unique")
        if any(value.provider != self.provider for value in candidates):
            raise ValueError("candidate discriminator provider must match observation provider")
        object.__setattr__(self, "candidate_discriminators", candidates)

    def observation_ref(self) -> ObservationRef:
        return ObservationRef(
            observation_id=self.observation_id,
            producer=self.provider,
            task_id=self.task_id,
            session_id=self.session_id,
            generation=self.generation,
            observed_at_ms=self.observed_at_ms,
            freshness=self.freshness,
        )

    def to_snapshot(self) -> ProcessSnapshot:
        ref = self.observation_ref()
        identity = ProcessIdentity(
            process_name=self.process_name,
            bundle_id=self.bundle_id,
            executable_digest=self.executable_digest,
            provider=self.provider,
        )
        accepted = tuple(
            evidence
            for candidate in self.candidate_discriminators
            if (evidence := candidate.accepted_evidence()) is not None
        )
        instance = ProcessInstanceEvidence(
            identity=identity,
            pid=self.pid,
            observation_ref=ref,
            provider=self.provider,
            observed_at_ms=self.observed_at_ms,
            instance_discriminators=accepted,
        )
        return ProcessSnapshot(
            instance=instance,
            observed_at_ms=self.observed_at_ms,
            observation_ref=ref,
            state=self.state,
            cpu_observation=self.cpu_observation,
            memory_observation_bytes=self.memory_observation_bytes,
            thread_count=self.thread_count,
            wakeup_observation=self.wakeup_observation,
            foreground_relation=self.foreground_relation,
        )

    def safe_semantic_record(self) -> dict[str, Any]:
        snapshot = self.to_snapshot()
        return {
            "schema_version": PROVIDER_OBSERVATION_SCHEMA,
            "provider": self.provider,
            "identity_strength": snapshot.instance.identity_strength.value,
            "snapshot_completeness": snapshot.completeness.value,
            "observed_fields": list(snapshot.observed_fields),
            "candidate_discriminator_kinds": [
                value.kind.value for value in self.candidate_discriminators
            ],
            "accepted_discriminator_count": len(
                snapshot.instance.instance_discriminators
            ),
            "bundle_identity_present": self.bundle_id is not None,
            "executable_digest_present": self.executable_digest is not None,
            "provenance_present": True,
            "authorization": False,
            "causal_proof": False,
            "app_lifecycle_authority": False,
            "shell_authority": False,
        }


@dataclass(frozen=True)
class SanitizedServiceObservation:
    label: str
    provider: str
    availability: ProviderAvailability
    resolved: bool
    provider_state: ProviderServiceState
    observation_id: str
    task_id: str
    session_id: str
    generation: int
    observed_at_ms: int
    process: SanitizedProcessObservation | None = None
    definition_digest: str | None = None
    freshness: ObservationFreshness = ObservationFreshness.FRESH

    def __post_init__(self) -> None:
        object.__setattr__(self, "availability", ProviderAvailability(self.availability))
        object.__setattr__(self, "provider_state", ProviderServiceState(self.provider_state))
        object.__setattr__(self, "freshness", ObservationFreshness(self.freshness))
        if not isinstance(self.resolved, bool):
            raise ValueError("resolved must be boolean")
        if self.process is not None:
            if not isinstance(self.process, SanitizedProcessObservation):
                raise ValueError("service process must use sanitized process evidence")
            expected = (
                self.provider,
                self.observation_id,
                self.task_id,
                self.session_id,
                self.generation,
                self.observed_at_ms,
                self.freshness,
            )
            actual = (
                self.process.provider,
                self.process.observation_id,
                self.process.task_id,
                self.process.session_id,
                self.process.generation,
                self.process.observed_at_ms,
                self.process.freshness,
            )
            if actual != expected:
                raise ValueError("service and process provenance must be identical")

    def observation_ref(self) -> ObservationRef:
        return ObservationRef(
            observation_id=self.observation_id,
            producer=self.provider,
            task_id=self.task_id,
            session_id=self.session_id,
            generation=self.generation,
            observed_at_ms=self.observed_at_ms,
            freshness=self.freshness,
        )

    def _canonical_state(self) -> ServiceStateKind:
        if self.availability not in {
            ProviderAvailability.AVAILABLE,
            ProviderAvailability.PARTIAL,
        }:
            return ServiceStateKind.UNAVAILABLE
        if not self.resolved:
            return ServiceStateKind.UNAVAILABLE
        if self.provider_state is ProviderServiceState.NOT_RUNNING:
            return ServiceStateKind.STOPPED
        if self.provider_state is ProviderServiceState.TRANSITIONING:
            return ServiceStateKind.TRANSITIONING
        if self.provider_state is ProviderServiceState.RUNNING:
            return (
                ServiceStateKind.RUNNING
                if self.process is not None
                else ServiceStateKind.UNKNOWN
            )
        return ServiceStateKind.UNKNOWN

    def to_evidence(self) -> ServiceStateEvidence:
        state = self._canonical_state()
        instance = None
        if state is ServiceStateKind.RUNNING and self.process is not None:
            instance = self.process.to_snapshot().instance
        return ServiceStateEvidence(
            identity=ServiceIdentity(
                label=self.label,
                provider=self.provider,
                definition_digest=self.definition_digest,
            ),
            state=state,
            observed_at_ms=self.observed_at_ms,
            observation_ref=self.observation_ref(),
            instance=instance,
        )

    def safe_semantic_record(self) -> dict[str, Any]:
        evidence = self.to_evidence()
        return {
            "schema_version": PROVIDER_OBSERVATION_SCHEMA,
            "provider": self.provider,
            "service_state": evidence.state.value,
            "service_resolved": self.resolved,
            "instance_present": evidence.instance is not None,
            "provider_availability": self.availability.value,
            "provenance_present": True,
            "unknown_is_stopped": False,
            "authorization": False,
            "semantic_success": False,
            "app_lifecycle_authority": False,
            "shell_authority": False,
        }


@dataclass(frozen=True)
class ProviderFusionResult:
    """Conservative comparison of independent read-only providers.

    Fusion reports compatibility; it does not manufacture a replacement
    observation, authorize an operation, or strengthen either provider's
    instance certainty.
    """

    disposition: ProviderFusionDisposition
    provider_count: int
    effective_identity_strength: InstanceIdentityStrength
    pid_consistent: bool | None
    logical_identity_consistent: bool | None
    discriminator_consistent: bool | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "disposition",
            ProviderFusionDisposition(self.disposition),
        )
        object.__setattr__(
            self,
            "effective_identity_strength",
            InstanceIdentityStrength(self.effective_identity_strength),
        )
        if self.provider_count not in {0, 1, 2}:
            raise ValueError("provider_count must describe the bounded fusion inputs")

    def safe_semantic_record(self) -> dict[str, Any]:
        return {
            "schema_version": PROVIDER_OBSERVATION_SCHEMA,
            "fusion_disposition": self.disposition.value,
            "provider_count": self.provider_count,
            "effective_identity_strength": self.effective_identity_strength.value,
            "pid_consistent": self.pid_consistent,
            "logical_identity_consistent": self.logical_identity_consistent,
            "discriminator_consistent": self.discriminator_consistent,
            "certainty_strengthened_by_fusion": False,
            "authorization": False,
        }


def _overlapping_identity_consistent(
    left: SanitizedProcessObservation,
    right: SanitizedProcessObservation,
) -> bool:
    for field_name in ("process_name", "bundle_id", "executable_digest"):
        left_value = getattr(left, field_name)
        right_value = getattr(right, field_name)
        if left_value is not None and right_value is not None and left_value != right_value:
            return False
    return True


def _discriminators_consistent(
    left: SanitizedProcessObservation,
    right: SanitizedProcessObservation,
) -> bool:
    left_values = {
        value.kind: value.evidence_ref
        for value in left.candidate_discriminators
        if value.stability_proven
    }
    right_values = {
        value.kind: value.evidence_ref
        for value in right.candidate_discriminators
        if value.stability_proven
    }
    for kind in left_values.keys() & right_values.keys():
        if left_values[kind] != right_values[kind]:
            return False
    return True


def _conservative_strength(
    left: InstanceIdentityStrength,
    right: InstanceIdentityStrength,
) -> InstanceIdentityStrength:
    if left is right:
        return left
    if InstanceIdentityStrength.NONE in {left, right}:
        return InstanceIdentityStrength.NONE
    if InstanceIdentityStrength.PID_ONLY in {left, right}:
        return InstanceIdentityStrength.PID_ONLY
    return InstanceIdentityStrength.PARTIAL


def fuse_process_observations(
    left: SanitizedProcessObservation | None,
    right: SanitizedProcessObservation | None,
) -> ProviderFusionResult:
    """Compare at most two providers without creating stronger evidence."""

    observations = tuple(value for value in (left, right) if value is not None)
    if not observations:
        return ProviderFusionResult(
            disposition=ProviderFusionDisposition.UNAVAILABLE,
            provider_count=0,
            effective_identity_strength=InstanceIdentityStrength.NONE,
            pid_consistent=None,
            logical_identity_consistent=None,
            discriminator_consistent=None,
        )
    if len(observations) == 1:
        strength = observations[0].to_snapshot().instance.identity_strength
        return ProviderFusionResult(
            disposition=ProviderFusionDisposition.PARTIAL,
            provider_count=1,
            effective_identity_strength=strength,
            pid_consistent=None,
            logical_identity_consistent=None,
            discriminator_consistent=None,
        )

    assert left is not None and right is not None
    left_snapshot = left.to_snapshot()
    right_snapshot = right.to_snapshot()
    pid_consistent = (
        left.pid is None or right.pid is None or left.pid == right.pid
    )
    identity_consistent = _overlapping_identity_consistent(left, right)
    discriminator_consistent = _discriminators_consistent(left, right)
    conflict = not (
        pid_consistent and identity_consistent and discriminator_consistent
    )
    return ProviderFusionResult(
        disposition=(
            ProviderFusionDisposition.CONFLICT
            if conflict
            else ProviderFusionDisposition.COMPOSED
        ),
        provider_count=2,
        effective_identity_strength=(
            InstanceIdentityStrength.NONE
            if conflict
            else _conservative_strength(
                left_snapshot.instance.identity_strength,
                right_snapshot.instance.identity_strength,
            )
        ),
        pid_consistent=pid_consistent,
        logical_identity_consistent=identity_consistent,
        discriminator_consistent=discriminator_consistent,
    )


_DERIVED_RATE_METRIC = {
    ProcessResourceMetric.CPU_USER_TIME_NS:
        ProcessResourceMetric.CPU_USER_TIME_RATE_NS_PER_SECOND,
    ProcessResourceMetric.CPU_SYSTEM_TIME_NS:
        ProcessResourceMetric.CPU_SYSTEM_TIME_RATE_NS_PER_SECOND,
    ProcessResourceMetric.INTERRUPT_WAKEUPS:
        ProcessResourceMetric.INTERRUPT_WAKEUPS_PER_SECOND,
    ProcessResourceMetric.PACKAGE_IDLE_WAKEUPS:
        ProcessResourceMetric.PACKAGE_IDLE_WAKEUPS_PER_SECOND,
}


def derive_resource_rate(
    previous: NormalizedResourceMetric,
    current: NormalizedResourceMetric,
    *,
    same_strong_instance: bool,
) -> NormalizedResourceMetric | None:
    """Derive a bounded rate only from ordered same-instance counters."""

    if not isinstance(previous, NormalizedResourceMetric) or not isinstance(
        current,
        NormalizedResourceMetric,
    ):
        raise ValueError("rate derivation requires normalized resource metrics")
    if not same_strong_instance:
        return None
    if previous.metric is not current.metric or previous.provider != current.provider:
        return None
    if previous.semantic_kind is not MetricSemanticKind.CUMULATIVE_COUNTER:
        return None
    if current.semantic_kind is not MetricSemanticKind.CUMULATIVE_COUNTER:
        return None
    if current.observed_at_ms <= previous.observed_at_ms:
        return None
    if current.value < previous.value:
        return None
    derived_metric = _DERIVED_RATE_METRIC.get(previous.metric)
    if derived_metric is None:
        return None
    elapsed_seconds = (current.observed_at_ms - previous.observed_at_ms) / 1000.0
    completeness = (
        MetricCompleteness.COMPLETE
        if previous.completeness is MetricCompleteness.COMPLETE
        and current.completeness is MetricCompleteness.COMPLETE
        else MetricCompleteness.PARTIAL
    )
    semantic_kind, unit = _METRIC_CONTRACT[derived_metric]
    return NormalizedResourceMetric(
        metric=derived_metric,
        value=(current.value - previous.value) / elapsed_seconds,
        semantic_kind=semantic_kind,
        unit=unit,
        provider=current.provider,
        observed_at_ms=current.observed_at_ms,
        completeness=completeness,
    )


@dataclass(frozen=True)
class TargetRevalidationResult:
    disposition: TargetRevalidationDisposition
    prepared_strength: InstanceIdentityStrength
    current_strength: InstanceIdentityStrength
    fresh_current_evidence: bool
    provider_consistent: bool | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "disposition",
            TargetRevalidationDisposition(self.disposition),
        )
        object.__setattr__(
            self,
            "prepared_strength",
            InstanceIdentityStrength(self.prepared_strength),
        )
        object.__setattr__(
            self,
            "current_strength",
            InstanceIdentityStrength(self.current_strength),
        )

    def safe_semantic_record(self) -> dict[str, Any]:
        return {
            "schema_version": PROVIDER_OBSERVATION_SCHEMA,
            "revalidation_disposition": self.disposition.value,
            "prepared_strength": self.prepared_strength.value,
            "current_strength": self.current_strength.value,
            "fresh_current_evidence": self.fresh_current_evidence,
            "provider_consistent": self.provider_consistent,
            "prepared_target_is_current_target": (
                self.disposition is TargetRevalidationDisposition.MATCH_STRONG
            ),
            "authorization": False,
        }


def _current_is_fresh(
    observation: SanitizedProcessObservation | SanitizedServiceObservation,
    *,
    now_ms: int,
    max_age_ms: int,
) -> bool:
    if (
        isinstance(now_ms, bool)
        or not isinstance(now_ms, int)
        or now_ms < 0
        or isinstance(max_age_ms, bool)
        or not isinstance(max_age_ms, int)
        or max_age_ms <= 0
    ):
        raise ValueError("revalidation clock inputs are invalid")
    if observation.freshness is not ObservationFreshness.FRESH:
        return False
    if observation.observed_at_ms > now_ms:
        return False
    return now_ms - observation.observed_at_ms <= max_age_ms


def revalidate_process_observations(
    prepared: SanitizedProcessObservation,
    current: SanitizedProcessObservation | None,
    *,
    now_ms: int,
    max_age_ms: int,
    provider_available: bool = True,
    target_exists: bool = True,
) -> TargetRevalidationResult:
    """Compare prepared and current process evidence without granting authority."""

    if not isinstance(prepared, SanitizedProcessObservation):
        raise ValueError("prepared process target must use sanitized evidence")
    prepared_strength = prepared.to_snapshot().instance.identity_strength
    if not target_exists:
        return TargetRevalidationResult(
            TargetRevalidationDisposition.TARGET_GONE,
            prepared_strength,
            InstanceIdentityStrength.NONE,
            False,
            None,
        )
    if not provider_available or current is None:
        return TargetRevalidationResult(
            TargetRevalidationDisposition.UNAVAILABLE,
            prepared_strength,
            InstanceIdentityStrength.NONE,
            False,
            None,
        )
    if not isinstance(current, SanitizedProcessObservation):
        raise ValueError("current process target must use sanitized evidence")
    current_snapshot = current.to_snapshot()
    current_strength = current_snapshot.instance.identity_strength
    provider_consistent = prepared.provider == current.provider
    fresh = _current_is_fresh(current, now_ms=now_ms, max_age_ms=max_age_ms)
    if current.observed_at_ms > now_ms:
        disposition = TargetRevalidationDisposition.CONFLICT
    elif not fresh:
        disposition = TargetRevalidationDisposition.STALE
    elif not _overlapping_identity_consistent(prepared, current):
        disposition = TargetRevalidationDisposition.CONFLICT
    elif prepared.pid != current.pid:
        disposition = TargetRevalidationDisposition.STALE
    elif (
        prepared_strength is InstanceIdentityStrength.STRONG_PROVIDER_EVIDENCE
        and current_strength is InstanceIdentityStrength.STRONG_PROVIDER_EVIDENCE
    ):
        disposition = (
            TargetRevalidationDisposition.MATCH_STRONG
            if prepared.to_snapshot().instance.same_instance_as(
                current_snapshot.instance
            )
            else TargetRevalidationDisposition.STALE
        )
    else:
        disposition = TargetRevalidationDisposition.MATCH_PARTIAL
    return TargetRevalidationResult(
        disposition,
        prepared_strength,
        current_strength,
        fresh,
        provider_consistent,
    )


def revalidate_service_observations(
    prepared: SanitizedServiceObservation,
    current: SanitizedServiceObservation | None,
    *,
    now_ms: int,
    max_age_ms: int,
    provider_available: bool = True,
    target_exists: bool = True,
) -> TargetRevalidationResult:
    """Compare service state without treating a label as an instance."""

    if not isinstance(prepared, SanitizedServiceObservation):
        raise ValueError("prepared service target must use sanitized evidence")
    prepared_evidence = prepared.to_evidence()
    prepared_strength = (
        prepared_evidence.instance.identity_strength
        if prepared_evidence.instance is not None
        else InstanceIdentityStrength.NONE
    )
    if not target_exists:
        return TargetRevalidationResult(
            TargetRevalidationDisposition.TARGET_GONE,
            prepared_strength,
            InstanceIdentityStrength.NONE,
            False,
            None,
        )
    if not provider_available or current is None:
        return TargetRevalidationResult(
            TargetRevalidationDisposition.UNAVAILABLE,
            prepared_strength,
            InstanceIdentityStrength.NONE,
            False,
            None,
        )
    if not isinstance(current, SanitizedServiceObservation):
        raise ValueError("current service target must use sanitized evidence")
    current_evidence = current.to_evidence()
    current_strength = (
        current_evidence.instance.identity_strength
        if current_evidence.instance is not None
        else InstanceIdentityStrength.NONE
    )
    provider_consistent = prepared.provider == current.provider
    fresh = _current_is_fresh(current, now_ms=now_ms, max_age_ms=max_age_ms)
    if current.observed_at_ms > now_ms:
        disposition = TargetRevalidationDisposition.CONFLICT
    elif not fresh:
        disposition = TargetRevalidationDisposition.STALE
    elif prepared.label != current.label or not provider_consistent:
        disposition = TargetRevalidationDisposition.CONFLICT
    elif current_evidence.state in {
        ServiceStateKind.UNKNOWN,
        ServiceStateKind.UNAVAILABLE,
        ServiceStateKind.TRANSITIONING,
    }:
        disposition = TargetRevalidationDisposition.UNAVAILABLE
    elif prepared_evidence.state is not current_evidence.state:
        disposition = TargetRevalidationDisposition.STALE
    elif prepared_evidence.instance is None and current_evidence.instance is None:
        disposition = TargetRevalidationDisposition.MATCH_PARTIAL
    elif prepared_evidence.instance is None or current_evidence.instance is None:
        disposition = TargetRevalidationDisposition.STALE
    elif prepared_evidence.instance.same_instance_as(current_evidence.instance):
        disposition = TargetRevalidationDisposition.MATCH_STRONG
    elif (
        prepared_strength is InstanceIdentityStrength.STRONG_PROVIDER_EVIDENCE
        or current_strength is InstanceIdentityStrength.STRONG_PROVIDER_EVIDENCE
    ):
        disposition = TargetRevalidationDisposition.STALE
    else:
        disposition = TargetRevalidationDisposition.MATCH_PARTIAL
    return TargetRevalidationResult(
        disposition,
        prepared_strength,
        current_strength,
        fresh,
        provider_consistent,
    )
def app_identity_correlates(
    process_observation: SanitizedProcessObservation,
    app_bundle_id: str,
) -> bool:
    """Descriptive exact bundle correlation; never lifecycle authority."""

    if not isinstance(app_bundle_id, str):
        return False
    snapshot = process_observation.to_snapshot()
    return snapshot.instance.identity.bundle_id == app_bundle_id.strip()


__all__ = [
    "CandidateInstanceDiscriminator",
    "MetricCompleteness",
    "MetricSemanticKind",
    "NormalizedResourceMetric",
    "ObservationProviderRole",
    "PROVIDER_OBSERVATION_SCHEMA",
    "ProcessResourceMetric",
    "ProviderAvailability",
    "ProviderFusionDisposition",
    "ProviderFusionResult",
    "ProviderRoleDescriptor",
    "ProviderServiceState",
    "ResourceMetricStatus",
    "SanitizedProcessObservation",
    "SanitizedServiceObservation",
    "TargetRevalidationDisposition",
    "TargetRevalidationResult",
    "app_identity_correlates",
    "derive_resource_rate",
    "fuse_process_observations",
    "InstanceIdentityStrength",
    "revalidate_process_observations",
    "revalidate_service_observations",
]
