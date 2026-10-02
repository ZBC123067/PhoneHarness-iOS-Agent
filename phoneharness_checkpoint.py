#!/usr/bin/env python3
"""Host-only safe checkpoint and resume foundation.

Checkpoint and resume records in this module are reference-oriented recovery
evidence. They cannot authorize, bind, dispatch, execute, retry, replay, or
mark semantic success.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import hashlib
import re
import threading
import time
from typing import Any, Callable
import uuid

from phoneharness_contracts import (
    ArtifactDescriptor,
    ArtifactLifetime,
    ArtifactRef,
    ObservationFreshness,
    ObservationRef,
    SensitivityClass,
)
from phoneharness_intervention import UserInterventionRequest
from phoneharness_retry import (
    ExecutionLoopState,
    LoopAssessment,
    RetryBudget,
)
from phoneharness_runtime import RuntimeInstanceRef
from phoneharness_store import (
    DispatchStatus,
    PhoneHarnessStore,
    ReceiptResultStatus,
    StoreConflictError,
    StoreSchemaError,
    TraceEvent,
    UnknownArtifactError,
    UnknownReceiptError,
    UnknownTraceEventError,
)
from phoneharness_uncertainty import (
    OutcomeReconciliationAssessment,
    ReconciliationDisposition,
    UncertainOutcomeRecord,
)


CHECKPOINT_REF_SCHEMA_VERSION = "phoneharness.checkpoint-ref.v1"
CHECKPOINT_RECORD_SCHEMA_VERSION = "phoneharness.checkpoint-record.v1"
CHECKPOINT_CONTRACT_VERSION = "phoneharness.checkpoint-contract.v1"
RESUME_REQUEST_SCHEMA_VERSION = "phoneharness.resume-request.v1"
RESUME_ASSESSMENT_SCHEMA_VERSION = "phoneharness.resume-assessment.v1"
RESUME_CLAIM_SCHEMA_VERSION = "phoneharness.resume-claim.v1"
MAX_CHECKPOINT_SEQUENCE = 1_000_000
MAX_CHECKPOINT_REVISION = 16

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")


class CheckpointError(RuntimeError):
    """Base class for deterministic checkpoint/resume failures."""


class CheckpointPolicyError(CheckpointError):
    """A checkpoint or resume contract is invalid."""


class CheckpointNotFound(CheckpointError):
    """The requested durable checkpoint does not exist."""


class CheckpointConflict(CheckpointError):
    """A checkpoint revision, sequence, or ownership claim conflicted."""


class CheckpointEvidenceError(CheckpointError):
    """Required durable checkpoint evidence is unresolved or contradictory."""


class ResumeRejected(CheckpointError):
    """A duplicate, stale, or incompatible resume request was rejected."""


class CheckpointBoundary(str, Enum):
    BEFORE_MUTATION = "BEFORE_MUTATION"
    AFTER_VERIFIED_EFFECT = "AFTER_VERIFIED_EFFECT"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    AFTER_READ_ONLY_STEP = "AFTER_READ_ONLY_STEP"
    AFTER_RECONCILIATION = "AFTER_RECONCILIATION"
    TERMINAL = "TERMINAL"


class CheckpointStatus(str, Enum):
    PREPARED = "PREPARED"
    COMMITTED = "COMMITTED"
    INVALIDATED = "INVALIDATED"
    SUPERSEDED = "SUPERSEDED"


class ResumeDisposition(str, Enum):
    CONTINUE_AFTER_CHECKPOINT = "CONTINUE_AFTER_CHECKPOINT"
    REQUIRE_FRESH_OBSERVATION = "REQUIRE_FRESH_OBSERVATION"
    RECONCILE_REQUIRED = "RECONCILE_REQUIRED"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    REPLAN_REQUIRED = "REPLAN_REQUIRED"
    TERMINAL_NO_ACTION = "TERMINAL_NO_ACTION"
    CHECKPOINT_INCOMPATIBLE = "CHECKPOINT_INCOMPATIBLE"
    FAIL_SAFE = "FAIL_SAFE"


class ResumeReason(str, Enum):
    SAFE_BOUNDARY_VALIDATED = "SAFE_BOUNDARY_VALIDATED"
    MISSING_CHECKPOINT = "MISSING_CHECKPOINT"
    CHECKPOINT_NOT_COMMITTED = "CHECKPOINT_NOT_COMMITTED"
    CHECKPOINT_INVALIDATED = "CHECKPOINT_INVALIDATED"
    CHECKPOINT_SUPERSEDED = "CHECKPOINT_SUPERSEDED"
    SCHEMA_OR_CONTRACT_INCOMPATIBLE = "SCHEMA_OR_CONTRACT_INCOMPATIBLE"
    SCOPE_MISMATCH = "SCOPE_MISMATCH"
    STALE_RUNTIME = "STALE_RUNTIME"
    REQUIRED_EVIDENCE_UNRESOLVED = "REQUIRED_EVIDENCE_UNRESOLVED"
    FRESH_OBSERVATION_REQUIRED = "FRESH_OBSERVATION_REQUIRED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    NEWER_AUTHORITATIVE_STATE = "NEWER_AUTHORITATIVE_STATE"
    WAITING_INTERVENTION_RESTORED = "WAITING_INTERVENTION_RESTORED"
    TERMINAL_CHECKPOINT = "TERMINAL_CHECKPOINT"
    RETRY_STATE_CHANGED = "RETRY_STATE_CHANGED"
    RETRY_EXHAUSTED = "RETRY_EXHAUSTED"
    LOOP_STOP_ACTIVE = "LOOP_STOP_ACTIVE"
    DUPLICATE_RESUME = "DUPLICATE_RESUME"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"


def _identifier(value: Any, field_name: str) -> str:
    normalized = str(value or "").strip()
    if _IDENTIFIER.fullmatch(normalized) is None:
        raise CheckpointPolicyError(f"{field_name} must be an opaque bounded identifier")
    return normalized


def _optional_identifier(value: Any, field_name: str) -> str | None:
    return None if value is None else _identifier(value, field_name)


def _timestamp(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CheckpointPolicyError(f"{field_name} must be a non-negative integer")
    return value


def _bounded_int(value: Any, field_name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise CheckpointPolicyError(f"{field_name} is outside its bounded range")
    return value


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _new_identifier(prefix: str) -> str:
    return f"{prefix}.{uuid.uuid4().hex}"


def _stable_identifier(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:40]
    return f"{prefix}.{digest}"


def _none(value: str | None) -> str:
    return "NONE" if value is None else value


def _from_none(value: str) -> str | None:
    return None if value == "NONE" else value


@dataclass(frozen=True)
class CheckpointRef:
    checkpoint_id: str
    task_id: str
    session_id: str
    sequence: int
    schema_version: str = CHECKPOINT_REF_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != CHECKPOINT_REF_SCHEMA_VERSION:
            raise CheckpointPolicyError("unsupported CheckpointRef schema version")
        for name in ("checkpoint_id", "task_id", "session_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        _bounded_int(self.sequence, "sequence", 1, MAX_CHECKPOINT_SEQUENCE)

    def audit(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "sequence": self.sequence,
            "authorization": False,
            "binding": False,
            "executor_authority": False,
            "semantic_success": False,
        }


@dataclass(frozen=True)
class CheckpointRecord:
    ref: CheckpointRef
    trace_id: str
    runtime_instance_id: str
    status: CheckpointStatus
    boundary: CheckpointBoundary
    revision: int
    canonical_state_revision: int
    created_at_ms: int
    updated_at_ms: int
    continuation_ref: str | None
    step_id: str | None = None
    execution_id: str | None = None
    capsule_ref: str | None = None
    observation_ref: ObservationRef | None = None
    receipt_ref: str | None = None
    verifier_evidence_ref: str | None = None
    ledger_evidence_ref: str | None = None
    uncertainty_ref: str | None = None
    retry_state_ref: str | None = None
    retry_revision: int | None = None
    loop_state_ref: str | None = None
    loop_stop_active: bool = False
    intervention_request_ref: str | None = None
    requires_fresh_observation: bool = True
    prior_checkpoint_ref: str | None = None
    invalidation_reason: str | None = None
    contract_version: str = CHECKPOINT_CONTRACT_VERSION
    schema_version: str = CHECKPOINT_RECORD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != CHECKPOINT_RECORD_SCHEMA_VERSION:
            raise CheckpointPolicyError("unsupported CheckpointRecord schema version")
        if self.contract_version != CHECKPOINT_CONTRACT_VERSION:
            raise CheckpointPolicyError("unsupported checkpoint contract version")
        if not isinstance(self.ref, CheckpointRef):
            raise CheckpointPolicyError("CheckpointRecord requires CheckpointRef")
        for name in ("trace_id", "runtime_instance_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        for name in (
            "continuation_ref",
            "step_id",
            "execution_id",
            "capsule_ref",
            "receipt_ref",
            "verifier_evidence_ref",
            "ledger_evidence_ref",
            "uncertainty_ref",
            "retry_state_ref",
            "loop_state_ref",
            "intervention_request_ref",
            "prior_checkpoint_ref",
            "invalidation_reason",
        ):
            object.__setattr__(self, name, _optional_identifier(getattr(self, name), name))
        object.__setattr__(self, "status", CheckpointStatus(self.status))
        object.__setattr__(self, "boundary", CheckpointBoundary(self.boundary))
        _bounded_int(self.revision, "revision", 1, MAX_CHECKPOINT_REVISION)
        _bounded_int(
            self.canonical_state_revision,
            "canonical_state_revision",
            1,
            MAX_CHECKPOINT_SEQUENCE,
        )
        _timestamp(self.created_at_ms, "created_at_ms")
        _timestamp(self.updated_at_ms, "updated_at_ms")
        if self.updated_at_ms < self.created_at_ms:
            raise CheckpointPolicyError("checkpoint update precedes creation")
        if not isinstance(self.requires_fresh_observation, bool):
            raise CheckpointPolicyError("fresh-observation policy must be boolean")
        if (self.retry_state_ref is None) is not (self.retry_revision is None):
            raise CheckpointPolicyError("retry reference and revision must be provided together")
        if self.retry_revision is not None:
            _bounded_int(self.retry_revision, "retry_revision", 1, MAX_CHECKPOINT_SEQUENCE)
        if not isinstance(self.loop_stop_active, bool):
            raise CheckpointPolicyError("loop-stop state must be boolean")
        if self.loop_stop_active and self.loop_state_ref is None:
            raise CheckpointPolicyError("loop stop requires durable loop-state reference")
        if self.observation_ref is not None:
            if not isinstance(self.observation_ref, ObservationRef):
                raise CheckpointPolicyError("checkpoint observation must use ObservationRef")
            if (
                self.observation_ref.task_id != self.ref.task_id
                or self.observation_ref.session_id not in (None, self.ref.session_id)
            ):
                raise CheckpointPolicyError("checkpoint observation scope does not match")
        if self.status in {CheckpointStatus.INVALIDATED, CheckpointStatus.SUPERSEDED}:
            if self.invalidation_reason is None:
                raise CheckpointPolicyError("inactive checkpoint requires a fixed reason")
        elif self.invalidation_reason is not None:
            raise CheckpointPolicyError("active checkpoint cannot carry invalidation reason")
        self._validate_boundary_shape()

    def _validate_boundary_shape(self) -> None:
        if self.boundary is CheckpointBoundary.TERMINAL:
            if self.continuation_ref is not None or self.requires_fresh_observation:
                raise CheckpointPolicyError("terminal checkpoint cannot carry continuation")
        elif self.continuation_ref is None:
            raise CheckpointPolicyError("non-terminal checkpoint requires logical continuation reference")
        if self.boundary is CheckpointBoundary.BEFORE_MUTATION and any(
            value is not None
            for value in (
                self.receipt_ref,
                self.verifier_evidence_ref,
                self.ledger_evidence_ref,
                self.uncertainty_ref,
            )
        ):
            raise CheckpointPolicyError("before-mutation checkpoint cannot claim effect evidence")
        if self.boundary is CheckpointBoundary.AFTER_VERIFIED_EFFECT and any(
            value is None
            for value in (
                self.observation_ref,
                self.receipt_ref,
                self.verifier_evidence_ref,
                self.ledger_evidence_ref,
            )
        ):
            raise CheckpointPolicyError("verified-effect checkpoint requires durable proof references")
        if self.boundary is CheckpointBoundary.AFTER_VERIFIED_EFFECT and self.uncertainty_ref is not None:
            raise CheckpointPolicyError("verified-effect checkpoint cannot carry unresolved outcome")
        if self.boundary is CheckpointBoundary.WAITING_FOR_USER and self.intervention_request_ref is None:
            raise CheckpointPolicyError("waiting checkpoint requires pending intervention reference")
        if self.boundary is CheckpointBoundary.AFTER_READ_ONLY_STEP and self.observation_ref is None:
            raise CheckpointPolicyError("read-only checkpoint requires observation reference")
        if self.boundary is CheckpointBoundary.AFTER_RECONCILIATION and (
            self.observation_ref is None or self.uncertainty_ref is None
        ):
            raise CheckpointPolicyError("reconciled checkpoint requires observation and outcome references")

    @property
    def committed(self) -> bool:
        return self.status is CheckpointStatus.COMMITTED

    def audit(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.ref.checkpoint_id,
            "sequence": self.ref.sequence,
            "revision": self.revision,
            "status": self.status.value,
            "boundary": self.boundary.value,
            "reference_oriented": True,
            "authorization": False,
            "binding": False,
            "executor_authority": False,
            "semantic_success": False,
            "replay": False,
        }

    def to_artifact_descriptor(self) -> ArtifactDescriptor:
        metadata = {
            "checkpoint_schema": self.schema_version,
            "contract_version": self.contract_version,
            "identity_refs": f"{self.trace_id}|{self.runtime_instance_id}",
            "state": "|".join(
                (
                    self.status.value,
                    self.boundary.value,
                    str(self.revision),
                    str(self.ref.sequence),
                    str(self.canonical_state_revision),
                )
            ),
            "time_refs": f"{self.created_at_ms}:{self.updated_at_ms}",
            "scope_refs": "|".join(
                (_none(self.step_id), _none(self.execution_id), _none(self.capsule_ref), _none(self.continuation_ref))
            ),
            "effect_refs": "|".join(
                (
                    _none(self.receipt_ref),
                    _none(self.verifier_evidence_ref),
                    _none(self.ledger_evidence_ref),
                    _none(self.uncertainty_ref),
                )
            ),
            "recovery_refs": "|".join(
                (
                    _none(self.retry_state_ref),
                    "NONE" if self.retry_revision is None else str(self.retry_revision),
                    _none(self.loop_state_ref),
                    "YES" if self.loop_stop_active else "NO",
                    _none(self.intervention_request_ref),
                )
            ),
            "policy_refs": "|".join(
                (
                    "YES" if self.requires_fresh_observation else "NO",
                    _none(self.prior_checkpoint_ref),
                    _none(self.invalidation_reason),
                )
            ),
        }
        return ArtifactDescriptor(
            ref=ArtifactRef(
                f"checkpoint-record.{self.ref.checkpoint_id}.r{self.revision:06d}",
                self.ref.task_id,
                self.ref.session_id,
            ),
            artifact_kind="checkpoint.record",
            producer="checkpoint.manager",
            created_at_ms=self.updated_at_ms,
            sensitivity=SensitivityClass.PRIVATE,
            lifetime=ArtifactLifetime.DURABLE,
            observation_ref=self.observation_ref,
            opaque_locator=self.ref.checkpoint_id,
            metadata=tuple(metadata.items()),
        )

    @classmethod
    def from_artifact_descriptor(cls, descriptor: ArtifactDescriptor) -> "CheckpointRecord":
        if descriptor.artifact_kind != "checkpoint.record" or descriptor.ref.session_id is None:
            raise CheckpointPolicyError("durable record is not CheckpointRecord")
        metadata = dict(descriptor.metadata)
        required = {
            "checkpoint_schema",
            "contract_version",
            "identity_refs",
            "state",
            "time_refs",
            "scope_refs",
            "effect_refs",
            "recovery_refs",
            "policy_refs",
        }
        if set(metadata) != required or descriptor.opaque_locator is None:
            raise CheckpointPolicyError("CheckpointRecord durable fields do not match schema")
        times = tuple(int(value) for value in metadata["time_refs"].split(":"))
        identity_refs = tuple(metadata["identity_refs"].split("|"))
        state = tuple(metadata["state"].split("|"))
        scope_refs = tuple(metadata["scope_refs"].split("|"))
        effect_refs = tuple(metadata["effect_refs"].split("|"))
        recovery_refs = tuple(metadata["recovery_refs"].split("|"))
        policy_refs = tuple(metadata["policy_refs"].split("|"))
        if (
            len(times) != 2
            or len(identity_refs) != 2
            or len(state) != 5
            or len(scope_refs) != 4
            or len(effect_refs) != 4
            or len(recovery_refs) != 5
            or len(policy_refs) != 3
        ):
            raise CheckpointPolicyError("CheckpointRecord durable composite fields are invalid")
        if policy_refs[0] not in {"YES", "NO"}:
            raise CheckpointPolicyError("CheckpointRecord freshness policy is invalid")
        if recovery_refs[3] not in {"YES", "NO"}:
            raise CheckpointPolicyError("CheckpointRecord loop-stop policy is invalid")
        retry_revision = recovery_refs[1]
        return cls(
            ref=CheckpointRef(
                descriptor.opaque_locator,
                descriptor.ref.task_id,
                descriptor.ref.session_id,
                int(state[3]),
            ),
            trace_id=identity_refs[0],
            runtime_instance_id=identity_refs[1],
            status=CheckpointStatus(state[0]),
            boundary=CheckpointBoundary(state[1]),
            revision=int(state[2]),
            canonical_state_revision=int(state[4]),
            created_at_ms=times[0],
            updated_at_ms=times[1],
            continuation_ref=_from_none(scope_refs[3]),
            step_id=_from_none(scope_refs[0]),
            execution_id=_from_none(scope_refs[1]),
            capsule_ref=_from_none(scope_refs[2]),
            observation_ref=descriptor.observation_ref,
            receipt_ref=_from_none(effect_refs[0]),
            verifier_evidence_ref=_from_none(effect_refs[1]),
            ledger_evidence_ref=_from_none(effect_refs[2]),
            uncertainty_ref=_from_none(effect_refs[3]),
            retry_state_ref=_from_none(recovery_refs[0]),
            retry_revision=None if retry_revision == "NONE" else int(retry_revision),
            loop_state_ref=_from_none(recovery_refs[2]),
            loop_stop_active=recovery_refs[3] == "YES",
            intervention_request_ref=_from_none(recovery_refs[4]),
            requires_fresh_observation=policy_refs[0] == "YES",
            prior_checkpoint_ref=_from_none(policy_refs[1]),
            invalidation_reason=_from_none(policy_refs[2]),
            contract_version=metadata["contract_version"],
            schema_version=metadata["checkpoint_schema"],
        )


@dataclass(frozen=True)
class ResumeRequest:
    request_id: str
    task_id: str
    session_id: str
    trace_id: str
    runtime_instance_id: str
    requested_at_ms: int
    current_state_revision: int
    checkpoint_ref: CheckpointRef | None = None
    fresh_observation_ref: ObservationRef | None = None
    reconciliation_assessment: OutcomeReconciliationAssessment | None = None
    retry_budget: RetryBudget | None = None
    loop_state_ref: str | None = None
    loop_assessment: LoopAssessment | None = None
    pending_intervention: UserInterventionRequest | None = None
    unknown_outcome_present: bool = False
    expected_contract_version: str = CHECKPOINT_CONTRACT_VERSION
    schema_version: str = RESUME_REQUEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RESUME_REQUEST_SCHEMA_VERSION:
            raise CheckpointPolicyError("unsupported ResumeRequest schema version")
        for name in ("request_id", "task_id", "session_id", "trace_id", "runtime_instance_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(self, "loop_state_ref", _optional_identifier(self.loop_state_ref, "loop_state_ref"))
        object.__setattr__(
            self,
            "expected_contract_version",
            _identifier(self.expected_contract_version, "expected_contract_version"),
        )
        _timestamp(self.requested_at_ms, "requested_at_ms")
        _bounded_int(
            self.current_state_revision,
            "current_state_revision",
            1,
            MAX_CHECKPOINT_SEQUENCE,
        )
        if self.checkpoint_ref is not None:
            if not isinstance(self.checkpoint_ref, CheckpointRef):
                raise CheckpointPolicyError("resume checkpoint must use CheckpointRef")
            if (
                self.checkpoint_ref.task_id != self.task_id
                or self.checkpoint_ref.session_id != self.session_id
            ):
                raise CheckpointPolicyError("resume checkpoint scope does not match request")
        if self.fresh_observation_ref is not None:
            if not isinstance(self.fresh_observation_ref, ObservationRef):
                raise CheckpointPolicyError("resume observation must use ObservationRef")
            if (
                self.fresh_observation_ref.task_id != self.task_id
                or self.fresh_observation_ref.session_id not in (None, self.session_id)
            ):
                raise CheckpointPolicyError("resume observation scope does not match request")
        if self.reconciliation_assessment is not None and not isinstance(
            self.reconciliation_assessment,
            OutcomeReconciliationAssessment,
        ):
            raise CheckpointPolicyError("resume reconciliation must use M4 assessment")
        if self.retry_budget is not None and not isinstance(self.retry_budget, RetryBudget):
            raise CheckpointPolicyError("resume retry state must use M5 RetryBudget")
        if self.loop_assessment is not None and not isinstance(self.loop_assessment, LoopAssessment):
            raise CheckpointPolicyError("resume loop state must use M5 LoopAssessment")
        if self.pending_intervention is not None and not isinstance(
            self.pending_intervention,
            UserInterventionRequest,
        ):
            raise CheckpointPolicyError("resume intervention must use M7 request")
        if not isinstance(self.unknown_outcome_present, bool):
            raise CheckpointPolicyError("unknown-outcome flag must be boolean")


@dataclass(frozen=True)
class ResumeAssessment:
    assessment_id: str
    request_id: str
    runtime_instance_id: str
    disposition: ResumeDisposition
    reason: ResumeReason
    assessed_at_ms: int
    checkpoint_ref: CheckpointRef | None = None
    continuation_ref: str | None = None
    preserved_retry_revision: int | None = None
    authority: bool = False
    dispatch: bool = False
    replay: bool = False
    schema_version: str = RESUME_ASSESSMENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RESUME_ASSESSMENT_SCHEMA_VERSION:
            raise CheckpointPolicyError("unsupported ResumeAssessment schema version")
        for name in ("assessment_id", "request_id", "runtime_instance_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(self, "continuation_ref", _optional_identifier(self.continuation_ref, "continuation_ref"))
        object.__setattr__(self, "disposition", ResumeDisposition(self.disposition))
        object.__setattr__(self, "reason", ResumeReason(self.reason))
        _timestamp(self.assessed_at_ms, "assessed_at_ms")
        if self.preserved_retry_revision is not None:
            _bounded_int(
                self.preserved_retry_revision,
                "preserved_retry_revision",
                1,
                MAX_CHECKPOINT_SEQUENCE,
            )
        if self.authority or self.dispatch or self.replay:
            raise CheckpointPolicyError("resume assessment cannot authorize, dispatch, or replay")
        if self.disposition is ResumeDisposition.CONTINUE_AFTER_CHECKPOINT and self.continuation_ref is None:
            raise CheckpointPolicyError("continuation assessment requires logical continuation reference")
        if self.disposition is not ResumeDisposition.CONTINUE_AFTER_CHECKPOINT and self.continuation_ref is not None:
            raise CheckpointPolicyError("non-continuation assessment cannot carry continuation position")

    def audit(self) -> dict[str, Any]:
        return {
            "assessment_id": self.assessment_id,
            "request_id": self.request_id,
            "disposition": self.disposition.value,
            "reason": self.reason.value,
            "authorization": False,
            "dispatch": False,
            "replay": False,
        }


class CheckpointManager:
    """Immutable S3-M1 checkpoint records with explicit commit transitions."""

    def __init__(
        self,
        store: PhoneHarnessStore,
        runtime_ref: RuntimeInstanceRef,
        *,
        ledger_state_resolver: Callable[[str], str | None] | None = None,
        now_ms: Callable[[], int] = _now_ms,
    ) -> None:
        if not isinstance(store, PhoneHarnessStore) or not isinstance(runtime_ref, RuntimeInstanceRef):
            raise CheckpointPolicyError("CheckpointManager requires typed Store and Runtime identity")
        self.store = store
        self.runtime_ref = runtime_ref
        self._ledger_state_resolver = ledger_state_resolver
        self._now_ms = now_ms
        self._mutex = threading.RLock()

    def prepare(
        self,
        *,
        task_id: str,
        session_id: str,
        trace_id: str,
        boundary: CheckpointBoundary,
        canonical_state_revision: int,
        continuation_ref: str | None,
        step_id: str | None = None,
        execution_id: str | None = None,
        capsule_ref: str | None = None,
        observation_ref: ObservationRef | None = None,
        receipt_ref: str | None = None,
        verifier_evidence_ref: str | None = None,
        ledger_evidence_ref: str | None = None,
        uncertainty_ref: str | None = None,
        retry_state_ref: str | None = None,
        retry_revision: int | None = None,
        loop_state_ref: str | None = None,
        loop_stop_active: bool = False,
        intervention_request_ref: str | None = None,
        requires_fresh_observation: bool = True,
    ) -> CheckpointRecord:
        task = _identifier(task_id, "task_id")
        session = _identifier(session_id, "session_id")
        trace = _identifier(trace_id, "trace_id")
        with self._mutex:
            latest = self.latest(task, session, required=False)
            if latest is not None and latest.status is CheckpointStatus.PREPARED:
                raise CheckpointConflict("latest checkpoint is still uncommitted")
            sequence = 1 if latest is None else latest.ref.sequence + 1
            checkpoint_id = _stable_identifier("checkpoint", f"{task}|{session}|{sequence}")
            now = self._now_ms()
            record = CheckpointRecord(
                ref=CheckpointRef(checkpoint_id, task, session, sequence),
                trace_id=trace,
                runtime_instance_id=self.runtime_ref.runtime_instance_id,
                status=CheckpointStatus.PREPARED,
                boundary=boundary,
                revision=1,
                canonical_state_revision=canonical_state_revision,
                created_at_ms=now,
                updated_at_ms=now,
                continuation_ref=continuation_ref,
                step_id=step_id,
                execution_id=execution_id,
                capsule_ref=capsule_ref,
                observation_ref=observation_ref,
                receipt_ref=receipt_ref,
                verifier_evidence_ref=verifier_evidence_ref,
                ledger_evidence_ref=ledger_evidence_ref,
                uncertainty_ref=uncertainty_ref,
                retry_state_ref=retry_state_ref,
                retry_revision=retry_revision,
                loop_state_ref=loop_state_ref,
                loop_stop_active=loop_stop_active,
                intervention_request_ref=intervention_request_ref,
                requires_fresh_observation=requires_fresh_observation,
                prior_checkpoint_ref=None if latest is None else latest.ref.checkpoint_id,
            )
            self._persist(record, "checkpoint_created")
            return record

    def commit(self, record: CheckpointRecord) -> CheckpointRecord:
        with self._mutex:
            current = self._require_current(record)
            if current.status is not CheckpointStatus.PREPARED:
                raise CheckpointConflict("only a prepared checkpoint can commit")
            latest = self.latest(record.ref.task_id, record.ref.session_id)
            if latest.ref != record.ref:
                raise CheckpointConflict("newer checkpoint state already exists")
            self.validate_evidence(current)
            committed = replace(
                current,
                status=CheckpointStatus.COMMITTED,
                revision=current.revision + 1,
                updated_at_ms=max(self._now_ms(), current.updated_at_ms + 1),
            )
            self._persist(committed, "checkpoint_committed")
            return committed

    def invalidate(self, record: CheckpointRecord, *, reason: str) -> CheckpointRecord:
        return self._deactivate(record, CheckpointStatus.INVALIDATED, reason, "checkpoint_invalidated")

    def supersede(self, record: CheckpointRecord, *, reason: str) -> CheckpointRecord:
        return self._deactivate(record, CheckpointStatus.SUPERSEDED, reason, "checkpoint_superseded")

    def _deactivate(
        self,
        record: CheckpointRecord,
        status: CheckpointStatus,
        reason: str,
        event_name: str,
    ) -> CheckpointRecord:
        with self._mutex:
            current = self._require_current(record)
            if current.status in {CheckpointStatus.INVALIDATED, CheckpointStatus.SUPERSEDED}:
                raise CheckpointConflict("checkpoint is already inactive")
            updated = replace(
                current,
                status=status,
                invalidation_reason=_identifier(reason, "reason"),
                revision=current.revision + 1,
                updated_at_ms=max(self._now_ms(), current.updated_at_ms + 1),
            )
            self._persist(updated, event_name)
            return updated

    def load(self, ref: CheckpointRef) -> CheckpointRecord:
        if not isinstance(ref, CheckpointRef):
            raise CheckpointPolicyError("checkpoint lookup requires CheckpointRef")
        records = [
            record
            for record in self._records(ref.task_id, ref.session_id)
            if record.ref.checkpoint_id == ref.checkpoint_id and record.ref.sequence == ref.sequence
        ]
        if not records:
            raise CheckpointNotFound("checkpoint reference is unknown")
        return max(records, key=lambda value: value.revision)

    def latest(self, task_id: str, session_id: str, *, required: bool = True) -> CheckpointRecord | None:
        records = self._records(task_id, session_id)
        if not records:
            if required:
                raise CheckpointNotFound("task/session has no durable checkpoint")
            return None
        current_by_id: dict[str, CheckpointRecord] = {}
        for record in records:
            prior = current_by_id.get(record.ref.checkpoint_id)
            if prior is None or record.revision > prior.revision:
                current_by_id[record.ref.checkpoint_id] = record
        highest = max(record.ref.sequence for record in current_by_id.values())
        candidates = [record for record in current_by_id.values() if record.ref.sequence == highest]
        if len(candidates) != 1:
            raise CheckpointConflict("checkpoint sequence has conflicting identities")
        return candidates[0]

    def validate_evidence(self, record: CheckpointRecord) -> None:
        if record.observation_ref is not None and record.observation_ref.freshness is not ObservationFreshness.FRESH:
            raise CheckpointEvidenceError("checkpoint observation is not fresh")
        receipt = None
        if record.receipt_ref is not None:
            try:
                receipt = self.store.get_receipt(record.receipt_ref)
            except (UnknownReceiptError, StoreSchemaError) as exc:
                raise CheckpointEvidenceError("checkpoint receipt is unresolved") from exc
            if (
                receipt.task_id != record.ref.task_id
                or (record.step_id is not None and receipt.step_id != record.step_id)
                or (record.execution_id is not None and receipt.execution_id != record.execution_id)
            ):
                raise CheckpointEvidenceError("checkpoint receipt scope does not match")
        verifier = None
        if record.verifier_evidence_ref is not None:
            try:
                verifier = self.store.get_trace_event(record.verifier_evidence_ref)
            except (UnknownTraceEventError, StoreSchemaError) as exc:
                raise CheckpointEvidenceError("checkpoint verifier evidence is unresolved") from exc
            if verifier.task_id != record.ref.task_id or verifier.verifier_result != "PASSED":
                raise CheckpointEvidenceError("checkpoint verifier evidence is not a pass")
            if record.receipt_ref is not None and record.receipt_ref not in verifier.receipt_refs:
                raise CheckpointEvidenceError("checkpoint verifier is not correlated to receipt")
        if record.boundary is CheckpointBoundary.AFTER_VERIFIED_EFFECT:
            if (
                receipt is None
                or receipt.result_status is not ReceiptResultStatus.VERIFIED
                or receipt.dispatch_status is not DispatchStatus.DISPATCHED
                or receipt.verification_ref != record.verifier_evidence_ref
            ):
                raise CheckpointEvidenceError("post-effect checkpoint lacks verified dispatch evidence")
            if self._ledger_state_resolver is None or record.ledger_evidence_ref is None:
                raise CheckpointEvidenceError("post-effect checkpoint lacks Ledger resolver")
            if self._ledger_state_resolver(record.ledger_evidence_ref) != "VERIFIED":
                raise CheckpointEvidenceError("post-effect checkpoint Ledger state is not VERIFIED")
        if record.retry_state_ref is not None:
            budgets = self._retry_budgets(record)
            if not any(item.revision == record.retry_revision for item in budgets):
                raise CheckpointEvidenceError("checkpoint retry state is unresolved or stale")
        if record.loop_state_ref is not None:
            loops = [
                ExecutionLoopState.from_artifact_descriptor(item)
                for item in self.store.list_artifacts(record.ref.task_id, session_id=record.ref.session_id)
                if item.artifact_kind == "execution.loop-state" and item.opaque_locator == record.loop_state_ref
            ]
            if not loops:
                raise CheckpointEvidenceError("checkpoint loop state is unresolved")
        if record.intervention_request_ref is not None:
            try:
                descriptor = self.store.get_artifact(
                    ArtifactRef(
                        record.intervention_request_ref,
                        record.ref.task_id,
                        record.ref.session_id,
                    )
                )
            except (UnknownArtifactError, StoreSchemaError) as exc:
                raise CheckpointEvidenceError("checkpoint intervention request is unresolved") from exc
            if descriptor.artifact_kind != "user.intervention-request":
                raise CheckpointEvidenceError("checkpoint intervention reference has wrong type")
        if record.uncertainty_ref is not None:
            cases = [
                UncertainOutcomeRecord.from_artifact_descriptor(item)
                for item in self.store.list_artifacts(record.ref.task_id, session_id=record.ref.session_id)
                if item.artifact_kind == "outcome.uncertain-case" and item.opaque_locator == record.uncertainty_ref
            ]
            if not cases:
                raise CheckpointEvidenceError("checkpoint uncertainty state is unresolved")

    def latest_retry_budget(self, record: CheckpointRecord) -> RetryBudget:
        budgets = self._retry_budgets(record)
        if not budgets:
            raise CheckpointEvidenceError("checkpoint retry state is unresolved")
        return max(budgets, key=lambda item: item.revision)

    def _retry_budgets(self, record: CheckpointRecord) -> tuple[RetryBudget, ...]:
        return tuple(
            RetryBudget.from_artifact_descriptor(item)
            for item in self.store.list_artifacts(record.ref.task_id, session_id=record.ref.session_id)
            if item.artifact_kind == "retry.budget" and item.opaque_locator == record.retry_state_ref
        )

    def _require_current(self, record: CheckpointRecord) -> CheckpointRecord:
        if not isinstance(record, CheckpointRecord):
            raise CheckpointPolicyError("checkpoint transition requires CheckpointRecord")
        current = self.load(record.ref)
        if current.revision != record.revision or current != record:
            raise CheckpointConflict("checkpoint revision is no longer current")
        return current

    def _records(self, task_id: str, session_id: str) -> tuple[CheckpointRecord, ...]:
        task = _identifier(task_id, "task_id")
        session = _identifier(session_id, "session_id")
        return tuple(
            CheckpointRecord.from_artifact_descriptor(item)
            for item in self.store.list_artifacts(task, session_id=session)
            if item.artifact_kind == "checkpoint.record"
        )

    def _persist(self, record: CheckpointRecord, event_name: str) -> None:
        descriptor = record.to_artifact_descriptor()
        event = TraceEvent(
            event_id=f"trace-event.{descriptor.ref.artifact_id}",
            task_id=record.ref.task_id,
            trace_id=record.trace_id,
            event_name=event_name,
            observed_timestamp_ms=record.updated_at_ms,
            step_id=record.step_id,
            execution_id=record.execution_id,
            artifact_refs=(descriptor.ref,),
            observation_refs=(() if record.observation_ref is None else (record.observation_ref,)),
            attributes=(("policy_class", "NON_AUTHORITATIVE"), ("replay_effect", "NONE")),
        )
        try:
            artifact_created, _ = self.store.record_artifact_and_trace(descriptor, event)
        except StoreConflictError as exc:
            raise CheckpointConflict("checkpoint durable write conflicted") from exc
        if not artifact_created:
            raise CheckpointConflict("checkpoint revision already exists")


class ResumeCoordinator:
    """Validates logical continuation and never dispatches or replays work."""

    def __init__(
        self,
        manager: CheckpointManager,
        runtime_ref: RuntimeInstanceRef,
        *,
        now_ms: Callable[[], int] = _now_ms,
        id_factory: Callable[[str], str] = _new_identifier,
    ) -> None:
        if not isinstance(manager, CheckpointManager) or not isinstance(runtime_ref, RuntimeInstanceRef):
            raise CheckpointPolicyError("ResumeCoordinator requires typed checkpoint manager and Runtime")
        self.manager = manager
        self.store = manager.store
        self.runtime_ref = runtime_ref
        self._now_ms = now_ms
        self._id_factory = id_factory
        self._mutex = threading.RLock()

    def assess(self, request: ResumeRequest) -> ResumeAssessment:
        if not isinstance(request, ResumeRequest):
            raise CheckpointPolicyError("resume assessment requires ResumeRequest")
        with self._mutex:
            self._record_request(request)
            assessment = self._assess(request)
            if assessment.disposition in {
                ResumeDisposition.CONTINUE_AFTER_CHECKPOINT,
                ResumeDisposition.WAITING_FOR_USER,
                ResumeDisposition.TERMINAL_NO_ACTION,
            }:
                try:
                    self._claim(request, assessment)
                except ResumeRejected:
                    assessment = self._result(
                        request,
                        ResumeDisposition.FAIL_SAFE,
                        ResumeReason.DUPLICATE_RESUME,
                    )
            self._record_assessment(request, assessment)
            return assessment

    def _assess(self, request: ResumeRequest) -> ResumeAssessment:
        if request.runtime_instance_id != self.runtime_ref.runtime_instance_id:
            return self._result(request, ResumeDisposition.FAIL_SAFE, ResumeReason.STALE_RUNTIME)
        if request.expected_contract_version != CHECKPOINT_CONTRACT_VERSION:
            return self._result(
                request,
                ResumeDisposition.CHECKPOINT_INCOMPATIBLE,
                ResumeReason.SCHEMA_OR_CONTRACT_INCOMPATIBLE,
            )
        if request.checkpoint_ref is None:
            disposition = (
                ResumeDisposition.RECONCILE_REQUIRED
                if request.unknown_outcome_present
                else ResumeDisposition.FAIL_SAFE
            )
            reason = ResumeReason.UNKNOWN_OUTCOME if request.unknown_outcome_present else ResumeReason.MISSING_CHECKPOINT
            return self._result(request, disposition, reason)
        try:
            record = self.manager.load(request.checkpoint_ref)
            latest = self.manager.latest(request.task_id, request.session_id)
        except (CheckpointError, StoreSchemaError, ValueError):
            return self._result(
                request,
                ResumeDisposition.CHECKPOINT_INCOMPATIBLE,
                ResumeReason.REQUIRED_EVIDENCE_UNRESOLVED,
            )
        if latest.ref != record.ref:
            return self._result(request, ResumeDisposition.REPLAN_REQUIRED, ResumeReason.CHECKPOINT_SUPERSEDED)
        if record.status is CheckpointStatus.PREPARED:
            return self._result(request, ResumeDisposition.FAIL_SAFE, ResumeReason.CHECKPOINT_NOT_COMMITTED)
        if record.status is CheckpointStatus.INVALIDATED:
            return self._result(request, ResumeDisposition.FAIL_SAFE, ResumeReason.CHECKPOINT_INVALIDATED)
        if record.status is CheckpointStatus.SUPERSEDED:
            return self._result(request, ResumeDisposition.REPLAN_REQUIRED, ResumeReason.CHECKPOINT_SUPERSEDED)
        if record.contract_version != request.expected_contract_version:
            return self._result(
                request,
                ResumeDisposition.CHECKPOINT_INCOMPATIBLE,
                ResumeReason.SCHEMA_OR_CONTRACT_INCOMPATIBLE,
            )
        try:
            self.manager.validate_evidence(record)
        except CheckpointError:
            return self._result(
                request,
                ResumeDisposition.FAIL_SAFE,
                ResumeReason.REQUIRED_EVIDENCE_UNRESOLVED,
            )
        if request.current_state_revision < record.canonical_state_revision:
            return self._result(request, ResumeDisposition.FAIL_SAFE, ResumeReason.NEWER_AUTHORITATIVE_STATE)
        if request.current_state_revision > record.canonical_state_revision:
            return self._result(
                request,
                ResumeDisposition.REQUIRE_FRESH_OBSERVATION,
                ResumeReason.NEWER_AUTHORITATIVE_STATE,
            )
        if request.unknown_outcome_present:
            return self._result(request, ResumeDisposition.RECONCILE_REQUIRED, ResumeReason.UNKNOWN_OUTCOME)
        retry_revision = self._retry_disposition(request, record)
        if isinstance(retry_revision, ResumeAssessment):
            return retry_revision
        loop_result = self._loop_disposition(request, record)
        if loop_result is not None:
            return loop_result
        if record.boundary is CheckpointBoundary.WAITING_FOR_USER:
            pending = request.pending_intervention
            if self._intervention_consumed(record):
                return self._result(
                    request,
                    ResumeDisposition.REQUIRE_FRESH_OBSERVATION,
                    ResumeReason.NEWER_AUTHORITATIVE_STATE,
                    retry_revision=retry_revision,
                )
            if (
                pending is None
                or pending.request_id != record.intervention_request_ref
                or pending.task_id != record.ref.task_id
                or pending.session_id != record.ref.session_id
                or request.requested_at_ms > pending.expires_at_ms
            ):
                return self._result(
                    request,
                    ResumeDisposition.FAIL_SAFE,
                    ResumeReason.REQUIRED_EVIDENCE_UNRESOLVED,
                    retry_revision=retry_revision,
                )
            return self._result(
                request,
                ResumeDisposition.WAITING_FOR_USER,
                ResumeReason.WAITING_INTERVENTION_RESTORED,
                retry_revision=retry_revision,
            )
        if record.boundary is CheckpointBoundary.TERMINAL:
            return self._result(
                request,
                ResumeDisposition.TERMINAL_NO_ACTION,
                ResumeReason.TERMINAL_CHECKPOINT,
                retry_revision=retry_revision,
            )
        if record.uncertainty_ref is not None:
            reconciliation = request.reconciliation_assessment
            if (
                reconciliation is None
                or reconciliation.uncertain_outcome_id != record.uncertainty_ref
                or reconciliation.task_id != record.ref.task_id
            ):
                return self._result(
                    request,
                    ResumeDisposition.RECONCILE_REQUIRED,
                    ResumeReason.RECONCILIATION_REQUIRED,
                    retry_revision=retry_revision,
                )
            if reconciliation.disposition not in {
                ReconciliationDisposition.SEMANTIC_SUCCESS_CONFIRMED,
                ReconciliationDisposition.NO_EFFECT_CONFIRMED,
                ReconciliationDisposition.SEMANTIC_FAILURE_CONFIRMED,
            }:
                return self._result(
                    request,
                    ResumeDisposition.RECONCILE_REQUIRED,
                    ResumeReason.RECONCILIATION_REQUIRED,
                    retry_revision=retry_revision,
                )
            if reconciliation.disposition is ReconciliationDisposition.SEMANTIC_FAILURE_CONFIRMED:
                return self._result(
                    request,
                    ResumeDisposition.TERMINAL_NO_ACTION,
                    ResumeReason.TERMINAL_CHECKPOINT,
                    retry_revision=retry_revision,
                )
        if record.requires_fresh_observation and not self._fresh_observation(request, record):
            return self._result(
                request,
                ResumeDisposition.REQUIRE_FRESH_OBSERVATION,
                ResumeReason.FRESH_OBSERVATION_REQUIRED,
                retry_revision=retry_revision,
            )
        return self._result(
            request,
            ResumeDisposition.CONTINUE_AFTER_CHECKPOINT,
            ResumeReason.SAFE_BOUNDARY_VALIDATED,
            continuation_ref=record.continuation_ref,
            retry_revision=retry_revision,
        )

    def _retry_disposition(
        self,
        request: ResumeRequest,
        record: CheckpointRecord,
    ) -> int | ResumeAssessment | None:
        if record.retry_state_ref is None:
            return None
        budget = request.retry_budget
        try:
            canonical = self.manager.latest_retry_budget(record)
        except (CheckpointError, StoreSchemaError, ValueError):
            return self._result(request, ResumeDisposition.FAIL_SAFE, ResumeReason.REQUIRED_EVIDENCE_UNRESOLVED)
        if (
            budget is None
            or budget.logical_operation_id != record.retry_state_ref
            or budget.task_id != record.ref.task_id
            or budget.session_id != record.ref.session_id
            or budget != canonical
        ):
            return self._result(request, ResumeDisposition.FAIL_SAFE, ResumeReason.REQUIRED_EVIDENCE_UNRESOLVED)
        if canonical.revision > (record.retry_revision or 1):
            return self._result(
                request,
                ResumeDisposition.REPLAN_REQUIRED,
                ResumeReason.RETRY_STATE_CHANGED,
                retry_revision=canonical.revision,
            )
        if budget.attempts_remaining == 0:
            return self._result(
                request,
                ResumeDisposition.REPLAN_REQUIRED,
                ResumeReason.RETRY_EXHAUSTED,
                retry_revision=budget.revision,
            )
        return budget.revision

    def _loop_disposition(
        self,
        request: ResumeRequest,
        record: CheckpointRecord,
    ) -> ResumeAssessment | None:
        if record.loop_state_ref is None:
            return None
        if record.loop_stop_active:
            return self._result(request, ResumeDisposition.REPLAN_REQUIRED, ResumeReason.LOOP_STOP_ACTIVE)
        if request.loop_state_ref != record.loop_state_ref or request.loop_assessment is None:
            return self._result(request, ResumeDisposition.FAIL_SAFE, ResumeReason.REQUIRED_EVIDENCE_UNRESOLVED)
        if request.loop_assessment.hard_stop:
            return self._result(request, ResumeDisposition.REPLAN_REQUIRED, ResumeReason.LOOP_STOP_ACTIVE)
        return None

    def _intervention_consumed(self, record: CheckpointRecord) -> bool:
        return any(
            item.artifact_kind == "user.intervention-decision"
            and item.opaque_locator == record.intervention_request_ref
            for item in self.store.list_artifacts(record.ref.task_id, session_id=record.ref.session_id)
        )

    @staticmethod
    def _fresh_observation(request: ResumeRequest, record: CheckpointRecord) -> bool:
        observation = request.fresh_observation_ref
        return bool(
            observation is not None
            and observation.freshness is ObservationFreshness.FRESH
            and observation.task_id == record.ref.task_id
            and observation.session_id in (None, record.ref.session_id)
            and observation.observed_at_ms is not None
            and observation.observed_at_ms > record.updated_at_ms
        )

    def _record_request(self, request: ResumeRequest) -> None:
        descriptor = ArtifactDescriptor(
            ref=ArtifactRef(
                f"resume-request.{request.request_id}",
                request.task_id,
                request.session_id,
            ),
            artifact_kind="checkpoint.resume-request",
            producer="resume.coordinator",
            created_at_ms=request.requested_at_ms,
            sensitivity=SensitivityClass.PRIVATE,
            lifetime=ArtifactLifetime.DURABLE,
            observation_ref=request.fresh_observation_ref,
            opaque_locator=request.request_id,
            metadata=(
                ("request_schema", request.schema_version),
                ("contract_version", request.expected_contract_version),
                ("checkpoint_ref", "NONE" if request.checkpoint_ref is None else request.checkpoint_ref.checkpoint_id),
                ("runtime_instance_id", request.runtime_instance_id),
                ("current_state_revision", str(request.current_state_revision)),
                ("unknown_outcome_present", "YES" if request.unknown_outcome_present else "NO"),
            ),
        )
        event = TraceEvent(
            event_id=f"trace-event.{descriptor.ref.artifact_id}",
            task_id=request.task_id,
            trace_id=request.trace_id,
            event_name="resume_requested",
            observed_timestamp_ms=request.requested_at_ms,
            artifact_refs=(descriptor.ref,),
            observation_refs=(() if request.fresh_observation_ref is None else (request.fresh_observation_ref,)),
            attributes=(("policy_class", "NON_AUTHORITATIVE"), ("dispatch_effect", "NONE")),
        )
        try:
            created, _ = self.store.record_artifact_and_trace(descriptor, event)
        except StoreConflictError as exc:
            raise ResumeRejected("resume request identity conflicted") from exc
        if not created:
            raise ResumeRejected("resume request was already consumed")

    def _claim(self, request: ResumeRequest, assessment: ResumeAssessment) -> None:
        if request.checkpoint_ref is None:
            raise ResumeRejected("missing checkpoint cannot be claimed")
        claim_id = _stable_identifier("resume-claim", request.checkpoint_ref.checkpoint_id)
        descriptor = ArtifactDescriptor(
            ref=ArtifactRef(claim_id, request.task_id, request.session_id),
            artifact_kind="checkpoint.resume-claim",
            producer="resume.coordinator",
            created_at_ms=assessment.assessed_at_ms,
            sensitivity=SensitivityClass.PRIVATE,
            lifetime=ArtifactLifetime.DURABLE,
            opaque_locator=request.checkpoint_ref.checkpoint_id,
            metadata=(
                ("claim_schema", RESUME_CLAIM_SCHEMA_VERSION),
                ("checkpoint_ref", request.checkpoint_ref.checkpoint_id),
                ("resume_request_ref", request.request_id),
                ("runtime_instance_id", request.runtime_instance_id),
                ("disposition", assessment.disposition.value),
            ),
        )
        event = TraceEvent(
            event_id=f"trace-event.{descriptor.ref.artifact_id}",
            task_id=request.task_id,
            trace_id=request.trace_id,
            event_name="resume_validated",
            observed_timestamp_ms=assessment.assessed_at_ms,
            artifact_refs=(descriptor.ref,),
            attributes=(("policy_class", "NON_AUTHORITATIVE"), ("replay_effect", "NONE")),
        )
        try:
            created, _ = self.store.record_artifact_and_trace(descriptor, event)
        except StoreConflictError as exc:
            raise ResumeRejected("checkpoint already has a conflicting resume claim") from exc
        if not created:
            raise ResumeRejected("checkpoint was already resumed")

    def _record_assessment(self, request: ResumeRequest, assessment: ResumeAssessment) -> None:
        event = TraceEvent(
            event_id=f"trace-event.resume-assessment.{assessment.assessment_id}",
            task_id=request.task_id,
            trace_id=request.trace_id,
            event_name=(
                "resume_validated"
                if assessment.disposition in {
                    ResumeDisposition.CONTINUE_AFTER_CHECKPOINT,
                    ResumeDisposition.WAITING_FOR_USER,
                    ResumeDisposition.TERMINAL_NO_ACTION,
                }
                else "resume_denied"
            ),
            observed_timestamp_ms=assessment.assessed_at_ms,
            observation_refs=(() if request.fresh_observation_ref is None else (request.fresh_observation_ref,)),
            attributes=(
                ("disposition", assessment.disposition.value),
                ("reason", assessment.reason.value),
                ("dispatch_effect", "NONE"),
            ),
        )
        self.store.append_trace_event(event)

    def _result(
        self,
        request: ResumeRequest,
        disposition: ResumeDisposition,
        reason: ResumeReason,
        *,
        continuation_ref: str | None = None,
        retry_revision: int | None = None,
    ) -> ResumeAssessment:
        return ResumeAssessment(
            assessment_id=self._id_factory("resume-assessment"),
            request_id=request.request_id,
            runtime_instance_id=self.runtime_ref.runtime_instance_id,
            disposition=disposition,
            reason=reason,
            assessed_at_ms=self._now_ms(),
            checkpoint_ref=request.checkpoint_ref,
            continuation_ref=continuation_ref,
            preserved_retry_revision=retry_revision,
        )
