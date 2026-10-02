#!/usr/bin/env python3
"""Host-only replanning, human-intervention, and credential policy foundation.

The types in this module are non-authoritative. They cannot authorize, bind,
dispatch, execute, retry, verify, resume, or bypass protected user interfaces.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re
import threading
import time
from typing import Any, Callable, Mapping, Protocol, TypeVar
import uuid

from phoneharness_agent import (
    RecoveryDecision,
    TaskExecutionReason,
    TaskExecutionState,
    TaskExecutionView,
)
from phoneharness_contracts import (
    ArtifactDescriptor,
    ArtifactLifetime,
    ArtifactRef,
    SensitivityClass,
)
from phoneharness_provider_health import FallbackDecision, FallbackDecisionKind
from phoneharness_retry import (
    LoopAssessment,
    LoopSignal,
    RetryEligibilityAssessment,
    RetryEligibilityCode,
)
from phoneharness_runtime import RuntimeInstanceRef
from phoneharness_store import PhoneHarnessStore, TraceEvent, UnknownArtifactError
from phoneharness_uncertainty import (
    OutcomeReconciliationAssessment,
    ReconciliationDisposition,
    ReconciliationState,
)


REPLAN_ASSESSMENT_SCHEMA_VERSION = "phoneharness.replan-assessment.v1"
USER_INTERVENTION_SCHEMA_VERSION = "phoneharness.user-intervention.v1"
USER_DECISION_SCHEMA_VERSION = "phoneharness.user-decision.v1"
CREDENTIAL_HANDLE_SCHEMA_VERSION = "phoneharness.credential-handle.v1"
CREDENTIAL_REQUEST_SCHEMA_VERSION = "phoneharness.credential-request.v1"
CREDENTIAL_ASSESSMENT_SCHEMA_VERSION = "phoneharness.credential-use-assessment.v1"
AUTH_EVIDENCE_SCHEMA_VERSION = "phoneharness.authentication-evidence.v1"
SECURE_UI_SCHEMA_VERSION = "phoneharness.secure-ui-assessment.v1"
MAX_SECRET_BYTES = 65_536

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class InterventionError(RuntimeError):
    """Base class for deterministic M7 policy failures."""


class InterventionPolicyError(InterventionError):
    """A typed intervention or credential contract is invalid."""


class UserDecisionRejected(InterventionError):
    """A stale, replayed, expired, or scope-mismatched decision was rejected."""


class CredentialUseDenied(InterventionError):
    """A credential request failed closed before secret delivery."""


class ReplanReason(str, Enum):
    RETRY_EXHAUSTED = "RETRY_EXHAUSTED"
    LOOP_DETECTED = "LOOP_DETECTED"
    NO_HEALTHY_PROVIDER = "NO_HEALTHY_PROVIDER"
    PRECONDITION_CHANGED = "PRECONDITION_CHANGED"
    CAPABILITY_UNAVAILABLE = "CAPABILITY_UNAVAILABLE"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    USER_INTENT_CHANGED = "USER_INTENT_CHANGED"
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"


class UserInterventionKind(str, Enum):
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    USER_ACTION_REQUIRED = "USER_ACTION_REQUIRED"
    CHOICE_REQUIRED = "CHOICE_REQUIRED"


class UserDecisionKind(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AuthRequirement(str, Enum):
    NONE = "NONE"
    USER_PRESENCE = "USER_PRESENCE"
    DEVICE_OWNER_AUTHENTICATION = "DEVICE_OWNER_AUTHENTICATION"
    USER_ACTION_REQUIRED = "USER_ACTION_REQUIRED"


class CredentialUseCode(str, Enum):
    ALLOWED = "ALLOWED"
    UNKNOWN_HANDLE = "UNKNOWN_HANDLE"
    WRONG_TASK = "WRONG_TASK"
    WRONG_PROVIDER = "WRONG_PROVIDER"
    WRONG_PURPOSE = "WRONG_PURPOSE"
    WRONG_EXECUTION = "WRONG_EXECUTION"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    AUTHENTICATION_INVALID = "AUTHENTICATION_INVALID"
    ALREADY_USED = "ALREADY_USED"
    SECRET_UNAVAILABLE = "SECRET_UNAVAILABLE"


class SecureUIKind(str, Enum):
    NONE = "NONE"
    PASSCODE = "PASSCODE"
    BIOMETRIC = "BIOMETRIC"
    BANK_AUTHENTICATION = "BANK_AUTHENTICATION"
    OTP_PROMPT = "OTP_PROMPT"
    SYSTEM_CREDENTIAL_SHEET = "SYSTEM_CREDENTIAL_SHEET"
    OTHER_PROTECTED_ENTRY = "OTHER_PROTECTED_ENTRY"


CredentialClass = SensitivityClass


def _identifier(value: Any, field_name: str) -> str:
    normalized = str(value or "").strip()
    if _IDENTIFIER.fullmatch(normalized) is None:
        raise InterventionPolicyError(f"{field_name} must be an opaque bounded identifier")
    return normalized


def _optional_identifier(value: Any, field_name: str) -> str | None:
    return None if value is None else _identifier(value, field_name)


def _timestamp(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InterventionPolicyError(f"{field_name} must be a non-negative integer")
    return value


def _digest(value: Any, field_name: str) -> str:
    normalized = str(value or "")
    if _DIGEST.fullmatch(normalized) is None:
        raise InterventionPolicyError(f"{field_name} must be a SHA-256 digest")
    return normalized


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _new_identifier(prefix: str) -> str:
    return f"{prefix}.{uuid.uuid4().hex}"


def _stable_id(prefix: str, value: str) -> str:
    return f"{prefix}.{hashlib.sha256(value.encode('utf-8')).hexdigest()[:40]}"


def operation_fingerprint(
    *,
    capability_id: str,
    operation: str,
    target_ref: str,
) -> str:
    """Build a safe binding digest without accepting raw operation arguments."""

    payload = {
        "capability_id": _identifier(capability_id, "capability_id"),
        "operation": _identifier(operation, "operation"),
        "target_ref": _identifier(target_ref, "target_ref"),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ReplanAssessment:
    assessment_id: str
    reason: ReplanReason
    observed_at_ms: int
    requires_new_plan: bool = True
    requires_user_intervention: bool = False
    fresh_reconciliation_required: bool = True
    schema_version: str = REPLAN_ASSESSMENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != REPLAN_ASSESSMENT_SCHEMA_VERSION:
            raise InterventionPolicyError("unsupported ReplanAssessment schema version")
        object.__setattr__(self, "assessment_id", _identifier(self.assessment_id, "assessment_id"))
        object.__setattr__(self, "reason", ReplanReason(self.reason))
        _timestamp(self.observed_at_ms, "observed_at_ms")
        if not self.requires_new_plan or not self.fresh_reconciliation_required:
            raise InterventionPolicyError("replan signal requires a new plan and fresh reconciliation")

    def audit(self) -> dict[str, Any]:
        return {
            "assessment_id": self.assessment_id,
            "reason": self.reason.value,
            "requires_new_plan": True,
            "requires_user_intervention": self.requires_user_intervention,
            "fresh_reconciliation_required": True,
            "authority": False,
            "dispatch": False,
            "retry": False,
        }


class ReplanPolicy:
    """Adapts frozen failure signals into non-authoritative planning signals."""

    def __init__(
        self,
        *,
        now_ms: Callable[[], int] = _now_ms,
        id_factory: Callable[[str], str] = _new_identifier,
    ) -> None:
        self._now_ms = now_ms
        self._id_factory = id_factory

    def from_retry(self, assessment: RetryEligibilityAssessment) -> ReplanAssessment:
        if not isinstance(assessment, RetryEligibilityAssessment):
            raise InterventionPolicyError("retry replan signal requires RetryEligibilityAssessment")
        if assessment.code not in {
            RetryEligibilityCode.BUDGET_EXHAUSTED,
            RetryEligibilityCode.DEADLINE_EXHAUSTED,
        }:
            raise InterventionPolicyError("retry assessment is not an exhaustion signal")
        return self._assessment(ReplanReason.RETRY_EXHAUSTED)

    def from_loop(self, assessment: LoopAssessment) -> ReplanAssessment:
        if not isinstance(assessment, LoopAssessment) or assessment.signal is LoopSignal.NONE:
            raise InterventionPolicyError("loop replan requires a hard loop signal")
        return self._assessment(ReplanReason.LOOP_DETECTED)

    def from_fallback(self, decision: FallbackDecision) -> ReplanAssessment:
        if not isinstance(decision, FallbackDecision):
            raise InterventionPolicyError("fallback replan requires FallbackDecision")
        if decision.kind is not FallbackDecisionKind.NO_HEALTHY_PROVIDER:
            raise InterventionPolicyError("fallback decision is not a no-provider signal")
        return self._assessment(ReplanReason.NO_HEALTHY_PROVIDER)

    def from_reconciliation(self, assessment: OutcomeReconciliationAssessment) -> ReplanAssessment:
        if not isinstance(assessment, OutcomeReconciliationAssessment):
            raise InterventionPolicyError("replan signal requires OutcomeReconciliationAssessment")
        if assessment.disposition is not ReconciliationDisposition.WAITING_FOR_USER:
            raise InterventionPolicyError("reconciliation does not require user intervention")
        return self._assessment(
            ReplanReason.RECONCILIATION_REQUIRED,
            user=assessment.state is ReconciliationState.WAITING_FOR_USER,
        )

    def direct(self, reason: ReplanReason) -> ReplanAssessment:
        typed = ReplanReason(reason)
        return self._assessment(
            typed,
            user=typed in {ReplanReason.USER_INTENT_CHANGED, ReplanReason.AUTHENTICATION_REQUIRED},
        )

    def _assessment(self, reason: ReplanReason, *, user: bool = False) -> ReplanAssessment:
        return ReplanAssessment(
            assessment_id=self._id_factory("replan-assessment"),
            reason=reason,
            observed_at_ms=self._now_ms(),
            requires_user_intervention=user,
        )


@dataclass(frozen=True)
class UserInterventionRequest:
    request_id: str
    task_id: str
    session_id: str
    trace_id: str
    kind: UserInterventionKind
    operation_fingerprint: str
    created_at_ms: int
    expires_at_ms: int
    runtime_instance_id: str
    step_id: str | None = None
    execution_id: str | None = None
    schema_version: str = USER_INTERVENTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != USER_INTERVENTION_SCHEMA_VERSION:
            raise InterventionPolicyError("unsupported UserInterventionRequest schema version")
        for name in ("request_id", "task_id", "session_id", "trace_id", "runtime_instance_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(self, "step_id", _optional_identifier(self.step_id, "step_id"))
        object.__setattr__(self, "execution_id", _optional_identifier(self.execution_id, "execution_id"))
        object.__setattr__(self, "kind", UserInterventionKind(self.kind))
        object.__setattr__(
            self,
            "operation_fingerprint",
            _digest(self.operation_fingerprint, "operation_fingerprint"),
        )
        _timestamp(self.created_at_ms, "created_at_ms")
        _timestamp(self.expires_at_ms, "expires_at_ms")
        if self.expires_at_ms <= self.created_at_ms:
            raise InterventionPolicyError("user intervention request must have a future expiry")

    def waiting_view(self) -> TaskExecutionView:
        secure = self.kind in {
            UserInterventionKind.AUTHENTICATION_REQUIRED,
            UserInterventionKind.USER_ACTION_REQUIRED,
        }
        return TaskExecutionView(
            TaskExecutionState.WAITING_FOR_USER,
            TaskExecutionReason.SECURE_UI_REQUIRES_USER if secure else None,
            RecoveryDecision.WAIT_FOR_USER_THEN_REOBSERVE,
        )

    def audit(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "task_id": self.task_id,
            "kind": self.kind.value,
            "operation_fingerprint": self.operation_fingerprint,
            "expires_at_ms": self.expires_at_ms,
            "task_state": TaskExecutionState.WAITING_FOR_USER.value,
            "authority": False,
            "dispatch": False,
        }

    def to_artifact_descriptor(self) -> ArtifactDescriptor:
        metadata = {
            "request_schema": self.schema_version,
            "trace_id": self.trace_id,
            "kind": self.kind.value,
            "operation_fingerprint": self.operation_fingerprint,
            "expires_at_ms": str(self.expires_at_ms),
            "runtime_instance_id": self.runtime_instance_id,
            "step_id": self.step_id or "NONE",
            "execution_id": self.execution_id or "NONE",
        }
        return ArtifactDescriptor(
            ref=ArtifactRef(self.request_id, self.task_id, self.session_id),
            artifact_kind="user.intervention-request",
            producer="user.intervention-manager",
            created_at_ms=self.created_at_ms,
            sensitivity=SensitivityClass.PRIVATE,
            lifetime=ArtifactLifetime.DURABLE,
            opaque_locator=self.request_id,
            metadata=tuple(metadata.items()),
        )

    @classmethod
    def from_artifact_descriptor(cls, descriptor: ArtifactDescriptor) -> "UserInterventionRequest":
        if descriptor.artifact_kind != "user.intervention-request" or descriptor.ref.session_id is None:
            raise InterventionPolicyError("durable record is not UserInterventionRequest")
        metadata = dict(descriptor.metadata)
        required = {
            "request_schema",
            "trace_id",
            "kind",
            "operation_fingerprint",
            "expires_at_ms",
            "runtime_instance_id",
            "step_id",
            "execution_id",
        }
        if set(metadata) != required:
            raise InterventionPolicyError("UserInterventionRequest durable fields do not match schema")
        return cls(
            request_id=descriptor.ref.artifact_id,
            task_id=descriptor.ref.task_id,
            session_id=descriptor.ref.session_id,
            trace_id=metadata["trace_id"],
            kind=UserInterventionKind(metadata["kind"]),
            operation_fingerprint=metadata["operation_fingerprint"],
            created_at_ms=descriptor.created_at_ms,
            expires_at_ms=int(metadata["expires_at_ms"]),
            runtime_instance_id=metadata["runtime_instance_id"],
            step_id=None if metadata["step_id"] == "NONE" else metadata["step_id"],
            execution_id=None if metadata["execution_id"] == "NONE" else metadata["execution_id"],
            schema_version=metadata["request_schema"],
        )


@dataclass(frozen=True)
class UserInterventionDecision:
    decision_id: str
    request_id: str
    task_id: str
    session_id: str
    kind: UserDecisionKind
    operation_fingerprint: str
    decided_at_ms: int
    selection_ref: str | None = None
    schema_version: str = USER_DECISION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != USER_DECISION_SCHEMA_VERSION:
            raise InterventionPolicyError("unsupported UserInterventionDecision schema version")
        for name in ("decision_id", "request_id", "task_id", "session_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(self, "selection_ref", _optional_identifier(self.selection_ref, "selection_ref"))
        object.__setattr__(self, "kind", UserDecisionKind(self.kind))
        object.__setattr__(
            self,
            "operation_fingerprint",
            _digest(self.operation_fingerprint, "operation_fingerprint"),
        )
        _timestamp(self.decided_at_ms, "decided_at_ms")

    def audit(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "request_id": self.request_id,
            "kind": self.kind.value,
            "consumed_once": True,
            "requires_fresh_reconciliation": True,
            "authority": False,
            "dispatch": False,
        }

    def to_artifact_descriptor(self) -> ArtifactDescriptor:
        metadata = {
            "decision_schema": self.schema_version,
            "request_id": self.request_id,
            "kind": self.kind.value,
            "operation_fingerprint": self.operation_fingerprint,
            "selection_ref": self.selection_ref or "NONE",
            "consumed_once": "YES",
        }
        return ArtifactDescriptor(
            ref=ArtifactRef(self.decision_id, self.task_id, self.session_id),
            artifact_kind="user.intervention-decision",
            producer="user.intervention-manager",
            created_at_ms=self.decided_at_ms,
            sensitivity=SensitivityClass.PRIVATE,
            lifetime=ArtifactLifetime.DURABLE,
            opaque_locator=self.request_id,
            metadata=tuple(metadata.items()),
        )


@dataclass(frozen=True)
class ResumeAfterUserActionAssessment:
    can_continue_planning: bool
    fresh_observation_present: bool
    reconciliation_complete: bool
    mutation_replay_allowed: bool = False
    authority: bool = False

    def __post_init__(self) -> None:
        if self.mutation_replay_allowed or self.authority:
            raise InterventionPolicyError("resume assessment cannot replay or authorize mutation")
        if self.can_continue_planning and not (
            self.fresh_observation_present and self.reconciliation_complete
        ):
            raise InterventionPolicyError("resume requires fresh observation and reconciliation")


class UserInterventionManager:
    """Durable pending-decision ownership with one-time decision consumption."""

    def __init__(
        self,
        store: PhoneHarnessStore,
        runtime_ref: RuntimeInstanceRef,
        *,
        now_ms: Callable[[], int] = _now_ms,
        id_factory: Callable[[str], str] = _new_identifier,
    ) -> None:
        if not isinstance(store, PhoneHarnessStore) or not isinstance(runtime_ref, RuntimeInstanceRef):
            raise InterventionPolicyError("manager requires typed Store and Runtime identity")
        self.store = store
        self.runtime_ref = runtime_ref
        self._now_ms = now_ms
        self._id_factory = id_factory
        self._mutex = threading.RLock()

    def create_request(
        self,
        *,
        task_id: str,
        session_id: str,
        trace_id: str,
        kind: UserInterventionKind,
        operation_fingerprint: str,
        ttl_ms: int,
        step_id: str | None = None,
        execution_id: str | None = None,
    ) -> UserInterventionRequest:
        if isinstance(ttl_ms, bool) or not isinstance(ttl_ms, int) or not 1 <= ttl_ms <= 86_400_000:
            raise InterventionPolicyError("user intervention ttl is outside its bounded range")
        now = self._now_ms()
        request = UserInterventionRequest(
            request_id=self._id_factory("user-request"),
            task_id=task_id,
            session_id=session_id,
            trace_id=trace_id,
            kind=kind,
            operation_fingerprint=operation_fingerprint,
            created_at_ms=now,
            expires_at_ms=now + ttl_ms,
            runtime_instance_id=self.runtime_ref.runtime_instance_id,
            step_id=step_id,
            execution_id=execution_id,
        )
        self._persist(request.to_artifact_descriptor(), request.trace_id, "user_intervention_requested")
        return request

    def load_request(
        self,
        *,
        request_id: str,
        task_id: str,
        session_id: str,
    ) -> UserInterventionRequest:
        ref = ArtifactRef(request_id, task_id, session_id)
        return UserInterventionRequest.from_artifact_descriptor(self.store.get_artifact(ref))

    def submit_decision(
        self,
        request: UserInterventionRequest,
        *,
        task_id: str,
        operation_fingerprint: str,
        decision: UserDecisionKind,
        selection_ref: str | None = None,
    ) -> UserInterventionDecision:
        if not isinstance(request, UserInterventionRequest):
            raise UserDecisionRejected("decision requires a typed pending request")
        task = _identifier(task_id, "task_id")
        fingerprint = _digest(operation_fingerprint, "operation_fingerprint")
        now = self._now_ms()
        with self._mutex:
            if task != request.task_id or fingerprint != request.operation_fingerprint:
                raise UserDecisionRejected("user decision scope does not match pending request")
            if now > request.expires_at_ms:
                raise UserDecisionRejected("user decision request expired")
            decision_id = _stable_id("user-decision", request.request_id)
            ref = ArtifactRef(decision_id, request.task_id, request.session_id)
            try:
                self.store.get_artifact(ref)
            except UnknownArtifactError:
                pass
            else:
                raise UserDecisionRejected("user decision was already consumed")
            result = UserInterventionDecision(
                decision_id=decision_id,
                request_id=request.request_id,
                task_id=request.task_id,
                session_id=request.session_id,
                kind=decision,
                operation_fingerprint=request.operation_fingerprint,
                decided_at_ms=now,
                selection_ref=selection_ref,
            )
            self._persist(
                result.to_artifact_descriptor(),
                request.trace_id,
                "user_approved" if result.kind is UserDecisionKind.APPROVED else "user_decision_recorded",
            )
            return result

    def assess_resume(
        self,
        request: UserInterventionRequest,
        decision: UserInterventionDecision,
        *,
        fresh_observation_present: bool,
        reconciliation_complete: bool,
    ) -> ResumeAfterUserActionAssessment:
        if (
            decision.request_id != request.request_id
            or decision.task_id != request.task_id
            or decision.operation_fingerprint != request.operation_fingerprint
        ):
            raise UserDecisionRejected("decision does not belong to pending request")
        approved = decision.kind in {UserDecisionKind.APPROVED, UserDecisionKind.COMPLETED}
        return ResumeAfterUserActionAssessment(
            can_continue_planning=bool(
                approved and fresh_observation_present and reconciliation_complete
            ),
            fresh_observation_present=fresh_observation_present,
            reconciliation_complete=reconciliation_complete,
        )

    def _persist(self, descriptor: ArtifactDescriptor, trace_id: str, event_name: str) -> None:
        event = TraceEvent(
            event_id=f"trace-event.{descriptor.ref.artifact_id}",
            task_id=descriptor.ref.task_id,
            trace_id=trace_id,
            event_name=event_name,
            observed_timestamp_ms=descriptor.created_at_ms,
            artifact_refs=(descriptor.ref,),
            attributes=(("policy_class", "NON_AUTHORITATIVE"), ("dispatch_effect", "NONE")),
        )
        self.store.record_artifact_and_trace(descriptor, event)


@dataclass(frozen=True)
class AuthenticationEvidenceRef:
    authentication_id: str
    request_id: str
    task_id: str
    execution_id: str
    requirement: AuthRequirement
    satisfied: bool
    observed_at_ms: int
    expires_at_ms: int
    schema_version: str = AUTH_EVIDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != AUTH_EVIDENCE_SCHEMA_VERSION:
            raise InterventionPolicyError("unsupported AuthenticationEvidenceRef schema version")
        for name in ("authentication_id", "request_id", "task_id", "execution_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(self, "requirement", AuthRequirement(self.requirement))
        _timestamp(self.observed_at_ms, "observed_at_ms")
        _timestamp(self.expires_at_ms, "expires_at_ms")
        if self.expires_at_ms <= self.observed_at_ms:
            raise InterventionPolicyError("authentication evidence must expire")

    def audit(self) -> dict[str, Any]:
        return {
            "authentication_id": self.authentication_id,
            "requirement": self.requirement.value,
            "satisfied": self.satisfied,
            "authorization": False,
        }


@dataclass(frozen=True)
class CredentialHandleRef:
    handle_id: str
    task_id: str
    session_id: str
    provider_id: str
    purpose: str
    execution_id: str
    credential_class: SensitivityClass
    auth_requirement: AuthRequirement
    created_at_ms: int
    expires_at_ms: int
    single_use: bool
    schema_version: str = CREDENTIAL_HANDLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != CREDENTIAL_HANDLE_SCHEMA_VERSION:
            raise InterventionPolicyError("unsupported CredentialHandleRef schema version")
        for name in (
            "handle_id",
            "task_id",
            "session_id",
            "provider_id",
            "purpose",
            "execution_id",
        ):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(self, "credential_class", SensitivityClass(self.credential_class))
        object.__setattr__(self, "auth_requirement", AuthRequirement(self.auth_requirement))
        _timestamp(self.created_at_ms, "created_at_ms")
        _timestamp(self.expires_at_ms, "expires_at_ms")
        if self.expires_at_ms <= self.created_at_ms:
            raise InterventionPolicyError("credential handle must expire")
        if self.credential_class in {
            SensitivityClass.AUTH_REQUIRED,
            SensitivityClass.NEVER_MODEL_VISIBLE,
        } and self.auth_requirement is AuthRequirement.NONE:
            raise InterventionPolicyError("protected credential class requires authentication policy")

    def audit(self) -> dict[str, Any]:
        return {
            "handle_id": self.handle_id,
            "provider_id": self.provider_id,
            "purpose": self.purpose,
            "credential_class": self.credential_class.value,
            "auth_requirement": self.auth_requirement.value,
            "expires_at_ms": self.expires_at_ms,
            "single_use": self.single_use,
            "plaintext_secret": False,
            "credential": False,
            "authorization": False,
        }

    def to_artifact_descriptor(self) -> ArtifactDescriptor:
        metadata = {
            "handle_schema": self.schema_version,
            "provider_id": self.provider_id,
            "purpose": self.purpose,
            "execution_id": self.execution_id,
            "sensitivity": self.credential_class.value,
            "auth_requirement": self.auth_requirement.value,
            "expires_at_ms": str(self.expires_at_ms),
            "single_use": "YES" if self.single_use else "NO",
        }
        return ArtifactDescriptor(
            ref=ArtifactRef(self.handle_id, self.task_id, self.session_id),
            artifact_kind="credential.handle-metadata",
            producer="credential.broker",
            created_at_ms=self.created_at_ms,
            sensitivity=SensitivityClass.NEVER_MODEL_VISIBLE,
            lifetime=ArtifactLifetime.DURABLE,
            opaque_locator=self.handle_id,
            metadata=tuple(metadata.items()),
        )

    @classmethod
    def from_artifact_descriptor(cls, descriptor: ArtifactDescriptor) -> "CredentialHandleRef":
        if descriptor.artifact_kind != "credential.handle-metadata" or descriptor.ref.session_id is None:
            raise InterventionPolicyError("durable record is not CredentialHandleRef")
        metadata = dict(descriptor.metadata)
        required = {
            "handle_schema",
            "provider_id",
            "purpose",
            "execution_id",
            "sensitivity",
            "auth_requirement",
            "expires_at_ms",
            "single_use",
        }
        if set(metadata) != required:
            raise InterventionPolicyError("CredentialHandleRef durable fields do not match schema")
        return cls(
            handle_id=descriptor.ref.artifact_id,
            task_id=descriptor.ref.task_id,
            session_id=descriptor.ref.session_id,
            provider_id=metadata["provider_id"],
            purpose=metadata["purpose"],
            execution_id=metadata["execution_id"],
            credential_class=SensitivityClass(metadata["sensitivity"]),
            auth_requirement=AuthRequirement(metadata["auth_requirement"]),
            created_at_ms=descriptor.created_at_ms,
            expires_at_ms=int(metadata["expires_at_ms"]),
            single_use=metadata["single_use"] == "YES",
            schema_version=metadata["handle_schema"],
        )


@dataclass(frozen=True)
class CredentialRequest:
    request_id: str
    handle_id: str
    task_id: str
    provider_id: str
    purpose: str
    execution_id: str
    requested_at_ms: int
    schema_version: str = CREDENTIAL_REQUEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != CREDENTIAL_REQUEST_SCHEMA_VERSION:
            raise InterventionPolicyError("unsupported CredentialRequest schema version")
        for name in ("request_id", "handle_id", "task_id", "provider_id", "purpose", "execution_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        _timestamp(self.requested_at_ms, "requested_at_ms")


@dataclass(frozen=True)
class CredentialUseAssessment:
    assessment_id: str
    request_id: str
    code: CredentialUseCode
    allowed: bool
    assessed_at_ms: int
    schema_version: str = CREDENTIAL_ASSESSMENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != CREDENTIAL_ASSESSMENT_SCHEMA_VERSION:
            raise InterventionPolicyError("unsupported CredentialUseAssessment schema version")
        object.__setattr__(self, "assessment_id", _identifier(self.assessment_id, "assessment_id"))
        object.__setattr__(self, "request_id", _identifier(self.request_id, "request_id"))
        object.__setattr__(self, "code", CredentialUseCode(self.code))
        _timestamp(self.assessed_at_ms, "assessed_at_ms")
        if self.allowed is not (self.code is CredentialUseCode.ALLOWED):
            raise InterventionPolicyError("credential assessment flag does not match its code")

    def audit(self) -> dict[str, Any]:
        return {
            "assessment_id": self.assessment_id,
            "request_id": self.request_id,
            "code": self.code.value,
            "allowed": self.allowed,
            "authorization": False,
            "plaintext_secret": False,
        }


@dataclass(frozen=True)
class CredentialUseResult:
    result_ref: str
    status: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "result_ref", _identifier(self.result_ref, "result_ref"))
        object.__setattr__(self, "status", _identifier(self.status, "status"))


class CredentialSecretBackend(Protocol):
    def put(self, handle_id: str, secret: bytes) -> None: ...

    def get(self, handle_id: str) -> bytes | None: ...

    def delete(self, handle_id: str) -> None: ...


class InMemoryCredentialVault:
    """Host test backend; secrets are process-local and never persisted."""

    def __init__(self) -> None:
        self._values: dict[str, bytes] = {}

    def put(self, handle_id: str, secret: bytes) -> None:
        self._values[_identifier(handle_id, "handle_id")] = bytes(secret)

    def get(self, handle_id: str) -> bytes | None:
        value = self._values.get(_identifier(handle_id, "handle_id"))
        return None if value is None else bytes(value)

    def delete(self, handle_id: str) -> None:
        self._values.pop(_identifier(handle_id, "handle_id"), None)


_T = TypeVar("_T")


class CredentialBroker:
    """Opaque-handle broker that never returns plaintext to model-facing code."""

    def __init__(
        self,
        store: PhoneHarnessStore,
        runtime_ref: RuntimeInstanceRef,
        vault: CredentialSecretBackend,
        *,
        now_ms: Callable[[], int] = _now_ms,
        id_factory: Callable[[str], str] = _new_identifier,
    ) -> None:
        if not isinstance(store, PhoneHarnessStore) or not isinstance(runtime_ref, RuntimeInstanceRef):
            raise InterventionPolicyError("CredentialBroker requires typed Store and Runtime identity")
        if not all(callable(getattr(vault, name, None)) for name in ("put", "get", "delete")):
            raise InterventionPolicyError("CredentialBroker requires a protected secret backend")
        self.store = store
        self.runtime_ref = runtime_ref
        self.vault = vault
        self._now_ms = now_ms
        self._id_factory = id_factory
        self._mutex = threading.RLock()

    def register(
        self,
        *,
        task_id: str,
        session_id: str,
        trace_id: str,
        provider_id: str,
        purpose: str,
        execution_id: str,
        secret: str | bytes,
        credential_class: SensitivityClass = SensitivityClass.NEVER_MODEL_VISIBLE,
        auth_requirement: AuthRequirement = AuthRequirement.USER_PRESENCE,
        ttl_ms: int = 300_000,
        single_use: bool = False,
    ) -> CredentialHandleRef:
        value = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
        if not value or len(value) > MAX_SECRET_BYTES:
            raise InterventionPolicyError("credential secret size is outside its bounded range")
        if isinstance(ttl_ms, bool) or not isinstance(ttl_ms, int) or not 1 <= ttl_ms <= 86_400_000:
            raise InterventionPolicyError("credential ttl is outside its bounded range")
        now = self._now_ms()
        handle = CredentialHandleRef(
            handle_id=self._id_factory("credential-handle"),
            task_id=task_id,
            session_id=session_id,
            provider_id=provider_id,
            purpose=purpose,
            execution_id=execution_id,
            credential_class=credential_class,
            auth_requirement=auth_requirement,
            created_at_ms=now,
            expires_at_ms=now + ttl_ms,
            single_use=single_use,
        )
        with self._mutex:
            self.vault.put(handle.handle_id, value)
            try:
                self._persist(handle.to_artifact_descriptor(), trace_id, "credential_handle_registered")
            except Exception:
                self.vault.delete(handle.handle_id)
                raise
        return handle

    def load_handle(self, *, handle_id: str, task_id: str, session_id: str) -> CredentialHandleRef:
        descriptor = self.store.get_artifact(ArtifactRef(handle_id, task_id, session_id))
        return CredentialHandleRef.from_artifact_descriptor(descriptor)

    def revoke(self, handle: CredentialHandleRef, *, trace_id: str) -> None:
        if not isinstance(handle, CredentialHandleRef):
            raise InterventionPolicyError("credential revocation requires CredentialHandleRef")
        descriptor = self._state_descriptor(handle, "credential.revocation", self._now_ms())
        with self._mutex:
            self.vault.delete(handle.handle_id)
            self._persist(descriptor, trace_id, "credential_revoked")

    def assess_use(
        self,
        handle: CredentialHandleRef,
        request: CredentialRequest,
        *,
        authentication: AuthenticationEvidenceRef | None = None,
    ) -> CredentialUseAssessment:
        now = self._now_ms()
        code = self._use_code(handle, request, authentication, now)
        return CredentialUseAssessment(
            assessment_id=self._id_factory("credential-assessment"),
            request_id=request.request_id,
            code=code,
            allowed=code is CredentialUseCode.ALLOWED,
            assessed_at_ms=now,
        )

    def use_credential(
        self,
        handle: CredentialHandleRef,
        request: CredentialRequest,
        *,
        trace_id: str,
        consumer: Callable[[bytes], CredentialUseResult],
        authentication: AuthenticationEvidenceRef | None = None,
    ) -> CredentialUseResult:
        if not callable(consumer):
            raise InterventionPolicyError("credential use requires a narrow typed consumer")
        with self._mutex:
            assessment = self.assess_use(handle, request, authentication=authentication)
            if not assessment.allowed:
                self._record_denial(handle, request, trace_id, assessment)
                raise CredentialUseDenied(f"credential use denied: {assessment.code.value}")
            secret = self.vault.get(handle.handle_id)
            if secret is None:
                unavailable = CredentialUseAssessment(
                    assessment_id=self._id_factory("credential-assessment"),
                    request_id=request.request_id,
                    code=CredentialUseCode.SECRET_UNAVAILABLE,
                    allowed=False,
                    assessed_at_ms=self._now_ms(),
                )
                self._record_denial(handle, request, trace_id, unavailable)
                raise CredentialUseDenied("credential use denied: SECRET_UNAVAILABLE")
            descriptor = self._use_descriptor(handle, request, assessment.assessed_at_ms)
            self._persist(descriptor, trace_id, "credential_handle_resolved")
            if handle.single_use:
                self.vault.delete(handle.handle_id)
            try:
                result = consumer(bytes(secret))
            except BaseException:
                raise CredentialUseDenied("credential consumer failed") from None
            finally:
                secret = b""
            if not isinstance(result, CredentialUseResult):
                raise CredentialUseDenied("credential consumer returned an unsafe result")
            return result

    def _use_code(
        self,
        handle: CredentialHandleRef,
        request: CredentialRequest,
        authentication: AuthenticationEvidenceRef | None,
        now: int,
    ) -> CredentialUseCode:
        if not isinstance(handle, CredentialHandleRef) or not isinstance(request, CredentialRequest):
            return CredentialUseCode.UNKNOWN_HANDLE
        try:
            current = self.load_handle(
                handle_id=handle.handle_id,
                task_id=handle.task_id,
                session_id=handle.session_id,
            )
        except Exception:
            return CredentialUseCode.UNKNOWN_HANDLE
        if current != handle or request.handle_id != handle.handle_id:
            return CredentialUseCode.UNKNOWN_HANDLE
        if self._has_state(handle, "credential.revocation"):
            return CredentialUseCode.REVOKED
        if now > handle.expires_at_ms:
            return CredentialUseCode.EXPIRED
        if request.task_id != handle.task_id:
            return CredentialUseCode.WRONG_TASK
        if request.provider_id != handle.provider_id:
            return CredentialUseCode.WRONG_PROVIDER
        if request.purpose != handle.purpose:
            return CredentialUseCode.WRONG_PURPOSE
        if request.execution_id != handle.execution_id:
            return CredentialUseCode.WRONG_EXECUTION
        if self._has_use_request(handle, request.request_id) or (
            handle.single_use and self._has_any_use(handle)
        ):
            return CredentialUseCode.ALREADY_USED
        if handle.auth_requirement is not AuthRequirement.NONE:
            if authentication is None:
                return CredentialUseCode.AUTHENTICATION_REQUIRED
            if not self._valid_authentication(authentication, handle, request, now):
                return CredentialUseCode.AUTHENTICATION_INVALID
        return CredentialUseCode.ALLOWED

    @staticmethod
    def _valid_authentication(
        authentication: AuthenticationEvidenceRef,
        handle: CredentialHandleRef,
        request: CredentialRequest,
        now: int,
    ) -> bool:
        return bool(
            isinstance(authentication, AuthenticationEvidenceRef)
            and authentication.satisfied
            and authentication.requirement is handle.auth_requirement
            and authentication.request_id == request.request_id
            and authentication.task_id == request.task_id
            and authentication.execution_id == request.execution_id
            and authentication.observed_at_ms <= now <= authentication.expires_at_ms
        )

    def _has_state(self, handle: CredentialHandleRef, kind: str) -> bool:
        return any(
            descriptor.artifact_kind == kind and descriptor.opaque_locator == handle.handle_id
            for descriptor in self.store.list_artifacts(handle.task_id, session_id=handle.session_id)
        )

    def _has_use_request(self, handle: CredentialHandleRef, request_id: str) -> bool:
        return any(
            descriptor.artifact_kind == "credential.use-record"
            and dict(descriptor.metadata).get("request_id") == request_id
            for descriptor in self.store.list_artifacts(handle.task_id, session_id=handle.session_id)
        )

    def _has_any_use(self, handle: CredentialHandleRef) -> bool:
        return self._has_state(handle, "credential.use-record")

    def _state_descriptor(self, handle: CredentialHandleRef, kind: str, created_at_ms: int) -> ArtifactDescriptor:
        return ArtifactDescriptor(
            ref=ArtifactRef(_stable_id(kind, handle.handle_id), handle.task_id, handle.session_id),
            artifact_kind=kind,
            producer="credential.broker",
            created_at_ms=created_at_ms,
            sensitivity=SensitivityClass.NEVER_MODEL_VISIBLE,
            lifetime=ArtifactLifetime.DURABLE,
            opaque_locator=handle.handle_id,
            metadata=(("handle_id", handle.handle_id), ("policy_class", "NON_AUTHORITATIVE")),
        )

    def _use_descriptor(
        self,
        handle: CredentialHandleRef,
        request: CredentialRequest,
        created_at_ms: int,
    ) -> ArtifactDescriptor:
        return ArtifactDescriptor(
            ref=ArtifactRef(_stable_id("credential-use", request.request_id), handle.task_id, handle.session_id),
            artifact_kind="credential.use-record",
            producer="credential.broker",
            created_at_ms=created_at_ms,
            sensitivity=SensitivityClass.NEVER_MODEL_VISIBLE,
            lifetime=ArtifactLifetime.DURABLE,
            opaque_locator=handle.handle_id,
            metadata=(
                ("handle_id", handle.handle_id),
                ("request_id", request.request_id),
                ("provider_id", request.provider_id),
                ("purpose", request.purpose),
                ("execution_id", request.execution_id),
                ("policy_class", "NON_AUTHORITATIVE"),
            ),
        )

    def _record_denial(
        self,
        handle: CredentialHandleRef,
        request: CredentialRequest,
        trace_id: str,
        assessment: CredentialUseAssessment,
    ) -> None:
        descriptor = ArtifactDescriptor(
            ref=ArtifactRef(
                self._id_factory("credential-denial"),
                handle.task_id,
                handle.session_id,
            ),
            artifact_kind="credential.use-denial",
            producer="credential.broker",
            created_at_ms=assessment.assessed_at_ms,
            sensitivity=SensitivityClass.NEVER_MODEL_VISIBLE,
            lifetime=ArtifactLifetime.DURABLE,
            opaque_locator=handle.handle_id,
            metadata=(
                ("request_id", request.request_id),
                ("code", assessment.code.value),
                ("policy_class", "NON_AUTHORITATIVE"),
            ),
        )
        self._persist(descriptor, trace_id, "credential_use_denied")

    def _persist(self, descriptor: ArtifactDescriptor, trace_id: str, event_name: str) -> None:
        event = TraceEvent(
            event_id=f"trace-event.{descriptor.ref.artifact_id}",
            task_id=descriptor.ref.task_id,
            trace_id=trace_id,
            event_name=event_name,
            observed_timestamp_ms=descriptor.created_at_ms,
            artifact_refs=(descriptor.ref,),
            attributes=(("policy_class", "NON_AUTHORITATIVE"), ("value_visibility", "OPAQUE_ONLY")),
        )
        self.store.record_artifact_and_trace(descriptor, event)


@dataclass(frozen=True)
class SecureUIAssessment:
    assessment_id: str
    kind: SecureUIKind
    auth_requirement: AuthRequirement
    observed_at_ms: int
    schema_version: str = SECURE_UI_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SECURE_UI_SCHEMA_VERSION:
            raise InterventionPolicyError("unsupported SecureUIAssessment schema version")
        object.__setattr__(self, "assessment_id", _identifier(self.assessment_id, "assessment_id"))
        object.__setattr__(self, "kind", SecureUIKind(self.kind))
        object.__setattr__(self, "auth_requirement", AuthRequirement(self.auth_requirement))
        _timestamp(self.observed_at_ms, "observed_at_ms")
        if self.kind is SecureUIKind.NONE and self.auth_requirement is not AuthRequirement.NONE:
            raise InterventionPolicyError("non-secure UI cannot require protected authentication")
        if self.kind is not SecureUIKind.NONE and self.auth_requirement is AuthRequirement.NONE:
            raise InterventionPolicyError("secure UI must require user-owned authentication")

    @property
    def secure_ui_detected(self) -> bool:
        return self.kind is not SecureUIKind.NONE

    def waiting_view(self) -> TaskExecutionView:
        if not self.secure_ui_detected:
            raise InterventionPolicyError("non-secure UI does not create a waiting state")
        return TaskExecutionView(
            TaskExecutionState.WAITING_FOR_USER,
            TaskExecutionReason.SECURE_UI_REQUIRES_USER,
            RecoveryDecision.WAIT_FOR_USER_THEN_REOBSERVE,
        )

    def audit(self) -> dict[str, Any]:
        return {
            "assessment_id": self.assessment_id,
            "kind": self.kind.value,
            "auth_requirement": self.auth_requirement.value,
            "secure_ui_detected": self.secure_ui_detected,
            "automation_stops": self.secure_ui_detected,
            "automated_secret_entry": False,
            "auth_bypass": False,
            "fresh_reconciliation_required": self.secure_ui_detected,
            "authorization": False,
        }
