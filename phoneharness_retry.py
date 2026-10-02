#!/usr/bin/env python3
"""Host-only bounded retry policy and execution-loop detection.

This module can assess and persist retry policy. It cannot authorize, bind,
dispatch, execute, verify, replan, or retry a device action by itself.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from enum import Enum
import hashlib
import json
import random
import re
import time
from typing import Any, Awaitable, Callable, Mapping
import uuid

from phoneharness_async import AsyncTaskContext
from phoneharness_contracts import ArtifactDescriptor, ArtifactLifetime, ArtifactRef, SensitivityClass
from phoneharness_runtime import RuntimeInstanceRef
from phoneharness_store import PhoneHarnessStore, SideEffectClass, TraceEvent
from phoneharness_uncertainty import (
    IdempotencyKeyRef,
    IdempotencyProfile,
    ReconciliationState,
    digest_operation_parameters,
)


RETRY_ATTEMPT_SCHEMA_VERSION = "phoneharness.retry-attempt.v1"
RETRY_POLICY_SCHEMA_VERSION = "phoneharness.retry-policy.v1"
RETRY_BUDGET_SCHEMA_VERSION = "phoneharness.retry-budget.v1"
RETRY_ASSESSMENT_SCHEMA_VERSION = "phoneharness.retry-assessment.v1"
RETRY_DECISION_SCHEMA_VERSION = "phoneharness.retry-decision.v1"
LOOP_STATE_SCHEMA_VERSION = "phoneharness.execution-loop-state.v1"
LOOP_ASSESSMENT_SCHEMA_VERSION = "phoneharness.execution-loop-assessment.v1"
MAX_RETRY_ATTEMPTS = 10
MAX_LOOP_HISTORY = 6
MAX_EXECUTION_STEPS = 10_000

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class RetryError(RuntimeError):
    """Base class for deterministic S3-M5 policy failures."""


class RetryPolicyError(RetryError):
    """A retry policy or typed contract is invalid."""


class RetryBudgetNotFound(RetryError):
    """A canonical durable retry budget cannot be resolved."""


class RetryBudgetConflict(RetryError):
    """A stale or duplicate retry-budget mutation was attempted."""


class RetryAdmissionError(RetryError):
    """A retry was admitted without a current eligible decision."""


class LoopStateNotFound(RetryError):
    """A canonical durable execution-loop state cannot be resolved."""


class LoopStateConflict(RetryError):
    """A stale execution-loop state update was attempted."""


class RetryFailureClass(str, Enum):
    TRANSIENT = "TRANSIENT"
    THROTTLED = "THROTTLED"
    PERMANENT = "PERMANENT"
    AUTHORIZATION_DENIED = "AUTHORIZATION_DENIED"
    INVALID_REQUEST = "INVALID_REQUEST"
    UNKNOWN = "UNKNOWN"


class RetryEligibilityCode(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    PERMANENT_FAILURE = "PERMANENT_FAILURE"
    AUTHORIZATION_DENIED = "AUTHORIZATION_DENIED"
    INVALID_REQUEST = "INVALID_REQUEST"
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"
    EVIDENCE_CONFLICT = "EVIDENCE_CONFLICT"
    SEMANTIC_SUCCESS = "SEMANTIC_SUCCESS"
    IDEMPOTENCY_UNSUPPORTED = "IDEMPOTENCY_UNSUPPORTED"
    IDEMPOTENCY_KEY_INVALID = "IDEMPOTENCY_KEY_INVALID"
    CONDITIONAL_GUARD_MISSING = "CONDITIONAL_GUARD_MISSING"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    DEADLINE_EXHAUSTED = "DEADLINE_EXHAUSTED"
    LOOP_STOP = "LOOP_STOP"
    PROVIDER_POLICY_DENIED = "PROVIDER_POLICY_DENIED"
    MUTATION_EFFECT_NOT_PROVEN_ABSENT = "MUTATION_EFFECT_NOT_PROVEN_ABSENT"


class RetryDecisionKind(str, Enum):
    DENY = "DENY"
    SCHEDULE_NEW_GOVERNED_ATTEMPT = "SCHEDULE_NEW_GOVERNED_ATTEMPT"


class LoopSignal(str, Enum):
    NONE = "NONE"
    IDENTICAL_REPETITION = "IDENTICAL_REPETITION"
    OSCILLATION = "OSCILLATION"
    STAGNATION = "STAGNATION"
    REPEATED_FAILURE_PATTERN = "REPEATED_FAILURE_PATTERN"
    HARD_EXECUTION_BUDGET_EXCEEDED = "HARD_EXECUTION_BUDGET_EXCEEDED"


class ProgressKind(str, Enum):
    EXTERNAL_STATE_CHANGED = "EXTERNAL_STATE_CHANGED"
    VERIFIER_ADVANCED = "VERIFIER_ADVANCED"
    UNCERTAINTY_RESOLVED = "UNCERTAINTY_RESOLVED"
    TASK_STATE_TRANSITION = "TASK_STATE_TRANSITION"
    PROVIDER_EVIDENCE_ADVANCED = "PROVIDER_EVIDENCE_ADVANCED"
    ARTIFACT_OR_OBSERVATION_ADVANCED = "ARTIFACT_OR_OBSERVATION_ADVANCED"
    MODEL_SELF_REPORT_ONLY = "MODEL_SELF_REPORT_ONLY"
    NONE = "NONE"


_AUTHORITATIVE_PROGRESS = frozenset(
    {
        ProgressKind.EXTERNAL_STATE_CHANGED,
        ProgressKind.VERIFIER_ADVANCED,
        ProgressKind.UNCERTAINTY_RESOLVED,
        ProgressKind.TASK_STATE_TRANSITION,
        ProgressKind.PROVIDER_EVIDENCE_ADVANCED,
        ProgressKind.ARTIFACT_OR_OBSERVATION_ADVANCED,
    }
)


def _identifier(value: Any, field_name: str) -> str:
    normalized = str(value or "").strip()
    if _IDENTIFIER.fullmatch(normalized) is None:
        raise RetryPolicyError(f"{field_name} must be an opaque bounded identifier")
    return normalized


def _optional_identifier(value: Any, field_name: str) -> str | None:
    return None if value is None else _identifier(value, field_name)


def _timestamp(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RetryPolicyError(f"{field_name} must be a non-negative integer")
    return value


def _bounded_int(value: Any, field_name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise RetryPolicyError(f"{field_name} is outside its bounded range")
    return value


def _digest(value: Any, field_name: str) -> str:
    normalized = str(value or "")
    if _DIGEST.fullmatch(normalized) is None:
        raise RetryPolicyError(f"{field_name} must be a SHA-256 digest")
    return normalized


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _new_identifier(prefix: str) -> str:
    return f"{prefix}.{uuid.uuid4().hex}"


def _logical_digest(logical_operation_id: str) -> str:
    return hashlib.sha256(logical_operation_id.encode("utf-8")).hexdigest()


def _bool_text(value: bool) -> str:
    return "YES" if value else "NO"


def _none(value: str | None) -> str:
    return "NONE" if value is None else value


def _from_none(value: str) -> str | None:
    return None if value == "NONE" else value


def _join(values: tuple[str, ...]) -> str:
    return "EMPTY" if not values else "|".join(values)


def _split(value: str) -> tuple[str, ...]:
    return () if value == "EMPTY" else tuple(value.split("|"))


def _canonical_digest(payload: Mapping[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RetryAttemptRef:
    retry_attempt_id: str
    logical_operation_id: str
    task_id: str
    session_id: str
    trace_id: str
    ordinal: int
    created_at_ms: int
    previous_attempt_ref: str | None = None
    policy_decision_ref: str | None = None
    schema_version: str = RETRY_ATTEMPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RETRY_ATTEMPT_SCHEMA_VERSION:
            raise RetryPolicyError("unsupported RetryAttemptRef schema version")
        for name in ("retry_attempt_id", "logical_operation_id", "task_id", "session_id", "trace_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(
            self,
            "previous_attempt_ref",
            _optional_identifier(self.previous_attempt_ref, "previous_attempt_ref"),
        )
        object.__setattr__(
            self,
            "policy_decision_ref",
            _optional_identifier(self.policy_decision_ref, "policy_decision_ref"),
        )
        _bounded_int(self.ordinal, "ordinal", 1, MAX_RETRY_ATTEMPTS)
        _timestamp(self.created_at_ms, "created_at_ms")
        if self.ordinal == 1 and (self.previous_attempt_ref is not None or self.policy_decision_ref is not None):
            raise RetryPolicyError("initial attempt cannot claim a retry predecessor or decision")
        if self.ordinal > 1 and (self.previous_attempt_ref is None or self.policy_decision_ref is None):
            raise RetryPolicyError("retry attempt requires predecessor and policy-decision evidence")

    def audit(self) -> dict[str, Any]:
        return {
            "retry_attempt_id": self.retry_attempt_id,
            "ordinal": self.ordinal,
            "new_governed_attempt_required": self.ordinal > 1,
            "authority": False,
            "dispatch": False,
        }

    def to_artifact_descriptor(self) -> ArtifactDescriptor:
        metadata = {
            "attempt_schema": self.schema_version,
            "retry_attempt_id": self.retry_attempt_id,
            "logical_operation_id": self.logical_operation_id,
            "trace_id": self.trace_id,
            "ordinal": str(self.ordinal),
            "previous_attempt_ref": _none(self.previous_attempt_ref),
            "policy_decision_ref": _none(self.policy_decision_ref),
        }
        return ArtifactDescriptor(
            ref=ArtifactRef(
                f"retry-attempt.{_logical_digest(self.logical_operation_id)[:32]}.{self.ordinal:04d}",
                self.task_id,
                self.session_id,
            ),
            artifact_kind="retry.attempt",
            producer="retry.controller",
            created_at_ms=self.created_at_ms,
            sensitivity=SensitivityClass.PRIVATE,
            lifetime=ArtifactLifetime.DURABLE,
            opaque_locator=self.retry_attempt_id,
            metadata=tuple(metadata.items()),
        )


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int
    base_delay_ms: int
    max_delay_ms: int
    overall_timeout_ms: int
    provider_internal_max_attempts: int = 1
    jitter_strategy: str = "FULL"
    schema_version: str = RETRY_POLICY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RETRY_POLICY_SCHEMA_VERSION:
            raise RetryPolicyError("unsupported RetryPolicy schema version")
        _bounded_int(self.max_attempts, "max_attempts", 1, MAX_RETRY_ATTEMPTS)
        _bounded_int(self.base_delay_ms, "base_delay_ms", 0, 3_600_000)
        _bounded_int(self.max_delay_ms, "max_delay_ms", 0, 3_600_000)
        _bounded_int(self.overall_timeout_ms, "overall_timeout_ms", 1, 86_400_000)
        _bounded_int(
            self.provider_internal_max_attempts,
            "provider_internal_max_attempts",
            1,
            MAX_RETRY_ATTEMPTS,
        )
        if self.max_delay_ms < self.base_delay_ms:
            raise RetryPolicyError("max_delay_ms cannot be less than base_delay_ms")
        if self.jitter_strategy != "FULL":
            raise RetryPolicyError("M5 supports only explicit full jitter")

    def audit(self) -> dict[str, Any]:
        return {
            "max_attempts": self.max_attempts,
            "max_attempts_includes_initial": True,
            "provider_internal_max_attempts": self.provider_internal_max_attempts,
            "bounded": True,
            "authority": False,
        }


@dataclass(frozen=True)
class RetryBudget:
    logical_operation_id: str
    task_id: str
    session_id: str
    trace_id: str
    policy: RetryPolicy
    attempts_consumed: int
    first_attempt_at_ms: int
    deadline_ms: int
    last_attempt_ref: str
    current_runtime_instance_id: str
    updated_at_ms: int
    revision: int = 1
    last_failure_class: RetryFailureClass | None = None
    schema_version: str = RETRY_BUDGET_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RETRY_BUDGET_SCHEMA_VERSION:
            raise RetryPolicyError("unsupported RetryBudget schema version")
        if not isinstance(self.policy, RetryPolicy):
            raise RetryPolicyError("RetryBudget requires RetryPolicy")
        for name in (
            "logical_operation_id",
            "task_id",
            "session_id",
            "trace_id",
            "last_attempt_ref",
            "current_runtime_instance_id",
        ):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        _bounded_int(self.attempts_consumed, "attempts_consumed", 1, self.policy.max_attempts)
        _timestamp(self.first_attempt_at_ms, "first_attempt_at_ms")
        _timestamp(self.deadline_ms, "deadline_ms")
        _timestamp(self.updated_at_ms, "updated_at_ms")
        _bounded_int(self.revision, "revision", 1, 1_000_000)
        if self.deadline_ms != self.first_attempt_at_ms + self.policy.overall_timeout_ms:
            raise RetryPolicyError("retry deadline must be derived from the first attempt")
        if self.updated_at_ms < self.first_attempt_at_ms:
            raise RetryPolicyError("retry budget update precedes its first attempt")
        if self.last_failure_class is not None:
            object.__setattr__(self, "last_failure_class", RetryFailureClass(self.last_failure_class))

    @property
    def attempts_remaining(self) -> int:
        return self.policy.max_attempts - self.attempts_consumed

    def audit(self) -> dict[str, Any]:
        return {
            "logical_operation_id": self.logical_operation_id,
            "attempts_consumed": self.attempts_consumed,
            "attempts_remaining": self.attempts_remaining,
            "revision": self.revision,
            "authority": False,
            "dispatch": False,
        }

    def to_artifact_descriptor(self) -> ArtifactDescriptor:
        metadata = {
            "budget_schema": self.schema_version,
            "logical_operation_id": self.logical_operation_id,
            "trace_id": self.trace_id,
            "policy": ":".join(
                str(value)
                for value in (
                    self.policy.max_attempts,
                    self.policy.base_delay_ms,
                    self.policy.max_delay_ms,
                    self.policy.overall_timeout_ms,
                    self.policy.provider_internal_max_attempts,
                )
            ),
            "jitter_strategy": self.policy.jitter_strategy,
            "attempts_consumed": str(self.attempts_consumed),
            "first_deadline": f"{self.first_attempt_at_ms}:{self.deadline_ms}",
            "last_attempt_ref": self.last_attempt_ref,
            "last_failure_class": self.last_failure_class.value if self.last_failure_class else "NONE",
            "current_runtime_instance_id": self.current_runtime_instance_id,
            "revision": str(self.revision),
        }
        return ArtifactDescriptor(
            ref=ArtifactRef(
                f"retry-budget.{_logical_digest(self.logical_operation_id)[:32]}.r{self.revision:06d}",
                self.task_id,
                self.session_id,
            ),
            artifact_kind="retry.budget",
            producer="retry.controller",
            created_at_ms=self.updated_at_ms,
            sensitivity=SensitivityClass.PRIVATE,
            lifetime=ArtifactLifetime.DURABLE,
            opaque_locator=self.logical_operation_id,
            metadata=tuple(metadata.items()),
        )

    @classmethod
    def from_artifact_descriptor(cls, descriptor: ArtifactDescriptor) -> "RetryBudget":
        if descriptor.artifact_kind != "retry.budget" or descriptor.ref.session_id is None:
            raise RetryPolicyError("durable record is not RetryBudget")
        metadata = dict(descriptor.metadata)
        required = {
            "budget_schema",
            "logical_operation_id",
            "trace_id",
            "policy",
            "jitter_strategy",
            "attempts_consumed",
            "first_deadline",
            "last_attempt_ref",
            "last_failure_class",
            "current_runtime_instance_id",
            "revision",
        }
        if set(metadata) != required:
            raise RetryPolicyError("RetryBudget durable fields do not match its schema")
        policy_values = tuple(int(value) for value in metadata["policy"].split(":"))
        times = tuple(int(value) for value in metadata["first_deadline"].split(":"))
        if len(policy_values) != 5 or len(times) != 2:
            raise RetryPolicyError("RetryBudget durable policy is invalid")
        failure = _from_none(metadata["last_failure_class"])
        return cls(
            logical_operation_id=metadata["logical_operation_id"],
            task_id=descriptor.ref.task_id,
            session_id=descriptor.ref.session_id,
            trace_id=metadata["trace_id"],
            policy=RetryPolicy(
                max_attempts=policy_values[0],
                base_delay_ms=policy_values[1],
                max_delay_ms=policy_values[2],
                overall_timeout_ms=policy_values[3],
                provider_internal_max_attempts=policy_values[4],
                jitter_strategy=metadata["jitter_strategy"],
            ),
            attempts_consumed=int(metadata["attempts_consumed"]),
            first_attempt_at_ms=times[0],
            deadline_ms=times[1],
            last_attempt_ref=metadata["last_attempt_ref"],
            current_runtime_instance_id=metadata["current_runtime_instance_id"],
            updated_at_ms=descriptor.created_at_ms,
            revision=int(metadata["revision"]),
            last_failure_class=RetryFailureClass(failure) if failure else None,
            schema_version=metadata["budget_schema"],
        )


@dataclass(frozen=True)
class LoopAssessment:
    signal: LoopSignal
    hard_stop: bool
    requires_replan_signal: bool
    observed_at_ms: int
    schema_version: str = LOOP_ASSESSMENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != LOOP_ASSESSMENT_SCHEMA_VERSION:
            raise RetryPolicyError("unsupported LoopAssessment schema version")
        object.__setattr__(self, "signal", LoopSignal(self.signal))
        _timestamp(self.observed_at_ms, "observed_at_ms")
        expected = self.signal is not LoopSignal.NONE
        if self.hard_stop is not expected or self.requires_replan_signal is not expected:
            raise RetryPolicyError("loop signal flags do not match fail-closed policy")

    def audit(self) -> dict[str, Any]:
        return {
            "signal": self.signal.value,
            "hard_stop": self.hard_stop,
            "requires_replan_signal": self.requires_replan_signal,
            "authority": False,
            "semantic_verifier": False,
        }


@dataclass(frozen=True)
class RetryEligibilityAssessment:
    assessment_id: str
    logical_operation_id: str
    budget_revision: int
    failure_class: RetryFailureClass
    reconciliation_state: ReconciliationState | None
    idempotency_profile: IdempotencyProfile
    idempotency_key_present: bool
    side_effect_class: SideEffectClass
    code: RetryEligibilityCode
    eligible: bool
    assessed_at_ms: int
    loop_signal: LoopSignal = LoopSignal.NONE
    schema_version: str = RETRY_ASSESSMENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RETRY_ASSESSMENT_SCHEMA_VERSION:
            raise RetryPolicyError("unsupported RetryEligibilityAssessment schema version")
        for name in ("assessment_id", "logical_operation_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        _bounded_int(self.budget_revision, "budget_revision", 1, 1_000_000)
        object.__setattr__(self, "failure_class", RetryFailureClass(self.failure_class))
        if self.reconciliation_state is not None:
            object.__setattr__(self, "reconciliation_state", ReconciliationState(self.reconciliation_state))
        object.__setattr__(self, "idempotency_profile", IdempotencyProfile(self.idempotency_profile))
        if not isinstance(self.idempotency_key_present, bool):
            raise RetryPolicyError("idempotency_key_present must be boolean")
        object.__setattr__(self, "side_effect_class", SideEffectClass(self.side_effect_class))
        object.__setattr__(self, "code", RetryEligibilityCode(self.code))
        object.__setattr__(self, "loop_signal", LoopSignal(self.loop_signal))
        _timestamp(self.assessed_at_ms, "assessed_at_ms")
        if self.eligible is not (self.code is RetryEligibilityCode.ELIGIBLE):
            raise RetryPolicyError("retry eligibility flag does not match its typed code")

    def audit(self) -> dict[str, Any]:
        return {
            "assessment_id": self.assessment_id,
            "eligible": self.eligible,
            "code": self.code.value,
            "authority": False,
            "new_governed_attempt_required": self.eligible,
        }


@dataclass(frozen=True)
class RetryDecision:
    decision_id: str
    logical_operation_id: str
    budget_revision: int
    kind: RetryDecisionKind
    reason: RetryEligibilityCode
    created_at_ms: int
    delay_ms: int
    not_before_ms: int
    expires_at_ms: int
    schema_version: str = RETRY_DECISION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RETRY_DECISION_SCHEMA_VERSION:
            raise RetryPolicyError("unsupported RetryDecision schema version")
        for name in ("decision_id", "logical_operation_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        _bounded_int(self.budget_revision, "budget_revision", 1, 1_000_000)
        object.__setattr__(self, "kind", RetryDecisionKind(self.kind))
        object.__setattr__(self, "reason", RetryEligibilityCode(self.reason))
        _timestamp(self.created_at_ms, "created_at_ms")
        _bounded_int(self.delay_ms, "delay_ms", 0, 3_600_000)
        _timestamp(self.not_before_ms, "not_before_ms")
        _timestamp(self.expires_at_ms, "expires_at_ms")
        if self.kind is RetryDecisionKind.SCHEDULE_NEW_GOVERNED_ATTEMPT:
            if self.reason is not RetryEligibilityCode.ELIGIBLE:
                raise RetryPolicyError("scheduled retry requires positive eligibility")
            if self.not_before_ms != self.created_at_ms + self.delay_ms:
                raise RetryPolicyError("scheduled retry delay is inconsistent")
            if self.not_before_ms > self.expires_at_ms:
                raise RetryPolicyError("scheduled retry falls after its deadline")
        elif self.delay_ms != 0 or self.not_before_ms != self.created_at_ms:
            raise RetryPolicyError("denied retry cannot carry a backoff schedule")

    @property
    def requires_new_governed_attempt(self) -> bool:
        return self.kind is RetryDecisionKind.SCHEDULE_NEW_GOVERNED_ATTEMPT

    def audit(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "kind": self.kind.value,
            "reason": self.reason.value,
            "scheduled_retry_is_started_retry": False,
            "new_governed_attempt_required": self.requires_new_governed_attempt,
            "authority": False,
            "dispatch": False,
        }


@dataclass(frozen=True)
class ActionSignature:
    capability_id: str
    operation: str
    target_fingerprint: str
    parameter_digest: str
    provider_class: str | None = None

    def __post_init__(self) -> None:
        for name in ("capability_id", "operation"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(self, "provider_class", _optional_identifier(self.provider_class, "provider_class"))
        object.__setattr__(self, "target_fingerprint", _digest(self.target_fingerprint, "target_fingerprint"))
        object.__setattr__(self, "parameter_digest", _digest(self.parameter_digest, "parameter_digest"))

    @classmethod
    def from_operation(
        cls,
        *,
        capability_id: str,
        operation: str,
        target_identity: str,
        parameters: Mapping[str, Any],
        provider_class: str | None = None,
    ) -> "ActionSignature":
        target = " ".join(str(target_identity or "").split())
        if not target or len(target) > 512:
            raise RetryPolicyError("target identity must be non-empty bounded input")
        return cls(
            capability_id=capability_id,
            operation=operation,
            target_fingerprint=hashlib.sha256(target.encode("utf-8")).hexdigest(),
            parameter_digest=digest_operation_parameters(parameters),
            provider_class=provider_class,
        )

    @property
    def digest(self) -> str:
        return _canonical_digest(
            {
                "capability_id": self.capability_id,
                "operation": self.operation,
                "target_fingerprint": self.target_fingerprint,
                "parameter_digest": self.parameter_digest,
                "provider_class": self.provider_class,
            }
        )


@dataclass(frozen=True)
class FailureSignature:
    error_class: str
    error_code: str
    provider_id: str
    capability_id: str
    operation: str
    parameter_digest: str

    def __post_init__(self) -> None:
        for name in ("error_class", "error_code", "provider_id", "capability_id", "operation"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(self, "parameter_digest", _digest(self.parameter_digest, "parameter_digest"))

    @property
    def digest(self) -> str:
        return _canonical_digest(
            {
                "error_class": self.error_class,
                "error_code": self.error_code,
                "provider_id": self.provider_id,
                "capability_id": self.capability_id,
                "operation": self.operation,
                "parameter_digest": self.parameter_digest,
            }
        )


@dataclass(frozen=True)
class ProgressAssessment:
    progress_id: str
    kind: ProgressKind
    observed_at_ms: int
    evidence_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "progress_id", _identifier(self.progress_id, "progress_id"))
        object.__setattr__(self, "kind", ProgressKind(self.kind))
        object.__setattr__(self, "evidence_ref", _optional_identifier(self.evidence_ref, "evidence_ref"))
        _timestamp(self.observed_at_ms, "observed_at_ms")
        if self.kind in _AUTHORITATIVE_PROGRESS and self.evidence_ref is None:
            raise RetryPolicyError("externally grounded progress requires typed evidence reference")
        if self.kind not in _AUTHORITATIVE_PROGRESS and self.evidence_ref is not None:
            raise RetryPolicyError("non-authoritative progress cannot carry authoritative evidence")

    @property
    def externally_grounded(self) -> bool:
        return self.kind in _AUTHORITATIVE_PROGRESS

    def audit(self) -> dict[str, Any]:
        return {
            "progress_id": self.progress_id,
            "kind": self.kind.value,
            "externally_grounded": self.externally_grounded,
            "model_self_report_authoritative": False,
            "authority": False,
        }


@dataclass(frozen=True)
class ExecutionLoopState:
    logical_operation_id: str
    task_id: str
    session_id: str
    trace_id: str
    current_runtime_instance_id: str
    action_history: tuple[str, ...]
    failure_history: tuple[str, ...]
    progress_history: tuple[str, ...]
    total_steps: int
    steps_since_progress: int
    updated_at_ms: int
    revision: int = 1
    schema_version: str = LOOP_STATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != LOOP_STATE_SCHEMA_VERSION:
            raise RetryPolicyError("unsupported ExecutionLoopState schema version")
        for name in (
            "logical_operation_id",
            "task_id",
            "session_id",
            "trace_id",
            "current_runtime_instance_id",
        ):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        actions = tuple(_digest(value, "action_history") for value in self.action_history)
        failures = tuple(value if value == "NONE" else _digest(value, "failure_history") for value in self.failure_history)
        progress = tuple(value for value in self.progress_history if value in {"0", "1"})
        if (
            len(actions) > MAX_LOOP_HISTORY
            or len(actions) != len(failures)
            or len(actions) != len(progress)
            or len(progress) != len(self.progress_history)
        ):
            raise RetryPolicyError("loop history is malformed or unbounded")
        object.__setattr__(self, "action_history", actions)
        object.__setattr__(self, "failure_history", failures)
        object.__setattr__(self, "progress_history", progress)
        _bounded_int(self.total_steps, "total_steps", 0, MAX_EXECUTION_STEPS)
        _bounded_int(self.steps_since_progress, "steps_since_progress", 0, MAX_EXECUTION_STEPS)
        if self.steps_since_progress > self.total_steps:
            raise RetryPolicyError("steps_since_progress exceeds total steps")
        _timestamp(self.updated_at_ms, "updated_at_ms")
        _bounded_int(self.revision, "revision", 1, 1_000_000)

    def to_artifact_descriptor(self) -> ArtifactDescriptor:
        metadata = {
            "loop_schema": self.schema_version,
            "logical_operation_id": self.logical_operation_id,
            "trace_id": self.trace_id,
            "current_runtime_instance_id": self.current_runtime_instance_id,
            "action_history_1": _join(self.action_history[:3]),
            "action_history_2": _join(self.action_history[3:]),
            "failure_history_1": _join(self.failure_history[:3]),
            "failure_history_2": _join(self.failure_history[3:]),
            "progress_history_1": _join(self.progress_history[:3]),
            "progress_history_2": _join(self.progress_history[3:]),
            "step_counts": f"{self.total_steps}:{self.steps_since_progress}",
            "revision": str(self.revision),
        }
        return ArtifactDescriptor(
            ref=ArtifactRef(
                f"execution-loop.{_logical_digest(self.logical_operation_id)[:32]}.r{self.revision:06d}",
                self.task_id,
                self.session_id,
            ),
            artifact_kind="execution.loop-state",
            producer="execution.loop-detector",
            created_at_ms=self.updated_at_ms,
            sensitivity=SensitivityClass.PRIVATE,
            lifetime=ArtifactLifetime.DURABLE,
            opaque_locator=self.logical_operation_id,
            metadata=tuple(metadata.items()),
        )

    @classmethod
    def from_artifact_descriptor(cls, descriptor: ArtifactDescriptor) -> "ExecutionLoopState":
        if descriptor.artifact_kind != "execution.loop-state" or descriptor.ref.session_id is None:
            raise RetryPolicyError("durable record is not ExecutionLoopState")
        metadata = dict(descriptor.metadata)
        required = {
            "loop_schema",
            "logical_operation_id",
            "trace_id",
            "current_runtime_instance_id",
            "action_history_1",
            "action_history_2",
            "failure_history_1",
            "failure_history_2",
            "progress_history_1",
            "progress_history_2",
            "step_counts",
            "revision",
        }
        if set(metadata) != required:
            raise RetryPolicyError("ExecutionLoopState durable fields do not match its schema")
        counts = tuple(int(value) for value in metadata["step_counts"].split(":"))
        if len(counts) != 2:
            raise RetryPolicyError("ExecutionLoopState durable counts are invalid")
        return cls(
            logical_operation_id=metadata["logical_operation_id"],
            task_id=descriptor.ref.task_id,
            session_id=descriptor.ref.session_id,
            trace_id=metadata["trace_id"],
            current_runtime_instance_id=metadata["current_runtime_instance_id"],
            action_history=_split(metadata["action_history_1"]) + _split(metadata["action_history_2"]),
            failure_history=_split(metadata["failure_history_1"]) + _split(metadata["failure_history_2"]),
            progress_history=_split(metadata["progress_history_1"]) + _split(metadata["progress_history_2"]),
            total_steps=counts[0],
            steps_since_progress=counts[1],
            updated_at_ms=descriptor.created_at_ms,
            revision=int(metadata["revision"]),
            schema_version=metadata["loop_schema"],
        )


class RetryController:
    """The single logical PhoneHarness retry-policy owner for Host M5."""

    def __init__(
        self,
        store: PhoneHarnessStore,
        runtime_ref: RuntimeInstanceRef,
        *,
        now_ms: Callable[[], int] = _now_ms,
        random_unit: Callable[[], float] = random.random,
        id_factory: Callable[[str], str] = _new_identifier,
    ) -> None:
        if not isinstance(store, PhoneHarnessStore) or not isinstance(runtime_ref, RuntimeInstanceRef):
            raise RetryPolicyError("RetryController requires typed store and Runtime identity")
        self.store = store
        self.runtime_ref = runtime_ref
        self._now_ms = now_ms
        self._random_unit = random_unit
        self._id_factory = id_factory

    def create_budget(
        self,
        *,
        logical_operation_id: str,
        task_id: str,
        session_id: str,
        trace_id: str,
        policy: RetryPolicy,
    ) -> tuple[RetryBudget, RetryAttemptRef]:
        operation = _identifier(logical_operation_id, "logical_operation_id")
        task = _identifier(task_id, "task_id")
        session = _identifier(session_id, "session_id")
        trace = _identifier(trace_id, "trace_id")
        if not isinstance(policy, RetryPolicy):
            raise RetryPolicyError("retry budget requires RetryPolicy")
        if self._budget_records(task, session, operation):
            raise RetryBudgetConflict("logical operation already has a canonical retry budget")
        now = self._now_ms()
        initial = RetryAttemptRef(
            retry_attempt_id=self._id_factory("retry-attempt"),
            logical_operation_id=operation,
            task_id=task,
            session_id=session,
            trace_id=trace,
            ordinal=1,
            created_at_ms=now,
        )
        budget = RetryBudget(
            logical_operation_id=operation,
            task_id=task,
            session_id=session,
            trace_id=trace,
            policy=policy,
            attempts_consumed=1,
            first_attempt_at_ms=now,
            deadline_ms=now + policy.overall_timeout_ms,
            last_attempt_ref=initial.retry_attempt_id,
            current_runtime_instance_id=self.runtime_ref.runtime_instance_id,
            updated_at_ms=now,
        )
        self._persist_attempt(initial, "retry.initial-attempt-recorded")
        self._persist_budget(budget, "retry.budget-created")
        return budget, initial

    def load_budget(self, *, logical_operation_id: str, task_id: str, session_id: str) -> RetryBudget:
        records = self._budget_records(
            _identifier(task_id, "task_id"),
            _identifier(session_id, "session_id"),
            _identifier(logical_operation_id, "logical_operation_id"),
        )
        if not records:
            raise RetryBudgetNotFound("retry budget is not present in canonical store")
        return max(records, key=lambda value: value.revision)

    def assess_eligibility(
        self,
        budget: RetryBudget,
        *,
        failure_class: RetryFailureClass,
        reconciliation_state: ReconciliationState | None,
        idempotency_profile: IdempotencyProfile,
        side_effect_class: SideEffectClass,
        loop_assessment: LoopAssessment,
        action_signature: ActionSignature | None = None,
        idempotency_key_ref: IdempotencyKeyRef | None = None,
        conditional_idempotency_proven: bool = False,
        provider_allows_retry: bool = True,
    ) -> RetryEligibilityAssessment:
        current = self._require_current_budget(budget)
        failure = RetryFailureClass(failure_class)
        state = None if reconciliation_state is None else ReconciliationState(reconciliation_state)
        profile = IdempotencyProfile(idempotency_profile)
        effect = SideEffectClass(side_effect_class)
        if not isinstance(loop_assessment, LoopAssessment):
            raise RetryPolicyError("retry eligibility requires LoopAssessment")
        now = self._now_ms()
        code = RetryEligibilityCode.ELIGIBLE
        if loop_assessment.hard_stop:
            code = RetryEligibilityCode.LOOP_STOP
        elif state is ReconciliationState.EVIDENCE_CONFLICT:
            code = RetryEligibilityCode.EVIDENCE_CONFLICT
        elif state in {
            ReconciliationState.OPEN,
            ReconciliationState.OBSERVING,
            ReconciliationState.UNRESOLVED,
            ReconciliationState.CLOSED_FAIL_SAFE,
        }:
            code = RetryEligibilityCode.UNKNOWN_OUTCOME
        elif state is ReconciliationState.RESOLVED_SEMANTIC_SUCCESS:
            code = RetryEligibilityCode.SEMANTIC_SUCCESS
        elif failure is RetryFailureClass.PERMANENT:
            code = RetryEligibilityCode.PERMANENT_FAILURE
        elif failure is RetryFailureClass.AUTHORIZATION_DENIED:
            code = RetryEligibilityCode.AUTHORIZATION_DENIED
        elif failure is RetryFailureClass.INVALID_REQUEST:
            code = RetryEligibilityCode.INVALID_REQUEST
        elif failure is RetryFailureClass.UNKNOWN:
            code = RetryEligibilityCode.UNKNOWN_FAILURE
        elif not provider_allows_retry:
            code = RetryEligibilityCode.PROVIDER_POLICY_DENIED
        elif current.attempts_remaining <= 0:
            code = RetryEligibilityCode.BUDGET_EXHAUSTED
        elif now >= current.deadline_ms:
            code = RetryEligibilityCode.DEADLINE_EXHAUSTED
        elif profile is IdempotencyProfile.UNKNOWN or profile is IdempotencyProfile.NON_IDEMPOTENT:
            code = RetryEligibilityCode.IDEMPOTENCY_UNSUPPORTED
        elif profile is IdempotencyProfile.PROVIDER_KEYED_IDEMPOTENT and (
            not isinstance(idempotency_key_ref, IdempotencyKeyRef)
            or not isinstance(action_signature, ActionSignature)
            or action_signature.provider_class is None
            or idempotency_key_ref.provider_id != action_signature.provider_class
            or idempotency_key_ref.logical_operation != action_signature.operation
            or idempotency_key_ref.parameter_digest != action_signature.parameter_digest
        ):
            code = RetryEligibilityCode.IDEMPOTENCY_KEY_INVALID
        elif profile is not IdempotencyProfile.PROVIDER_KEYED_IDEMPOTENT and idempotency_key_ref is not None:
            code = RetryEligibilityCode.IDEMPOTENCY_KEY_INVALID
        elif profile is IdempotencyProfile.CONDITIONALLY_IDEMPOTENT and not conditional_idempotency_proven:
            code = RetryEligibilityCode.CONDITIONAL_GUARD_MISSING
        elif effect is not SideEffectClass.READ_ONLY and state is not ReconciliationState.RESOLVED_NO_EFFECT_CONFIRMED:
            code = RetryEligibilityCode.MUTATION_EFFECT_NOT_PROVEN_ABSENT
        assessment = RetryEligibilityAssessment(
            assessment_id=self._id_factory("retry-assessment"),
            logical_operation_id=current.logical_operation_id,
            budget_revision=current.revision,
            failure_class=failure,
            reconciliation_state=state,
            idempotency_profile=profile,
            idempotency_key_present=idempotency_key_ref is not None,
            side_effect_class=effect,
            code=code,
            eligible=code is RetryEligibilityCode.ELIGIBLE,
            assessed_at_ms=now,
            loop_signal=loop_assessment.signal,
        )
        self._persist_assessment(assessment, current)
        return assessment

    def decide(
        self,
        budget: RetryBudget,
        assessment: RetryEligibilityAssessment,
        *,
        provider_retry_after_ms: int | None = None,
    ) -> RetryDecision:
        current = self._require_current_budget(budget)
        if (
            not isinstance(assessment, RetryEligibilityAssessment)
            or assessment.logical_operation_id != current.logical_operation_id
            or assessment.budget_revision != current.revision
        ):
            raise RetryAdmissionError("retry assessment does not match current budget")
        now = self._now_ms()
        kind = RetryDecisionKind.DENY
        reason = assessment.code
        delay = 0
        if assessment.eligible:
            exponent = current.attempts_consumed - 1
            cap = min(current.policy.max_delay_ms, current.policy.base_delay_ms * (2**exponent))
            sample = float(self._random_unit())
            if not 0.0 <= sample <= 1.0:
                raise RetryPolicyError("jitter source must produce a unit interval value")
            delay = int(cap * sample)
            if provider_retry_after_ms is not None:
                hint = _bounded_int(provider_retry_after_ms, "provider_retry_after_ms", 0, 86_400_000)
                delay = min(current.policy.max_delay_ms, max(delay, hint))
            if now + delay > current.deadline_ms:
                reason = RetryEligibilityCode.DEADLINE_EXHAUSTED
                delay = 0
            else:
                kind = RetryDecisionKind.SCHEDULE_NEW_GOVERNED_ATTEMPT
                reason = RetryEligibilityCode.ELIGIBLE
        decision = RetryDecision(
            decision_id=self._id_factory("retry-decision"),
            logical_operation_id=current.logical_operation_id,
            budget_revision=current.revision,
            kind=kind,
            reason=reason,
            created_at_ms=now,
            delay_ms=delay,
            not_before_ms=now + delay,
            expires_at_ms=current.deadline_ms,
        )
        self._persist_decision(decision, current)
        return decision

    async def wait_for_schedule(
        self,
        decision: RetryDecision,
        context: AsyncTaskContext,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """Wait cooperatively for an admitted schedule without starting an attempt."""

        if not isinstance(decision, RetryDecision) or not decision.requires_new_governed_attempt:
            raise RetryAdmissionError("only a scheduled retry can enter bounded backoff")
        if not isinstance(context, AsyncTaskContext):
            raise RetryPolicyError("retry backoff requires an S3-M2 AsyncTaskContext")
        await context.cancellation_point()
        await sleep(decision.delay_ms / 1000.0)
        await context.cancellation_point()

    def admit_new_attempt(
        self,
        budget: RetryBudget,
        decision: RetryDecision,
        *,
        failure_class: RetryFailureClass,
    ) -> tuple[RetryBudget, RetryAttemptRef]:
        current = self._require_current_budget(budget)
        if (
            not isinstance(decision, RetryDecision)
            or decision.kind is not RetryDecisionKind.SCHEDULE_NEW_GOVERNED_ATTEMPT
            or decision.logical_operation_id != current.logical_operation_id
            or decision.budget_revision != current.revision
        ):
            raise RetryAdmissionError("retry decision does not admit a new governed attempt")
        now = self._now_ms()
        if now < decision.not_before_ms or now > min(decision.expires_at_ms, current.deadline_ms):
            raise RetryAdmissionError("retry decision is outside its bounded schedule")
        if current.attempts_remaining <= 0:
            raise RetryAdmissionError("retry budget is exhausted")
        attempt = RetryAttemptRef(
            retry_attempt_id=self._id_factory("retry-attempt"),
            logical_operation_id=current.logical_operation_id,
            task_id=current.task_id,
            session_id=current.session_id,
            trace_id=current.trace_id,
            ordinal=current.attempts_consumed + 1,
            created_at_ms=now,
            previous_attempt_ref=current.last_attempt_ref,
            policy_decision_ref=decision.decision_id,
        )
        updated = replace(
            current,
            attempts_consumed=current.attempts_consumed + 1,
            last_attempt_ref=attempt.retry_attempt_id,
            current_runtime_instance_id=self.runtime_ref.runtime_instance_id,
            updated_at_ms=max(now, current.updated_at_ms + 1),
            revision=current.revision + 1,
            last_failure_class=RetryFailureClass(failure_class),
        )
        self._persist_attempt(attempt, "retry.new-governed-attempt-admitted")
        self._persist_budget(updated, "retry.budget-consumed")
        return updated, attempt

    def _require_current_budget(self, budget: RetryBudget) -> RetryBudget:
        if not isinstance(budget, RetryBudget):
            raise RetryPolicyError("retry operation requires RetryBudget")
        current = self.load_budget(
            logical_operation_id=budget.logical_operation_id,
            task_id=budget.task_id,
            session_id=budget.session_id,
        )
        if current.revision != budget.revision:
            raise RetryBudgetConflict("retry budget revision is no longer current")
        return current

    def _budget_records(self, task_id: str, session_id: str, logical_operation_id: str) -> tuple[RetryBudget, ...]:
        return tuple(
            RetryBudget.from_artifact_descriptor(descriptor)
            for descriptor in self.store.list_artifacts(task_id, session_id=session_id)
            if descriptor.artifact_kind == "retry.budget"
            and descriptor.opaque_locator == logical_operation_id
        )

    def _persist_attempt(self, attempt: RetryAttemptRef, event_name: str) -> None:
        descriptor = attempt.to_artifact_descriptor()
        self._record_artifact(descriptor, attempt.trace_id, event_name, attempt.logical_operation_id)

    def _persist_budget(self, budget: RetryBudget, event_name: str) -> None:
        descriptor = budget.to_artifact_descriptor()
        self._record_artifact(descriptor, budget.trace_id, event_name, budget.logical_operation_id)

    def _persist_assessment(self, assessment: RetryEligibilityAssessment, budget: RetryBudget) -> None:
        metadata = {
            "assessment_schema": assessment.schema_version,
            "assessment_id": assessment.assessment_id,
            "logical_operation_id": assessment.logical_operation_id,
            "budget_revision": str(assessment.budget_revision),
            "failure_class": assessment.failure_class.value,
            "reconciliation_state": assessment.reconciliation_state.value if assessment.reconciliation_state else "NONE",
            "idempotency_profile": assessment.idempotency_profile.value,
            "idempotency_key_present": _bool_text(assessment.idempotency_key_present),
            "side_effect_class": assessment.side_effect_class.value,
            "code": assessment.code.value,
            "eligible": _bool_text(assessment.eligible),
            "loop_signal": assessment.loop_signal.value,
        }
        descriptor = ArtifactDescriptor(
            ref=ArtifactRef(f"retry-assessment.{assessment.assessment_id}", budget.task_id, budget.session_id),
            artifact_kind="retry.assessment",
            producer="retry.controller",
            created_at_ms=assessment.assessed_at_ms,
            sensitivity=SensitivityClass.PRIVATE,
            lifetime=ArtifactLifetime.DURABLE,
            opaque_locator=assessment.logical_operation_id,
            metadata=tuple(metadata.items()),
        )
        event_name = "retry.considered" if assessment.eligible else "retry.denied"
        self._record_artifact(descriptor, budget.trace_id, event_name, budget.logical_operation_id)

    def _persist_decision(self, decision: RetryDecision, budget: RetryBudget) -> None:
        metadata = {
            "decision_schema": decision.schema_version,
            "decision_id": decision.decision_id,
            "logical_operation_id": decision.logical_operation_id,
            "budget_revision": str(decision.budget_revision),
            "kind": decision.kind.value,
            "reason": decision.reason.value,
            "schedule": f"{decision.delay_ms}:{decision.not_before_ms}:{decision.expires_at_ms}",
            "new_governed_attempt_required": _bool_text(decision.requires_new_governed_attempt),
        }
        descriptor = ArtifactDescriptor(
            ref=ArtifactRef(f"retry-decision.{decision.decision_id}", budget.task_id, budget.session_id),
            artifact_kind="retry.decision",
            producer="retry.controller",
            created_at_ms=decision.created_at_ms,
            sensitivity=SensitivityClass.PRIVATE,
            lifetime=ArtifactLifetime.DURABLE,
            opaque_locator=decision.logical_operation_id,
            metadata=tuple(metadata.items()),
        )
        self._record_artifact(descriptor, budget.trace_id, "retry.scheduled" if decision.requires_new_governed_attempt else "retry.denied", budget.logical_operation_id)

    def _record_artifact(
        self,
        descriptor: ArtifactDescriptor,
        trace_id: str,
        event_name: str,
        logical_operation_id: str,
    ) -> None:
        event = TraceEvent(
            event_id=f"trace-event.{descriptor.ref.artifact_id}",
            task_id=descriptor.ref.task_id,
            trace_id=trace_id,
            event_name=event_name,
            observed_timestamp_ms=descriptor.created_at_ms,
            artifact_refs=(descriptor.ref,),
            attributes=(("logical_operation_id", logical_operation_id),),
        )
        self.store.record_artifact_and_trace(descriptor, event)


class ExecutionLoopDetector:
    """Bounded, persistent signal detector with no authority or replanning."""

    def __init__(
        self,
        store: PhoneHarnessStore,
        runtime_ref: RuntimeInstanceRef,
        *,
        now_ms: Callable[[], int] = _now_ms,
    ) -> None:
        if not isinstance(store, PhoneHarnessStore) or not isinstance(runtime_ref, RuntimeInstanceRef):
            raise RetryPolicyError("ExecutionLoopDetector requires typed store and Runtime identity")
        self.store = store
        self.runtime_ref = runtime_ref
        self._now_ms = now_ms

    def create_state(
        self,
        *,
        logical_operation_id: str,
        task_id: str,
        session_id: str,
        trace_id: str,
    ) -> ExecutionLoopState:
        operation = _identifier(logical_operation_id, "logical_operation_id")
        task = _identifier(task_id, "task_id")
        session = _identifier(session_id, "session_id")
        trace = _identifier(trace_id, "trace_id")
        if self._state_records(task, session, operation):
            raise LoopStateConflict("logical operation already has canonical loop state")
        state = ExecutionLoopState(
            logical_operation_id=operation,
            task_id=task,
            session_id=session,
            trace_id=trace,
            current_runtime_instance_id=self.runtime_ref.runtime_instance_id,
            action_history=(),
            failure_history=(),
            progress_history=(),
            total_steps=0,
            steps_since_progress=0,
            updated_at_ms=self._now_ms(),
        )
        self._persist_state(state, "execution-loop.state-created")
        return state

    def load_state(self, *, logical_operation_id: str, task_id: str, session_id: str) -> ExecutionLoopState:
        records = self._state_records(
            _identifier(task_id, "task_id"),
            _identifier(session_id, "session_id"),
            _identifier(logical_operation_id, "logical_operation_id"),
        )
        if not records:
            raise LoopStateNotFound("execution-loop state is not present in canonical store")
        return max(records, key=lambda value: value.revision)

    def observe(
        self,
        state: ExecutionLoopState,
        *,
        action: ActionSignature,
        failure: FailureSignature | None,
        progress: ProgressAssessment,
        max_no_progress_steps: int = 4,
        max_execution_steps: int = 100,
    ) -> tuple[ExecutionLoopState, LoopAssessment]:
        current = self._require_current_state(state)
        if not isinstance(action, ActionSignature) or not isinstance(progress, ProgressAssessment):
            raise RetryPolicyError("loop observation requires typed action and progress")
        if failure is not None and not isinstance(failure, FailureSignature):
            raise RetryPolicyError("loop failure must use FailureSignature")
        _bounded_int(max_no_progress_steps, "max_no_progress_steps", 1, MAX_EXECUTION_STEPS)
        _bounded_int(max_execution_steps, "max_execution_steps", 1, MAX_EXECUTION_STEPS)
        if max_no_progress_steps > max_execution_steps:
            raise RetryPolicyError("stagnation bound cannot exceed hard execution bound")
        action_history = (*current.action_history, action.digest)[-MAX_LOOP_HISTORY:]
        failure_history = (*current.failure_history, failure.digest if failure else "NONE")[-MAX_LOOP_HISTORY:]
        progress_history = (*current.progress_history, "1" if progress.externally_grounded else "0")[-MAX_LOOP_HISTORY:]
        total_steps = current.total_steps + 1
        steps_since_progress = 0 if progress.externally_grounded else current.steps_since_progress + 1
        signal = self._classify(
            action_history,
            failure_history,
            progress_history,
            total_steps=total_steps,
            steps_since_progress=steps_since_progress,
            max_no_progress_steps=max_no_progress_steps,
            max_execution_steps=max_execution_steps,
        )
        now = max(self._now_ms(), current.updated_at_ms + 1)
        updated = replace(
            current,
            current_runtime_instance_id=self.runtime_ref.runtime_instance_id,
            action_history=action_history,
            failure_history=failure_history,
            progress_history=progress_history,
            total_steps=total_steps,
            steps_since_progress=steps_since_progress,
            updated_at_ms=now,
            revision=current.revision + 1,
        )
        assessment = LoopAssessment(
            signal=signal,
            hard_stop=signal is not LoopSignal.NONE,
            requires_replan_signal=signal is not LoopSignal.NONE,
            observed_at_ms=now,
        )
        self._persist_state(updated, f"execution-loop.{signal.value.casefold().replace('_', '-')}")
        return updated, assessment

    @staticmethod
    def _classify(
        actions: tuple[str, ...],
        failures: tuple[str, ...],
        progress: tuple[str, ...],
        *,
        total_steps: int,
        steps_since_progress: int,
        max_no_progress_steps: int,
        max_execution_steps: int,
    ) -> LoopSignal:
        if total_steps >= max_execution_steps:
            return LoopSignal.HARD_EXECUTION_BUDGET_EXCEEDED
        if len(actions) >= 3 and len(set(actions[-3:])) == 1 and "1" not in progress[-3:]:
            return LoopSignal.IDENTICAL_REPETITION
        if len(failures) >= 3 and failures[-1] != "NONE" and len(set(failures[-3:])) == 1 and "1" not in progress[-3:]:
            return LoopSignal.REPEATED_FAILURE_PATTERN
        for cycle_length in (2, 3):
            if len(actions) >= cycle_length * 2:
                window = actions[-cycle_length * 2 :]
                progress_window = progress[-cycle_length * 2 :]
                if window[:cycle_length] == window[cycle_length:] and "1" not in progress_window:
                    return LoopSignal.OSCILLATION
        if steps_since_progress >= max_no_progress_steps:
            return LoopSignal.STAGNATION
        return LoopSignal.NONE

    def _require_current_state(self, state: ExecutionLoopState) -> ExecutionLoopState:
        if not isinstance(state, ExecutionLoopState):
            raise RetryPolicyError("loop observation requires ExecutionLoopState")
        current = self.load_state(
            logical_operation_id=state.logical_operation_id,
            task_id=state.task_id,
            session_id=state.session_id,
        )
        if current.revision != state.revision:
            raise LoopStateConflict("execution-loop state revision is no longer current")
        return current

    def _state_records(self, task_id: str, session_id: str, logical_operation_id: str) -> tuple[ExecutionLoopState, ...]:
        return tuple(
            ExecutionLoopState.from_artifact_descriptor(descriptor)
            for descriptor in self.store.list_artifacts(task_id, session_id=session_id)
            if descriptor.artifact_kind == "execution.loop-state"
            and descriptor.opaque_locator == logical_operation_id
        )

    def _persist_state(self, state: ExecutionLoopState, event_name: str) -> None:
        descriptor = state.to_artifact_descriptor()
        event = TraceEvent(
            event_id=f"trace-event.{descriptor.ref.artifact_id}",
            task_id=state.task_id,
            trace_id=state.trace_id,
            event_name=event_name,
            observed_timestamp_ms=state.updated_at_ms,
            artifact_refs=(descriptor.ref,),
            attributes=(
                ("logical_operation_id", state.logical_operation_id),
                ("total_steps", str(state.total_steps)),
                ("steps_since_progress", str(state.steps_since_progress)),
            ),
        )
        self.store.record_artifact_and_trace(descriptor, event)


__all__ = [
    "MAX_EXECUTION_STEPS",
    "MAX_LOOP_HISTORY",
    "MAX_RETRY_ATTEMPTS",
    "ActionSignature",
    "ExecutionLoopDetector",
    "ExecutionLoopState",
    "FailureSignature",
    "LoopAssessment",
    "LoopSignal",
    "LoopStateConflict",
    "LoopStateNotFound",
    "ProgressAssessment",
    "ProgressKind",
    "RetryAdmissionError",
    "RetryAttemptRef",
    "RetryBudget",
    "RetryBudgetConflict",
    "RetryBudgetNotFound",
    "RetryController",
    "RetryDecision",
    "RetryDecisionKind",
    "RetryEligibilityAssessment",
    "RetryEligibilityCode",
    "RetryError",
    "RetryFailureClass",
    "RetryPolicy",
    "RetryPolicyError",
]
