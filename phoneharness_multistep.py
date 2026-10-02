#!/usr/bin/env python3
"""Host-only governed multi-step runtime foundation.

This module interprets the frozen S3-M0 structured program contract. It does
not authorize or dispatch mutations itself; mutating calls must pass through
an injected canonical governed execution port for every step.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import hashlib
import re
import threading
import time
from typing import Any, Callable, Mapping, Protocol
import uuid

from phoneharness_checkpoint import (
    CheckpointBoundary,
    CheckpointError,
    CheckpointManager,
    CheckpointRef,
    ResumeAssessment,
    ResumeDisposition,
)
from phoneharness_contracts import (
    ArtifactDescriptor,
    ArtifactLifetime,
    ArtifactRef,
    ObservationFreshness,
    ObservationRef,
    SemanticProgramNode,
    SemanticProgramNodeType,
    SemanticTaskProgram,
    SensitivityClass,
)
from phoneharness_retry import LoopAssessment
from phoneharness_runtime import RuntimeInstanceRef
from phoneharness_store import PhoneHarnessStore, StoreConflictError, TraceEvent


PROGRAM_EXECUTION_REF_SCHEMA = "phoneharness.program-execution-ref.v1"
STEP_EXECUTION_REF_SCHEMA = "phoneharness.step-execution-ref.v1"
PROGRAM_EXECUTION_RECORD_SCHEMA = "phoneharness.program-execution-record.v1"
STEP_EXECUTION_RECORD_SCHEMA = "phoneharness.step-execution-record.v1"
PROGRAM_CONTRACT_VERSION = "phoneharness.governed-multistep.v1"
MAX_PROGRAM_STEPS = 512
MAX_VARIABLES = 32
MAX_EVIDENCE_REFS = 12
MAX_PERSISTED_REFERENCE_TEXT = 512

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_VARIABLE_WORDS = frozenset(
    {"password", "passcode", "otp", "privatekey", "secret", "token", "chainofthought"}
)
_SAFE_VALUE_PREFIXES = (
    "artifact.",
    "observation.",
    "result.",
    "value.",
    "credential-handle.",
    "bool.",
    "number.",
)


class MultiStepError(RuntimeError):
    """Base class for deterministic M9 failures."""


class ProgramPolicyError(MultiStepError):
    """Program input or interpreter policy is invalid."""


class ProgramVersionError(MultiStepError):
    """A durable execution is incompatible with the current program."""


class ProgramStateConflict(MultiStepError):
    """A durable program/step identity or revision conflicted."""


class UnsupportedProgramOperation(MultiStepError):
    """A node, operator, skill, or route is not registered."""


class ProgramExecutionState(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    BLOCKED = "BLOCKED"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"
    REPLAN_REQUIRED = "REPLAN_REQUIRED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class StepExecutionState(str, Enum):
    ACCEPTED = "ACCEPTED"
    DISPATCHED = "DISPATCHED"
    EFFECT_OBSERVED = "EFFECT_OBSERVED"
    VERIFIED = "VERIFIED"
    SUCCEEDED = "SUCCEEDED"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    BLOCKED = "BLOCKED"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"
    FAILED = "FAILED"


class GovernedOutcomeState(str, Enum):
    VERIFIED = "VERIFIED"
    DISPATCHED = "DISPATCHED"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"
    RETRY_CONSIDERATION = "RETRY_CONSIDERATION"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class RecoveryRoute(str, Enum):
    M4_RECONCILIATION = "M4_RECONCILIATION"
    M5_RETRY = "M5_RETRY"
    M6_FALLBACK = "M6_FALLBACK"
    M7_INTERVENTION = "M7_INTERVENTION"
    M8_CHECKPOINT_RESUME = "M8_CHECKPOINT_RESUME"
    FAIL_SAFE = "FAIL_SAFE"


class _Signal(str, Enum):
    CONTINUE = "CONTINUE"
    RETURN = "RETURN"
    HALT = "HALT"


def _identifier(value: Any, name: str) -> str:
    normalized = str(value or "").strip()
    if _IDENTIFIER.fullmatch(normalized) is None:
        raise ProgramPolicyError(f"{name} must be an opaque bounded identifier")
    return normalized


def _optional_identifier(value: Any, name: str) -> str | None:
    return None if value is None else _identifier(value, name)


def _timestamp(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProgramPolicyError(f"{name} must be a non-negative integer")
    return value


def _bounded_int(value: Any, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ProgramPolicyError(f"{name} is outside its bounded range")
    return value


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _new_identifier(prefix: str) -> str:
    return f"{prefix}.{uuid.uuid4().hex}"


def _program_digest(program: SemanticTaskProgram) -> str:
    return hashlib.sha256(program.to_json().encode("utf-8")).hexdigest()


def _safe_value_ref(value: Any, name: str) -> str:
    normalized = _identifier(value, name)
    compact = normalized.casefold().replace("-", "").replace("_", "").replace(".", "")
    if any(word in compact for word in _FORBIDDEN_VARIABLE_WORDS):
        raise ProgramPolicyError(f"{name} cannot contain plaintext secret material")
    if not normalized.startswith(_SAFE_VALUE_PREFIXES):
        raise ProgramPolicyError(f"{name} must be a typed safe reference")
    return normalized


def _join(values: tuple[str, ...]) -> str:
    return "EMPTY" if not values else "|".join(values)


@dataclass(frozen=True)
class ProgramExecutionRef:
    program_execution_id: str
    task_id: str
    session_id: str
    program_id: str
    program_digest: str
    schema_version: str = PROGRAM_EXECUTION_REF_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != PROGRAM_EXECUTION_REF_SCHEMA:
            raise ProgramPolicyError("unsupported ProgramExecutionRef schema")
        for name in ("program_execution_id", "task_id", "session_id", "program_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        if _DIGEST.fullmatch(self.program_digest) is None:
            raise ProgramPolicyError("program_digest must be SHA-256")

    def audit(self) -> dict[str, Any]:
        return {"program_execution_id": self.program_execution_id, "authority": False}


@dataclass(frozen=True)
class StepExecutionRef:
    step_execution_id: str
    program_execution_id: str
    node_id: str
    ordinal: int
    schema_version: str = STEP_EXECUTION_REF_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != STEP_EXECUTION_REF_SCHEMA:
            raise ProgramPolicyError("unsupported StepExecutionRef schema")
        for name in ("step_execution_id", "program_execution_id", "node_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        _bounded_int(self.ordinal, "ordinal", 1, MAX_PROGRAM_STEPS)

    def audit(self) -> dict[str, Any]:
        return {"step_execution_id": self.step_execution_id, "authority": False}


@dataclass(frozen=True)
class CapabilityProfile:
    capability_id: str
    operation: str
    registered: bool
    mutation_capable: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "capability_id", _identifier(self.capability_id, "capability_id"))
        object.__setattr__(self, "operation", _identifier(self.operation, "operation"))
        if not isinstance(self.registered, bool) or not isinstance(self.mutation_capable, bool):
            raise ProgramPolicyError("capability profile flags must be boolean")


@dataclass(frozen=True)
class GovernedStepRequest:
    program_execution_ref: ProgramExecutionRef
    step_execution_ref: StepExecutionRef
    capability_id: str
    operation: str
    arguments: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.program_execution_ref, ProgramExecutionRef):
            raise ProgramPolicyError("governed call requires ProgramExecutionRef")
        if not isinstance(self.step_execution_ref, StepExecutionRef):
            raise ProgramPolicyError("governed call requires StepExecutionRef")
        object.__setattr__(self, "capability_id", _identifier(self.capability_id, "capability_id"))
        object.__setattr__(self, "operation", _identifier(self.operation, "operation"))
        object.__setattr__(
            self,
            "arguments",
            tuple((_identifier(key, "argument_name"), _safe_value_ref(value, "argument_ref")) for key, value in self.arguments),
        )


@dataclass(frozen=True)
class GovernedStepOutcome:
    state: GovernedOutcomeState
    executor_succeeded: bool
    verifier_passed: bool
    evidence_refs: tuple[str, ...] = ()
    observation_ref: ObservationRef | None = None
    receipt_ref: str | None = None
    verifier_evidence_ref: str | None = None
    ledger_evidence_ref: str | None = None
    binding_consumption_ref: str | None = None
    executor_consumption_ref: str | None = None
    failure_code: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", GovernedOutcomeState(self.state))
        if not isinstance(self.executor_succeeded, bool) or not isinstance(self.verifier_passed, bool):
            raise ProgramPolicyError("governed outcome flags must be boolean")
        refs = tuple(_identifier(value, "evidence_ref") for value in self.evidence_refs)
        if len(refs) > MAX_EVIDENCE_REFS or len(refs) != len(set(refs)):
            raise ProgramPolicyError("governed evidence refs must be bounded and unique")
        object.__setattr__(self, "evidence_refs", refs)
        for name in (
            "receipt_ref",
            "verifier_evidence_ref",
            "ledger_evidence_ref",
            "binding_consumption_ref",
            "executor_consumption_ref",
            "failure_code",
        ):
            object.__setattr__(self, name, _optional_identifier(getattr(self, name), name))
        if self.observation_ref is not None and not isinstance(self.observation_ref, ObservationRef):
            raise ProgramPolicyError("governed observation must use ObservationRef")


@dataclass(frozen=True)
class BranchDecision:
    value: bool
    trusted: bool
    evidence_ref: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, bool) or not isinstance(self.trusted, bool):
            raise ProgramPolicyError("branch decision flags must be boolean")
        object.__setattr__(self, "evidence_ref", _identifier(self.evidence_ref, "evidence_ref"))


@dataclass(frozen=True)
class WaitAssessment:
    ready: bool
    evidence_ref: str
    route: RecoveryRoute = RecoveryRoute.M7_INTERVENTION

    def __post_init__(self) -> None:
        if not isinstance(self.ready, bool):
            raise ProgramPolicyError("wait readiness must be boolean")
        object.__setattr__(self, "evidence_ref", _identifier(self.evidence_ref, "evidence_ref"))
        object.__setattr__(self, "route", RecoveryRoute(self.route))


class GovernedStepPort(Protocol):
    def execute(self, request: GovernedStepRequest) -> GovernedStepOutcome: ...


class SkillStepPort(Protocol):
    def is_registered(self, skill_id: str) -> bool: ...

    def execute(self, skill_id: str, request: GovernedStepRequest) -> GovernedStepOutcome: ...


class RecoveryRouter(Protocol):
    def route(self, route: RecoveryRoute, execution_ref: ProgramExecutionRef, node_id: str) -> str: ...


@dataclass(frozen=True)
class StepExecutionRecord:
    ref: StepExecutionRef
    task_id: str
    session_id: str
    node_type: SemanticProgramNodeType
    state: StepExecutionState
    mutation_capable: bool
    semantic_verified: bool
    started_at_ms: int
    ended_at_ms: int
    evidence_refs: tuple[str, ...] = ()
    observation_ref: ObservationRef | None = None
    receipt_ref: str | None = None
    verifier_evidence_ref: str | None = None
    ledger_evidence_ref: str | None = None
    recovery_route: RecoveryRoute | None = None
    failure_code: str | None = None
    binding_consumption_ref: str | None = None
    executor_consumption_ref: str | None = None
    schema_version: str = STEP_EXECUTION_RECORD_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != STEP_EXECUTION_RECORD_SCHEMA:
            raise ProgramPolicyError("unsupported StepExecutionRecord schema")
        if not isinstance(self.ref, StepExecutionRef):
            raise ProgramPolicyError("step record requires StepExecutionRef")
        object.__setattr__(self, "task_id", _identifier(self.task_id, "task_id"))
        object.__setattr__(self, "session_id", _identifier(self.session_id, "session_id"))
        object.__setattr__(self, "node_type", SemanticProgramNodeType(self.node_type))
        object.__setattr__(self, "state", StepExecutionState(self.state))
        if not isinstance(self.mutation_capable, bool) or not isinstance(self.semantic_verified, bool):
            raise ProgramPolicyError("step flags must be boolean")
        _timestamp(self.started_at_ms, "started_at_ms")
        _timestamp(self.ended_at_ms, "ended_at_ms")
        if self.ended_at_ms < self.started_at_ms:
            raise ProgramPolicyError("step ended before it started")
        refs = tuple(_identifier(value, "evidence_ref") for value in self.evidence_refs)
        if len(refs) > MAX_EVIDENCE_REFS or len(refs) != len(set(refs)):
            raise ProgramPolicyError("step evidence refs must be bounded and unique")
        if len(_join(refs)) > MAX_PERSISTED_REFERENCE_TEXT:
            raise ProgramPolicyError("step evidence refs exceed the durable metadata bound")
        object.__setattr__(self, "evidence_refs", refs)
        for name in (
            "receipt_ref",
            "verifier_evidence_ref",
            "ledger_evidence_ref",
            "failure_code",
            "binding_consumption_ref",
            "executor_consumption_ref",
        ):
            object.__setattr__(self, name, _optional_identifier(getattr(self, name), name))
        if self.recovery_route is not None:
            object.__setattr__(self, "recovery_route", RecoveryRoute(self.recovery_route))
        if self.semantic_verified and self.state is not StepExecutionState.VERIFIED:
            raise ProgramPolicyError("semantic verification requires VERIFIED step state")
        if self.mutation_capable and self.state is StepExecutionState.SUCCEEDED:
            raise ProgramPolicyError("mutation cannot bypass semantic VERIFIED state")

    def to_artifact_descriptor(self, trace_id: str) -> ArtifactDescriptor:
        metadata = {
            "step_schema": self.schema_version,
            "program_execution_id": self.ref.program_execution_id,
            "node": f"{self.ref.node_id}|{self.node_type.value}|{self.ref.ordinal}",
            "state": self.state.value,
            "flags": f"{'YES' if self.mutation_capable else 'NO'}|{'YES' if self.semantic_verified else 'NO'}",
            "times": f"{self.started_at_ms}:{self.ended_at_ms}",
            "evidence_refs": _join(self.evidence_refs),
            "effect_refs": "|".join(
                value or "NONE"
                for value in (
                    self.receipt_ref,
                    self.verifier_evidence_ref,
                    self.ledger_evidence_ref,
                )
            ),
            "route_and_failure": f"{self.recovery_route.value if self.recovery_route else 'NONE'}|{self.failure_code or 'NONE'}",
            "governance_consumptions": (
                f"{self.binding_consumption_ref or 'NONE'}|{self.executor_consumption_ref or 'NONE'}"
            ),
            "trace_id": _identifier(trace_id, "trace_id"),
        }
        return ArtifactDescriptor(
            ref=ArtifactRef(f"step-record.{self.ref.step_execution_id}", self.task_id, self.session_id),
            artifact_kind="program.step-record",
            producer="semantic-task-program.runner",
            created_at_ms=self.ended_at_ms,
            sensitivity=SensitivityClass.PRIVATE,
            lifetime=ArtifactLifetime.DURABLE,
            observation_ref=self.observation_ref,
            opaque_locator=self.ref.step_execution_id,
            metadata=tuple(metadata.items()),
        )


@dataclass(frozen=True)
class ProgramExecutionRecord:
    ref: ProgramExecutionRef
    trace_id: str
    runtime_instance_id: str
    state: ProgramExecutionState
    revision: int
    created_at_ms: int
    updated_at_ms: int
    current_node_id: str | None = None
    last_step_ref: str | None = None
    checkpoint_ref: CheckpointRef | None = None
    result_ref: str | None = None
    recovery_route: RecoveryRoute | None = None
    variable_refs: tuple[tuple[str, str], ...] = ()
    contract_version: str = PROGRAM_CONTRACT_VERSION
    schema_version: str = PROGRAM_EXECUTION_RECORD_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != PROGRAM_EXECUTION_RECORD_SCHEMA:
            raise ProgramPolicyError("unsupported ProgramExecutionRecord schema")
        if self.contract_version != PROGRAM_CONTRACT_VERSION:
            raise ProgramVersionError("unsupported governed multi-step contract")
        if not isinstance(self.ref, ProgramExecutionRef):
            raise ProgramPolicyError("program record requires ProgramExecutionRef")
        for name in ("trace_id", "runtime_instance_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        for name in ("current_node_id", "last_step_ref", "result_ref"):
            object.__setattr__(self, name, _optional_identifier(getattr(self, name), name))
        object.__setattr__(self, "state", ProgramExecutionState(self.state))
        if self.recovery_route is not None:
            object.__setattr__(self, "recovery_route", RecoveryRoute(self.recovery_route))
        _bounded_int(self.revision, "revision", 1, MAX_PROGRAM_STEPS + 16)
        _timestamp(self.created_at_ms, "created_at_ms")
        _timestamp(self.updated_at_ms, "updated_at_ms")
        if self.updated_at_ms < self.created_at_ms:
            raise ProgramPolicyError("program update precedes creation")
        variables = tuple(
            (_identifier(name, "variable_name"), _safe_value_ref(value, "variable_ref"))
            for name, value in self.variable_refs
        )
        if len(variables) > MAX_VARIABLES or len({name for name, _ in variables}) != len(variables):
            raise ProgramPolicyError("program variables must be bounded and unique")
        encoded_variables = "EMPTY" if not variables else "|".join(f"{key}={value}" for key, value in variables)
        if len(encoded_variables) > MAX_PERSISTED_REFERENCE_TEXT:
            raise ProgramPolicyError("program variables exceed the durable metadata bound")
        object.__setattr__(self, "variable_refs", tuple(sorted(variables)))

    def audit(self) -> dict[str, Any]:
        return {
            "program_execution_id": self.ref.program_execution_id,
            "state": self.state.value,
            "authority": False,
            "dispatch": False,
            "semantic_success": self.state is ProgramExecutionState.SUCCEEDED,
        }

    def to_artifact_descriptor(self) -> ArtifactDescriptor:
        variables = "EMPTY" if not self.variable_refs else "|".join(f"{key}={value}" for key, value in self.variable_refs)
        metadata = {
            "record_schema": self.schema_version,
            "contract_version": self.contract_version,
            "program_identity": f"{self.ref.program_id}|{self.ref.program_digest}",
            "trace_runtime": f"{self.trace_id}|{self.runtime_instance_id}",
            "state_revision": f"{self.state.value}|{self.revision}",
            "times": f"{self.created_at_ms}:{self.updated_at_ms}",
            "current_node_id": self.current_node_id or "NONE",
            "last_step_ref": self.last_step_ref or "NONE",
            "checkpoint_ref": self.checkpoint_ref.checkpoint_id if self.checkpoint_ref else "NONE",
            "checkpoint_sequence": str(self.checkpoint_ref.sequence) if self.checkpoint_ref else "NONE",
            "result_ref": self.result_ref or "NONE",
            "recovery_route": self.recovery_route.value if self.recovery_route else "NONE",
            "variable_refs": variables,
        }
        return ArtifactDescriptor(
            ref=ArtifactRef(
                f"program-record.{self.ref.program_execution_id}.r{self.revision:06d}",
                self.ref.task_id,
                self.ref.session_id,
            ),
            artifact_kind="program.execution-record",
            producer="semantic-task-program.runner",
            created_at_ms=self.updated_at_ms,
            sensitivity=SensitivityClass.PRIVATE,
            lifetime=ArtifactLifetime.DURABLE,
            opaque_locator=self.ref.program_execution_id,
            metadata=tuple(metadata.items()),
        )


@dataclass(frozen=True)
class StepExecutionAssessment:
    record: StepExecutionRecord
    program_state: ProgramExecutionState
    authority: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.record, StepExecutionRecord):
            raise ProgramPolicyError("step assessment requires StepExecutionRecord")
        object.__setattr__(self, "program_state", ProgramExecutionState(self.program_state))
        if self.authority:
            raise ProgramPolicyError("step assessment cannot authorize")


@dataclass(frozen=True)
class ProgramExecutionAssessment:
    record: ProgramExecutionRecord
    steps: tuple[StepExecutionRecord, ...]
    authority: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.record, ProgramExecutionRecord):
            raise ProgramPolicyError("program assessment requires ProgramExecutionRecord")
        if any(not isinstance(step, StepExecutionRecord) for step in self.steps):
            raise ProgramPolicyError("program assessment steps must be typed")
        if self.authority:
            raise ProgramPolicyError("program assessment cannot authorize")


@dataclass
class _Context:
    record: ProgramExecutionRecord
    variables: dict[str, str]
    steps: list[StepExecutionRecord]
    last_step: StepExecutionRecord | None
    ordinal: int
    returned: bool = False


@dataclass(frozen=True)
class _NodeResult:
    signal: _Signal
    program_state: ProgramExecutionState = ProgramExecutionState.RUNNING
    result_ref: str | None = None
    recovery_route: RecoveryRoute | None = None


class SemanticTaskProgramRunner:
    """Deterministic bounded interpreter over the frozen S3-M0 node schema."""

    _RECOVERY_POLICIES = {
        "reconcile": RecoveryRoute.M4_RECONCILIATION,
        "retry": RecoveryRoute.M5_RETRY,
        "fallback": RecoveryRoute.M6_FALLBACK,
        "replan": RecoveryRoute.M7_INTERVENTION,
        "wait_for_user": RecoveryRoute.M7_INTERVENTION,
        "checkpoint_resume": RecoveryRoute.M8_CHECKPOINT_RESUME,
        "fail_safe": RecoveryRoute.FAIL_SAFE,
    }

    def __init__(
        self,
        store: PhoneHarnessStore,
        runtime_ref: RuntimeInstanceRef,
        *,
        governed_port: GovernedStepPort,
        capability_resolver: Callable[[str, str], CapabilityProfile],
        condition_resolver: Callable[[str, Mapping[str, str]], BranchDecision],
        collection_resolver: Callable[[str, Mapping[str, str]], tuple[str, ...]],
        recovery_router: RecoveryRouter,
        checkpoint_manager: CheckpointManager | None = None,
        skill_port: SkillStepPort | None = None,
        wait_resolver: Callable[[str, Mapping[str, str]], WaitAssessment] | None = None,
        verifier: Callable[[str, StepExecutionRecord | None], tuple[bool, str]] | None = None,
        loop_assessor: Callable[[str, int], LoopAssessment] | None = None,
        now_ms: Callable[[], int] = _now_ms,
        id_factory: Callable[[str], str] = _new_identifier,
    ) -> None:
        if not isinstance(store, PhoneHarnessStore) or not isinstance(runtime_ref, RuntimeInstanceRef):
            raise ProgramPolicyError("runner requires typed Store and Runtime identity")
        for value, name in (
            (governed_port, "governed_port"),
            (capability_resolver, "capability_resolver"),
            (condition_resolver, "condition_resolver"),
            (collection_resolver, "collection_resolver"),
            (recovery_router, "recovery_router"),
        ):
            if value is None:
                raise ProgramPolicyError(f"runner requires {name}")
        self.store = store
        self.runtime_ref = runtime_ref
        self.governed_port = governed_port
        self.capability_resolver = capability_resolver
        self.condition_resolver = condition_resolver
        self.collection_resolver = collection_resolver
        self.recovery_router = recovery_router
        self.checkpoint_manager = checkpoint_manager
        self.skill_port = skill_port
        self.wait_resolver = wait_resolver
        self.verifier = verifier
        self.loop_assessor = loop_assessor
        self._now_ms = now_ms
        self._id_factory = id_factory
        self._binding_consumptions: set[str] = set()
        self._executor_consumptions: set[str] = set()
        self._mutex = threading.RLock()
        if checkpoint_manager is not None and checkpoint_manager.runtime_ref != runtime_ref:
            raise ProgramPolicyError("checkpoint manager must share the current Runtime identity")

    def start(
        self,
        program: SemanticTaskProgram,
        *,
        session_id: str,
        trace_id: str,
    ) -> ProgramExecutionAssessment:
        if not isinstance(program, SemanticTaskProgram):
            raise ProgramPolicyError("runner requires SemanticTaskProgram")
        session = _identifier(session_id, "session_id")
        trace = _identifier(trace_id, "trace_id")
        now = self._now_ms()
        ref = ProgramExecutionRef(
            self._id_factory("program-execution"),
            program.task_id,
            session,
            program.program_id,
            _program_digest(program),
        )
        record = ProgramExecutionRecord(
            ref,
            trace,
            self.runtime_ref.runtime_instance_id,
            ProgramExecutionState.PENDING,
            1,
            now,
            now,
        )
        with self._mutex:
            self._persist_program(record, "program_execution_created")
            record = self._update_program(record, state=ProgramExecutionState.RUNNING)
            context = _Context(record, {}, [], None, 0)
            result = self._execute_node(program.root, context)
            return self._finalize(program, context, result)

    def resume(
        self,
        program: SemanticTaskProgram,
        prior_record: ProgramExecutionRecord,
        resume_assessment: ResumeAssessment,
    ) -> ProgramExecutionAssessment:
        if not isinstance(program, SemanticTaskProgram) or not isinstance(prior_record, ProgramExecutionRecord):
            raise ProgramPolicyError("resume requires typed program and execution record")
        if not isinstance(resume_assessment, ResumeAssessment):
            raise ProgramPolicyError("resume requires M8 ResumeAssessment")
        with self._mutex:
            current = self.load(prior_record.ref)
            if current != prior_record:
                raise ProgramStateConflict("resume record is not current")
            if current.ref.program_digest != _program_digest(program) or current.ref.program_id != program.program_id:
                raise ProgramVersionError("program definition changed since checkpoint")
            if current.runtime_instance_id == self.runtime_ref.runtime_instance_id:
                raise ProgramPolicyError("resume requires a new Runtime instance")
            if (
                resume_assessment.disposition is not ResumeDisposition.CONTINUE_AFTER_CHECKPOINT
                or resume_assessment.continuation_ref is None
                or current.checkpoint_ref is None
                or resume_assessment.checkpoint_ref != current.checkpoint_ref
                or resume_assessment.runtime_instance_id != self.runtime_ref.runtime_instance_id
            ):
                raise ProgramPolicyError("resume assessment does not authorize logical continuation")
            root = program.root
            if root.node_type is not SemanticProgramNodeType.SEQUENCE:
                raise ProgramPolicyError("M9-A resume continuation requires top-level sequence")
            index = next(
                (position for position, child in enumerate(root.children) if child.node_id == resume_assessment.continuation_ref),
                None,
            )
            if index is None:
                raise ProgramPolicyError("resume continuation is not a top-level program node")
            record = self._update_program(
                current,
                state=ProgramExecutionState.RUNNING,
                runtime_instance_id=self.runtime_ref.runtime_instance_id,
                current_node_id=resume_assessment.continuation_ref,
            )
            prior_step_count = self._restore_governance_consumptions(current.ref)
            context = _Context(record, dict(record.variable_refs), [], None, prior_step_count)
            result = self._execute_sequence(root.children[index:], context)
            return self._finalize(program, context, result)

    def load(self, ref: ProgramExecutionRef) -> ProgramExecutionRecord:
        records = self._program_records(ref)
        if not records:
            raise ProgramStateConflict("program execution record is unavailable")
        return max(records, key=lambda item: item.revision)

    def _execute_node(self, node: SemanticProgramNode, context: _Context) -> _NodeResult:
        if context.ordinal >= MAX_PROGRAM_STEPS:
            return _NodeResult(_Signal.HALT, ProgramExecutionState.BLOCKED, recovery_route=RecoveryRoute.FAIL_SAFE)
        if node.node_type is SemanticProgramNodeType.SEQUENCE:
            return self._execute_sequence(node.children, context)
        if node.node_type is SemanticProgramNodeType.IF:
            return self._execute_if(node, context)
        if node.node_type is SemanticProgramNodeType.FOR_EACH:
            return self._execute_for_each(node, context)
        if node.node_type is SemanticProgramNodeType.BOUNDED_WHILE:
            return self._execute_while(node, context)
        return self._execute_leaf(node, context)

    def _execute_sequence(self, nodes: tuple[SemanticProgramNode, ...], context: _Context) -> _NodeResult:
        for node in nodes:
            result = self._execute_node(node, context)
            if result.signal is not _Signal.CONTINUE:
                return result
        return _NodeResult(_Signal.CONTINUE)

    def _execute_if(self, node: SemanticProgramNode, context: _Context) -> _NodeResult:
        decision = self.condition_resolver(dict(node.arguments)["condition_ref"], dict(context.variables))
        if not isinstance(decision, BranchDecision) or not decision.trusted:
            self._record_structural_step(node, context, StepExecutionState.BLOCKED, (getattr(decision, "evidence_ref", "evidence.untrusted"),), "UNTRUSTED_BRANCH_INPUT")
            return _NodeResult(_Signal.HALT, ProgramExecutionState.BLOCKED, recovery_route=RecoveryRoute.FAIL_SAFE)
        self._record_structural_step(node, context, StepExecutionState.SUCCEEDED, (decision.evidence_ref,))
        if decision.value:
            return self._execute_node(node.children[0], context)
        if len(node.children) == 2:
            return self._execute_node(node.children[1], context)
        return _NodeResult(_Signal.CONTINUE)

    def _execute_for_each(self, node: SemanticProgramNode, context: _Context) -> _NodeResult:
        args = dict(node.arguments)
        items = self.collection_resolver(args["collection_ref"], dict(context.variables))
        if not isinstance(items, tuple):
            self._record_structural_step(node, context, StepExecutionState.BLOCKED, (), "FOR_EACH_COLLECTION_NOT_BOUNDED")
            return _NodeResult(_Signal.HALT, ProgramExecutionState.BLOCKED, recovery_route=RecoveryRoute.FAIL_SAFE)
        if len(items) > (node.maximum_iterations or 0):
            self._record_structural_step(node, context, StepExecutionState.BLOCKED, (), "FOR_EACH_BOUND_EXCEEDED")
            return _NodeResult(_Signal.HALT, ProgramExecutionState.BLOCKED, recovery_route=RecoveryRoute.FAIL_SAFE)
        for item in items:
            context.variables[args["variable_name"]] = _safe_value_ref(item, "collection_item_ref")
            result = self._execute_node(node.children[0], context)
            if result.signal is not _Signal.CONTINUE:
                return result
        self._record_structural_step(node, context, StepExecutionState.SUCCEEDED)
        return _NodeResult(_Signal.CONTINUE)

    def _execute_while(self, node: SemanticProgramNode, context: _Context) -> _NodeResult:
        if self.loop_assessor is None:
            return self._route(
                node,
                context,
                RecoveryRoute.M5_RETRY,
                ProgramExecutionState.BLOCKED,
                failure_code="LOOP_ASSESSOR_UNAVAILABLE",
            )
        condition_ref = dict(node.arguments)["condition_ref"]
        for iteration in range(node.maximum_iterations or 0):
            loop = self.loop_assessor(node.node_id, iteration)
            if not isinstance(loop, LoopAssessment) or loop.hard_stop:
                return self._route(
                    node,
                    context,
                    RecoveryRoute.M5_RETRY,
                    ProgramExecutionState.REPLAN_REQUIRED,
                    failure_code="M5_LOOP_STOP",
                )
            decision = self.condition_resolver(condition_ref, dict(context.variables))
            if not isinstance(decision, BranchDecision) or not decision.trusted:
                self._record_structural_step(node, context, StepExecutionState.BLOCKED, (), "UNTRUSTED_LOOP_CONDITION")
                return _NodeResult(_Signal.HALT, ProgramExecutionState.BLOCKED, recovery_route=RecoveryRoute.FAIL_SAFE)
            if not decision.value:
                self._record_structural_step(node, context, StepExecutionState.SUCCEEDED, (decision.evidence_ref,))
                return _NodeResult(_Signal.CONTINUE)
            result = self._execute_node(node.children[0], context)
            if result.signal is not _Signal.CONTINUE:
                return result
        return self._route(
            node,
            context,
            RecoveryRoute.M5_RETRY,
            ProgramExecutionState.REPLAN_REQUIRED,
            failure_code="WHILE_MAX_ITERATIONS",
        )

    def _execute_leaf(self, node: SemanticProgramNode, context: _Context) -> _NodeResult:
        if node.node_type is SemanticProgramNodeType.VARIABLE:
            args = dict(node.arguments)
            context.variables[_identifier(args["variable_name"], "variable_name")] = _safe_value_ref(args["value_ref"], "value_ref")
            self._record_structural_step(node, context, StepExecutionState.SUCCEEDED)
            return _NodeResult(_Signal.CONTINUE)
        if node.node_type is SemanticProgramNodeType.CALL_TOOL:
            return self._execute_call(node, context, skill_id=None)
        if node.node_type is SemanticProgramNodeType.CALL_SKILL:
            skill_id = dict(node.arguments)["skill_id"]
            if self.skill_port is None or not self.skill_port.is_registered(skill_id):
                self._record_structural_step(node, context, StepExecutionState.BLOCKED, (), "SKILL_NOT_REGISTERED")
                return _NodeResult(_Signal.HALT, ProgramExecutionState.BLOCKED, recovery_route=RecoveryRoute.FAIL_SAFE)
            return self._execute_call(node, context, skill_id=skill_id)
        if node.node_type is SemanticProgramNodeType.VERIFY:
            return self._execute_verify(node, context)
        if node.node_type is SemanticProgramNodeType.WAIT_FOR:
            return self._execute_wait(node, context)
        if node.node_type is SemanticProgramNodeType.CHECKPOINT:
            return self._execute_checkpoint(node, context)
        if node.node_type is SemanticProgramNodeType.RECOVER:
            policy = dict(node.arguments)["recovery_policy"]
            route = self._RECOVERY_POLICIES.get(policy)
            if route is None:
                self._record_structural_step(node, context, StepExecutionState.BLOCKED, (), "RECOVERY_POLICY_NOT_REGISTERED")
                return _NodeResult(_Signal.HALT, ProgramExecutionState.BLOCKED, recovery_route=RecoveryRoute.FAIL_SAFE)
            state = ProgramExecutionState.WAITING_FOR_USER if route is RecoveryRoute.M7_INTERVENTION else ProgramExecutionState.REPLAN_REQUIRED
            return self._route(node, context, route, state)
        if node.node_type is SemanticProgramNodeType.RETURN:
            result_ref = self._resolve_value_ref(dict(node.arguments)["result_ref"], context.variables)
            self._record_structural_step(node, context, StepExecutionState.SUCCEEDED, (result_ref,))
            context.returned = True
            return _NodeResult(_Signal.RETURN, ProgramExecutionState.SUCCEEDED, result_ref=result_ref)
        raise UnsupportedProgramOperation("semantic node is not supported by the frozen S3-M0 contract")

    def _execute_call(self, node: SemanticProgramNode, context: _Context, *, skill_id: str | None) -> _NodeResult:
        args = dict(node.arguments)
        capability_id = args.get("capability_id", f"skill.{skill_id}")
        operation = args.get("operation", "registered.invoke")
        profile = self.capability_resolver(capability_id, operation)
        if not isinstance(profile, CapabilityProfile) or not profile.registered:
            self._record_structural_step(node, context, StepExecutionState.BLOCKED, (), "CAPABILITY_NOT_REGISTERED")
            return _NodeResult(_Signal.HALT, ProgramExecutionState.BLOCKED, recovery_route=RecoveryRoute.FAIL_SAFE)
        step_ref = self._next_step_ref(node, context)
        call_arguments = tuple(
            (key, self._resolve_value_ref(value, context.variables))
            for key, value in node.arguments
            if key not in {"capability_id", "operation", "skill_id"}
        )
        request = GovernedStepRequest(context.record.ref, step_ref, capability_id, operation, call_arguments)
        started = self._now_ms()
        outcome = self.skill_port.execute(skill_id, request) if skill_id is not None else self.governed_port.execute(request)
        if not isinstance(outcome, GovernedStepOutcome):
            raise ProgramPolicyError("governed execution port returned an untyped outcome")
        return self._apply_governed_outcome(node, context, step_ref, profile, outcome, started)

    def _apply_governed_outcome(
        self,
        node: SemanticProgramNode,
        context: _Context,
        step_ref: StepExecutionRef,
        profile: CapabilityProfile,
        outcome: GovernedStepOutcome,
        started: int,
    ) -> _NodeResult:
        observation_scoped = (
            outcome.observation_ref is None
            or (
                outcome.observation_ref.task_id == context.record.ref.task_id
                and outcome.observation_ref.session_id in (None, context.record.ref.session_id)
            )
        )
        safe_observation = outcome.observation_ref if observation_scoped else None
        if profile.mutation_capable:
            dispatch_possible = outcome.executor_succeeded or outcome.state in {
                GovernedOutcomeState.VERIFIED,
                GovernedOutcomeState.DISPATCHED,
                GovernedOutcomeState.UNKNOWN_OUTCOME,
            }
            consumption_complete = bool(outcome.binding_consumption_ref and outcome.executor_consumption_ref)
            consumption_partial = bool(outcome.binding_consumption_ref) != bool(outcome.executor_consumption_ref)
            if consumption_partial or (dispatch_possible and not consumption_complete):
                return self._governance_failure(node, context, step_ref, profile, started, "GOVERNANCE_EVIDENCE_MISSING")
            if consumption_complete:
                if (
                    outcome.binding_consumption_ref in self._binding_consumptions
                    or outcome.executor_consumption_ref in self._executor_consumptions
                ):
                    return self._governance_failure(node, context, step_ref, profile, started, "CROSS_STEP_AUTHORITY_REUSE")
                self._binding_consumptions.add(outcome.binding_consumption_ref)
                self._executor_consumptions.add(outcome.executor_consumption_ref)
        route = self._route_for_outcome(outcome.state)
        if route is not None:
            state = {
                RecoveryRoute.M4_RECONCILIATION: ProgramExecutionState.UNKNOWN_OUTCOME,
                RecoveryRoute.M7_INTERVENTION: ProgramExecutionState.WAITING_FOR_USER,
            }.get(route, ProgramExecutionState.REPLAN_REQUIRED)
            step_state = StepExecutionState.UNKNOWN_OUTCOME if route is RecoveryRoute.M4_RECONCILIATION else StepExecutionState.BLOCKED
            self._record_step(
                context,
                StepExecutionRecord(
                    step_ref,
                    context.record.ref.task_id,
                    context.record.ref.session_id,
                    node.node_type,
                    step_state,
                    profile.mutation_capable,
                    False,
                    started,
                    self._now_ms(),
                    outcome.evidence_refs,
                    safe_observation,
                    outcome.receipt_ref,
                    outcome.verifier_evidence_ref,
                    outcome.ledger_evidence_ref,
                    route,
                    outcome.failure_code,
                    outcome.binding_consumption_ref,
                    outcome.executor_consumption_ref,
                ),
            )
            return self._route(node, context, route, state, record_step=False)
        if profile.mutation_capable:
            fresh = (
                observation_scoped
                and outcome.observation_ref is not None
                and outcome.observation_ref.freshness is ObservationFreshness.FRESH
            )
            verified = (
                outcome.state is GovernedOutcomeState.VERIFIED
                and outcome.executor_succeeded
                and outcome.verifier_passed
                and fresh
                and outcome.receipt_ref is not None
                and outcome.verifier_evidence_ref is not None
                and outcome.ledger_evidence_ref is not None
            )
            if not verified:
                state = StepExecutionState.DISPATCHED if outcome.executor_succeeded else StepExecutionState.BLOCKED
                self._record_step(
                    context,
                    StepExecutionRecord(
                        step_ref,
                        context.record.ref.task_id,
                        context.record.ref.session_id,
                        node.node_type,
                        state,
                        True,
                        False,
                        started,
                        self._now_ms(),
                        outcome.evidence_refs,
                        safe_observation,
                        outcome.receipt_ref,
                        outcome.verifier_evidence_ref,
                        outcome.ledger_evidence_ref,
                        RecoveryRoute.FAIL_SAFE,
                        outcome.failure_code
                        or ("OBSERVATION_SCOPE_MISMATCH" if not observation_scoped else "SEMANTIC_VERIFICATION_REQUIRED"),
                        outcome.binding_consumption_ref,
                        outcome.executor_consumption_ref,
                    ),
                )
                return _NodeResult(_Signal.HALT, ProgramExecutionState.BLOCKED, recovery_route=RecoveryRoute.FAIL_SAFE)
            state = StepExecutionState.VERIFIED
        else:
            if (
                outcome.state is not GovernedOutcomeState.VERIFIED
                or not outcome.verifier_passed
                or not observation_scoped
            ):
                state = StepExecutionState.FAILED
                semantic_verified = False
            else:
                state = StepExecutionState.SUCCEEDED
                semantic_verified = False
            if state is StepExecutionState.FAILED:
                self._record_step(
                    context,
                    StepExecutionRecord(
                        step_ref,
                        context.record.ref.task_id,
                        context.record.ref.session_id,
                        node.node_type,
                        state,
                        False,
                        False,
                        started,
                        self._now_ms(),
                        outcome.evidence_refs,
                        safe_observation,
                        outcome.receipt_ref,
                        outcome.verifier_evidence_ref,
                        outcome.ledger_evidence_ref,
                        RecoveryRoute.FAIL_SAFE,
                        outcome.failure_code
                        or ("OBSERVATION_SCOPE_MISMATCH" if not observation_scoped else "READ_ONLY_STEP_FAILED"),
                    ),
                )
                return _NodeResult(_Signal.HALT, ProgramExecutionState.FAILED, recovery_route=RecoveryRoute.FAIL_SAFE)
        semantic_verified = profile.mutation_capable
        self._record_step(
            context,
            StepExecutionRecord(
                step_ref,
                context.record.ref.task_id,
                context.record.ref.session_id,
                node.node_type,
                state,
                profile.mutation_capable,
                semantic_verified,
                started,
                self._now_ms(),
                outcome.evidence_refs,
                safe_observation,
                outcome.receipt_ref,
                outcome.verifier_evidence_ref,
                outcome.ledger_evidence_ref,
                binding_consumption_ref=outcome.binding_consumption_ref,
                executor_consumption_ref=outcome.executor_consumption_ref,
            ),
        )
        return _NodeResult(_Signal.CONTINUE)

    def _governance_failure(
        self,
        node: SemanticProgramNode,
        context: _Context,
        step_ref: StepExecutionRef,
        profile: CapabilityProfile,
        started: int,
        code: str,
    ) -> _NodeResult:
        self._record_step(
            context,
            StepExecutionRecord(
                step_ref,
                context.record.ref.task_id,
                context.record.ref.session_id,
                node.node_type,
                StepExecutionState.BLOCKED,
                profile.mutation_capable,
                False,
                started,
                self._now_ms(),
                recovery_route=RecoveryRoute.FAIL_SAFE,
                failure_code=code,
            ),
        )
        return _NodeResult(_Signal.HALT, ProgramExecutionState.BLOCKED, recovery_route=RecoveryRoute.FAIL_SAFE)

    def _execute_verify(self, node: SemanticProgramNode, context: _Context) -> _NodeResult:
        if self.verifier is None:
            self._record_structural_step(node, context, StepExecutionState.BLOCKED, (), "VERIFIER_UNAVAILABLE")
            return _NodeResult(_Signal.HALT, ProgramExecutionState.BLOCKED, recovery_route=RecoveryRoute.FAIL_SAFE)
        passed, evidence_ref = self.verifier(dict(node.arguments)["verifier_id"], context.last_step)
        evidence = _identifier(evidence_ref, "verifier_evidence_ref")
        self._record_structural_step(
            node,
            context,
            StepExecutionState.SUCCEEDED if passed else StepExecutionState.FAILED,
            (evidence,),
            None if passed else "VERIFICATION_FAILED",
        )
        return _NodeResult(_Signal.CONTINUE) if passed else _NodeResult(_Signal.HALT, ProgramExecutionState.FAILED)

    def _execute_wait(self, node: SemanticProgramNode, context: _Context) -> _NodeResult:
        if self.wait_resolver is None:
            self._record_structural_step(node, context, StepExecutionState.BLOCKED, (), "WAIT_RESOLVER_UNAVAILABLE")
            return _NodeResult(_Signal.HALT, ProgramExecutionState.BLOCKED, recovery_route=RecoveryRoute.FAIL_SAFE)
        wait = self.wait_resolver(dict(node.arguments)["condition_ref"], dict(context.variables))
        if not isinstance(wait, WaitAssessment):
            raise ProgramPolicyError("wait resolver returned an untyped assessment")
        if wait.ready:
            self._record_structural_step(node, context, StepExecutionState.SUCCEEDED, (wait.evidence_ref,))
            return _NodeResult(_Signal.CONTINUE)
        self._record_structural_step(
            node,
            context,
            StepExecutionState.WAITING_FOR_USER,
            (wait.evidence_ref,),
            recovery_route=wait.route,
        )
        return self._route(node, context, wait.route, ProgramExecutionState.WAITING_FOR_USER, record_step=False)

    def _execute_checkpoint(self, node: SemanticProgramNode, context: _Context) -> _NodeResult:
        if self.checkpoint_manager is None:
            self._record_structural_step(
                node,
                context,
                StepExecutionState.BLOCKED,
                (),
                "CHECKPOINT_MANAGER_UNAVAILABLE",
                RecoveryRoute.M8_CHECKPOINT_RESUME,
            )
            return _NodeResult(_Signal.HALT, ProgramExecutionState.BLOCKED, recovery_route=RecoveryRoute.M8_CHECKPOINT_RESUME)
        continuation_ref = _identifier(dict(node.arguments)["artifact_ref"], "continuation_ref")
        last = context.last_step
        boundary = CheckpointBoundary.BEFORE_MUTATION
        values: dict[str, Any] = {}
        if last is not None and last.mutation_capable and last.semantic_verified:
            boundary = CheckpointBoundary.AFTER_VERIFIED_EFFECT
            values = {
                "observation_ref": last.observation_ref,
                "receipt_ref": last.receipt_ref,
                "verifier_evidence_ref": last.verifier_evidence_ref,
                "ledger_evidence_ref": last.ledger_evidence_ref,
            }
        elif last is not None and last.observation_ref is not None:
            boundary = CheckpointBoundary.AFTER_READ_ONLY_STEP
            values = {"observation_ref": last.observation_ref}
        try:
            prepared = self.checkpoint_manager.prepare(
                task_id=context.record.ref.task_id,
                session_id=context.record.ref.session_id,
                trace_id=context.record.trace_id,
                boundary=boundary,
                canonical_state_revision=context.record.revision,
                continuation_ref=continuation_ref,
                step_id=last.ref.node_id if last else None,
                execution_id=last.ref.step_execution_id if last else None,
                requires_fresh_observation=True,
                **values,
            )
            committed = self.checkpoint_manager.commit(prepared)
        except CheckpointError:
            self._record_structural_step(
                node,
                context,
                StepExecutionState.BLOCKED,
                (),
                "CHECKPOINT_COMMIT_FAILED",
                RecoveryRoute.M8_CHECKPOINT_RESUME,
            )
            return _NodeResult(_Signal.HALT, ProgramExecutionState.BLOCKED, recovery_route=RecoveryRoute.M8_CHECKPOINT_RESUME)
        self._record_structural_step(node, context, StepExecutionState.SUCCEEDED, (committed.ref.checkpoint_id,))
        context.record = self._update_program(context.record, checkpoint_ref=committed.ref)
        return _NodeResult(_Signal.CONTINUE)

    def _route(
        self,
        node: SemanticProgramNode,
        context: _Context,
        route: RecoveryRoute,
        state: ProgramExecutionState,
        *,
        record_step: bool = True,
        failure_code: str | None = None,
    ) -> _NodeResult:
        if record_step:
            self._record_structural_step(
                node,
                context,
                StepExecutionState.BLOCKED,
                (),
                failure_code or route.value,
                route,
            )
        route_ref = self.recovery_router.route(route, context.record.ref, node.node_id)
        _identifier(route_ref, "recovery_route_ref")
        return _NodeResult(_Signal.HALT, state, recovery_route=route)

    @staticmethod
    def _route_for_outcome(state: GovernedOutcomeState) -> RecoveryRoute | None:
        return {
            GovernedOutcomeState.UNKNOWN_OUTCOME: RecoveryRoute.M4_RECONCILIATION,
            GovernedOutcomeState.RETRY_CONSIDERATION: RecoveryRoute.M5_RETRY,
            GovernedOutcomeState.PROVIDER_UNAVAILABLE: RecoveryRoute.M6_FALLBACK,
            GovernedOutcomeState.WAITING_FOR_USER: RecoveryRoute.M7_INTERVENTION,
            GovernedOutcomeState.BLOCKED: RecoveryRoute.FAIL_SAFE,
            GovernedOutcomeState.FAILED: RecoveryRoute.FAIL_SAFE,
        }.get(state)

    def _record_structural_step(
        self,
        node: SemanticProgramNode,
        context: _Context,
        state: StepExecutionState,
        evidence_refs: tuple[str, ...] = (),
        failure_code: str | None = None,
        recovery_route: RecoveryRoute | None = None,
    ) -> StepExecutionRecord:
        now = self._now_ms()
        record = StepExecutionRecord(
            self._next_step_ref(node, context),
            context.record.ref.task_id,
            context.record.ref.session_id,
            node.node_type,
            state,
            False,
            False,
            now,
            now,
            evidence_refs,
            recovery_route=(
                recovery_route
                if recovery_route is not None
                else RecoveryRoute.FAIL_SAFE if state in {StepExecutionState.BLOCKED, StepExecutionState.FAILED} else None
            ),
            failure_code=failure_code,
        )
        self._record_step(context, record)
        return record

    def _next_step_ref(self, node: SemanticProgramNode, context: _Context) -> StepExecutionRef:
        context.ordinal += 1
        if context.ordinal > MAX_PROGRAM_STEPS:
            raise ProgramPolicyError("program exceeded bounded step count")
        return StepExecutionRef(
            self._id_factory("step-execution"),
            context.record.ref.program_execution_id,
            node.node_id,
            context.ordinal,
        )

    def _record_step(self, context: _Context, record: StepExecutionRecord) -> None:
        descriptor = record.to_artifact_descriptor(context.record.trace_id)
        event = TraceEvent(
            event_id=f"trace-event.{descriptor.ref.artifact_id}",
            task_id=record.task_id,
            trace_id=context.record.trace_id,
            event_name="program_step_recorded",
            observed_timestamp_ms=record.ended_at_ms,
            step_id=record.ref.node_id,
            execution_id=record.ref.step_execution_id,
            artifact_refs=(descriptor.ref,),
            observation_refs=(() if record.observation_ref is None else (record.observation_ref,)),
            attributes=(
                ("step_state", record.state.value),
                ("semantic_verified", "YES" if record.semantic_verified else "NO"),
                ("policy_class", "NON_AUTHORITATIVE"),
            ),
        )
        try:
            created, _ = self.store.record_artifact_and_trace(descriptor, event)
        except StoreConflictError as exc:
            raise ProgramStateConflict("step evidence identity conflicted") from exc
        if not created:
            raise ProgramStateConflict("step evidence was already recorded")
        context.steps.append(record)
        context.last_step = record
        context.record = self._update_program(
            context.record,
            current_node_id=record.ref.node_id,
            last_step_ref=record.ref.step_execution_id,
            variable_refs=tuple(context.variables.items()),
        )

    def _finalize(
        self,
        program: SemanticTaskProgram,
        context: _Context,
        result: _NodeResult,
    ) -> ProgramExecutionAssessment:
        if result.signal is _Signal.RETURN and context.returned:
            state = ProgramExecutionState.SUCCEEDED
        elif result.signal is _Signal.HALT:
            state = result.program_state
        else:
            state = ProgramExecutionState.FAILED
            result = replace(result, recovery_route=RecoveryRoute.FAIL_SAFE)
        context.record = self._update_program(
            context.record,
            state=state,
            result_ref=result.result_ref,
            recovery_route=result.recovery_route,
            variable_refs=tuple(context.variables.items()),
        )
        return ProgramExecutionAssessment(context.record, tuple(context.steps))

    def _update_program(self, record: ProgramExecutionRecord, **changes: Any) -> ProgramExecutionRecord:
        updated = replace(
            record,
            revision=record.revision + 1,
            updated_at_ms=max(self._now_ms(), record.updated_at_ms + 1),
            **changes,
        )
        self._persist_program(updated, "program_execution_updated")
        return updated

    def _persist_program(self, record: ProgramExecutionRecord, event_name: str) -> None:
        descriptor = record.to_artifact_descriptor()
        event = TraceEvent(
            event_id=f"trace-event.{descriptor.ref.artifact_id}",
            task_id=record.ref.task_id,
            trace_id=record.trace_id,
            event_name=event_name,
            observed_timestamp_ms=record.updated_at_ms,
            artifact_refs=(descriptor.ref,),
            attributes=(
                ("program_state", record.state.value),
                ("policy_class", "NON_AUTHORITATIVE"),
                ("dispatch_effect", "NONE"),
            ),
        )
        try:
            created, _ = self.store.record_artifact_and_trace(descriptor, event)
        except StoreConflictError as exc:
            raise ProgramStateConflict("program record identity conflicted") from exc
        if not created:
            raise ProgramStateConflict("program revision already exists")

    def _program_records(self, ref: ProgramExecutionRef) -> tuple[ProgramExecutionRecord, ...]:
        records: list[ProgramExecutionRecord] = []
        for descriptor in self.store.list_artifacts(ref.task_id, session_id=ref.session_id):
            if descriptor.artifact_kind != "program.execution-record" or descriptor.opaque_locator != ref.program_execution_id:
                continue
            records.append(self._record_from_descriptor(descriptor, ref))
        return tuple(records)

    def _restore_governance_consumptions(self, ref: ProgramExecutionRef) -> int:
        step_count = 0
        for descriptor in self.store.list_artifacts(ref.task_id, session_id=ref.session_id):
            if descriptor.artifact_kind != "program.step-record":
                continue
            metadata = dict(descriptor.metadata)
            if metadata.get("program_execution_id") != ref.program_execution_id:
                continue
            step_count += 1
            encoded = metadata.get("governance_consumptions")
            if encoded is None:
                raise ProgramVersionError("step record lacks governance consumption evidence")
            values = encoded.split("|")
            if len(values) != 2:
                raise ProgramVersionError("step governance consumption evidence is malformed")
            binding_ref, executor_ref = values
            if (binding_ref == "NONE") != (executor_ref == "NONE"):
                raise ProgramVersionError("step governance consumption evidence is incomplete")
            if binding_ref != "NONE":
                self._binding_consumptions.add(_identifier(binding_ref, "binding_consumption_ref"))
                self._executor_consumptions.add(_identifier(executor_ref, "executor_consumption_ref"))
        return step_count

    @staticmethod
    def _record_from_descriptor(descriptor: ArtifactDescriptor, ref: ProgramExecutionRef) -> ProgramExecutionRecord:
        metadata = dict(descriptor.metadata)
        required = {
            "record_schema",
            "contract_version",
            "program_identity",
            "trace_runtime",
            "state_revision",
            "times",
            "current_node_id",
            "last_step_ref",
            "checkpoint_ref",
            "checkpoint_sequence",
            "result_ref",
            "recovery_route",
            "variable_refs",
        }
        if set(metadata) != required:
            raise ProgramVersionError("program execution record schema is incompatible")
        program_identity = metadata["program_identity"].split("|")
        trace_runtime = metadata["trace_runtime"].split("|")
        state_revision = metadata["state_revision"].split("|")
        times = metadata["times"].split(":")
        if len(program_identity) != 2 or len(trace_runtime) != 2 or len(state_revision) != 2 or len(times) != 2:
            raise ProgramVersionError("program execution record composite fields are invalid")
        if program_identity != [ref.program_id, ref.program_digest]:
            raise ProgramVersionError("durable program identity changed")
        variables = () if metadata["variable_refs"] == "EMPTY" else tuple(
            item.split("=", 1) for item in metadata["variable_refs"].split("|")
        )
        checkpoint = None
        if metadata["checkpoint_ref"] != "NONE":
            checkpoint = CheckpointRef(
                metadata["checkpoint_ref"],
                ref.task_id,
                ref.session_id,
                int(metadata["checkpoint_sequence"]),
            )
        route = None if metadata["recovery_route"] == "NONE" else RecoveryRoute(metadata["recovery_route"])
        return ProgramExecutionRecord(
            ref,
            trace_runtime[0],
            trace_runtime[1],
            ProgramExecutionState(state_revision[0]),
            int(state_revision[1]),
            int(times[0]),
            int(times[1]),
            None if metadata["current_node_id"] == "NONE" else metadata["current_node_id"],
            None if metadata["last_step_ref"] == "NONE" else metadata["last_step_ref"],
            checkpoint,
            None if metadata["result_ref"] == "NONE" else metadata["result_ref"],
            route,
            tuple((str(key), str(value)) for key, value in variables),
            metadata["contract_version"],
            metadata["record_schema"],
        )

    @staticmethod
    def _resolve_value_ref(value: str, variables: Mapping[str, str]) -> str:
        return variables[value] if value in variables else _safe_value_ref(value, "value_ref")
