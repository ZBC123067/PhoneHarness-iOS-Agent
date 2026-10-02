#!/usr/bin/env python3
"""Immutable observation snapshots, scoped epochs, and freshness gates.

This Host-only foundation coordinates observation evidence. It cannot
authorize, bind, dispatch, verify, retry, resume, or mutate device state.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
import threading
import time
from typing import Any, Callable, Iterable, Mapping
import uuid

from phoneharness_contracts import (
    ArtifactDescriptor,
    ArtifactLifetime,
    ArtifactRef,
    ObservationFreshness,
    ObservationRef,
    ObservedTargetRef,
    SensitivityClass,
)
from phoneharness_store import PhoneHarnessStore, TraceEvent


OBSERVATION_SCOPE_SCHEMA = "phoneharness.observation-scope.v1"
OBSERVATION_EPOCH_SCHEMA = "phoneharness.observation-epoch.v1"
OBSERVATION_SNAPSHOT_SCHEMA = "phoneharness.observation-snapshot.v1"
OBSERVATION_INVALIDATION_SCHEMA = "phoneharness.observation-invalidation.v1"
FRESHNESS_REQUIREMENT_SCHEMA = "phoneharness.freshness-requirement.v1"
FRESHNESS_ASSESSMENT_SCHEMA = "phoneharness.freshness-assessment.v1"
MAX_SNAPSHOT_METADATA_ITEMS = 16
MAX_IN_MEMORY_SNAPSHOTS = 256

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_SECRET_VALUE_PATTERNS = (
    re.compile(r"(?i)^bearer\s+\S+"),
    re.compile(r"(?i)^(?:sk|ghp|github_pat|xox[baprs])[-_]\S+"),
    re.compile(r"^eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$"),
)
_FORBIDDEN_FIELD_WORDS = frozenset(
    {
        "authorization",
        "binding",
        "credential",
        "executorauthority",
        "executorport",
        "otp",
        "passcode",
        "password",
        "privatekey",
        "secret",
        "token",
        "chainofthought",
    }
)


class ObservationError(RuntimeError):
    """Base class for deterministic observation-foundation failures."""


class ObservationPolicyError(ObservationError):
    """Observation input or lifecycle violated the bounded policy."""


class ObservationScopeMismatch(ObservationError):
    """An observation was used outside its exact scope."""


class ObservationNotFound(ObservationError):
    """An observation reference is not present in the active tracker."""


class ObservationStateConflict(ObservationError):
    """Observation state changed without an explicit invalidation boundary."""


class ObservationFreshnessRequired(ObservationError):
    """Current evidence was required but the assessment failed closed."""


class InvalidationReason(str, Enum):
    MUTATION_DISPATCH = "MUTATION_DISPATCH"
    FRONTMOST_TRANSITION = "FRONTMOST_TRANSITION"
    RUNTIME_TRANSITION = "RUNTIME_TRANSITION"
    SESSION_TRANSITION = "SESSION_TRANSITION"
    EXPLICIT = "EXPLICIT"
    USER_ACTION = "USER_ACTION"
    RECONCILIATION = "RECONCILIATION"
    SOURCE_REPLACED = "SOURCE_REPLACED"


class FreshnessRequirementKind(str, Enum):
    ANY_VALID = "ANY_VALID"
    CURRENT_EPOCH = "CURRENT_EPOCH"
    POST_DISPATCH = "POST_DISPATCH"
    POST_RESTART = "POST_RESTART"
    NEWER_THAN = "NEWER_THAN"


class FreshnessState(str, Enum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"
    INVALIDATED = "INVALIDATED"


class FreshnessReason(str, Enum):
    SATISFIED = "SATISFIED"
    UNKNOWN_OBSERVATION = "UNKNOWN_OBSERVATION"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    SCOPE_MISMATCH = "SCOPE_MISMATCH"
    RUNTIME_MISMATCH = "RUNTIME_MISMATCH"
    EPOCH_INVALIDATED = "EPOCH_INVALIDATED"
    FUTURE_EPOCH = "FUTURE_EPOCH"
    GENERATION_SUPERSEDED = "GENERATION_SUPERSEDED"
    AGE_EXCEEDED = "AGE_EXCEEDED"
    BOUNDARY_NOT_CROSSED = "BOUNDARY_NOT_CROSSED"
    REFERENCE_NOT_EXCEEDED = "REFERENCE_NOT_EXCEEDED"
    REFERENCE_SCOPE_MISMATCH = "REFERENCE_SCOPE_MISMATCH"


def _identifier(value: Any, field_name: str) -> str:
    normalized = str(value or "").strip()
    if _IDENTIFIER.fullmatch(normalized) is None:
        raise ObservationPolicyError(f"{field_name} must be an opaque bounded identifier")
    return normalized


def _optional_identifier(value: Any, field_name: str) -> str | None:
    return None if value is None else _identifier(value, field_name)


def _non_negative(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ObservationPolicyError(f"{field_name} must be a non-negative integer")
    return value


def _positive(value: Any, field_name: str) -> int:
    result = _non_negative(value, field_name)
    if result == 0:
        raise ObservationPolicyError(f"{field_name} must be positive")
    return result


def _field_words(key: str) -> set[str]:
    words = {part.casefold() for part in re.split(r"[._:-]+", key) if part}
    words.add(re.sub(r"[^a-z0-9]", "", key.casefold()))
    return words


def _safe_metadata(
    value: Mapping[str, Any] | Iterable[tuple[str, Any]],
    field_name: str,
) -> tuple[tuple[str, str], ...]:
    items = value.items() if isinstance(value, Mapping) else value
    normalized: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw_key, raw_value in items:
        key = _identifier(raw_key, f"{field_name} key")
        if _field_words(key) & _FORBIDDEN_FIELD_WORDS:
            raise ObservationPolicyError(f"{field_name} cannot contain authority or secret fields")
        text = " ".join(str(raw_value or "").split())
        if not text or len(text) > 256 or any(pattern.search(text) for pattern in _SECRET_VALUE_PATTERNS):
            raise ObservationPolicyError(f"{field_name} value must be bounded and non-secret")
        if key in seen:
            raise ObservationPolicyError(f"{field_name} cannot contain duplicate keys")
        seen.add(key)
        normalized.append((key, text))
    if len(normalized) > MAX_SNAPSHOT_METADATA_ITEMS:
        raise ObservationPolicyError(f"{field_name} exceeds its bounded size")
    return tuple(sorted(normalized))


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _new_identifier(prefix: str) -> str:
    return f"{prefix}.{uuid.uuid4().hex}"


@dataclass(frozen=True)
class ObservationScope:
    scope_id: str
    task_id: str
    session_id: str
    runtime_instance_id: str
    source: str
    frontmost_app_id: str | None = None
    process_instance_ref: str | None = None
    schema_version: str = OBSERVATION_SCOPE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != OBSERVATION_SCOPE_SCHEMA:
            raise ObservationPolicyError("unsupported ObservationScope schema version")
        for name in ("scope_id", "task_id", "session_id", "runtime_instance_id", "source"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(self, "frontmost_app_id", _optional_identifier(self.frontmost_app_id, "frontmost_app_id"))
        object.__setattr__(
            self,
            "process_instance_ref",
            _optional_identifier(self.process_instance_ref, "process_instance_ref"),
        )

    def audit(self) -> dict[str, Any]:
        return {
            "scope_id": self.scope_id,
            "task_id": self.task_id,
            "session_id": self.session_id,
            "runtime_instance_id": self.runtime_instance_id,
            "source": self.source,
            "authorization": False,
        }


@dataclass(frozen=True)
class ObservationEpoch:
    scope_id: str
    value: int
    started_at_ms: int
    schema_version: str = OBSERVATION_EPOCH_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != OBSERVATION_EPOCH_SCHEMA:
            raise ObservationPolicyError("unsupported ObservationEpoch schema version")
        object.__setattr__(self, "scope_id", _identifier(self.scope_id, "scope_id"))
        _positive(self.value, "epoch value")
        _non_negative(self.started_at_ms, "epoch started_at_ms")


@dataclass(frozen=True)
class ObservationSnapshot:
    observation_ref: ObservationRef
    scope: ObservationScope
    epoch: ObservationEpoch
    generation: int
    captured_at_ms: int
    artifact_refs: tuple[ArtifactRef, ...] = ()
    evidence: tuple[tuple[str, str], ...] = ()
    secure_ui_present: bool | None = None
    fingerprint: str | None = None
    schema_version: str = OBSERVATION_SNAPSHOT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != OBSERVATION_SNAPSHOT_SCHEMA:
            raise ObservationPolicyError("unsupported ObservationSnapshot schema version")
        if not isinstance(self.observation_ref, ObservationRef):
            raise ObservationPolicyError("ObservationSnapshot requires ObservationRef")
        if not isinstance(self.scope, ObservationScope) or not isinstance(self.epoch, ObservationEpoch):
            raise ObservationPolicyError("ObservationSnapshot requires typed scope and epoch")
        _positive(self.generation, "generation")
        _non_negative(self.captured_at_ms, "captured_at_ms")
        if (
            self.epoch.scope_id != self.scope.scope_id
            or self.observation_ref.task_id != self.scope.task_id
            or self.observation_ref.session_id != self.scope.session_id
            or self.observation_ref.producer != self.scope.source
            or self.observation_ref.generation != self.generation
            or self.observation_ref.observed_at_ms != self.captured_at_ms
            or self.observation_ref.freshness is not ObservationFreshness.FRESH
        ):
            raise ObservationScopeMismatch("snapshot reference does not match its exact observation scope")
        refs = tuple(self.artifact_refs)
        if len(refs) > 32 or any(not isinstance(ref, ArtifactRef) for ref in refs):
            raise ObservationPolicyError("snapshot artifact references must be bounded and typed")
        if len({ref.artifact_id for ref in refs}) != len(refs):
            raise ObservationPolicyError("snapshot artifact references must be unique")
        if any(ref.task_id != self.scope.task_id or ref.session_id not in (None, self.scope.session_id) for ref in refs):
            raise ObservationScopeMismatch("snapshot artifact scope does not match")
        object.__setattr__(self, "artifact_refs", refs)
        object.__setattr__(self, "evidence", _safe_metadata(self.evidence, "snapshot evidence"))
        if self.secure_ui_present is not None and not isinstance(self.secure_ui_present, bool):
            raise ObservationPolicyError("secure_ui_present must be a boolean or unknown")
        if self.fingerprint is not None and _DIGEST.fullmatch(self.fingerprint) is None:
            raise ObservationPolicyError("snapshot fingerprint must be lowercase SHA-256")

    def audit(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "observation_id": self.observation_ref.observation_id,
            "scope_id": self.scope.scope_id,
            "epoch": self.epoch.value,
            "generation": self.generation,
            "artifact_ref_count": len(self.artifact_refs),
            "secure_ui_known": self.secure_ui_present is not None,
            "fingerprint_present": self.fingerprint is not None,
            "authorization": False,
            "semantic_success": False,
        }


@dataclass(frozen=True)
class ObservationInvalidation:
    invalidation_id: str
    scope_id: str
    previous_epoch: int
    next_epoch: int
    reason: InvalidationReason
    invalidated_at_ms: int
    schema_version: str = OBSERVATION_INVALIDATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != OBSERVATION_INVALIDATION_SCHEMA:
            raise ObservationPolicyError("unsupported ObservationInvalidation schema version")
        object.__setattr__(self, "invalidation_id", _identifier(self.invalidation_id, "invalidation_id"))
        object.__setattr__(self, "scope_id", _identifier(self.scope_id, "scope_id"))
        _positive(self.previous_epoch, "previous_epoch")
        _positive(self.next_epoch, "next_epoch")
        if self.next_epoch != self.previous_epoch + 1:
            raise ObservationPolicyError("observation epoch must advance exactly once per invalidation")
        object.__setattr__(self, "reason", InvalidationReason(self.reason))
        _non_negative(self.invalidated_at_ms, "invalidated_at_ms")


@dataclass(frozen=True)
class FreshnessRequirement:
    kind: FreshnessRequirementKind
    reference: ObservationRef | None = None
    boundary_epoch: int | None = None
    boundary_at_ms: int | None = None
    max_age_ms: int | None = None
    schema_version: str = FRESHNESS_REQUIREMENT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != FRESHNESS_REQUIREMENT_SCHEMA:
            raise ObservationPolicyError("unsupported FreshnessRequirement schema version")
        object.__setattr__(self, "kind", FreshnessRequirementKind(self.kind))
        if self.max_age_ms is not None:
            _positive(self.max_age_ms, "max_age_ms")
        if self.kind is FreshnessRequirementKind.NEWER_THAN:
            if not isinstance(self.reference, ObservationRef):
                raise ObservationPolicyError("NEWER_THAN requires ObservationRef")
            if self.boundary_epoch is not None or self.boundary_at_ms is not None:
                raise ObservationPolicyError("NEWER_THAN cannot carry a dispatch/restart boundary")
        elif self.kind in {FreshnessRequirementKind.POST_DISPATCH, FreshnessRequirementKind.POST_RESTART}:
            if self.reference is not None or self.boundary_epoch is None or self.boundary_at_ms is None:
                raise ObservationPolicyError("post-boundary freshness requires epoch and timestamp")
            _positive(self.boundary_epoch, "boundary_epoch")
            _non_negative(self.boundary_at_ms, "boundary_at_ms")
        elif any(value is not None for value in (self.reference, self.boundary_epoch, self.boundary_at_ms)):
            raise ObservationPolicyError("freshness requirement carries incompatible fields")

    @classmethod
    def any_valid(cls, *, max_age_ms: int | None = None) -> "FreshnessRequirement":
        return cls(FreshnessRequirementKind.ANY_VALID, max_age_ms=max_age_ms)

    @classmethod
    def current_epoch(cls, *, max_age_ms: int | None = None) -> "FreshnessRequirement":
        return cls(FreshnessRequirementKind.CURRENT_EPOCH, max_age_ms=max_age_ms)

    @classmethod
    def newer_than(cls, reference: ObservationRef, *, max_age_ms: int | None = None) -> "FreshnessRequirement":
        return cls(FreshnessRequirementKind.NEWER_THAN, reference=reference, max_age_ms=max_age_ms)

    @classmethod
    def post_dispatch(cls, invalidation: ObservationInvalidation) -> "FreshnessRequirement":
        if not isinstance(invalidation, ObservationInvalidation) or invalidation.reason is not InvalidationReason.MUTATION_DISPATCH:
            raise ObservationPolicyError("POST_DISPATCH requires a mutation invalidation boundary")
        return cls(
            FreshnessRequirementKind.POST_DISPATCH,
            boundary_epoch=invalidation.previous_epoch,
            boundary_at_ms=invalidation.invalidated_at_ms,
        )

    @classmethod
    def post_restart(cls, invalidation: ObservationInvalidation) -> "FreshnessRequirement":
        if not isinstance(invalidation, ObservationInvalidation) or invalidation.reason is not InvalidationReason.RUNTIME_TRANSITION:
            raise ObservationPolicyError("POST_RESTART requires a runtime-transition boundary")
        return cls(
            FreshnessRequirementKind.POST_RESTART,
            boundary_epoch=invalidation.previous_epoch,
            boundary_at_ms=invalidation.invalidated_at_ms,
        )


@dataclass(frozen=True)
class FreshnessAssessment:
    observation_ref: ObservationRef
    requirement: FreshnessRequirementKind
    state: FreshnessState
    reason: FreshnessReason
    evaluated_at_ms: int
    current_epoch: int | None
    satisfies: bool
    schema_version: str = FRESHNESS_ASSESSMENT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != FRESHNESS_ASSESSMENT_SCHEMA:
            raise ObservationPolicyError("unsupported FreshnessAssessment schema version")
        if not isinstance(self.observation_ref, ObservationRef):
            raise ObservationPolicyError("FreshnessAssessment requires ObservationRef")
        object.__setattr__(self, "requirement", FreshnessRequirementKind(self.requirement))
        object.__setattr__(self, "state", FreshnessState(self.state))
        object.__setattr__(self, "reason", FreshnessReason(self.reason))
        _non_negative(self.evaluated_at_ms, "evaluated_at_ms")
        if self.current_epoch is not None:
            _positive(self.current_epoch, "current_epoch")
        if not isinstance(self.satisfies, bool):
            raise ObservationPolicyError("freshness satisfaction must be boolean")
        if self.satisfies != (self.state is FreshnessState.CURRENT and self.reason is FreshnessReason.SATISFIED):
            raise ObservationPolicyError("freshness result is internally inconsistent")

    def audit(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_ref.observation_id,
            "requirement": self.requirement.value,
            "state": self.state.value,
            "reason": self.reason.value,
            "satisfies": self.satisfies,
            "authorization": False,
            "semantic_success": False,
        }


@dataclass
class _ScopeState:
    scope: ObservationScope
    epoch: int
    generation: int
    epoch_started_at_ms: int
    source_available: bool = True
    latest_observation_id: str | None = None


class ObservationTracker:
    """Bounded in-memory freshness coordinator backed by the S3-M1 store.

    Durable records are evidence only. Reopening the store does not reconstruct
    current-world state; a new tracker requires a new observation boundary.
    """

    def __init__(
        self,
        store: PhoneHarnessStore | None = None,
        *,
        now_ms: Callable[[], int] = _now_ms,
        id_factory: Callable[[str], str] = _new_identifier,
        max_snapshots: int = MAX_IN_MEMORY_SNAPSHOTS,
    ) -> None:
        if store is not None and not isinstance(store, PhoneHarnessStore):
            raise ObservationPolicyError("ObservationTracker requires PhoneHarnessStore or no durable store")
        _positive(max_snapshots, "max_snapshots")
        self.store = store
        self._now_ms = now_ms
        self._id_factory = id_factory
        self._max_snapshots = max_snapshots
        self._states: dict[str, _ScopeState] = {}
        self._snapshots: dict[str, ObservationSnapshot] = {}
        self._snapshot_order: list[str] = []
        self._mutex = threading.RLock()

    def capture(
        self,
        scope: ObservationScope,
        *,
        trace_id: str,
        artifact_refs: Iterable[ArtifactRef] = (),
        evidence: Mapping[str, Any] | Iterable[tuple[str, Any]] = (),
        secure_ui_present: bool | None = None,
        fingerprint: str | None = None,
        captured_at_ms: int | None = None,
    ) -> ObservationSnapshot:
        if not isinstance(scope, ObservationScope):
            raise ObservationPolicyError("capture requires ObservationScope")
        trace = _identifier(trace_id, "trace_id")
        with self._mutex:
            timestamp = self._now_ms() if captured_at_ms is None else _non_negative(captured_at_ms, "captured_at_ms")
            state = self._states.get(scope.scope_id)
            if state is None:
                state = _ScopeState(scope, 1, 0, timestamp)
            elif state.scope != scope:
                raise ObservationStateConflict("scope changed without explicit invalidation")
            if not state.source_available:
                raise ObservationFreshnessRequired("observation source is unavailable")
            generation = state.generation + 1
            reference = ObservationRef(
                self._id_factory("observation"),
                scope.source,
                scope.task_id,
                scope.session_id,
                generation=generation,
                observed_at_ms=timestamp,
                freshness=ObservationFreshness.FRESH,
            )
            snapshot = ObservationSnapshot(
                reference,
                scope,
                ObservationEpoch(scope.scope_id, state.epoch, state.epoch_started_at_ms),
                generation,
                timestamp,
                tuple(artifact_refs),
                _safe_metadata(evidence, "snapshot evidence"),
                secure_ui_present,
                fingerprint,
            )
            self._persist_snapshot(snapshot, trace)
            state.generation = generation
            state.latest_observation_id = reference.observation_id
            self._states[scope.scope_id] = state
            self._snapshots[reference.observation_id] = snapshot
            self._snapshot_order.append(reference.observation_id)
            self._trim_history()
            return snapshot

    def invalidate(
        self,
        scope: ObservationScope,
        reason: InvalidationReason,
        *,
        trace_id: str,
        replacement_scope: ObservationScope | None = None,
        invalidated_at_ms: int | None = None,
    ) -> ObservationInvalidation:
        if not isinstance(scope, ObservationScope):
            raise ObservationPolicyError("invalidation requires ObservationScope")
        trace = _identifier(trace_id, "trace_id")
        reason = InvalidationReason(reason)
        with self._mutex:
            state = self._states.get(scope.scope_id)
            if state is None or state.scope != scope:
                raise ObservationScopeMismatch("invalidation requires the current exact scope")
            target = scope if replacement_scope is None else replacement_scope
            if not isinstance(target, ObservationScope) or target.scope_id != scope.scope_id or target.task_id != scope.task_id:
                raise ObservationScopeMismatch("replacement scope must preserve scope and task identity")
            if reason is InvalidationReason.RUNTIME_TRANSITION and target.runtime_instance_id == scope.runtime_instance_id:
                raise ObservationPolicyError("runtime transition requires a new runtime identity")
            if reason is InvalidationReason.SESSION_TRANSITION and target.session_id == scope.session_id:
                raise ObservationPolicyError("session transition requires a new session identity")
            if reason is InvalidationReason.SOURCE_REPLACED and target.source == scope.source:
                raise ObservationPolicyError("source replacement requires a new source identity")
            timestamp = self._now_ms() if invalidated_at_ms is None else _non_negative(
                invalidated_at_ms,
                "invalidated_at_ms",
            )
            invalidation = ObservationInvalidation(
                self._id_factory("observation-invalidation"),
                scope.scope_id,
                state.epoch,
                state.epoch + 1,
                reason,
                timestamp,
            )
            self._persist_invalidation(invalidation, state, trace)
            state.scope = target
            state.epoch = invalidation.next_epoch
            state.epoch_started_at_ms = timestamp
            state.source_available = True
            self._states[scope.scope_id] = state
            return invalidation

    def mark_mutation_dispatched(
        self,
        scope: ObservationScope,
        *,
        trace_id: str,
        dispatched_at_ms: int | None = None,
    ) -> ObservationInvalidation:
        return self.invalidate(
            scope,
            InvalidationReason.MUTATION_DISPATCH,
            trace_id=trace_id,
            invalidated_at_ms=dispatched_at_ms,
        )

    def mark_source_unavailable(self, scope: ObservationScope, *, trace_id: str) -> None:
        trace = _identifier(trace_id, "trace_id")
        with self._mutex:
            state = self._states.get(scope.scope_id)
            if state is None or state.scope != scope:
                raise ObservationScopeMismatch("source availability requires the current exact scope")
            self._append_trace(
                event_name="observation.source-unavailable",
                trace_id=trace,
                task_id=scope.task_id,
                timestamp=self._now_ms(),
                observation_refs=self._latest_ref_tuple(state),
                attributes=(("scope_id", scope.scope_id), ("epoch", str(state.epoch))),
            )
            state.source_available = False

    def assess(
        self,
        snapshot_or_ref: ObservationSnapshot | ObservationRef,
        requirement: FreshnessRequirement,
        *,
        expected_scope: ObservationScope | None = None,
        evaluated_at_ms: int | None = None,
        trace_id: str | None = None,
    ) -> FreshnessAssessment:
        if not isinstance(requirement, FreshnessRequirement):
            raise ObservationPolicyError("freshness assessment requires FreshnessRequirement")
        with self._mutex:
            reference = (
                snapshot_or_ref.observation_ref
                if isinstance(snapshot_or_ref, ObservationSnapshot)
                else snapshot_or_ref
            )
            if not isinstance(reference, ObservationRef):
                raise ObservationPolicyError("freshness assessment requires ObservationSnapshot or ObservationRef")
            timestamp = self._now_ms() if evaluated_at_ms is None else _non_negative(
                evaluated_at_ms,
                "evaluated_at_ms",
            )
            snapshot = self._snapshots.get(reference.observation_id)
            if snapshot is None or snapshot.observation_ref != reference:
                return self._assessment(reference, requirement, FreshnessState.UNKNOWN, FreshnessReason.UNKNOWN_OBSERVATION, timestamp, None, trace_id)
            state = self._states.get(snapshot.scope.scope_id)
            if state is None:
                return self._assessment(reference, requirement, FreshnessState.UNKNOWN, FreshnessReason.UNKNOWN_OBSERVATION, timestamp, None, trace_id)
            if expected_scope is not None and snapshot.scope.scope_id != expected_scope.scope_id:
                return self._assessment(reference, requirement, FreshnessState.INVALIDATED, FreshnessReason.SCOPE_MISMATCH, timestamp, state.epoch, trace_id)
            if expected_scope is not None and (
                snapshot.scope.task_id != expected_scope.task_id
                or snapshot.scope.session_id != expected_scope.session_id
                or snapshot.scope.source != expected_scope.source
            ):
                return self._assessment(reference, requirement, FreshnessState.INVALIDATED, FreshnessReason.SCOPE_MISMATCH, timestamp, state.epoch, trace_id)
            if not state.source_available:
                return self._assessment(reference, requirement, FreshnessState.UNKNOWN, FreshnessReason.SOURCE_UNAVAILABLE, timestamp, state.epoch, trace_id)
            if snapshot.epoch.value < state.epoch:
                return self._assessment(reference, requirement, FreshnessState.INVALIDATED, FreshnessReason.EPOCH_INVALIDATED, timestamp, state.epoch, trace_id)
            if snapshot.epoch.value > state.epoch:
                return self._assessment(reference, requirement, FreshnessState.UNKNOWN, FreshnessReason.FUTURE_EPOCH, timestamp, state.epoch, trace_id)
            if snapshot.scope.runtime_instance_id != state.scope.runtime_instance_id:
                return self._assessment(reference, requirement, FreshnessState.INVALIDATED, FreshnessReason.RUNTIME_MISMATCH, timestamp, state.epoch, trace_id)
            if requirement.max_age_ms is not None and timestamp - snapshot.captured_at_ms > requirement.max_age_ms:
                return self._assessment(reference, requirement, FreshnessState.STALE, FreshnessReason.AGE_EXCEEDED, timestamp, state.epoch, trace_id)
            if requirement.kind in {FreshnessRequirementKind.POST_DISPATCH, FreshnessRequirementKind.POST_RESTART}:
                if (
                    requirement.boundary_epoch is None
                    or requirement.boundary_at_ms is None
                    or snapshot.epoch.value <= requirement.boundary_epoch
                    or snapshot.captured_at_ms <= requirement.boundary_at_ms
                ):
                    return self._assessment(reference, requirement, FreshnessState.STALE, FreshnessReason.BOUNDARY_NOT_CROSSED, timestamp, state.epoch, trace_id)
            if requirement.kind is FreshnessRequirementKind.NEWER_THAN:
                prior = requirement.reference
                if prior is None or prior.task_id != reference.task_id or prior.session_id != reference.session_id:
                    return self._assessment(reference, requirement, FreshnessState.INVALIDATED, FreshnessReason.REFERENCE_SCOPE_MISMATCH, timestamp, state.epoch, trace_id)
                if (
                    prior.generation is None
                    or reference.generation is None
                    or reference.generation <= prior.generation
                    or prior.observed_at_ms is None
                    or reference.observed_at_ms is None
                    or reference.observed_at_ms <= prior.observed_at_ms
                ):
                    return self._assessment(reference, requirement, FreshnessState.STALE, FreshnessReason.REFERENCE_NOT_EXCEEDED, timestamp, state.epoch, trace_id)
            if requirement.kind is FreshnessRequirementKind.CURRENT_EPOCH and reference.generation != state.generation:
                return self._assessment(reference, requirement, FreshnessState.STALE, FreshnessReason.GENERATION_SUPERSEDED, timestamp, state.epoch, trace_id)
            return self._assessment(reference, requirement, FreshnessState.CURRENT, FreshnessReason.SATISFIED, timestamp, state.epoch, trace_id)

    def assess_for_verification(
        self,
        snapshot_or_ref: ObservationSnapshot | ObservationRef,
        requirement: FreshnessRequirement,
        *,
        expected_scope: ObservationScope,
        dispatch_invalidation: ObservationInvalidation | None = None,
        restart_invalidation: ObservationInvalidation | None = None,
        evaluated_at_ms: int | None = None,
        trace_id: str | None = None,
    ) -> FreshnessAssessment:
        if dispatch_invalidation is not None and restart_invalidation is not None:
            raise ObservationPolicyError("verification accepts only one controlling freshness boundary")
        effective = requirement
        if dispatch_invalidation is not None:
            effective = FreshnessRequirement.post_dispatch(dispatch_invalidation)
        elif restart_invalidation is not None:
            effective = FreshnessRequirement.post_restart(restart_invalidation)
        elif requirement.kind is FreshnessRequirementKind.ANY_VALID:
            effective = FreshnessRequirement.current_epoch(max_age_ms=requirement.max_age_ms)
        return self.assess(
            snapshot_or_ref,
            effective,
            expected_scope=expected_scope,
            evaluated_at_ms=evaluated_at_ms,
            trace_id=trace_id,
        )

    def require_for_verification(
        self,
        snapshot_or_ref: ObservationSnapshot | ObservationRef,
        requirement: FreshnessRequirement,
        *,
        expected_scope: ObservationScope,
        dispatch_invalidation: ObservationInvalidation | None = None,
        restart_invalidation: ObservationInvalidation | None = None,
        evaluated_at_ms: int | None = None,
        trace_id: str | None = None,
    ) -> ObservationSnapshot:
        assessment = self.assess_for_verification(
            snapshot_or_ref,
            requirement,
            expected_scope=expected_scope,
            dispatch_invalidation=dispatch_invalidation,
            restart_invalidation=restart_invalidation,
            evaluated_at_ms=evaluated_at_ms,
            trace_id=trace_id,
        )
        if not assessment.satisfies:
            raise ObservationFreshnessRequired(
                f"fresh observation required: {assessment.state.value}/{assessment.reason.value}"
            )
        if isinstance(snapshot_or_ref, ObservationSnapshot):
            return snapshot_or_ref
        if isinstance(snapshot_or_ref, ObservationRef):
            return self.snapshot(snapshot_or_ref)
        raise ObservationPolicyError("verification requires ObservationSnapshot or ObservationRef")

    def assess_target(
        self,
        target: ObservedTargetRef,
        *,
        expected_scope: ObservationScope,
        requirement: FreshnessRequirement | None = None,
        evaluated_at_ms: int | None = None,
    ) -> FreshnessAssessment:
        if not isinstance(target, ObservedTargetRef):
            raise ObservationPolicyError("target freshness requires ObservedTargetRef")
        return self.assess_for_verification(
            target.observation_ref,
            requirement or FreshnessRequirement.current_epoch(),
            expected_scope=expected_scope,
            evaluated_at_ms=evaluated_at_ms,
        )

    def snapshot(self, reference: ObservationRef) -> ObservationSnapshot:
        if not isinstance(reference, ObservationRef):
            raise ObservationPolicyError("snapshot lookup requires ObservationRef")
        with self._mutex:
            snapshot = self._snapshots.get(reference.observation_id)
            if snapshot is None or snapshot.observation_ref != reference:
                raise ObservationNotFound("observation reference is not present in active tracker")
            return snapshot

    def current_epoch(self, scope: ObservationScope) -> ObservationEpoch:
        if not isinstance(scope, ObservationScope):
            raise ObservationPolicyError("epoch lookup requires ObservationScope")
        with self._mutex:
            state = self._states.get(scope.scope_id)
            if state is None or state.scope != scope:
                raise ObservationScopeMismatch("epoch lookup requires current exact scope")
            return ObservationEpoch(scope.scope_id, state.epoch, state.epoch_started_at_ms)

    def _assessment(
        self,
        reference: ObservationRef,
        requirement: FreshnessRequirement,
        state: FreshnessState,
        reason: FreshnessReason,
        timestamp: int,
        current_epoch: int | None,
        trace_id: str | None,
    ) -> FreshnessAssessment:
        assessment = FreshnessAssessment(
            reference,
            requirement.kind,
            state,
            reason,
            timestamp,
            current_epoch,
            state is FreshnessState.CURRENT and reason is FreshnessReason.SATISFIED,
        )
        if trace_id is not None:
            self._append_trace(
                event_name="observation.freshness-checked" if assessment.satisfies else "observation.fresh-observation-required",
                trace_id=_identifier(trace_id, "trace_id"),
                task_id=reference.task_id,
                timestamp=timestamp,
                observation_refs=(reference,),
                attributes=(
                    ("requirement", requirement.kind.value),
                    ("freshness_state", state.value),
                    ("freshness_reason", reason.value),
                ),
            )
        return assessment

    def _persist_snapshot(self, snapshot: ObservationSnapshot, trace_id: str) -> None:
        if self.store is None:
            return
        metadata = [
            ("snapshot_schema", snapshot.schema_version),
            ("scope_id", snapshot.scope.scope_id),
            ("runtime_instance_id", snapshot.scope.runtime_instance_id),
            ("source", snapshot.scope.source),
            ("epoch", str(snapshot.epoch.value)),
            ("generation", str(snapshot.generation)),
            ("secure_ui", "UNKNOWN" if snapshot.secure_ui_present is None else str(snapshot.secure_ui_present).upper()),
            ("fingerprint_present", str(snapshot.fingerprint is not None).upper()),
        ]
        if snapshot.scope.frontmost_app_id is not None:
            metadata.append(("frontmost_app_id", snapshot.scope.frontmost_app_id))
        descriptor = ArtifactDescriptor(
            ref=ArtifactRef(
                f"artifact.{snapshot.observation_ref.observation_id}",
                snapshot.scope.task_id,
                snapshot.scope.session_id,
            ),
            artifact_kind="observation.snapshot",
            producer="observation.tracker",
            created_at_ms=snapshot.captured_at_ms,
            sensitivity=SensitivityClass.PRIVATE,
            lifetime=ArtifactLifetime.DURABLE,
            observation_ref=snapshot.observation_ref,
            content_digest=snapshot.fingerprint,
            opaque_locator=snapshot.observation_ref.observation_id,
            metadata=tuple(metadata),
        )
        event = TraceEvent(
            event_id=self._id_factory("trace-event"),
            task_id=snapshot.scope.task_id,
            trace_id=trace_id,
            event_name="observation.captured",
            observed_timestamp_ms=snapshot.captured_at_ms,
            artifact_refs=(descriptor.ref, *snapshot.artifact_refs),
            observation_refs=(snapshot.observation_ref,),
            attributes=(("scope_id", snapshot.scope.scope_id), ("epoch", str(snapshot.epoch.value)), ("generation", str(snapshot.generation))),
        )
        self.store.record_artifact_and_trace(descriptor, event)

    def _persist_invalidation(
        self,
        invalidation: ObservationInvalidation,
        state: _ScopeState,
        trace_id: str,
    ) -> None:
        self._append_trace(
            event_name="observation.invalidated",
            trace_id=trace_id,
            task_id=state.scope.task_id,
            timestamp=invalidation.invalidated_at_ms,
            observation_refs=self._latest_ref_tuple(state),
            attributes=(
                ("scope_id", invalidation.scope_id),
                ("reason", invalidation.reason.value),
                ("previous_epoch", str(invalidation.previous_epoch)),
                ("next_epoch", str(invalidation.next_epoch)),
            ),
        )

    def _append_trace(
        self,
        *,
        event_name: str,
        trace_id: str,
        task_id: str,
        timestamp: int,
        observation_refs: tuple[ObservationRef, ...],
        attributes: tuple[tuple[str, str], ...],
    ) -> None:
        if self.store is None:
            return
        self.store.append_trace_event(
            TraceEvent(
                event_id=self._id_factory("trace-event"),
                task_id=task_id,
                trace_id=trace_id,
                event_name=event_name,
                observed_timestamp_ms=timestamp,
                observation_refs=observation_refs,
                attributes=attributes,
            )
        )

    def _latest_ref_tuple(self, state: _ScopeState) -> tuple[ObservationRef, ...]:
        if state.latest_observation_id is None:
            return ()
        snapshot = self._snapshots.get(state.latest_observation_id)
        return () if snapshot is None else (snapshot.observation_ref,)

    def _trim_history(self) -> None:
        while len(self._snapshot_order) > self._max_snapshots:
            expired = self._snapshot_order.pop(0)
            self._snapshots.pop(expired, None)


__all__ = [
    "FreshnessAssessment",
    "FreshnessReason",
    "FreshnessRequirement",
    "FreshnessRequirementKind",
    "FreshnessState",
    "InvalidationReason",
    "ObservationEpoch",
    "ObservationError",
    "ObservationFreshnessRequired",
    "ObservationInvalidation",
    "ObservationNotFound",
    "ObservationPolicyError",
    "ObservationScope",
    "ObservationScopeMismatch",
    "ObservationSnapshot",
    "ObservationStateConflict",
    "ObservationTracker",
]
