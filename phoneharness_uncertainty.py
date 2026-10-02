#!/usr/bin/env python3
"""Host-only evidence reconciliation for uncertain external outcomes.

This module records and reconciles evidence. It never authorizes, retries,
replays, redispatches, or performs a mutating probe.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import hashlib
import json
import re
import time
from typing import Any, Callable, Iterable, Mapping
import uuid

from phoneharness_agent import TaskExecutionState
from phoneharness_contracts import (
    ArtifactDescriptor,
    ArtifactLifetime,
    ArtifactRef,
    ContractValidationError,
    ObservationFreshness,
    ObservationRef,
    SensitivityClass,
)
from phoneharness_runtime import (
    RuntimeInstanceRef,
    RuntimeRecoveryAssessment,
    SupervisorRecoveryDisposition,
    TaskCapsule,
)
from phoneharness_store import (
    DispatchStatus,
    ExecutionReceipt,
    PhoneHarnessStore,
    ReceiptResultStatus,
    SideEffectClass,
    StoreConflictError,
    TraceEvent,
)


UNCERTAIN_OUTCOME_SCHEMA_VERSION = "phoneharness.uncertain-outcome.v1"
OUTCOME_EVIDENCE_SCHEMA_VERSION = "phoneharness.outcome-evidence.v1"
RECONCILIATION_ASSESSMENT_SCHEMA_VERSION = "phoneharness.outcome-assessment.v1"
IDEMPOTENCY_REF_SCHEMA_VERSION = "phoneharness.idempotency-ref.v1"
MAX_EVIDENCE_REFS = 16
MAX_PROBE_ATTEMPTS = 5

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_FACT_WORDS = frozenset(
    {
        "authorization",
        "binding",
        "credential",
        "executor",
        "otp",
        "passcode",
        "password",
        "privatekey",
        "secret",
        "token",
    }
)


class UncertaintyError(RuntimeError):
    """Base class for deterministic uncertainty failures."""


class UncertaintyPolicyError(UncertaintyError):
    """An uncertainty contract is invalid or unsupported."""


class UncertaintyCaseNotFound(UncertaintyError):
    """A durable uncertainty case cannot be resolved."""


class InvalidOutcomeEvidence(UncertaintyError):
    """Outcome evidence is malformed, stale, or out of scope."""


class OutcomeEvidenceConflict(UncertaintyError):
    """Strong evidence proves incompatible outcomes."""


class ReconciliationProbePolicyError(UncertaintyError):
    """A reconciliation probe violates its bounded read-only contract."""


class MutatingReconciliationProbeForbidden(ReconciliationProbePolicyError):
    """A reconciliation probe is not read only."""


class IdempotencyPolicyError(UncertaintyError):
    """Idempotency metadata is unsupported or incomplete."""


class IdempotencyParameterMismatch(IdempotencyPolicyError):
    """One provider idempotency reference was rebound to different intent."""


class UncertaintyCause(str, Enum):
    DISPATCH_RESPONSE_LOST = "DISPATCH_RESPONSE_LOST"
    POST_DISPATCH_OBSERVATION_UNAVAILABLE = "POST_DISPATCH_OBSERVATION_UNAVAILABLE"
    VERIFICATION_EVIDENCE_INCONCLUSIVE = "VERIFICATION_EVIDENCE_INCONCLUSIVE"
    RUNTIME_INTERRUPTED_AFTER_POSSIBLE_DISPATCH = "RUNTIME_INTERRUPTED_AFTER_POSSIBLE_DISPATCH"
    PROVIDER_ACK_AMBIGUOUS = "PROVIDER_ACK_AMBIGUOUS"
    EVIDENCE_CONFLICT = "EVIDENCE_CONFLICT"
    EXTERNAL_STATE_UNAVAILABLE = "EXTERNAL_STATE_UNAVAILABLE"
    OTHER_TYPED_CAUSE = "OTHER_TYPED_CAUSE"


class ReconciliationState(str, Enum):
    OPEN = "OPEN"
    OBSERVING = "OBSERVING"
    EVIDENCE_CONFLICT = "EVIDENCE_CONFLICT"
    RESOLVED_EFFECT_CONFIRMED = "RESOLVED_EFFECT_CONFIRMED"
    RESOLVED_NO_EFFECT_CONFIRMED = "RESOLVED_NO_EFFECT_CONFIRMED"
    RESOLVED_SEMANTIC_SUCCESS = "RESOLVED_SEMANTIC_SUCCESS"
    RESOLVED_SEMANTIC_FAILURE = "RESOLVED_SEMANTIC_FAILURE"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    UNRESOLVED = "UNRESOLVED"
    CLOSED_FAIL_SAFE = "CLOSED_FAIL_SAFE"


class OutcomeEvidenceKind(str, Enum):
    DISPATCH_RECEIPT = "DISPATCH_RECEIPT"
    PROVIDER_CORRELATION = "PROVIDER_CORRELATION"
    IDEMPOTENCY_LOOKUP = "IDEMPOTENCY_LOOKUP"
    FRESH_OBSERVATION = "FRESH_OBSERVATION"
    SEMANTIC_VERIFIER_RESULT = "SEMANTIC_VERIFIER_RESULT"
    LEDGER_EVIDENCE = "LEDGER_EVIDENCE"
    EXTERNAL_RESOURCE_LOOKUP = "EXTERNAL_RESOURCE_LOOKUP"
    USER_CONFIRMATION = "USER_CONFIRMATION"
    TRACE_EVIDENCE = "TRACE_EVIDENCE"


class EvidenceFreshness(str, Enum):
    PRE_ATTEMPT = "PRE_ATTEMPT"
    POST_ATTEMPT = "POST_ATTEMPT"
    POST_RESTART = "POST_RESTART"
    CURRENT = "CURRENT"


class EvidenceStrength(str, Enum):
    HEURISTIC = "HEURISTIC"
    CORRELATED = "CORRELATED"
    AUTHORITATIVE = "AUTHORITATIVE"


class OutcomeClaim(str, Enum):
    DISPATCH_POSSIBLE = "DISPATCH_POSSIBLE"
    DISPATCH_CONFIRMED = "DISPATCH_CONFIRMED"
    EFFECT_CONFIRMED = "EFFECT_CONFIRMED"
    NO_EFFECT_CONFIRMED = "NO_EFFECT_CONFIRMED"
    SEMANTIC_SUCCESS = "SEMANTIC_SUCCESS"
    SEMANTIC_FAILURE = "SEMANTIC_FAILURE"
    INCONCLUSIVE = "INCONCLUSIVE"


class IdempotencyProfile(str, Enum):
    INHERENTLY_IDEMPOTENT = "INHERENTLY_IDEMPOTENT"
    PROVIDER_KEYED_IDEMPOTENT = "PROVIDER_KEYED_IDEMPOTENT"
    CONDITIONALLY_IDEMPOTENT = "CONDITIONALLY_IDEMPOTENT"
    NON_IDEMPOTENT = "NON_IDEMPOTENT"
    UNKNOWN = "UNKNOWN"


class ReconciliationDisposition(str, Enum):
    SEMANTIC_SUCCESS_CONFIRMED = "SEMANTIC_SUCCESS_CONFIRMED"
    EFFECT_CONFIRMED_SEMANTIC_UNRESOLVED = "EFFECT_CONFIRMED_SEMANTIC_UNRESOLVED"
    NO_EFFECT_CONFIRMED = "NO_EFFECT_CONFIRMED"
    SEMANTIC_FAILURE_CONFIRMED = "SEMANTIC_FAILURE_CONFIRMED"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    MORE_EVIDENCE_REQUIRED = "MORE_EVIDENCE_REQUIRED"
    EVIDENCE_CONFLICT = "EVIDENCE_CONFLICT"
    FAIL_SAFE_UNRESOLVED = "FAIL_SAFE_UNRESOLVED"


class EvidenceCommitDisposition(str, Enum):
    COMMITTED = "COMMITTED"
    STALE_DROPPED = "STALE_DROPPED"


def _identifier(value: Any, field_name: str) -> str:
    normalized = str(value or "").strip()
    if _IDENTIFIER.fullmatch(normalized) is None:
        raise UncertaintyPolicyError(f"{field_name} must be an opaque bounded identifier")
    return normalized


def _optional_identifier(value: Any, field_name: str) -> str | None:
    return None if value is None else _identifier(value, field_name)


def _timestamp(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise UncertaintyPolicyError(f"{field_name} must be a non-negative integer")
    return value


def _positive(value: Any, field_name: str, *, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise UncertaintyPolicyError(f"{field_name} must be a positive integer")
    if maximum is not None and value > maximum:
        raise UncertaintyPolicyError(f"{field_name} exceeds its bounded maximum")
    return value


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _new_identifier(prefix: str) -> str:
    return f"{prefix}.{uuid.uuid4().hex}"


def _none(value: str | None) -> str:
    return value if value is not None else "NONE"


def _from_none(value: str) -> str | None:
    return None if value == "NONE" else value


def _joined(values: Iterable[str]) -> str:
    items = tuple(values)
    return "NONE" if not items else "|".join(items)


def _split(value: str) -> tuple[str, ...]:
    return () if value == "NONE" else tuple(value.split("|"))


def _safe_facts(values: Mapping[str, Any] | Iterable[tuple[str, Any]]) -> tuple[tuple[str, str], ...]:
    items = values.items() if isinstance(values, Mapping) else values
    normalized: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw_key, raw_value in items:
        key = _identifier(raw_key, "safe fact key")
        words = {part.casefold() for part in re.split(r"[._:-]+", key)}
        if words & _FORBIDDEN_FACT_WORDS:
            raise InvalidOutcomeEvidence("safe facts cannot contain authority or secret fields")
        value = " ".join(str(raw_value or "").split())
        if not value or len(value) > 128:
            raise InvalidOutcomeEvidence("safe fact values must be non-empty bounded text")
        if key in seen:
            raise InvalidOutcomeEvidence("safe facts cannot contain duplicate keys")
        seen.add(key)
        normalized.append((key, value))
    if len(normalized) > 8:
        raise InvalidOutcomeEvidence("safe facts exceed their bounded size")
    return tuple(sorted(normalized))


def _facts_json(values: tuple[tuple[str, str], ...]) -> str:
    return json.dumps(dict(values), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _facts_from_json(value: str) -> tuple[tuple[str, str], ...]:
    try:
        payload = json.loads(value)
    except (TypeError, ValueError) as exc:
        raise InvalidOutcomeEvidence("stored safe facts are invalid") from exc
    if not isinstance(payload, dict):
        raise InvalidOutcomeEvidence("stored safe facts are invalid")
    return _safe_facts(payload)


def digest_operation_parameters(parameters: Mapping[str, Any]) -> str:
    try:
        canonical = json.dumps(parameters, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    except (TypeError, ValueError) as exc:
        raise IdempotencyPolicyError("operation parameters must be canonically serializable") from exc
    if len(canonical.encode("utf-8")) > 4096:
        raise IdempotencyPolicyError("operation parameters exceed the bounded digest input")
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class IdempotencyKeyRef:
    key_ref: str
    provider_id: str
    logical_operation: str
    parameter_digest: str
    created_at_ms: int
    schema_version: str = IDEMPOTENCY_REF_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != IDEMPOTENCY_REF_SCHEMA_VERSION:
            raise IdempotencyPolicyError("unsupported IdempotencyKeyRef schema version")
        for name in ("key_ref", "provider_id", "logical_operation"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        if _DIGEST.fullmatch(str(self.parameter_digest)) is None:
            raise IdempotencyPolicyError("idempotency parameters require a SHA-256 digest")
        _timestamp(self.created_at_ms, "created_at_ms")

    def audit(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "provider_id": self.provider_id,
            "logical_operation": self.logical_operation,
            "parameter_digest_present": True,
            "authority": False,
        }


@dataclass(frozen=True)
class OutcomeEvidence:
    evidence_id: str
    uncertain_outcome_id: str
    task_id: str
    execution_id: str
    kind: OutcomeEvidenceKind
    source: str
    observed_at_ms: int
    freshness: EvidenceFreshness
    strength: EvidenceStrength
    claim: OutcomeClaim
    observation_ref: ObservationRef | None = None
    receipt_ref: str | None = None
    artifact_ref: ArtifactRef | None = None
    trace_event_ref: str | None = None
    verifier_result: str | None = None
    safe_facts: tuple[tuple[str, str], ...] = ()
    schema_version: str = OUTCOME_EVIDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != OUTCOME_EVIDENCE_SCHEMA_VERSION:
            raise InvalidOutcomeEvidence("unsupported OutcomeEvidence schema version")
        for name in ("evidence_id", "uncertain_outcome_id", "task_id", "execution_id", "source"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(self, "receipt_ref", _optional_identifier(self.receipt_ref, "receipt_ref"))
        object.__setattr__(
            self,
            "trace_event_ref",
            _optional_identifier(self.trace_event_ref, "trace_event_ref"),
        )
        object.__setattr__(
            self,
            "verifier_result",
            _optional_identifier(self.verifier_result, "verifier_result"),
        )
        _timestamp(self.observed_at_ms, "observed_at_ms")
        try:
            object.__setattr__(self, "kind", OutcomeEvidenceKind(self.kind))
            object.__setattr__(self, "freshness", EvidenceFreshness(self.freshness))
            object.__setattr__(self, "strength", EvidenceStrength(self.strength))
            object.__setattr__(self, "claim", OutcomeClaim(self.claim))
        except ValueError as exc:
            raise InvalidOutcomeEvidence("outcome evidence contains an unsupported classification") from exc
        if self.observation_ref is not None:
            if not isinstance(self.observation_ref, ObservationRef) or self.observation_ref.task_id != self.task_id:
                raise InvalidOutcomeEvidence("observation evidence must share exact task scope")
        if self.artifact_ref is not None:
            if not isinstance(self.artifact_ref, ArtifactRef) or self.artifact_ref.task_id != self.task_id:
                raise InvalidOutcomeEvidence("artifact evidence must share exact task scope")
        semantic_claims = {OutcomeClaim.SEMANTIC_SUCCESS, OutcomeClaim.SEMANTIC_FAILURE}
        if self.claim in semantic_claims:
            if self.kind is not OutcomeEvidenceKind.SEMANTIC_VERIFIER_RESULT:
                raise InvalidOutcomeEvidence("semantic outcome requires Semantic Verifier evidence")
            expected = "PASSED" if self.claim is OutcomeClaim.SEMANTIC_SUCCESS else "FAILED"
            if self.verifier_result != expected:
                raise InvalidOutcomeEvidence("semantic claim does not match verifier result")
        if self.claim is OutcomeClaim.NO_EFFECT_CONFIRMED:
            allowed = {
                OutcomeEvidenceKind.PROVIDER_CORRELATION,
                OutcomeEvidenceKind.IDEMPOTENCY_LOOKUP,
                OutcomeEvidenceKind.FRESH_OBSERVATION,
                OutcomeEvidenceKind.EXTERNAL_RESOURCE_LOOKUP,
            }
            if self.kind not in allowed or self.strength is not EvidenceStrength.AUTHORITATIVE:
                raise InvalidOutcomeEvidence("no-effect confirmation requires explicit authoritative evidence")
        if self.freshness is EvidenceFreshness.PRE_ATTEMPT and self.claim in {
            OutcomeClaim.EFFECT_CONFIRMED,
            OutcomeClaim.NO_EFFECT_CONFIRMED,
            OutcomeClaim.SEMANTIC_SUCCESS,
            OutcomeClaim.SEMANTIC_FAILURE,
        }:
            raise InvalidOutcomeEvidence("pre-attempt evidence cannot resolve a post-attempt outcome")
        object.__setattr__(self, "safe_facts", _safe_facts(self.safe_facts))

    def audit(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "kind": self.kind.value,
            "freshness": self.freshness.value,
            "strength": self.strength.value,
            "claim": self.claim.value,
            "authority": False,
        }

    def to_artifact_descriptor(self, session_id: str | None) -> ArtifactDescriptor:
        metadata = {
            "evidence_schema": self.schema_version,
            "evidence_id": self.evidence_id,
            "uncertain_outcome_id": self.uncertain_outcome_id,
            "execution_id": self.execution_id,
            "kind": self.kind.value,
            "source": self.source,
            "observed_at_ms": str(self.observed_at_ms),
            "freshness": self.freshness.value,
            "strength": self.strength.value,
            "claim": self.claim.value,
            "receipt_ref": _none(self.receipt_ref),
            "artifact_ref": _none(self.artifact_ref.artifact_id if self.artifact_ref else None),
            "trace_event_ref": _none(self.trace_event_ref),
            "verifier_result": _none(self.verifier_result),
            "safe_facts": _facts_json(self.safe_facts),
        }
        return ArtifactDescriptor(
            ref=ArtifactRef(f"outcome-evidence.{self.evidence_id}", self.task_id, session_id),
            artifact_kind="outcome.evidence",
            producer="outcome.reconciler",
            created_at_ms=self.observed_at_ms,
            sensitivity=SensitivityClass.PRIVATE,
            lifetime=ArtifactLifetime.DURABLE,
            observation_ref=self.observation_ref,
            opaque_locator=self.uncertain_outcome_id,
            metadata=tuple(metadata.items()),
        )

    @classmethod
    def from_artifact_descriptor(cls, descriptor: ArtifactDescriptor) -> "OutcomeEvidence":
        if descriptor.artifact_kind != "outcome.evidence":
            raise InvalidOutcomeEvidence("durable record is not OutcomeEvidence")
        metadata = dict(descriptor.metadata)
        required = {
            "evidence_schema",
            "evidence_id",
            "uncertain_outcome_id",
            "execution_id",
            "kind",
            "source",
            "observed_at_ms",
            "freshness",
            "strength",
            "claim",
            "receipt_ref",
            "artifact_ref",
            "trace_event_ref",
            "verifier_result",
            "safe_facts",
        }
        if set(metadata) != required or descriptor.ref.session_id is None:
            raise InvalidOutcomeEvidence("OutcomeEvidence durable fields do not match its schema")
        artifact_id = _from_none(metadata["artifact_ref"])
        return cls(
            evidence_id=metadata["evidence_id"],
            uncertain_outcome_id=metadata["uncertain_outcome_id"],
            task_id=descriptor.ref.task_id,
            execution_id=metadata["execution_id"],
            kind=OutcomeEvidenceKind(metadata["kind"]),
            source=metadata["source"],
            observed_at_ms=int(metadata["observed_at_ms"]),
            freshness=EvidenceFreshness(metadata["freshness"]),
            strength=EvidenceStrength(metadata["strength"]),
            claim=OutcomeClaim(metadata["claim"]),
            observation_ref=descriptor.observation_ref,
            receipt_ref=_from_none(metadata["receipt_ref"]),
            artifact_ref=(
                ArtifactRef(artifact_id, descriptor.ref.task_id, descriptor.ref.session_id)
                if artifact_id is not None
                else None
            ),
            trace_event_ref=_from_none(metadata["trace_event_ref"]),
            verifier_result=_from_none(metadata["verifier_result"]),
            safe_facts=_facts_from_json(metadata["safe_facts"]),
            schema_version=metadata["evidence_schema"],
        )


@dataclass(frozen=True)
class UncertainOutcomeRecord:
    uncertain_outcome_id: str
    task_id: str
    session_id: str
    trace_id: str
    execution_id: str
    capability_id: str
    provider_id: str
    original_runtime_instance_id: str
    current_runtime_instance_id: str
    dispatch_receipt_ref: str
    cause: UncertaintyCause
    state: ReconciliationState
    created_at_ms: int
    updated_at_ms: int
    revision: int = 1
    step_id: str | None = None
    evidence_refs: tuple[str, ...] = ()
    idempotency_profile: IdempotencyProfile = IdempotencyProfile.UNKNOWN
    idempotency_binding_ref: str | None = None
    schema_version: str = UNCERTAIN_OUTCOME_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != UNCERTAIN_OUTCOME_SCHEMA_VERSION:
            raise UncertaintyPolicyError("unsupported UncertainOutcomeRecord schema version")
        for name in (
            "uncertain_outcome_id",
            "task_id",
            "session_id",
            "trace_id",
            "execution_id",
            "capability_id",
            "provider_id",
            "original_runtime_instance_id",
            "current_runtime_instance_id",
            "dispatch_receipt_ref",
        ):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(self, "step_id", _optional_identifier(self.step_id, "step_id"))
        object.__setattr__(
            self,
            "idempotency_binding_ref",
            _optional_identifier(self.idempotency_binding_ref, "idempotency_binding_ref"),
        )
        try:
            object.__setattr__(self, "cause", UncertaintyCause(self.cause))
            object.__setattr__(self, "state", ReconciliationState(self.state))
            object.__setattr__(self, "idempotency_profile", IdempotencyProfile(self.idempotency_profile))
        except ValueError as exc:
            raise UncertaintyPolicyError("uncertain outcome contains an unsupported classification") from exc
        _timestamp(self.created_at_ms, "created_at_ms")
        _timestamp(self.updated_at_ms, "updated_at_ms")
        if self.updated_at_ms < self.created_at_ms:
            raise UncertaintyPolicyError("uncertain outcome update precedes creation")
        _positive(self.revision, "revision")
        refs = tuple(_identifier(value, "evidence_ref") for value in self.evidence_refs)
        if len(refs) > MAX_EVIDENCE_REFS or len(refs) != len(set(refs)):
            raise UncertaintyPolicyError("outcome evidence references must be bounded and unique")
        object.__setattr__(self, "evidence_refs", refs)
        if self.idempotency_profile is IdempotencyProfile.PROVIDER_KEYED_IDEMPOTENT:
            if self.idempotency_binding_ref is None:
                raise IdempotencyPolicyError("provider-keyed idempotency requires an explicit binding reference")
        elif self.idempotency_binding_ref is not None:
            raise IdempotencyPolicyError("idempotency binding is unsupported for this profile")

    def audit(self) -> dict[str, Any]:
        return {
            "uncertain_outcome_id": self.uncertain_outcome_id,
            "task_state": TaskExecutionState.UNKNOWN_OUTCOME.value,
            "reconciliation_state": self.state.value,
            "cause": self.cause.value,
            "idempotency_profile": self.idempotency_profile.value,
            "authority": {
                "action": False,
                "retry": False,
                "replay": False,
                "binding": False,
                "executor": False,
            },
        }

    def to_artifact_descriptor(self) -> ArtifactDescriptor:
        metadata = {
            "case_schema": self.schema_version,
            "uncertain_outcome_id": self.uncertain_outcome_id,
            "trace_id": self.trace_id,
            "step_id": _none(self.step_id),
            "execution_id": self.execution_id,
            "capability_id": self.capability_id,
            "provider_id": self.provider_id,
            "runtime_ids": f"{self.original_runtime_instance_id}|{self.current_runtime_instance_id}",
            "cause": self.cause.value,
            "state": self.state.value,
            "time_revision": f"{self.created_at_ms}:{self.updated_at_ms}:{self.revision}",
            "dispatch_receipt_ref": self.dispatch_receipt_ref,
            "evidence_ref_ids": _joined(self.evidence_refs),
            "idempotency_profile": self.idempotency_profile.value,
            "idempotency_correlation_ref": _none(self.idempotency_binding_ref),
        }
        return ArtifactDescriptor(
            ref=ArtifactRef(
                f"uncertain-outcome.{self.uncertain_outcome_id}.r{self.revision:06d}",
                self.task_id,
                self.session_id,
            ),
            artifact_kind="outcome.uncertain-case",
            producer="outcome.reconciler",
            created_at_ms=self.updated_at_ms,
            sensitivity=SensitivityClass.PRIVATE,
            lifetime=ArtifactLifetime.DURABLE,
            opaque_locator=self.uncertain_outcome_id,
            metadata=tuple(metadata.items()),
        )

    @classmethod
    def from_artifact_descriptor(cls, descriptor: ArtifactDescriptor) -> "UncertainOutcomeRecord":
        if descriptor.artifact_kind != "outcome.uncertain-case" or descriptor.ref.session_id is None:
            raise UncertaintyPolicyError("durable record is not an uncertainty case")
        metadata = dict(descriptor.metadata)
        required = {
            "case_schema",
            "uncertain_outcome_id",
            "trace_id",
            "step_id",
            "execution_id",
            "capability_id",
            "provider_id",
            "runtime_ids",
            "cause",
            "state",
            "time_revision",
            "dispatch_receipt_ref",
            "evidence_ref_ids",
            "idempotency_profile",
            "idempotency_correlation_ref",
        }
        if set(metadata) != required:
            raise UncertaintyPolicyError("uncertainty case durable fields do not match its schema")
        runtime_ids = tuple(metadata["runtime_ids"].split("|"))
        time_revision = tuple(int(value) for value in metadata["time_revision"].split(":"))
        if len(runtime_ids) != 2 or len(time_revision) != 3:
            raise UncertaintyPolicyError("uncertainty case durable identity is invalid")
        return cls(
            uncertain_outcome_id=metadata["uncertain_outcome_id"],
            task_id=descriptor.ref.task_id,
            session_id=descriptor.ref.session_id,
            trace_id=metadata["trace_id"],
            step_id=_from_none(metadata["step_id"]),
            execution_id=metadata["execution_id"],
            capability_id=metadata["capability_id"],
            provider_id=metadata["provider_id"],
            original_runtime_instance_id=runtime_ids[0],
            current_runtime_instance_id=runtime_ids[1],
            dispatch_receipt_ref=metadata["dispatch_receipt_ref"],
            cause=UncertaintyCause(metadata["cause"]),
            state=ReconciliationState(metadata["state"]),
            created_at_ms=time_revision[0],
            updated_at_ms=time_revision[1],
            revision=time_revision[2],
            evidence_refs=_split(metadata["evidence_ref_ids"]),
            idempotency_profile=IdempotencyProfile(metadata["idempotency_profile"]),
            idempotency_binding_ref=_from_none(metadata["idempotency_correlation_ref"]),
            schema_version=metadata["case_schema"],
        )


@dataclass(frozen=True)
class OutcomeReconciliationAssessment:
    assessment_id: str
    uncertain_outcome_id: str
    task_id: str
    trace_id: str
    state: ReconciliationState
    disposition: ReconciliationDisposition
    recommended_task_state: TaskExecutionState
    created_at_ms: int
    evidence_refs: tuple[str, ...]
    verifier_evidence_ref: str | None = None
    schema_version: str = RECONCILIATION_ASSESSMENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RECONCILIATION_ASSESSMENT_SCHEMA_VERSION:
            raise UncertaintyPolicyError("unsupported reconciliation assessment schema")
        for name in ("assessment_id", "uncertain_outcome_id", "task_id", "trace_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(
            self,
            "verifier_evidence_ref",
            _optional_identifier(self.verifier_evidence_ref, "verifier_evidence_ref"),
        )
        try:
            object.__setattr__(self, "state", ReconciliationState(self.state))
            object.__setattr__(self, "disposition", ReconciliationDisposition(self.disposition))
        except ValueError as exc:
            raise UncertaintyPolicyError("assessment contains an unsupported classification") from exc
        if not isinstance(self.recommended_task_state, TaskExecutionState):
            raise UncertaintyPolicyError("assessment requires a typed TaskExecutionState")
        _timestamp(self.created_at_ms, "created_at_ms")
        refs = tuple(_identifier(value, "evidence_ref") for value in self.evidence_refs)
        if len(refs) > MAX_EVIDENCE_REFS or len(refs) != len(set(refs)):
            raise UncertaintyPolicyError("assessment evidence references must be bounded and unique")
        object.__setattr__(self, "evidence_refs", refs)

    def audit(self) -> dict[str, Any]:
        return {
            "assessment_id": self.assessment_id,
            "state": self.state.value,
            "disposition": self.disposition.value,
            "recommended_task_state": self.recommended_task_state.value,
            "mutation_dispatch_count": 0,
            "original_action_retry_count": 0,
            "authority": False,
        }

    def to_artifact_descriptor(self, session_id: str) -> ArtifactDescriptor:
        metadata = {
            "assessment_schema": self.schema_version,
            "assessment_id": self.assessment_id,
            "uncertain_outcome_id": self.uncertain_outcome_id,
            "trace_id": self.trace_id,
            "state": self.state.value,
            "disposition": self.disposition.value,
            "recommended_task_state": self.recommended_task_state.value,
            "evidence_ref_ids": _joined(self.evidence_refs),
            "verifier_evidence_ref": _none(self.verifier_evidence_ref),
        }
        return ArtifactDescriptor(
            ref=ArtifactRef(f"outcome-assessment.{self.assessment_id}", self.task_id, session_id),
            artifact_kind="outcome.assessment",
            producer="outcome.reconciler",
            created_at_ms=self.created_at_ms,
            sensitivity=SensitivityClass.PRIVATE,
            lifetime=ArtifactLifetime.DURABLE,
            opaque_locator=self.uncertain_outcome_id,
            metadata=tuple(metadata.items()),
        )


@dataclass(frozen=True)
class EvidenceCommitResult:
    disposition: EvidenceCommitDisposition
    record: UncertainOutcomeRecord


@dataclass(frozen=True)
class ReconciliationProbe:
    probe_id: str
    evidence_kind: OutcomeEvidenceKind
    side_effect_class: SideEffectClass
    max_attempts: int
    deadline_ms: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "probe_id", _identifier(self.probe_id, "probe_id"))
        try:
            object.__setattr__(self, "evidence_kind", OutcomeEvidenceKind(self.evidence_kind))
            object.__setattr__(self, "side_effect_class", SideEffectClass(self.side_effect_class))
        except ValueError as exc:
            raise ReconciliationProbePolicyError("probe contains an unsupported classification") from exc
        _positive(self.max_attempts, "max_attempts", maximum=MAX_PROBE_ATTEMPTS)
        _timestamp(self.deadline_ms, "deadline_ms")


@dataclass(frozen=True)
class ProbeRunResult:
    attempts: int
    evidence_added: bool
    final_record: UncertainOutcomeRecord
    mutating_probe_count: int = 0
    original_action_retry_count: int = 0
    redispatch_count: int = 0


class OutcomeReconciler:
    """Durable evidence reconciler with no mutation or retry capability."""

    def __init__(
        self,
        store: PhoneHarnessStore,
        runtime_ref: RuntimeInstanceRef,
        *,
        now_ms: Callable[[], int] = _now_ms,
        id_factory: Callable[[str], str] = _new_identifier,
    ) -> None:
        if not isinstance(store, PhoneHarnessStore) or not isinstance(runtime_ref, RuntimeInstanceRef):
            raise UncertaintyPolicyError("OutcomeReconciler requires typed store and Runtime identity")
        self.store = store
        self.runtime_ref = runtime_ref
        self._now_ms = now_ms
        self._id_factory = id_factory

    def open_case(
        self,
        receipt: ExecutionReceipt,
        *,
        session_id: str,
        trace_id: str,
        cause: UncertaintyCause,
        idempotency_profile: IdempotencyProfile = IdempotencyProfile.UNKNOWN,
        idempotency_ref: IdempotencyKeyRef | None = None,
    ) -> UncertainOutcomeRecord:
        if not isinstance(receipt, ExecutionReceipt):
            raise UncertaintyPolicyError("uncertainty case requires ExecutionReceipt")
        durable = self.store.get_receipt(receipt.receipt_id)
        if durable != receipt:
            raise UncertaintyPolicyError("uncertainty case receipt does not match durable evidence")
        if (
            receipt.result_status is not ReceiptResultStatus.UNKNOWN_OUTCOME
            or receipt.dispatch_status is DispatchStatus.NOT_DISPATCHED
        ):
            raise UncertaintyPolicyError("uncertainty case requires possible dispatch and UNKNOWN_OUTCOME")
        session = _identifier(session_id, "session_id")
        for descriptor in self.store.list_artifacts(receipt.task_id, session_id=session):
            if descriptor.artifact_kind != "outcome.uncertain-case":
                continue
            existing = UncertainOutcomeRecord.from_artifact_descriptor(descriptor)
            if existing.dispatch_receipt_ref == receipt.receipt_id:
                raise UncertaintyPolicyError("dispatch receipt already has an uncertainty case")
        profile = IdempotencyProfile(idempotency_profile)
        binding_ref = self._persist_idempotency_binding(
            receipt,
            session,
            profile,
            idempotency_ref,
        )
        now = self._now_ms()
        record = UncertainOutcomeRecord(
            uncertain_outcome_id=self._id_factory("uncertain-outcome"),
            task_id=receipt.task_id,
            session_id=session,
            trace_id=trace_id,
            step_id=receipt.step_id,
            execution_id=receipt.execution_id,
            capability_id=receipt.capability_id,
            provider_id=receipt.provider_id,
            original_runtime_instance_id=self.runtime_ref.runtime_instance_id,
            current_runtime_instance_id=self.runtime_ref.runtime_instance_id,
            dispatch_receipt_ref=receipt.receipt_id,
            cause=UncertaintyCause(cause),
            state=ReconciliationState.OPEN,
            created_at_ms=now,
            updated_at_ms=now,
            idempotency_profile=profile,
            idempotency_binding_ref=binding_ref,
        )
        self._persist_case(record, "uncertain-outcome.opened")
        return record

    def load_case(
        self,
        *,
        uncertain_outcome_id: str,
        task_id: str,
        session_id: str,
    ) -> UncertainOutcomeRecord:
        case_id = _identifier(uncertain_outcome_id, "uncertain_outcome_id")
        records = []
        for descriptor in self.store.list_artifacts(task_id, session_id=session_id):
            if descriptor.artifact_kind != "outcome.uncertain-case":
                continue
            record = UncertainOutcomeRecord.from_artifact_descriptor(descriptor)
            if record.uncertain_outcome_id == case_id:
                records.append(record)
        if not records:
            raise UncertaintyCaseNotFound("uncertainty case is not present in canonical store")
        return max(records, key=lambda value: value.revision)

    def route_runtime_reconciliation(
        self,
        capsule: TaskCapsule,
        assessment: RuntimeRecoveryAssessment,
    ) -> UncertainOutcomeRecord:
        if not isinstance(capsule, TaskCapsule) or not isinstance(assessment, RuntimeRecoveryAssessment):
            raise UncertaintyPolicyError("Runtime reconciliation requires typed M3 evidence")
        if (
            capsule.task_state is not TaskExecutionState.UNKNOWN_OUTCOME
            or assessment.task_state is not TaskExecutionState.UNKNOWN_OUTCOME
            or assessment.disposition is not SupervisorRecoveryDisposition.RECONCILE_REQUIRED
            or capsule.last_receipt_ref is None
        ):
            raise UncertaintyPolicyError("Runtime assessment does not route to uncertain-outcome reconciliation")
        cases = [
            UncertainOutcomeRecord.from_artifact_descriptor(descriptor)
            for descriptor in self.store.list_artifacts(
                capsule.task_id,
                session_id=capsule.session_ref.session_id,
            )
            if descriptor.artifact_kind == "outcome.uncertain-case"
        ]
        matching = [case for case in cases if case.dispatch_receipt_ref == capsule.last_receipt_ref]
        if not matching:
            raise UncertaintyCaseNotFound("Runtime capsule has no canonical uncertainty case")
        current = max(matching, key=lambda value: value.revision)
        if current.current_runtime_instance_id == self.runtime_ref.runtime_instance_id:
            return current
        updated = replace(
            current,
            current_runtime_instance_id=self.runtime_ref.runtime_instance_id,
            state=ReconciliationState.OBSERVING,
            revision=current.revision + 1,
            updated_at_ms=max(self._now_ms(), current.updated_at_ms + 1),
        )
        self._persist_case(updated, "reconciliation.runtime-claimed")
        return updated

    def add_evidence(
        self,
        record: UncertainOutcomeRecord,
        evidence: OutcomeEvidence,
        *,
        origin_runtime_instance_id: str,
    ) -> EvidenceCommitResult:
        current = self._require_current(record)
        if (
            evidence.uncertain_outcome_id != current.uncertain_outcome_id
            or evidence.task_id != current.task_id
            or evidence.execution_id != current.execution_id
        ):
            raise InvalidOutcomeEvidence("outcome evidence correlation does not match its case")
        self._validate_evidence_references(current, evidence)
        descriptor = evidence.to_artifact_descriptor(current.session_id)
        origin = _identifier(origin_runtime_instance_id, "origin_runtime_instance_id")
        if origin != current.current_runtime_instance_id or origin != self.runtime_ref.runtime_instance_id:
            self._persist_evidence(descriptor, current, "reconciliation.stale-evidence-dropped")
            return EvidenceCommitResult(EvidenceCommitDisposition.STALE_DROPPED, current)
        self._persist_evidence(descriptor, current, "reconciliation.evidence-added")
        if evidence.evidence_id in current.evidence_refs:
            return EvidenceCommitResult(EvidenceCommitDisposition.COMMITTED, current)
        updated = replace(
            current,
            state=ReconciliationState.OBSERVING,
            evidence_refs=(*current.evidence_refs, evidence.evidence_id),
            revision=current.revision + 1,
            updated_at_ms=max(self._now_ms(), current.updated_at_ms + 1),
        )
        self._persist_case(updated, "reconciliation.evidence-linked")
        return EvidenceCommitResult(EvidenceCommitDisposition.COMMITTED, updated)

    def record_verifier_result(
        self,
        record: UncertainOutcomeRecord,
        *,
        observation_ref: ObservationRef,
        verifier_trace_ref: str,
        origin_runtime_instance_id: str,
    ) -> EvidenceCommitResult:
        if not isinstance(observation_ref, ObservationRef):
            raise InvalidOutcomeEvidence("verifier evidence requires ObservationRef")
        if observation_ref.freshness is not ObservationFreshness.FRESH:
            raise InvalidOutcomeEvidence("semantic verifier evidence must use a fresh observation")
        current = self._require_current(record)
        verifier_ref = _identifier(verifier_trace_ref, "verifier_trace_ref")
        event = self.store.get_trace_event(verifier_ref)
        if (
            event.task_id != current.task_id
            or event.trace_id != current.trace_id
            or event.execution_id != current.execution_id
            or observation_ref not in event.observation_refs
            or event.verifier_result not in {"PASSED", "FAILED"}
        ):
            raise InvalidOutcomeEvidence("semantic verifier trace is not exactly correlated")
        dispatch_receipt = self.store.get_receipt(current.dispatch_receipt_ref)
        if observation_ref.observed_at_ms is None or observation_ref.observed_at_ms <= dispatch_receipt.ended_at_ms:
            raise InvalidOutcomeEvidence("semantic verifier observation is not post-attempt evidence")
        passed = event.verifier_result == "PASSED"
        evidence = OutcomeEvidence(
            evidence_id=self._id_factory("outcome-evidence"),
            uncertain_outcome_id=record.uncertain_outcome_id,
            task_id=record.task_id,
            execution_id=record.execution_id,
            kind=OutcomeEvidenceKind.SEMANTIC_VERIFIER_RESULT,
            source="semantic.verifier",
            observed_at_ms=observation_ref.observed_at_ms or self._now_ms(),
            freshness=EvidenceFreshness.CURRENT,
            strength=EvidenceStrength.AUTHORITATIVE,
            claim=OutcomeClaim.SEMANTIC_SUCCESS if passed else OutcomeClaim.SEMANTIC_FAILURE,
            observation_ref=observation_ref,
            trace_event_ref=verifier_ref,
            verifier_result="PASSED" if passed else "FAILED",
        )
        return self.add_evidence(
            record,
            evidence,
            origin_runtime_instance_id=origin_runtime_instance_id,
        )

    def reconcile(self, record: UncertainOutcomeRecord) -> OutcomeReconciliationAssessment:
        current = self._require_current(record)
        evidence = self._load_linked_evidence(current)
        authoritative = tuple(
            item
            for item in evidence
            if item.strength is EvidenceStrength.AUTHORITATIVE
            and item.freshness is not EvidenceFreshness.PRE_ATTEMPT
        )
        claims = {item.claim for item in authoritative}
        semantic_conflict = {
            OutcomeClaim.SEMANTIC_SUCCESS,
            OutcomeClaim.SEMANTIC_FAILURE,
        }.issubset(claims)
        effect_conflict = {
            OutcomeClaim.EFFECT_CONFIRMED,
            OutcomeClaim.NO_EFFECT_CONFIRMED,
        }.issubset(claims)
        if semantic_conflict or effect_conflict:
            state = ReconciliationState.EVIDENCE_CONFLICT
            disposition = ReconciliationDisposition.EVIDENCE_CONFLICT
            task_state = TaskExecutionState.UNKNOWN_OUTCOME
        elif OutcomeClaim.SEMANTIC_SUCCESS in claims:
            state = ReconciliationState.RESOLVED_SEMANTIC_SUCCESS
            disposition = ReconciliationDisposition.SEMANTIC_SUCCESS_CONFIRMED
            task_state = TaskExecutionState.SUCCEEDED
        elif OutcomeClaim.SEMANTIC_FAILURE in claims:
            state = ReconciliationState.RESOLVED_SEMANTIC_FAILURE
            disposition = ReconciliationDisposition.SEMANTIC_FAILURE_CONFIRMED
            task_state = TaskExecutionState.FAILED
        elif OutcomeClaim.NO_EFFECT_CONFIRMED in claims:
            state = ReconciliationState.RESOLVED_NO_EFFECT_CONFIRMED
            disposition = ReconciliationDisposition.NO_EFFECT_CONFIRMED
            task_state = TaskExecutionState.UNKNOWN_OUTCOME
        elif OutcomeClaim.EFFECT_CONFIRMED in claims:
            state = ReconciliationState.RESOLVED_EFFECT_CONFIRMED
            disposition = ReconciliationDisposition.EFFECT_CONFIRMED_SEMANTIC_UNRESOLVED
            task_state = TaskExecutionState.UNKNOWN_OUTCOME
        elif any(item.kind is OutcomeEvidenceKind.USER_CONFIRMATION for item in evidence):
            state = ReconciliationState.WAITING_FOR_USER
            disposition = ReconciliationDisposition.WAITING_FOR_USER
            task_state = TaskExecutionState.WAITING_FOR_USER
        elif evidence:
            state = ReconciliationState.UNRESOLVED
            disposition = ReconciliationDisposition.MORE_EVIDENCE_REQUIRED
            task_state = TaskExecutionState.UNKNOWN_OUTCOME
        else:
            state = ReconciliationState.CLOSED_FAIL_SAFE
            disposition = ReconciliationDisposition.FAIL_SAFE_UNRESOLVED
            task_state = TaskExecutionState.UNKNOWN_OUTCOME
        verifier_refs = [
            item.evidence_id
            for item in authoritative
            if item.kind is OutcomeEvidenceKind.SEMANTIC_VERIFIER_RESULT
        ]
        assessment = OutcomeReconciliationAssessment(
            assessment_id=self._id_factory("outcome-assessment"),
            uncertain_outcome_id=current.uncertain_outcome_id,
            task_id=current.task_id,
            trace_id=current.trace_id,
            state=state,
            disposition=disposition,
            recommended_task_state=task_state,
            created_at_ms=self._now_ms(),
            evidence_refs=current.evidence_refs,
            verifier_evidence_ref=verifier_refs[-1] if verifier_refs else None,
        )
        updated = replace(
            current,
            state=state,
            revision=current.revision + 1,
            updated_at_ms=max(assessment.created_at_ms, current.updated_at_ms + 1),
        )
        self._persist_assessment(assessment, current.session_id)
        self._persist_case(updated, f"reconciliation.{disposition.value.casefold().replace('_', '-')}")
        return assessment

    def run_probe(
        self,
        record: UncertainOutcomeRecord,
        probe: ReconciliationProbe,
        observe: Callable[[int], OutcomeEvidence | None],
    ) -> ProbeRunResult:
        current = self._require_current(record)
        if not isinstance(probe, ReconciliationProbe):
            raise ReconciliationProbePolicyError("reconciliation requires a typed probe")
        if probe.side_effect_class is not SideEffectClass.READ_ONLY:
            raise MutatingReconciliationProbeForbidden("reconciliation probes must be read only")
        attempts = 0
        evidence_added = False
        while attempts < probe.max_attempts and self._now_ms() <= probe.deadline_ms:
            attempts += 1
            observed = observe(attempts)
            if observed is None:
                continue
            if observed.kind is not probe.evidence_kind:
                raise ReconciliationProbePolicyError("probe returned an undeclared evidence kind")
            result = self.add_evidence(
                current,
                observed,
                origin_runtime_instance_id=self.runtime_ref.runtime_instance_id,
            )
            current = result.record
            evidence_added = result.disposition is EvidenceCommitDisposition.COMMITTED
            if observed.claim is not OutcomeClaim.INCONCLUSIVE:
                break
        return ProbeRunResult(attempts, evidence_added, current)

    def _persist_idempotency_binding(
        self,
        receipt: ExecutionReceipt,
        session_id: str,
        profile: IdempotencyProfile,
        key_ref: IdempotencyKeyRef | None,
    ) -> str | None:
        if profile is IdempotencyProfile.PROVIDER_KEYED_IDEMPOTENT:
            if key_ref is None:
                raise IdempotencyPolicyError("provider-keyed idempotency requires explicit metadata")
            if key_ref.provider_id != receipt.provider_id or key_ref.logical_operation != receipt.operation:
                raise IdempotencyParameterMismatch("idempotency reference does not match provider operation")
            key_digest = hashlib.sha256(
                f"{key_ref.provider_id}\0{key_ref.key_ref}".encode("utf-8")
            ).hexdigest()
            binding_id = f"idempotency-binding.{key_digest}"
            descriptor = ArtifactDescriptor(
                ref=ArtifactRef(binding_id, receipt.task_id, session_id),
                artifact_kind="outcome.idempotency-binding",
                producer="outcome.reconciler",
                created_at_ms=key_ref.created_at_ms,
                sensitivity=SensitivityClass.PRIVATE,
                lifetime=ArtifactLifetime.DURABLE,
                content_digest=key_ref.parameter_digest,
                opaque_locator=binding_id,
                metadata=(
                    ("idempotency_schema", key_ref.schema_version),
                    ("provider_id", key_ref.provider_id),
                    ("logical_operation", key_ref.logical_operation),
                    ("profile", profile.value),
                ),
            )
            try:
                self.store.register_artifact(descriptor)
            except StoreConflictError as exc:
                raise IdempotencyParameterMismatch(
                    "idempotency reference was already bound to different parameters"
                ) from exc
            return binding_id
        if key_ref is not None:
            raise IdempotencyPolicyError("idempotency key metadata is unsupported for this profile")
        return None

    def _require_current(self, record: UncertainOutcomeRecord) -> UncertainOutcomeRecord:
        if not isinstance(record, UncertainOutcomeRecord):
            raise UncertaintyPolicyError("reconciliation requires UncertainOutcomeRecord")
        current = self.load_case(
            uncertain_outcome_id=record.uncertain_outcome_id,
            task_id=record.task_id,
            session_id=record.session_id,
        )
        if current.revision != record.revision:
            raise UncertaintyPolicyError("uncertainty case revision is no longer current")
        if current.current_runtime_instance_id != self.runtime_ref.runtime_instance_id:
            raise UncertaintyPolicyError("uncertainty case belongs to a different Runtime incarnation")
        return current

    def _load_linked_evidence(self, record: UncertainOutcomeRecord) -> tuple[OutcomeEvidence, ...]:
        by_id = {}
        for descriptor in self.store.list_artifacts(record.task_id, session_id=record.session_id):
            if descriptor.artifact_kind == "outcome.evidence":
                evidence = OutcomeEvidence.from_artifact_descriptor(descriptor)
                by_id[evidence.evidence_id] = evidence
        try:
            return tuple(by_id[evidence_id] for evidence_id in record.evidence_refs)
        except KeyError as exc:
            raise InvalidOutcomeEvidence("linked outcome evidence is missing from canonical store") from exc

    def _validate_evidence_references(
        self,
        record: UncertainOutcomeRecord,
        evidence: OutcomeEvidence,
    ) -> None:
        dispatch_receipt = self.store.get_receipt(record.dispatch_receipt_ref)
        if dispatch_receipt.task_id != record.task_id or dispatch_receipt.execution_id != record.execution_id:
            raise InvalidOutcomeEvidence("dispatch receipt does not match uncertainty case")
        if evidence.receipt_ref is not None:
            receipt = self.store.get_receipt(evidence.receipt_ref)
            if receipt.task_id != record.task_id or receipt.execution_id != record.execution_id:
                raise InvalidOutcomeEvidence("receipt evidence is not exactly correlated")
        if evidence.artifact_ref is not None:
            descriptor = self.store.get_artifact(evidence.artifact_ref)
            if descriptor.ref.task_id != record.task_id:
                raise InvalidOutcomeEvidence("artifact evidence is not exactly correlated")
        if evidence.trace_event_ref is not None:
            event = self.store.get_trace_event(evidence.trace_event_ref)
            if (
                event.task_id != record.task_id
                or event.trace_id != record.trace_id
                or event.execution_id != record.execution_id
            ):
                raise InvalidOutcomeEvidence("trace evidence is not exactly correlated")
            if (
                evidence.kind is OutcomeEvidenceKind.SEMANTIC_VERIFIER_RESULT
                and event.verifier_result != evidence.verifier_result
            ):
                raise InvalidOutcomeEvidence("verifier result does not match durable trace evidence")
        if evidence.observation_ref is not None:
            if evidence.observation_ref.session_id not in (None, record.session_id):
                raise InvalidOutcomeEvidence("observation evidence session does not match")
            if (
                evidence.freshness is not EvidenceFreshness.PRE_ATTEMPT
                and (
                    evidence.observation_ref.observed_at_ms is None
                    or evidence.observation_ref.observed_at_ms <= dispatch_receipt.ended_at_ms
                )
            ):
                raise InvalidOutcomeEvidence("post-attempt observation is not newer than dispatch evidence")
        if evidence.kind is OutcomeEvidenceKind.FRESH_OBSERVATION and evidence.observation_ref is None:
            raise InvalidOutcomeEvidence("fresh-observation evidence requires ObservationRef")
        if evidence.kind is OutcomeEvidenceKind.DISPATCH_RECEIPT and evidence.receipt_ref is None:
            raise InvalidOutcomeEvidence("dispatch evidence requires a durable receipt reference")
        if (
            evidence.kind is OutcomeEvidenceKind.SEMANTIC_VERIFIER_RESULT
            and evidence.trace_event_ref is None
        ):
            raise InvalidOutcomeEvidence("semantic result requires a durable verifier trace")
        lookup_kinds = {
            OutcomeEvidenceKind.PROVIDER_CORRELATION,
            OutcomeEvidenceKind.IDEMPOTENCY_LOOKUP,
            OutcomeEvidenceKind.EXTERNAL_RESOURCE_LOOKUP,
        }
        if (
            evidence.kind in lookup_kinds
            and evidence.strength is EvidenceStrength.AUTHORITATIVE
            and evidence.artifact_ref is None
        ):
            raise InvalidOutcomeEvidence("authoritative lookup evidence requires a durable artifact reference")

    def _persist_case(self, record: UncertainOutcomeRecord, event_name: str) -> None:
        descriptor = record.to_artifact_descriptor()
        event = TraceEvent(
            event_id=f"trace-event.{descriptor.ref.artifact_id}",
            task_id=record.task_id,
            trace_id=record.trace_id,
            event_name=event_name,
            observed_timestamp_ms=record.updated_at_ms,
            step_id=record.step_id,
            execution_id=record.execution_id,
            provider_id=record.provider_id,
            capability_id=record.capability_id,
            receipt_refs=(record.dispatch_receipt_ref,),
            artifact_refs=(descriptor.ref,),
            attributes=(
                ("uncertain_outcome_id", record.uncertain_outcome_id),
                ("reconciliation_state", record.state.value),
                ("case_revision", str(record.revision)),
            ),
        )
        self.store.record_artifact_and_trace(descriptor, event)

    def _persist_evidence(
        self,
        descriptor: ArtifactDescriptor,
        record: UncertainOutcomeRecord,
        event_name: str,
    ) -> None:
        event = TraceEvent(
            event_id=f"trace-event.{descriptor.ref.artifact_id}",
            task_id=record.task_id,
            trace_id=record.trace_id,
            event_name=event_name,
            observed_timestamp_ms=descriptor.created_at_ms,
            step_id=record.step_id,
            execution_id=record.execution_id,
            provider_id=record.provider_id,
            capability_id=record.capability_id,
            receipt_refs=(record.dispatch_receipt_ref,),
            artifact_refs=(descriptor.ref,),
            observation_refs=(descriptor.observation_ref,) if descriptor.observation_ref else (),
            attributes=(("uncertain_outcome_id", record.uncertain_outcome_id),),
        )
        self.store.record_artifact_and_trace(descriptor, event)

    def _persist_assessment(
        self,
        assessment: OutcomeReconciliationAssessment,
        session_id: str,
    ) -> None:
        descriptor = assessment.to_artifact_descriptor(session_id)
        event = TraceEvent(
            event_id=f"trace-event.{descriptor.ref.artifact_id}",
            task_id=assessment.task_id,
            trace_id=assessment.trace_id,
            event_name="reconciliation.assessed",
            observed_timestamp_ms=assessment.created_at_ms,
            artifact_refs=(descriptor.ref,),
            attributes=(
                ("uncertain_outcome_id", assessment.uncertain_outcome_id),
                ("disposition", assessment.disposition.value),
                ("recommended_task_state", assessment.recommended_task_state.value),
            ),
        )
        self.store.record_artifact_and_trace(descriptor, event)


__all__ = [
    "MAX_PROBE_ATTEMPTS",
    "EvidenceCommitDisposition",
    "EvidenceCommitResult",
    "EvidenceFreshness",
    "EvidenceStrength",
    "IdempotencyKeyRef",
    "IdempotencyParameterMismatch",
    "IdempotencyPolicyError",
    "IdempotencyProfile",
    "InvalidOutcomeEvidence",
    "MutatingReconciliationProbeForbidden",
    "OutcomeClaim",
    "OutcomeEvidence",
    "OutcomeEvidenceConflict",
    "OutcomeEvidenceKind",
    "OutcomeReconciliationAssessment",
    "OutcomeReconciler",
    "ProbeRunResult",
    "ReconciliationDisposition",
    "ReconciliationProbe",
    "ReconciliationProbePolicyError",
    "ReconciliationState",
    "UncertainOutcomeRecord",
    "UncertaintyCaseNotFound",
    "UncertaintyCause",
    "UncertaintyError",
    "UncertaintyPolicyError",
    "digest_operation_parameters",
]
