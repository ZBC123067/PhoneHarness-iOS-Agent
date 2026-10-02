#!/usr/bin/env python3
"""Host-only provider health, circuit-breaker, and fallback policy foundation.

This module records and assesses provider availability. It cannot authorize,
bind, dispatch, execute, retry, verify, replan, or restart a process.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum, IntEnum
import hashlib
import re
import time
from typing import Any, Callable, Iterable
import uuid

from phoneharness_agent import (
    CapabilityDefinition,
    CapabilityMethodDefinition,
    CapabilityMethodRegistry,
)
from phoneharness_contracts import ArtifactDescriptor, ArtifactLifetime, ArtifactRef, SensitivityClass
from phoneharness_runtime import RuntimeInstanceRef
from phoneharness_store import DispatchStatus, PhoneHarnessStore, SideEffectClass, TraceEvent
from phoneharness_uncertainty import ReconciliationState


PROVIDER_HEALTH_SCHEMA_VERSION = "phoneharness.provider-health.v1"
PROVIDER_SIGNAL_SCHEMA_VERSION = "phoneharness.provider-health-signal.v1"
FALLBACK_ASSESSMENT_SCHEMA_VERSION = "phoneharness.fallback-assessment.v1"
FALLBACK_DECISION_SCHEMA_VERSION = "phoneharness.fallback-decision.v1"
MAX_FAILURE_THRESHOLD = 32
MAX_HALF_OPEN_PROBES = 8
MAX_COOLDOWN_MS = 86_400_000
MAX_FRESHNESS_MS = 604_800_000

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")


class ProviderHealthError(RuntimeError):
    """Base class for deterministic provider-health failures."""


class ProviderHealthPolicyError(ProviderHealthError):
    """A provider-health or fallback contract is invalid."""


class ProviderHealthNotFound(ProviderHealthError):
    """No durable health snapshot exists for the requested provider scope."""


class ProviderHealthConflict(ProviderHealthError):
    """A stale health snapshot revision was used for an update."""


class ProviderProbeRejected(ProviderHealthError):
    """A health probe is mutating, premature, or exceeds the bounded policy."""


class ProviderHealthState(str, Enum):
    UNKNOWN = "UNKNOWN"
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"
    PROBING = "PROBING"


class CircuitBreakerState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class HealthSignalOrigin(str, Enum):
    PASSIVE = "PASSIVE"
    ACTIVE = "ACTIVE"


class HealthEvidenceStrength(IntEnum):
    WEAK = 1
    CORRELATED = 2
    AUTHORITATIVE = 3


class ProviderHealthSignalKind(str, Enum):
    OPERATION_SUCCEEDED = "OPERATION_SUCCEEDED"
    TRANSIENT_FAILURE = "TRANSIENT_FAILURE"
    PERMANENT_FAILURE = "PERMANENT_FAILURE"
    TIMEOUT = "TIMEOUT"
    CONNECTION_FAILURE = "CONNECTION_FAILURE"
    THROTTLED = "THROTTLED"
    LATENCY_THRESHOLD_EXCEEDED = "LATENCY_THRESHOLD_EXCEEDED"
    ACTIVE_PROBE_SUCCEEDED = "ACTIVE_PROBE_SUCCEEDED"
    ACTIVE_PROBE_FAILED = "ACTIVE_PROBE_FAILED"


class FallbackDecisionKind(str, Enum):
    USE_PRIMARY = "USE_PRIMARY"
    USE_ALTERNATE = "USE_ALTERNATE"
    NO_HEALTHY_PROVIDER = "NO_HEALTHY_PROVIDER"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"
    PROBE_REQUIRED = "PROBE_REQUIRED"
    FALLBACK_NOT_ALLOWED = "FALLBACK_NOT_ALLOWED"
    SERVICE_RECOVERY_REQUIRED = "SERVICE_RECOVERY_REQUIRED"


class FallbackEligibilityCode(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    UNREGISTERED_PROVIDER = "UNREGISTERED_PROVIDER"
    WRONG_CAPABILITY = "WRONG_CAPABILITY"
    METHOD_NOT_ACTIVE = "METHOD_NOT_ACTIVE"
    METHOD_UNAVAILABLE = "METHOD_UNAVAILABLE"
    REQUIRED_TOOLS_UNAVAILABLE = "REQUIRED_TOOLS_UNAVAILABLE"
    REQUIRED_PERMISSIONS_UNAVAILABLE = "REQUIRED_PERMISSIONS_UNAVAILABLE"
    PLATFORM_INCOMPATIBLE = "PLATFORM_INCOMPATIBLE"
    SIDE_EFFECT_INCOMPATIBLE = "SIDE_EFFECT_INCOMPATIBLE"
    TARGET_SEMANTICS_INCOMPATIBLE = "TARGET_SEMANTICS_INCOMPATIBLE"
    BINDING_INCOMPATIBLE = "BINDING_INCOMPATIBLE"
    VERIFIER_UNAVAILABLE = "VERIFIER_UNAVAILABLE"
    PROVIDER_UNKNOWN = "PROVIDER_UNKNOWN"
    PROVIDER_STALE = "PROVIDER_STALE"
    PROVIDER_DEGRADED = "PROVIDER_DEGRADED"
    PROVIDER_UNHEALTHY = "PROVIDER_UNHEALTHY"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"
    PROBE_REQUIRED = "PROBE_REQUIRED"
    POSSIBLE_DISPATCH = "POSSIBLE_DISPATCH"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"
    EVIDENCE_CONFLICT = "EVIDENCE_CONFLICT"
    PRE_DISPATCH_FAILURE_NOT_PROVEN = "PRE_DISPATCH_FAILURE_NOT_PROVEN"
    NEW_GOVERNED_ATTEMPT_REQUIRED = "NEW_GOVERNED_ATTEMPT_REQUIRED"


class OwnedServiceRecoveryDisposition(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    OWNED_SERVICE_RECOVERY_REQUIRED = "OWNED_SERVICE_RECOVERY_REQUIRED"
    NOT_OWNED_FAIL_CLOSED = "NOT_OWNED_FAIL_CLOSED"


def _identifier(value: Any, field_name: str) -> str:
    normalized = str(value or "").strip()
    if _IDENTIFIER.fullmatch(normalized) is None:
        raise ProviderHealthPolicyError(f"{field_name} must be an opaque bounded identifier")
    return normalized


def _timestamp(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProviderHealthPolicyError(f"{field_name} must be a non-negative integer")
    return value


def _bounded_int(value: Any, field_name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ProviderHealthPolicyError(f"{field_name} is outside its bounded range")
    return value


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _new_identifier(prefix: str) -> str:
    return f"{prefix}.{uuid.uuid4().hex}"


def _scope_digest(ref: "ProviderRef") -> str:
    body = f"{ref.provider_id}\0{ref.capability_id}".encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _none(value: str | None) -> str:
    return "NONE" if value is None else value


def _from_none(value: str) -> str | None:
    return None if value == "NONE" else value


@dataclass(frozen=True)
class ProviderRef:
    provider_id: str
    capability_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_id", _identifier(self.provider_id, "provider_id"))
        object.__setattr__(self, "capability_id", _identifier(self.capability_id, "capability_id"))

    @property
    def scope_id(self) -> str:
        return f"provider-health.{_scope_digest(self)[:40]}"


@dataclass(frozen=True)
class CircuitBreakerPolicy:
    failure_threshold: int = 3
    cooldown_ms: int = 30_000
    max_half_open_probes: int = 1
    freshness_ttl_ms: int = 300_000

    def __post_init__(self) -> None:
        _bounded_int(self.failure_threshold, "failure_threshold", 1, MAX_FAILURE_THRESHOLD)
        _bounded_int(self.cooldown_ms, "cooldown_ms", 1, MAX_COOLDOWN_MS)
        _bounded_int(self.max_half_open_probes, "max_half_open_probes", 1, MAX_HALF_OPEN_PROBES)
        _bounded_int(self.freshness_ttl_ms, "freshness_ttl_ms", 1, MAX_FRESHNESS_MS)

    def audit(self) -> dict[str, Any]:
        return {
            "failure_threshold": self.failure_threshold,
            "cooldown_ms": self.cooldown_ms,
            "max_half_open_probes": self.max_half_open_probes,
            "freshness_ttl_ms": self.freshness_ttl_ms,
            "authority": False,
            "retry_policy": False,
        }


_SUCCESS_SIGNALS = frozenset(
    {ProviderHealthSignalKind.OPERATION_SUCCEEDED, ProviderHealthSignalKind.ACTIVE_PROBE_SUCCEEDED}
)
_FAILURE_SIGNALS = frozenset(
    {
        ProviderHealthSignalKind.TRANSIENT_FAILURE,
        ProviderHealthSignalKind.PERMANENT_FAILURE,
        ProviderHealthSignalKind.TIMEOUT,
        ProviderHealthSignalKind.CONNECTION_FAILURE,
        ProviderHealthSignalKind.THROTTLED,
        ProviderHealthSignalKind.ACTIVE_PROBE_FAILED,
    }
)
_ACTIVE_SIGNALS = frozenset(
    {ProviderHealthSignalKind.ACTIVE_PROBE_SUCCEEDED, ProviderHealthSignalKind.ACTIVE_PROBE_FAILED}
)


@dataclass(frozen=True)
class ProviderHealthSignal:
    signal_id: str
    provider_ref: ProviderRef
    kind: ProviderHealthSignalKind
    origin: HealthSignalOrigin
    strength: HealthEvidenceStrength
    observed_at_ms: int
    qualified_recovery: bool = False
    schema_version: str = PROVIDER_SIGNAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PROVIDER_SIGNAL_SCHEMA_VERSION:
            raise ProviderHealthPolicyError("unsupported ProviderHealthSignal schema version")
        object.__setattr__(self, "signal_id", _identifier(self.signal_id, "signal_id"))
        if not isinstance(self.provider_ref, ProviderRef):
            raise ProviderHealthPolicyError("provider signal requires ProviderRef")
        object.__setattr__(self, "kind", ProviderHealthSignalKind(self.kind))
        object.__setattr__(self, "origin", HealthSignalOrigin(self.origin))
        object.__setattr__(self, "strength", HealthEvidenceStrength(self.strength))
        _timestamp(self.observed_at_ms, "observed_at_ms")
        if not isinstance(self.qualified_recovery, bool):
            raise ProviderHealthPolicyError("qualified_recovery must be boolean")
        if (self.kind in _ACTIVE_SIGNALS) is not (self.origin is HealthSignalOrigin.ACTIVE):
            raise ProviderHealthPolicyError("health signal kind and origin do not match")
        if self.qualified_recovery and self.kind is not ProviderHealthSignalKind.ACTIVE_PROBE_SUCCEEDED:
            raise ProviderHealthPolicyError("only a successful active probe may be a qualified recovery")

    @property
    def succeeded(self) -> bool:
        return self.kind in _SUCCESS_SIGNALS

    @property
    def failed(self) -> bool:
        return self.kind in _FAILURE_SIGNALS


@dataclass(frozen=True)
class ProviderHealthSnapshot:
    provider_ref: ProviderRef
    task_id: str
    session_id: str
    trace_id: str
    current_runtime_instance_id: str
    health_state: ProviderHealthState
    circuit_state: CircuitBreakerState
    consecutive_failures: int
    half_open_probes_admitted: int
    last_signal_kind: ProviderHealthSignalKind | None
    last_signal_origin: HealthSignalOrigin | None
    last_signal_strength: HealthEvidenceStrength | None
    strongest_unresolved_failure_strength: HealthEvidenceStrength | None
    last_evidence_at_ms: int | None
    opened_at_ms: int | None
    updated_at_ms: int
    revision: int = 1
    schema_version: str = PROVIDER_HEALTH_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PROVIDER_HEALTH_SCHEMA_VERSION:
            raise ProviderHealthPolicyError("unsupported ProviderHealthSnapshot schema version")
        if not isinstance(self.provider_ref, ProviderRef):
            raise ProviderHealthPolicyError("provider health requires ProviderRef")
        for name in ("task_id", "session_id", "trace_id", "current_runtime_instance_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(self, "health_state", ProviderHealthState(self.health_state))
        object.__setattr__(self, "circuit_state", CircuitBreakerState(self.circuit_state))
        _bounded_int(self.consecutive_failures, "consecutive_failures", 0, MAX_FAILURE_THRESHOLD)
        _bounded_int(self.half_open_probes_admitted, "half_open_probes_admitted", 0, MAX_HALF_OPEN_PROBES)
        _bounded_int(self.revision, "revision", 1, 1_000_000)
        _timestamp(self.updated_at_ms, "updated_at_ms")
        for name in ("last_evidence_at_ms", "opened_at_ms"):
            value = getattr(self, name)
            if value is not None:
                _timestamp(value, name)
        if self.last_signal_kind is not None:
            object.__setattr__(self, "last_signal_kind", ProviderHealthSignalKind(self.last_signal_kind))
        if self.last_signal_origin is not None:
            object.__setattr__(self, "last_signal_origin", HealthSignalOrigin(self.last_signal_origin))
        if self.last_signal_strength is not None:
            object.__setattr__(self, "last_signal_strength", HealthEvidenceStrength(self.last_signal_strength))
        if self.strongest_unresolved_failure_strength is not None:
            object.__setattr__(
                self,
                "strongest_unresolved_failure_strength",
                HealthEvidenceStrength(self.strongest_unresolved_failure_strength),
            )
        if self.circuit_state is CircuitBreakerState.OPEN:
            if self.health_state is not ProviderHealthState.UNHEALTHY or self.opened_at_ms is None:
                raise ProviderHealthPolicyError("OPEN circuit requires UNHEALTHY state and opened timestamp")
        elif self.circuit_state is CircuitBreakerState.HALF_OPEN:
            if self.health_state is not ProviderHealthState.PROBING:
                raise ProviderHealthPolicyError("HALF_OPEN circuit requires PROBING state")
        elif self.opened_at_ms is not None or self.health_state is ProviderHealthState.PROBING:
            raise ProviderHealthPolicyError("CLOSED circuit cannot retain open/probing state")

    def effective_health(self, now_ms: int, policy: CircuitBreakerPolicy) -> ProviderHealthState:
        _timestamp(now_ms, "now_ms")
        if not isinstance(policy, CircuitBreakerPolicy):
            raise ProviderHealthPolicyError("effective health requires CircuitBreakerPolicy")
        if self.circuit_state is CircuitBreakerState.OPEN:
            if now_ms >= int(self.opened_at_ms or 0) + policy.cooldown_ms:
                return ProviderHealthState.PROBING
            return ProviderHealthState.UNHEALTHY
        if self.circuit_state is CircuitBreakerState.HALF_OPEN:
            return ProviderHealthState.PROBING
        if self.last_evidence_at_ms is None or now_ms - self.last_evidence_at_ms > policy.freshness_ttl_ms:
            return ProviderHealthState.UNKNOWN
        return self.health_state

    def audit(self, now_ms: int, policy: CircuitBreakerPolicy) -> dict[str, Any]:
        return {
            "provider_id": self.provider_ref.provider_id,
            "capability_id": self.provider_ref.capability_id,
            "health_state": self.effective_health(now_ms, policy).value,
            "circuit_state": self.circuit_state.value,
            "revision": self.revision,
            "authority": False,
            "dispatch": False,
            "retry": False,
        }

    def to_artifact_descriptor(self) -> ArtifactDescriptor:
        metadata = {
            "health_schema": self.schema_version,
            "provider_id": self.provider_ref.provider_id,
            "capability_id": self.provider_ref.capability_id,
            "trace_id": self.trace_id,
            "runtime_instance_id": self.current_runtime_instance_id,
            "health_state": self.health_state.value,
            "circuit_state": self.circuit_state.value,
            "consecutive_failures": str(self.consecutive_failures),
            "half_open_probes_admitted": str(self.half_open_probes_admitted),
            "last_signal_kind": _none(self.last_signal_kind.value if self.last_signal_kind else None),
            "last_signal_origin": _none(self.last_signal_origin.value if self.last_signal_origin else None),
            "last_signal_strength": _none(self.last_signal_strength.name if self.last_signal_strength else None),
            "unresolved_failure_strength": _none(
                self.strongest_unresolved_failure_strength.name
                if self.strongest_unresolved_failure_strength
                else None
            ),
            "last_evidence_at_ms": _none(str(self.last_evidence_at_ms) if self.last_evidence_at_ms is not None else None),
            "opened_at_ms": _none(str(self.opened_at_ms) if self.opened_at_ms is not None else None),
            "revision": str(self.revision),
        }
        return ArtifactDescriptor(
            ref=ArtifactRef(
                f"{self.provider_ref.scope_id}.r{self.revision:06d}",
                self.task_id,
                self.session_id,
            ),
            artifact_kind="provider.health-state",
            producer="provider.health-tracker",
            created_at_ms=self.updated_at_ms,
            sensitivity=SensitivityClass.PRIVATE,
            lifetime=ArtifactLifetime.DURABLE,
            opaque_locator=self.provider_ref.scope_id,
            metadata=tuple(metadata.items()),
        )

    @classmethod
    def from_artifact_descriptor(cls, descriptor: ArtifactDescriptor) -> "ProviderHealthSnapshot":
        if descriptor.artifact_kind != "provider.health-state" or descriptor.ref.session_id is None:
            raise ProviderHealthPolicyError("durable record is not ProviderHealthSnapshot")
        metadata = dict(descriptor.metadata)
        required = {
            "health_schema",
            "provider_id",
            "capability_id",
            "trace_id",
            "runtime_instance_id",
            "health_state",
            "circuit_state",
            "consecutive_failures",
            "half_open_probes_admitted",
            "last_signal_kind",
            "last_signal_origin",
            "last_signal_strength",
            "unresolved_failure_strength",
            "last_evidence_at_ms",
            "opened_at_ms",
            "revision",
        }
        if set(metadata) != required:
            raise ProviderHealthPolicyError("ProviderHealthSnapshot durable fields do not match its schema")
        kind = _from_none(metadata["last_signal_kind"])
        origin = _from_none(metadata["last_signal_origin"])
        strength = _from_none(metadata["last_signal_strength"])
        unresolved = _from_none(metadata["unresolved_failure_strength"])
        last_evidence = _from_none(metadata["last_evidence_at_ms"])
        opened = _from_none(metadata["opened_at_ms"])
        return cls(
            provider_ref=ProviderRef(metadata["provider_id"], metadata["capability_id"]),
            task_id=descriptor.ref.task_id,
            session_id=descriptor.ref.session_id,
            trace_id=metadata["trace_id"],
            current_runtime_instance_id=metadata["runtime_instance_id"],
            health_state=ProviderHealthState(metadata["health_state"]),
            circuit_state=CircuitBreakerState(metadata["circuit_state"]),
            consecutive_failures=int(metadata["consecutive_failures"]),
            half_open_probes_admitted=int(metadata["half_open_probes_admitted"]),
            last_signal_kind=ProviderHealthSignalKind(kind) if kind else None,
            last_signal_origin=HealthSignalOrigin(origin) if origin else None,
            last_signal_strength=HealthEvidenceStrength[strength] if strength else None,
            strongest_unresolved_failure_strength=HealthEvidenceStrength[unresolved] if unresolved else None,
            last_evidence_at_ms=int(last_evidence) if last_evidence else None,
            opened_at_ms=int(opened) if opened else None,
            updated_at_ms=descriptor.created_at_ms,
            revision=int(metadata["revision"]),
            schema_version=metadata["health_schema"],
        )


class ProviderHealthTracker:
    """Persistent provider/capability health policy with no dispatch authority."""

    def __init__(
        self,
        store: PhoneHarnessStore,
        runtime_ref: RuntimeInstanceRef,
        method_registry: CapabilityMethodRegistry,
        *,
        policy: CircuitBreakerPolicy | None = None,
        now_ms: Callable[[], int] = _now_ms,
        id_factory: Callable[[str], str] = _new_identifier,
    ) -> None:
        if not isinstance(store, PhoneHarnessStore):
            raise ProviderHealthPolicyError("ProviderHealthTracker requires PhoneHarnessStore")
        if not isinstance(runtime_ref, RuntimeInstanceRef):
            raise ProviderHealthPolicyError("ProviderHealthTracker requires RuntimeInstanceRef")
        if not isinstance(method_registry, CapabilityMethodRegistry):
            raise ProviderHealthPolicyError("ProviderHealthTracker requires the canonical method registry")
        self.store = store
        self.runtime_ref = runtime_ref
        self.method_registry = method_registry
        self.policy = policy or CircuitBreakerPolicy()
        self._now_ms = now_ms
        self._id_factory = id_factory

    def create_snapshot(
        self,
        provider_ref: ProviderRef,
        *,
        task_id: str,
        session_id: str,
        trace_id: str,
    ) -> ProviderHealthSnapshot:
        self.require_registered(provider_ref)
        if self._records(task_id, session_id, provider_ref):
            raise ProviderHealthConflict("provider health scope already exists")
        now = self._now_ms()
        snapshot = ProviderHealthSnapshot(
            provider_ref=provider_ref,
            task_id=task_id,
            session_id=session_id,
            trace_id=trace_id,
            current_runtime_instance_id=self.runtime_ref.runtime_instance_id,
            health_state=ProviderHealthState.UNKNOWN,
            circuit_state=CircuitBreakerState.CLOSED,
            consecutive_failures=0,
            half_open_probes_admitted=0,
            last_signal_kind=None,
            last_signal_origin=None,
            last_signal_strength=None,
            strongest_unresolved_failure_strength=None,
            last_evidence_at_ms=None,
            opened_at_ms=None,
            updated_at_ms=now,
        )
        self._persist(snapshot, "provider_health_initialized")
        return snapshot

    def load_snapshot(
        self,
        provider_ref: ProviderRef,
        *,
        task_id: str,
        session_id: str,
    ) -> ProviderHealthSnapshot:
        self.require_registered(provider_ref)
        records = self._records(task_id, session_id, provider_ref)
        if not records:
            raise ProviderHealthNotFound("provider health scope is unknown")
        return max(records, key=lambda item: item.revision)

    def record_signal(
        self,
        snapshot: ProviderHealthSnapshot,
        signal: ProviderHealthSignal,
    ) -> ProviderHealthSnapshot:
        current = self._require_current(snapshot)
        if signal.provider_ref != current.provider_ref:
            raise ProviderHealthPolicyError("health signal belongs to a different provider scope")
        if signal.observed_at_ms < current.updated_at_ms:
            raise ProviderHealthPolicyError("health signal predates current provider state")

        failures = current.consecutive_failures
        state = current.health_state
        circuit = current.circuit_state
        opened_at = current.opened_at_ms
        admitted = current.half_open_probes_admitted
        unresolved = current.strongest_unresolved_failure_strength

        if signal.failed:
            unresolved = max(unresolved or signal.strength, signal.strength)
            failures = min(self.policy.failure_threshold, failures + 1)
            if circuit is CircuitBreakerState.HALF_OPEN or failures >= self.policy.failure_threshold:
                state = ProviderHealthState.UNHEALTHY
                circuit = CircuitBreakerState.OPEN
                opened_at = signal.observed_at_ms
                admitted = 0
            else:
                state = ProviderHealthState.DEGRADED
        elif signal.kind is ProviderHealthSignalKind.LATENCY_THRESHOLD_EXCEEDED:
            state = ProviderHealthState.DEGRADED
        elif signal.succeeded:
            strong_enough = unresolved is None or signal.strength >= unresolved
            if circuit is CircuitBreakerState.HALF_OPEN:
                if signal.qualified_recovery and strong_enough:
                    state = ProviderHealthState.HEALTHY
                    circuit = CircuitBreakerState.CLOSED
                    opened_at = None
                    admitted = 0
                    failures = 0
                    unresolved = None
                else:
                    state = ProviderHealthState.PROBING
            elif circuit is CircuitBreakerState.OPEN:
                state = ProviderHealthState.UNHEALTHY
            elif strong_enough:
                state = ProviderHealthState.HEALTHY
                failures = 0
                unresolved = None
            else:
                state = ProviderHealthState.DEGRADED

        updated = replace(
            current,
            current_runtime_instance_id=self.runtime_ref.runtime_instance_id,
            health_state=state,
            circuit_state=circuit,
            consecutive_failures=failures,
            half_open_probes_admitted=admitted,
            last_signal_kind=signal.kind,
            last_signal_origin=signal.origin,
            last_signal_strength=signal.strength,
            strongest_unresolved_failure_strength=unresolved,
            last_evidence_at_ms=signal.observed_at_ms,
            opened_at_ms=opened_at,
            updated_at_ms=signal.observed_at_ms,
            revision=current.revision + 1,
        )
        event = "provider_health_changed"
        if current.circuit_state is not CircuitBreakerState.OPEN and circuit is CircuitBreakerState.OPEN:
            event = "circuit_opened"
        elif current.circuit_state is CircuitBreakerState.HALF_OPEN and circuit is CircuitBreakerState.CLOSED:
            event = "circuit_closed"
        elif signal.origin is HealthSignalOrigin.ACTIVE:
            event = "health_probe"
        self._persist(updated, event)
        return updated

    def begin_probe(self, snapshot: ProviderHealthSnapshot) -> ProviderHealthSnapshot:
        current = self._require_current(snapshot)
        now = self._now_ms()
        circuit = current.circuit_state
        if circuit is CircuitBreakerState.OPEN:
            if now < int(current.opened_at_ms or 0) + self.policy.cooldown_ms:
                raise ProviderProbeRejected("OPEN circuit cooldown has not elapsed")
            current = replace(
                current,
                health_state=ProviderHealthState.PROBING,
                circuit_state=CircuitBreakerState.HALF_OPEN,
                opened_at_ms=None,
                half_open_probes_admitted=0,
                current_runtime_instance_id=self.runtime_ref.runtime_instance_id,
                updated_at_ms=now,
                revision=current.revision + 1,
            )
            self._persist(current, "circuit_half_open")
        elif circuit is CircuitBreakerState.CLOSED and current.effective_health(now, self.policy) in {
            ProviderHealthState.UNKNOWN,
            ProviderHealthState.DEGRADED,
        }:
            current = replace(
                current,
                health_state=ProviderHealthState.PROBING,
                circuit_state=CircuitBreakerState.HALF_OPEN,
                half_open_probes_admitted=0,
                current_runtime_instance_id=self.runtime_ref.runtime_instance_id,
                updated_at_ms=now,
                revision=current.revision + 1,
            )
            self._persist(current, "circuit_half_open")
        elif circuit is not CircuitBreakerState.HALF_OPEN:
            raise ProviderProbeRejected("provider does not require a recovery probe")

        if current.half_open_probes_admitted >= self.policy.max_half_open_probes:
            raise ProviderProbeRejected("HALF_OPEN probe budget is exhausted")
        admitted = replace(
            current,
            half_open_probes_admitted=current.half_open_probes_admitted + 1,
            current_runtime_instance_id=self.runtime_ref.runtime_instance_id,
            updated_at_ms=max(now, current.updated_at_ms),
            revision=current.revision + 1,
        )
        self._persist(admitted, "health_probe_admitted")
        return admitted

    def run_active_probe(
        self,
        snapshot: ProviderHealthSnapshot,
        *,
        side_effect_class: SideEffectClass,
        probe: Callable[[], bool],
        strength: HealthEvidenceStrength = HealthEvidenceStrength.WEAK,
        qualified_recovery: bool = False,
    ) -> ProviderHealthSnapshot:
        if SideEffectClass(side_effect_class) is not SideEffectClass.READ_ONLY:
            raise ProviderProbeRejected("active health probes must be read only")
        if not callable(probe):
            raise ProviderProbeRejected("active health probe must be callable")
        admitted = self.begin_probe(snapshot)
        try:
            passed = probe() is True
        except Exception:
            passed = False
        signal = ProviderHealthSignal(
            signal_id=self._id_factory("provider-health-signal"),
            provider_ref=admitted.provider_ref,
            kind=(
                ProviderHealthSignalKind.ACTIVE_PROBE_SUCCEEDED
                if passed
                else ProviderHealthSignalKind.ACTIVE_PROBE_FAILED
            ),
            origin=HealthSignalOrigin.ACTIVE,
            strength=strength,
            observed_at_ms=max(self._now_ms(), admitted.updated_at_ms),
            qualified_recovery=qualified_recovery if passed else False,
        )
        return self.record_signal(admitted, signal)

    def require_registered(self, provider_ref: ProviderRef) -> CapabilityMethodDefinition:
        if not isinstance(provider_ref, ProviderRef):
            raise ProviderHealthPolicyError("provider identity must use ProviderRef")
        for method in self.method_registry.definitions():
            if method.method_id == provider_ref.provider_id:
                if method.capability_id != provider_ref.capability_id:
                    raise ProviderHealthPolicyError("provider is registered for a different capability")
                return method
        raise ProviderHealthPolicyError("provider is not registered in the canonical method registry")

    def _require_current(self, snapshot: ProviderHealthSnapshot) -> ProviderHealthSnapshot:
        if not isinstance(snapshot, ProviderHealthSnapshot):
            raise ProviderHealthPolicyError("provider update requires ProviderHealthSnapshot")
        current = self.load_snapshot(
            snapshot.provider_ref,
            task_id=snapshot.task_id,
            session_id=snapshot.session_id,
        )
        if current.revision != snapshot.revision:
            raise ProviderHealthConflict("provider health revision is no longer current")
        return current

    def _records(
        self,
        task_id: str,
        session_id: str,
        provider_ref: ProviderRef,
    ) -> tuple[ProviderHealthSnapshot, ...]:
        return tuple(
            ProviderHealthSnapshot.from_artifact_descriptor(descriptor)
            for descriptor in self.store.list_artifacts(task_id, session_id=session_id)
            if descriptor.artifact_kind == "provider.health-state"
            and descriptor.opaque_locator == provider_ref.scope_id
        )

    def _persist(self, snapshot: ProviderHealthSnapshot, event_name: str) -> None:
        descriptor = snapshot.to_artifact_descriptor()
        event = TraceEvent(
            event_id=f"trace-event.{descriptor.ref.artifact_id}",
            task_id=snapshot.task_id,
            trace_id=snapshot.trace_id,
            provider_id=snapshot.provider_ref.provider_id,
            capability_id=snapshot.provider_ref.capability_id,
            event_name=event_name,
            observed_timestamp_ms=snapshot.updated_at_ms,
            artifact_refs=(descriptor.ref,),
            attributes=(
                ("health_state", snapshot.health_state.value),
                ("circuit_state", snapshot.circuit_state.value),
                ("revision", str(snapshot.revision)),
            ),
        )
        self.store.record_artifact_and_trace(descriptor, event)


@dataclass(frozen=True)
class FallbackCandidate:
    provider_ref: ProviderRef
    priority: int

    def __post_init__(self) -> None:
        if not isinstance(self.provider_ref, ProviderRef):
            raise ProviderHealthPolicyError("fallback candidate requires ProviderRef")
        _bounded_int(self.priority, "priority", 0, 10_000)


@dataclass(frozen=True)
class FallbackAssessment:
    candidate: FallbackCandidate
    code: FallbackEligibilityCode
    eligible: bool
    health_state: ProviderHealthState
    circuit_state: CircuitBreakerState
    assessed_at_ms: int
    schema_version: str = FALLBACK_ASSESSMENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != FALLBACK_ASSESSMENT_SCHEMA_VERSION:
            raise ProviderHealthPolicyError("unsupported FallbackAssessment schema version")
        if not isinstance(self.candidate, FallbackCandidate):
            raise ProviderHealthPolicyError("fallback assessment requires FallbackCandidate")
        object.__setattr__(self, "code", FallbackEligibilityCode(self.code))
        object.__setattr__(self, "health_state", ProviderHealthState(self.health_state))
        object.__setattr__(self, "circuit_state", CircuitBreakerState(self.circuit_state))
        _timestamp(self.assessed_at_ms, "assessed_at_ms")
        if self.eligible is not (self.code is FallbackEligibilityCode.ELIGIBLE):
            raise ProviderHealthPolicyError("fallback eligibility flag does not match typed code")


@dataclass(frozen=True)
class FallbackDecision:
    decision_id: str
    kind: FallbackDecisionKind
    primary: ProviderRef
    selected: ProviderRef | None
    reason: FallbackEligibilityCode
    assessments: tuple[FallbackAssessment, ...]
    created_at_ms: int
    requires_current_governed_authority: bool = True
    schema_version: str = FALLBACK_DECISION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != FALLBACK_DECISION_SCHEMA_VERSION:
            raise ProviderHealthPolicyError("unsupported FallbackDecision schema version")
        object.__setattr__(self, "decision_id", _identifier(self.decision_id, "decision_id"))
        object.__setattr__(self, "kind", FallbackDecisionKind(self.kind))
        object.__setattr__(self, "reason", FallbackEligibilityCode(self.reason))
        if not isinstance(self.primary, ProviderRef):
            raise ProviderHealthPolicyError("fallback decision requires primary ProviderRef")
        if self.selected is not None and not isinstance(self.selected, ProviderRef):
            raise ProviderHealthPolicyError("fallback selected provider must use ProviderRef")
        if any(not isinstance(item, FallbackAssessment) for item in self.assessments):
            raise ProviderHealthPolicyError("fallback decision assessments must be typed")
        _timestamp(self.created_at_ms, "created_at_ms")
        if self.requires_current_governed_authority is not True:
            raise ProviderHealthPolicyError("fallback cannot waive current governed authority")
        if self.kind in {FallbackDecisionKind.USE_PRIMARY, FallbackDecisionKind.USE_ALTERNATE}:
            if self.selected is None or self.reason is not FallbackEligibilityCode.ELIGIBLE:
                raise ProviderHealthPolicyError("provider-use decision requires an eligible selection")
        elif self.selected is not None:
            raise ProviderHealthPolicyError("blocked fallback decision cannot select a provider")

    def audit(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "kind": self.kind.value,
            "reason": self.reason.value,
            "selected_provider": self.selected.provider_id if self.selected else None,
            "authority": False,
            "dispatch": False,
            "retry": False,
            "requires_current_governed_authority": True,
            "same_attempt_dispatch_count": 0,
        }


class FallbackPolicy:
    """Deterministic selection advice over the existing canonical registry."""

    def __init__(
        self,
        method_registry: CapabilityMethodRegistry,
        health_tracker: ProviderHealthTracker,
        *,
        owned_service_provider_ids: Iterable[str] = (),
        now_ms: Callable[[], int] = _now_ms,
        id_factory: Callable[[str], str] = _new_identifier,
    ) -> None:
        if not isinstance(method_registry, CapabilityMethodRegistry):
            raise ProviderHealthPolicyError("FallbackPolicy requires the canonical method registry")
        if not isinstance(health_tracker, ProviderHealthTracker) or health_tracker.method_registry is not method_registry:
            raise ProviderHealthPolicyError("FallbackPolicy and health tracker must share one canonical registry")
        self.method_registry = method_registry
        self.health_tracker = health_tracker
        self.owned_service_provider_ids = frozenset(
            _identifier(value, "owned_service_provider_id") for value in owned_service_provider_ids
        )
        self._now_ms = now_ms
        self._id_factory = id_factory

    def decide(
        self,
        *,
        primary: FallbackCandidate,
        alternates: Iterable[FallbackCandidate],
        task_id: str,
        session_id: str,
        trace_id: str,
        dispatch_status: DispatchStatus,
        reconciliation_state: ReconciliationState | None,
        primary_failure_pre_dispatch: bool,
        available_tools: Iterable[str],
        available_permissions: Iterable[str],
        available_platforms: Iterable[str],
    ) -> FallbackDecision:
        now = self._now_ms()
        dispatch = DispatchStatus(dispatch_status)
        if reconciliation_state is not None:
            reconciliation_state = ReconciliationState(reconciliation_state)
        candidates = (primary,) + tuple(alternates)
        if len({item.provider_ref.provider_id for item in candidates}) != len(candidates):
            raise ProviderHealthPolicyError("fallback candidate provider IDs must be unique")
        tools = frozenset(str(value) for value in available_tools)
        permissions = frozenset(str(value) for value in available_permissions)
        platforms = frozenset(str(value) for value in available_platforms)
        assessments = tuple(
            self._assess(
                candidate,
                task_id=task_id,
                session_id=session_id,
                tools=tools,
                permissions=permissions,
                platforms=platforms,
                now=now,
                expected_capability_id=primary.provider_ref.capability_id,
            )
            for candidate in candidates
        )

        if dispatch is not DispatchStatus.NOT_DISPATCHED:
            reason = FallbackEligibilityCode.POSSIBLE_DISPATCH
            return self._decision(primary, assessments, FallbackDecisionKind.FALLBACK_NOT_ALLOWED, reason, None, now, task_id, trace_id)
        if reconciliation_state is ReconciliationState.EVIDENCE_CONFLICT:
            return self._decision(primary, assessments, FallbackDecisionKind.FALLBACK_NOT_ALLOWED, FallbackEligibilityCode.EVIDENCE_CONFLICT, None, now, task_id, trace_id)
        if reconciliation_state in {
            ReconciliationState.OPEN,
            ReconciliationState.OBSERVING,
            ReconciliationState.UNRESOLVED,
            ReconciliationState.CLOSED_FAIL_SAFE,
            ReconciliationState.WAITING_FOR_USER,
        }:
            return self._decision(primary, assessments, FallbackDecisionKind.FALLBACK_NOT_ALLOWED, FallbackEligibilityCode.UNKNOWN_OUTCOME, None, now, task_id, trace_id)

        primary_assessment = assessments[0]
        if primary_assessment.eligible and not primary_failure_pre_dispatch:
            return self._decision(primary, assessments, FallbackDecisionKind.USE_PRIMARY, FallbackEligibilityCode.ELIGIBLE, primary.provider_ref, now, task_id, trace_id)
        if not primary_failure_pre_dispatch:
            if primary_assessment.code in {
                FallbackEligibilityCode.PROBE_REQUIRED,
                FallbackEligibilityCode.PROVIDER_STALE,
                FallbackEligibilityCode.PROVIDER_UNKNOWN,
            }:
                return self._decision(primary, assessments, FallbackDecisionKind.PROBE_REQUIRED, FallbackEligibilityCode.PROBE_REQUIRED, None, now, task_id, trace_id)
            reason = (
                FallbackEligibilityCode.CIRCUIT_OPEN
                if primary_assessment.code is FallbackEligibilityCode.CIRCUIT_OPEN
                else FallbackEligibilityCode.PRE_DISPATCH_FAILURE_NOT_PROVEN
            )
            kind = FallbackDecisionKind.CIRCUIT_OPEN if reason is FallbackEligibilityCode.CIRCUIT_OPEN else FallbackDecisionKind.FALLBACK_NOT_ALLOWED
            return self._decision(primary, assessments, kind, reason, None, now, task_id, trace_id)

        eligible_alternates = sorted(
            (item for item in assessments[1:] if item.eligible),
            key=lambda item: (item.candidate.priority, item.candidate.provider_ref.provider_id),
        )
        if eligible_alternates:
            selected = eligible_alternates[0].candidate.provider_ref
            return self._decision(primary, assessments, FallbackDecisionKind.USE_ALTERNATE, FallbackEligibilityCode.ELIGIBLE, selected, now, task_id, trace_id)
        if any(item.code in {FallbackEligibilityCode.PROBE_REQUIRED, FallbackEligibilityCode.PROVIDER_STALE, FallbackEligibilityCode.PROVIDER_UNKNOWN} for item in assessments[1:]):
            return self._decision(primary, assessments, FallbackDecisionKind.PROBE_REQUIRED, FallbackEligibilityCode.PROBE_REQUIRED, None, now, task_id, trace_id)
        return self._decision(primary, assessments, FallbackDecisionKind.NO_HEALTHY_PROVIDER, FallbackEligibilityCode.PROVIDER_UNHEALTHY, None, now, task_id, trace_id)

    def service_recovery_disposition(
        self,
        provider_ref: ProviderRef,
        *,
        task_id: str,
        session_id: str,
    ) -> OwnedServiceRecoveryDisposition:
        try:
            self.health_tracker.require_registered(provider_ref)
        except ProviderHealthPolicyError:
            return OwnedServiceRecoveryDisposition.NOT_OWNED_FAIL_CLOSED
        if provider_ref.provider_id not in self.owned_service_provider_ids:
            return OwnedServiceRecoveryDisposition.NOT_OWNED_FAIL_CLOSED
        snapshot = self.health_tracker.load_snapshot(
            provider_ref,
            task_id=task_id,
            session_id=session_id,
        )
        if snapshot.circuit_state is CircuitBreakerState.OPEN or snapshot.health_state is ProviderHealthState.UNHEALTHY:
            return OwnedServiceRecoveryDisposition.OWNED_SERVICE_RECOVERY_REQUIRED
        return OwnedServiceRecoveryDisposition.NOT_REQUIRED

    def _assess(
        self,
        candidate: FallbackCandidate,
        *,
        task_id: str,
        session_id: str,
        tools: frozenset[str],
        permissions: frozenset[str],
        platforms: frozenset[str],
        now: int,
        expected_capability_id: str,
    ) -> FallbackAssessment:
        if candidate.provider_ref.capability_id != expected_capability_id:
            return self._assessment(candidate, FallbackEligibilityCode.WRONG_CAPABILITY, ProviderHealthState.UNKNOWN, CircuitBreakerState.CLOSED, now)
        method = self._registered_method(candidate.provider_ref.provider_id)
        if method is None:
            return self._assessment(candidate, FallbackEligibilityCode.UNREGISTERED_PROVIDER, ProviderHealthState.UNKNOWN, CircuitBreakerState.CLOSED, now)
        if method.capability_id != candidate.provider_ref.capability_id:
            return self._assessment(candidate, FallbackEligibilityCode.WRONG_CAPABILITY, ProviderHealthState.UNKNOWN, CircuitBreakerState.CLOSED, now)
        capability = self._capability(method.capability_id)
        if capability is None:
            return self._assessment(candidate, FallbackEligibilityCode.WRONG_CAPABILITY, ProviderHealthState.UNKNOWN, CircuitBreakerState.CLOSED, now)
        if method.lifecycle != "ACTIVE":
            return self._assessment(candidate, FallbackEligibilityCode.METHOD_NOT_ACTIVE, ProviderHealthState.UNKNOWN, CircuitBreakerState.CLOSED, now)
        if method.availability != "available":
            return self._assessment(candidate, FallbackEligibilityCode.METHOD_UNAVAILABLE, ProviderHealthState.UNKNOWN, CircuitBreakerState.CLOSED, now)
        if not capability.required_tools.issubset(tools):
            return self._assessment(candidate, FallbackEligibilityCode.REQUIRED_TOOLS_UNAVAILABLE, ProviderHealthState.UNKNOWN, CircuitBreakerState.CLOSED, now)
        if not set(capability.required_permissions).union(method.required_permissions).issubset(permissions):
            return self._assessment(candidate, FallbackEligibilityCode.REQUIRED_PERMISSIONS_UNAVAILABLE, ProviderHealthState.UNKNOWN, CircuitBreakerState.CLOSED, now)
        if not set(capability.platform_support).intersection(platforms) or not set(method.platform_support).intersection(platforms):
            return self._assessment(candidate, FallbackEligibilityCode.PLATFORM_INCOMPATIBLE, ProviderHealthState.UNKNOWN, CircuitBreakerState.CLOSED, now)
        if method.risk_level != capability.risk_level:
            return self._assessment(candidate, FallbackEligibilityCode.SIDE_EFFECT_INCOMPATIBLE, ProviderHealthState.UNKNOWN, CircuitBreakerState.CLOSED, now)
        if capability.target_requirement.value not in {"NONE", "FRESH_TARGET_REQUIRED"}:
            return self._assessment(candidate, FallbackEligibilityCode.TARGET_SEMANTICS_INCOMPATIBLE, ProviderHealthState.UNKNOWN, CircuitBreakerState.CLOSED, now)
        if capability.binding_required and capability.target_binding_kind == "none":
            return self._assessment(candidate, FallbackEligibilityCode.BINDING_INCOMPATIBLE, ProviderHealthState.UNKNOWN, CircuitBreakerState.CLOSED, now)
        if method.verifier != capability.verifier_id:
            return self._assessment(candidate, FallbackEligibilityCode.VERIFIER_UNAVAILABLE, ProviderHealthState.UNKNOWN, CircuitBreakerState.CLOSED, now)
        try:
            snapshot = self.health_tracker.load_snapshot(
                candidate.provider_ref,
                task_id=task_id,
                session_id=session_id,
            )
        except ProviderHealthNotFound:
            return self._assessment(candidate, FallbackEligibilityCode.PROVIDER_UNKNOWN, ProviderHealthState.UNKNOWN, CircuitBreakerState.CLOSED, now)
        effective = snapshot.effective_health(now, self.health_tracker.policy)
        if snapshot.circuit_state is CircuitBreakerState.OPEN:
            code = FallbackEligibilityCode.PROBE_REQUIRED if effective is ProviderHealthState.PROBING else FallbackEligibilityCode.CIRCUIT_OPEN
            return self._assessment(candidate, code, effective, snapshot.circuit_state, now)
        if effective is ProviderHealthState.PROBING:
            return self._assessment(candidate, FallbackEligibilityCode.PROBE_REQUIRED, effective, snapshot.circuit_state, now)
        if effective is ProviderHealthState.UNKNOWN:
            code = FallbackEligibilityCode.PROVIDER_STALE if snapshot.last_evidence_at_ms is not None else FallbackEligibilityCode.PROVIDER_UNKNOWN
            return self._assessment(candidate, code, effective, snapshot.circuit_state, now)
        if effective is ProviderHealthState.DEGRADED:
            return self._assessment(candidate, FallbackEligibilityCode.PROVIDER_DEGRADED, effective, snapshot.circuit_state, now)
        if effective is ProviderHealthState.UNHEALTHY:
            return self._assessment(candidate, FallbackEligibilityCode.PROVIDER_UNHEALTHY, effective, snapshot.circuit_state, now)
        return self._assessment(candidate, FallbackEligibilityCode.ELIGIBLE, effective, snapshot.circuit_state, now)

    @staticmethod
    def _assessment(
        candidate: FallbackCandidate,
        code: FallbackEligibilityCode,
        health: ProviderHealthState,
        circuit: CircuitBreakerState,
        now: int,
    ) -> FallbackAssessment:
        return FallbackAssessment(candidate, code, code is FallbackEligibilityCode.ELIGIBLE, health, circuit, now)

    def _decision(
        self,
        primary: FallbackCandidate,
        assessments: tuple[FallbackAssessment, ...],
        kind: FallbackDecisionKind,
        reason: FallbackEligibilityCode,
        selected: ProviderRef | None,
        now: int,
        task_id: str,
        trace_id: str,
    ) -> FallbackDecision:
        decision = FallbackDecision(
            decision_id=self._id_factory("fallback-decision"),
            kind=kind,
            primary=primary.provider_ref,
            selected=selected,
            reason=reason,
            assessments=assessments,
            created_at_ms=now,
        )
        event_name = {
            FallbackDecisionKind.USE_PRIMARY: "fallback_considered",
            FallbackDecisionKind.USE_ALTERNATE: "fallback_selected",
            FallbackDecisionKind.NO_HEALTHY_PROVIDER: "no_healthy_provider",
            FallbackDecisionKind.SERVICE_RECOVERY_REQUIRED: "service_recovery_required",
        }.get(kind, "fallback_denied")
        self.health_tracker.store.append_trace_event(
            TraceEvent(
                event_id=f"trace-event.{decision.decision_id}",
                task_id=task_id,
                trace_id=trace_id,
                provider_id=selected.provider_id if selected else primary.provider_ref.provider_id,
                capability_id=primary.provider_ref.capability_id,
                event_name=event_name,
                observed_timestamp_ms=now,
                attributes=(("decision_kind", kind.value), ("reason_code", reason.value)),
            )
        )
        return decision

    def _registered_method(self, provider_id: str) -> CapabilityMethodDefinition | None:
        return next((item for item in self.method_registry.definitions() if item.method_id == provider_id), None)

    def _capability(self, capability_id: str) -> CapabilityDefinition | None:
        return next((item for item in self.method_registry.catalog.definitions() if item.capability_id == capability_id), None)


__all__ = [
    "CircuitBreakerPolicy",
    "CircuitBreakerState",
    "FallbackAssessment",
    "FallbackCandidate",
    "FallbackDecision",
    "FallbackDecisionKind",
    "FallbackEligibilityCode",
    "FallbackPolicy",
    "HealthEvidenceStrength",
    "HealthSignalOrigin",
    "OwnedServiceRecoveryDisposition",
    "ProviderHealthConflict",
    "ProviderHealthError",
    "ProviderHealthNotFound",
    "ProviderHealthPolicyError",
    "ProviderHealthSignal",
    "ProviderHealthSignalKind",
    "ProviderHealthSnapshot",
    "ProviderHealthState",
    "ProviderHealthTracker",
    "ProviderProbeRejected",
    "ProviderRef",
]
