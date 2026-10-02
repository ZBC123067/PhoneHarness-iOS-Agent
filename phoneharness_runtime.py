#!/usr/bin/env python3
"""Host-only session and logical runtime-supervision foundation.

The supervisor records bounded recovery evidence in the existing S3-M1
Artifact/Trace Store. It never authorizes, dispatches, retries, replays, or
restores governed bindings or executor authority.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import re
import threading
import time
from typing import Any, Callable, Iterable
import uuid
import weakref

from phoneharness_agent import TaskExecutionState
from phoneharness_async import AsyncCommitDisposition
from phoneharness_contracts import (
    ArtifactDescriptor,
    ArtifactLifetime,
    ArtifactRef,
    ContractValidationError,
    ObservationFreshness,
    ObservationRef,
    SensitivityClass,
)
from phoneharness_store import (
    PhoneHarnessStore,
    StoreConflictError,
    TraceEvent,
    UnknownArtifactError,
    UnknownReceiptError,
    UnknownTraceEventError,
)


SESSION_SCHEMA_VERSION = "phoneharness.session-ref.v1"
RUNTIME_SCHEMA_VERSION = "phoneharness.runtime-instance-ref.v1"
CAPSULE_SCHEMA_VERSION = "phoneharness.task-capsule.v1"
SYSTEM_TASK_ID = "task.runtime-supervisor"
MAX_RECOVERY_ATTEMPTS = 3
MAX_CAPSULE_ARTIFACT_REFS = 8
MAX_CAPSULE_ASYNC_REFS = 8

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")


class RuntimeSupervisorError(RuntimeError):
    """Base class for deterministic logical-runtime failures."""


class RuntimePolicyError(RuntimeSupervisorError):
    """A runtime/session/capsule contract is invalid."""


class RuntimeStateError(RuntimeSupervisorError):
    """A logical runtime lifecycle transition is invalid."""


class RuntimeOwnershipConflictError(RuntimeSupervisorError):
    """The canonical store already has an incompatible runtime owner."""


class RuntimeCapsuleError(RuntimeSupervisorError):
    """A TaskCapsule is corrupt, incomplete, or incompatible."""


class RestartReconciliationRequiredError(RuntimeSupervisorError):
    """A session belongs to a predecessor runtime and cannot be reattached."""


class RuntimeLifecycleState(str, Enum):
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    QUIESCING = "QUIESCING"
    STOPPED = "STOPPED"
    INTERRUPTED = "INTERRUPTED"


class RuntimeTermination(str, Enum):
    CLEAN_STOP = "CLEAN_STOP"
    INTERRUPTED = "INTERRUPTED"


class CapsuleBoundary(str, Enum):
    TASK_ADMITTED = "TASK_ADMITTED"
    STATE_TRANSITION = "STATE_TRANSITION"
    POST_DISPATCH_EVIDENCE = "POST_DISPATCH_EVIDENCE"
    VERIFICATION = "VERIFICATION"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    SAFE_PROGRESSION = "SAFE_PROGRESSION"
    CLEAN_SHUTDOWN_PREPARATION = "CLEAN_SHUTDOWN_PREPARATION"


class SupervisorRecoveryDisposition(str, Enum):
    TERMINAL_NO_ACTION = "TERMINAL_NO_ACTION"
    RESTORE_WAITING_FOR_USER = "RESTORE_WAITING_FOR_USER"
    REQUIRE_FRESH_OBSERVATION = "REQUIRE_FRESH_OBSERVATION"
    RECONCILE_REQUIRED = "RECONCILE_REQUIRED"
    REPLAN_REQUIRED = "REPLAN_REQUIRED"
    FAIL_SAFE = "FAIL_SAFE"
    CONTINUE_IN_CURRENT_RUNTIME = "CONTINUE_IN_CURRENT_RUNTIME"


def _identifier(value: Any, field_name: str) -> str:
    normalized = str(value or "").strip()
    if _IDENTIFIER.fullmatch(normalized) is None:
        raise RuntimePolicyError(f"{field_name} must be an opaque bounded identifier")
    return normalized


def _optional_identifier(value: Any, field_name: str) -> str | None:
    return None if value is None else _identifier(value, field_name)


def _timestamp(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RuntimePolicyError(f"{field_name} must be a non-negative integer")
    return value


def _positive(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RuntimePolicyError(f"{field_name} must be a positive integer")
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


@dataclass(frozen=True)
class SessionRef:
    session_id: str
    created_at_ms: int
    owner_task_id: str | None = None
    schema_version: str = SESSION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SESSION_SCHEMA_VERSION:
            raise RuntimePolicyError("unsupported SessionRef schema version")
        object.__setattr__(self, "session_id", _identifier(self.session_id, "session_id"))
        object.__setattr__(
            self,
            "owner_task_id",
            _optional_identifier(self.owner_task_id, "owner_task_id"),
        )
        _timestamp(self.created_at_ms, "created_at_ms")

    def audit(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "created_at_ms": self.created_at_ms,
            "owner_task_id": self.owner_task_id,
            "authority": False,
        }


@dataclass(frozen=True)
class RuntimeInstanceRef:
    runtime_instance_id: str
    started_at_ms: int
    schema_version: str = RUNTIME_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RUNTIME_SCHEMA_VERSION:
            raise RuntimePolicyError("unsupported RuntimeInstanceRef schema version")
        object.__setattr__(
            self,
            "runtime_instance_id",
            _identifier(self.runtime_instance_id, "runtime_instance_id"),
        )
        _timestamp(self.started_at_ms, "started_at_ms")

    def audit(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "runtime_instance_id": self.runtime_instance_id,
            "started_at_ms": self.started_at_ms,
            "authority": False,
        }


@dataclass(frozen=True)
class TaskCapsule:
    capsule_id: str
    session_ref: SessionRef
    task_id: str
    trace_id: str
    last_runtime_instance_id: str
    task_state: TaskExecutionState
    created_at_ms: int
    updated_at_ms: int
    revision: int = 1
    last_step_id: str | None = None
    last_execution_id: str | None = None
    last_observation_ref: ObservationRef | None = None
    last_receipt_ref: str | None = None
    artifact_refs: tuple[ArtifactRef, ...] = ()
    verifier_evidence_ref: str | None = None
    async_task_refs: tuple[str, ...] = ()
    last_safe_boundary: CapsuleBoundary = CapsuleBoundary.TASK_ADMITTED
    recovery_required: bool = False
    recovery_attempts: int = 0
    schema_version: str = CAPSULE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != CAPSULE_SCHEMA_VERSION:
            raise RuntimeCapsuleError("unsupported TaskCapsule schema version")
        if not isinstance(self.session_ref, SessionRef):
            raise RuntimeCapsuleError("TaskCapsule requires SessionRef")
        for name in ("capsule_id", "task_id", "trace_id", "last_runtime_instance_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        for name in ("last_step_id", "last_execution_id", "last_receipt_ref", "verifier_evidence_ref"):
            object.__setattr__(self, name, _optional_identifier(getattr(self, name), name))
        if self.session_ref.owner_task_id not in (None, self.task_id):
            raise RuntimeCapsuleError("TaskCapsule session belongs to a different task")
        if not isinstance(self.task_state, TaskExecutionState):
            raise RuntimeCapsuleError("TaskCapsule requires TaskExecutionState")
        _timestamp(self.created_at_ms, "created_at_ms")
        _timestamp(self.updated_at_ms, "updated_at_ms")
        if self.updated_at_ms < self.created_at_ms:
            raise RuntimeCapsuleError("TaskCapsule update precedes creation")
        _positive(self.revision, "revision")
        if isinstance(self.recovery_attempts, bool) or not 0 <= self.recovery_attempts <= MAX_RECOVERY_ATTEMPTS:
            raise RuntimeCapsuleError("TaskCapsule recovery attempts exceed the bounded policy")
        if not isinstance(self.recovery_required, bool):
            raise RuntimeCapsuleError("TaskCapsule recovery flag must be boolean")
        try:
            object.__setattr__(self, "last_safe_boundary", CapsuleBoundary(self.last_safe_boundary))
        except ValueError as exc:
            raise RuntimeCapsuleError("TaskCapsule safe boundary is unsupported") from exc
        if self.last_observation_ref is not None:
            if not isinstance(self.last_observation_ref, ObservationRef):
                raise RuntimeCapsuleError("TaskCapsule observation must use ObservationRef")
            if (
                self.last_observation_ref.task_id != self.task_id
                or self.last_observation_ref.session_id not in (None, self.session_ref.session_id)
            ):
                raise RuntimeCapsuleError("TaskCapsule observation scope does not match")
        refs = tuple(self.artifact_refs)
        if len(refs) > MAX_CAPSULE_ARTIFACT_REFS or any(not isinstance(ref, ArtifactRef) for ref in refs):
            raise RuntimeCapsuleError("TaskCapsule artifact references must be bounded and typed")
        if len({ref.artifact_id for ref in refs}) != len(refs):
            raise RuntimeCapsuleError("TaskCapsule artifact references must be bounded and unique")
        if any(
            ref.task_id != self.task_id
            or ref.session_id not in (None, self.session_ref.session_id)
            for ref in refs
        ):
            raise RuntimeCapsuleError("TaskCapsule artifact reference scope does not match")
        object.__setattr__(self, "artifact_refs", refs)
        async_refs = tuple(_identifier(value, "async_task_ref") for value in self.async_task_refs)
        if len(async_refs) > MAX_CAPSULE_ASYNC_REFS or len(set(async_refs)) != len(async_refs):
            raise RuntimeCapsuleError("TaskCapsule async references must be bounded and unique")
        object.__setattr__(self, "async_task_refs", async_refs)
        if self.task_state is TaskExecutionState.SUCCEEDED and not (
            self.last_observation_ref and self.last_receipt_ref and self.verifier_evidence_ref
        ):
            raise RuntimeCapsuleError("SUCCEEDED TaskCapsule requires observation, receipt, and verifier evidence")
        if self.task_state is TaskExecutionState.UNKNOWN_OUTCOME and self.last_receipt_ref is None:
            raise RuntimeCapsuleError("UNKNOWN_OUTCOME TaskCapsule requires receipt evidence")

    def audit(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "capsule_id": self.capsule_id,
            "session_id": self.session_ref.session_id,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "last_runtime_instance_id": self.last_runtime_instance_id,
            "task_state": self.task_state.value,
            "revision": self.revision,
            "recovery_required": self.recovery_required,
            "authority": {
                "action": False,
                "binding": False,
                "executor": False,
                "retry": False,
                "replay": False,
            },
        }

    def to_artifact_descriptor(self) -> ArtifactDescriptor:
        artifact_links = tuple(
            ("SESSION:" if ref.session_id is not None else "TASK:") + ref.artifact_id
            for ref in self.artifact_refs
        )
        metadata = {
            "capsule_schema": self.schema_version,
            "capsule_id": self.capsule_id,
            "trace_id": self.trace_id,
            "last_runtime_instance_id": self.last_runtime_instance_id,
            "task_state": self.task_state.value,
            "time_refs": "%d:%d:%d"
            % (self.session_ref.created_at_ms, self.created_at_ms, self.updated_at_ms),
            "revision": str(self.revision),
            "last_step_id": _none(self.last_step_id),
            "last_execution_id": _none(self.last_execution_id),
            "last_receipt_ref": _none(self.last_receipt_ref),
            "artifact_ref_ids": _joined(artifact_links),
            "verifier_evidence_ref": _none(self.verifier_evidence_ref),
            "async_task_refs": _joined(self.async_task_refs),
            "last_safe_boundary": self.last_safe_boundary.value,
            "recovery_required": "true" if self.recovery_required else "false",
            "recovery_attempts": str(self.recovery_attempts),
        }
        return ArtifactDescriptor(
            ref=ArtifactRef(
                artifact_id=f"capsule-record.{self.capsule_id}.r{self.revision:06d}",
                task_id=self.task_id,
                session_id=self.session_ref.session_id,
            ),
            artifact_kind="runtime.task-capsule",
            producer="runtime.supervisor",
            created_at_ms=self.updated_at_ms,
            sensitivity=SensitivityClass.PRIVATE,
            lifetime=ArtifactLifetime.DURABLE,
            observation_ref=self.last_observation_ref,
            opaque_locator=self.capsule_id,
            metadata=tuple(metadata.items()),
        )

    @classmethod
    def from_artifact_descriptor(cls, descriptor: ArtifactDescriptor) -> "TaskCapsule":
        if not isinstance(descriptor, ArtifactDescriptor) or descriptor.artifact_kind != "runtime.task-capsule":
            raise RuntimeCapsuleError("durable record is not a TaskCapsule")
        metadata = dict(descriptor.metadata)
        required = {
            "capsule_schema",
            "capsule_id",
            "trace_id",
            "last_runtime_instance_id",
            "task_state",
            "time_refs",
            "revision",
            "last_step_id",
            "last_execution_id",
            "last_receipt_ref",
            "artifact_ref_ids",
            "verifier_evidence_ref",
            "async_task_refs",
            "last_safe_boundary",
            "recovery_required",
            "recovery_attempts",
        }
        if set(metadata) != required:
            raise RuntimeCapsuleError("TaskCapsule durable fields do not match its schema")
        if metadata["capsule_schema"] != CAPSULE_SCHEMA_VERSION:
            raise RuntimeCapsuleError("unsupported TaskCapsule durable schema")
        if descriptor.ref.session_id is None:
            raise RuntimeCapsuleError("TaskCapsule is missing required session scope")
        try:
            artifact_refs_list = []
            for value in _split(metadata["artifact_ref_ids"]):
                scope, separator, artifact_id = value.partition(":")
                if separator != ":" or scope not in {"TASK", "SESSION"}:
                    raise RuntimeCapsuleError("TaskCapsule artifact scope is invalid")
                artifact_refs_list.append(
                    ArtifactRef(
                        artifact_id,
                        descriptor.ref.task_id,
                        descriptor.ref.session_id if scope == "SESSION" else None,
                    )
                )
            artifact_refs = tuple(artifact_refs_list)
            time_parts = tuple(int(value) for value in metadata["time_refs"].split(":"))
            if len(time_parts) != 3:
                raise RuntimeCapsuleError("TaskCapsule time references are invalid")
            session_created_at_ms, created_at_ms, updated_at_ms = time_parts
            session = SessionRef(
                descriptor.ref.session_id,
                session_created_at_ms,
                descriptor.ref.task_id,
            )
            return cls(
                capsule_id=metadata["capsule_id"],
                session_ref=session,
                task_id=descriptor.ref.task_id,
                trace_id=metadata["trace_id"],
                last_runtime_instance_id=metadata["last_runtime_instance_id"],
                task_state=TaskExecutionState(metadata["task_state"]),
                created_at_ms=created_at_ms,
                updated_at_ms=updated_at_ms,
                revision=int(metadata["revision"]),
                last_step_id=_from_none(metadata["last_step_id"]),
                last_execution_id=_from_none(metadata["last_execution_id"]),
                last_observation_ref=descriptor.observation_ref,
                last_receipt_ref=_from_none(metadata["last_receipt_ref"]),
                artifact_refs=artifact_refs,
                verifier_evidence_ref=_from_none(metadata["verifier_evidence_ref"]),
                async_task_refs=_split(metadata["async_task_refs"]),
                last_safe_boundary=CapsuleBoundary(metadata["last_safe_boundary"]),
                recovery_required=metadata["recovery_required"] == "true",
                recovery_attempts=int(metadata["recovery_attempts"]),
                schema_version=metadata["capsule_schema"],
            )
        except (TypeError, ValueError, ContractValidationError, RuntimePolicyError) as exc:
            raise RuntimeCapsuleError("TaskCapsule durable record is invalid") from exc


@dataclass(frozen=True)
class RuntimeStartup:
    runtime_ref: RuntimeInstanceRef
    interrupted_predecessor: RuntimeInstanceRef | None


@dataclass(frozen=True)
class RuntimeRecoveryAssessment:
    disposition: SupervisorRecoveryDisposition
    task_state: TaskExecutionState
    fresh_observation_required: bool
    mutation_resume_allowed: bool = False
    authority: bool = False
    dispatch_count: int = 0

    def __post_init__(self) -> None:
        if self.mutation_resume_allowed or self.authority or self.dispatch_count != 0:
            raise RuntimePolicyError("recovery assessment cannot authorize or dispatch")


@dataclass(frozen=True)
class CapsuleEvidenceSummary:
    receipt_resolved: bool
    verifier_evidence_resolved: bool
    artifact_reference_count: int
    observation_reference_present: bool
    authority: bool = False

    def __post_init__(self) -> None:
        if self.authority:
            raise RuntimePolicyError("capsule evidence cannot authorize")
        if self.artifact_reference_count < 0:
            raise RuntimePolicyError("artifact evidence count cannot be negative")


class RuntimeSupervisor:
    """Minimal logical supervisor over immutable S3-M1 evidence records."""

    _active_lock = threading.RLock()
    _active_stores: "weakref.WeakKeyDictionary[PhoneHarnessStore, RuntimeSupervisor]" = weakref.WeakKeyDictionary()

    def __init__(
        self,
        store: PhoneHarnessStore,
        *,
        now_ms: Callable[[], int] = _now_ms,
        id_factory: Callable[[str], str] = _new_identifier,
    ) -> None:
        if not isinstance(store, PhoneHarnessStore):
            raise RuntimePolicyError("RuntimeSupervisor requires the canonical PhoneHarnessStore")
        self.store = store
        self._now_ms = now_ms
        self._id_factory = id_factory
        self.runtime_ref = RuntimeInstanceRef(
            self._id_factory("runtime"),
            self._now_ms(),
        )
        self.lifecycle_state = RuntimeLifecycleState.STARTING
        self._started = False
        self._dispatch_count = 0

    @property
    def dispatch_count(self) -> int:
        return self._dispatch_count

    def start(self) -> RuntimeStartup:
        if self._started or self.lifecycle_state is not RuntimeLifecycleState.STARTING:
            raise RuntimeStateError("RuntimeSupervisor can start exactly once")
        with self._active_lock:
            active = self._active_stores.get(self.store)
            if active is not None and active.lifecycle_state in {
                RuntimeLifecycleState.STARTING,
                RuntimeLifecycleState.RUNNING,
                RuntimeLifecycleState.QUIESCING,
            }:
                raise RuntimeOwnershipConflictError("canonical store already has an active Runtime owner")
            predecessor = self._latest_runtime_start()
            interrupted = None
            if predecessor is not None and not self._runtime_has_terminal_event(predecessor.runtime_instance_id):
                interrupted = predecessor
                self._persist_runtime_event(
                    predecessor,
                    "INTERRUPTED",
                    RuntimeLifecycleState.INTERRUPTED,
                    predecessor_runtime_id=None,
                )
            self._persist_runtime_event(
                self.runtime_ref,
                "STARTED",
                RuntimeLifecycleState.RUNNING,
                predecessor_runtime_id=(
                    interrupted.runtime_instance_id if interrupted is not None else None
                ),
            )
            self.lifecycle_state = RuntimeLifecycleState.RUNNING
            self._started = True
            self._active_stores[self.store] = self
            return RuntimeStartup(self.runtime_ref, interrupted)

    def create_session(self, owner_task_id: str | None = None) -> SessionRef:
        self._require_running()
        session = SessionRef(
            self._id_factory("session"),
            self._now_ms(),
            owner_task_id,
        )
        self.store.register_artifact(self._session_descriptor(session))
        return session

    def attach_session(self, session_id: str, owner_task_id: str) -> SessionRef:
        self._require_running()
        ref = ArtifactRef(
            artifact_id=f"session-record.{_identifier(session_id, 'session_id')}",
            task_id=_identifier(owner_task_id, "owner_task_id"),
            session_id=session_id,
        )
        descriptor = self.store.get_artifact(ref)
        return self._session_from_descriptor(descriptor)

    def create_task_capsule(
        self,
        session: SessionRef,
        *,
        task_id: str,
        trace_id: str,
        task_state: TaskExecutionState = TaskExecutionState.READY,
        last_observation_ref: ObservationRef | None = None,
        last_receipt_ref: str | None = None,
        verifier_evidence_ref: str | None = None,
        artifact_refs: tuple[ArtifactRef, ...] = (),
        async_task_refs: tuple[str, ...] = (),
        last_safe_boundary: CapsuleBoundary = CapsuleBoundary.TASK_ADMITTED,
    ) -> TaskCapsule:
        self._require_running()
        if session.owner_task_id not in (None, task_id):
            raise RuntimeOwnershipConflictError("session belongs to a different task")
        if self._task_capsules(task_id, session.session_id):
            raise RuntimeOwnershipConflictError("task/session already has a durable Runtime owner")
        now = self._now_ms()
        capsule = TaskCapsule(
            capsule_id=self._id_factory("capsule"),
            session_ref=session,
            task_id=task_id,
            trace_id=trace_id,
            last_runtime_instance_id=self.runtime_ref.runtime_instance_id,
            task_state=task_state,
            created_at_ms=now,
            updated_at_ms=now,
            last_observation_ref=last_observation_ref,
            last_receipt_ref=last_receipt_ref,
            artifact_refs=artifact_refs,
            verifier_evidence_ref=verifier_evidence_ref,
            async_task_refs=async_task_refs,
            last_safe_boundary=last_safe_boundary,
        )
        self._persist_capsule(capsule, "capsule.created")
        return capsule

    def load_task_capsule(self, *, task_id: str, session_id: str) -> TaskCapsule:
        capsules = self._task_capsules(task_id, session_id)
        if not capsules:
            raise RuntimeCapsuleError("task/session has no durable TaskCapsule")
        capsule_ids = {capsule.capsule_id for capsule in capsules}
        if len(capsule_ids) != 1:
            raise RuntimeOwnershipConflictError("task/session has conflicting capsule identities")
        return max(capsules, key=lambda value: value.revision)

    def update_task_capsule(
        self,
        capsule: TaskCapsule,
        *,
        task_state: TaskExecutionState | None = None,
        last_observation_ref: ObservationRef | None = None,
        last_receipt_ref: str | None = None,
        verifier_evidence_ref: str | None = None,
        last_safe_boundary: CapsuleBoundary | None = None,
        recovery_required: bool | None = None,
    ) -> TaskCapsule:
        self._require_running()
        latest = self.load_task_capsule(
            task_id=capsule.task_id,
            session_id=capsule.session_ref.session_id,
        )
        if latest.capsule_id != capsule.capsule_id or latest.revision != capsule.revision:
            raise RuntimeOwnershipConflictError("TaskCapsule revision is no longer current")
        updated = replace(
            capsule,
            task_state=task_state if task_state is not None else capsule.task_state,
            last_observation_ref=(
                last_observation_ref if last_observation_ref is not None else capsule.last_observation_ref
            ),
            last_receipt_ref=(
                last_receipt_ref if last_receipt_ref is not None else capsule.last_receipt_ref
            ),
            verifier_evidence_ref=(
                verifier_evidence_ref
                if verifier_evidence_ref is not None
                else capsule.verifier_evidence_ref
            ),
            last_safe_boundary=(
                last_safe_boundary if last_safe_boundary is not None else capsule.last_safe_boundary
            ),
            recovery_required=(
                recovery_required if recovery_required is not None else capsule.recovery_required
            ),
            revision=capsule.revision + 1,
            updated_at_ms=max(self._now_ms(), capsule.updated_at_ms + 1),
        )
        try:
            self._persist_capsule(updated, "capsule.updated")
        except StoreConflictError as exc:
            raise RuntimeOwnershipConflictError("TaskCapsule ownership claim conflicted") from exc
        return updated

    def claim_recovered_task(self, capsule: TaskCapsule) -> TaskCapsule:
        self._require_running()
        if capsule.last_runtime_instance_id == self.runtime_ref.runtime_instance_id:
            return capsule
        if capsule.recovery_attempts >= MAX_RECOVERY_ATTEMPTS:
            raise RuntimeStateError("bounded Runtime recovery attempts are exhausted")
        self.resolve_capsule_evidence(capsule)
        latest = self.load_task_capsule(
            task_id=capsule.task_id,
            session_id=capsule.session_ref.session_id,
        )
        if latest.revision != capsule.revision or latest.capsule_id != capsule.capsule_id:
            raise RuntimeOwnershipConflictError("recovered task ownership is no longer current")
        claimed = replace(
            capsule,
            last_runtime_instance_id=self.runtime_ref.runtime_instance_id,
            recovery_required=True,
            recovery_attempts=capsule.recovery_attempts + 1,
            revision=capsule.revision + 1,
            updated_at_ms=max(self._now_ms(), capsule.updated_at_ms + 1),
        )
        try:
            self._persist_capsule(claimed, "capsule.recovery-claimed")
        except StoreConflictError as exc:
            raise RuntimeOwnershipConflictError("recovered task ownership claim conflicted") from exc
        return claimed

    def resolve_capsule_evidence(self, capsule: TaskCapsule) -> CapsuleEvidenceSummary:
        """Resolve only durable references; never infer authority or semantic success."""

        self._require_running()
        try:
            for artifact_ref in capsule.artifact_refs:
                self.store.get_artifact(artifact_ref)
            receipt_resolved = False
            if capsule.last_receipt_ref is not None:
                receipt = self.store.get_receipt(capsule.last_receipt_ref)
                if receipt.task_id != capsule.task_id:
                    raise RuntimeCapsuleError("TaskCapsule receipt scope does not match")
                receipt_resolved = True
            verifier_resolved = False
            if capsule.verifier_evidence_ref is not None:
                event = self.store.get_trace_event(capsule.verifier_evidence_ref)
                if event.task_id != capsule.task_id or event.verifier_result is None:
                    raise RuntimeCapsuleError("TaskCapsule verifier evidence is invalid")
                verifier_resolved = True
        except (UnknownArtifactError, UnknownReceiptError, UnknownTraceEventError) as exc:
            raise RuntimeCapsuleError("TaskCapsule durable evidence reference is unresolved") from exc
        return CapsuleEvidenceSummary(
            receipt_resolved=receipt_resolved,
            verifier_evidence_resolved=verifier_resolved,
            artifact_reference_count=len(capsule.artifact_refs),
            observation_reference_present=capsule.last_observation_ref is not None,
        )

    def reattach_same_runtime(self, *, task_id: str, session_id: str) -> TaskCapsule:
        self._require_running()
        capsule = self.load_task_capsule(task_id=task_id, session_id=session_id)
        if capsule.last_runtime_instance_id != self.runtime_ref.runtime_instance_id or capsule.recovery_required:
            raise RestartReconciliationRequiredError("runtime changed; restart reconciliation is required")
        self._append_trace(
            capsule.task_id,
            capsule.trace_id,
            "runtime.session-reattached",
            attributes=(("runtime_instance_id", self.runtime_ref.runtime_instance_id),),
        )
        return capsule

    def assess_recovery(
        self,
        capsule: TaskCapsule,
        *,
        fresh_observation: ObservationRef | None = None,
    ) -> RuntimeRecoveryAssessment:
        self._require_running()
        if capsule.recovery_attempts >= MAX_RECOVERY_ATTEMPTS:
            return self._assessment(capsule.task_state, SupervisorRecoveryDisposition.FAIL_SAFE, False)
        restarted = capsule.recovery_required or (
            capsule.last_runtime_instance_id != self.runtime_ref.runtime_instance_id
        )
        if not restarted:
            return self._assessment(
                capsule.task_state,
                SupervisorRecoveryDisposition.CONTINUE_IN_CURRENT_RUNTIME,
                False,
            )
        if capsule.task_state in {TaskExecutionState.SUCCEEDED, TaskExecutionState.FAILED}:
            return self._assessment(
                capsule.task_state,
                SupervisorRecoveryDisposition.TERMINAL_NO_ACTION,
                False,
            )
        if capsule.task_state is TaskExecutionState.BLOCKED:
            return self._assessment(capsule.task_state, SupervisorRecoveryDisposition.FAIL_SAFE, False)
        if capsule.task_state is TaskExecutionState.WAITING_FOR_USER:
            return self._assessment(
                capsule.task_state,
                SupervisorRecoveryDisposition.RESTORE_WAITING_FOR_USER,
                True,
            )
        if capsule.task_state is TaskExecutionState.UNKNOWN_OUTCOME:
            return self._assessment(
                capsule.task_state,
                SupervisorRecoveryDisposition.RECONCILE_REQUIRED,
                True,
            )
        if not self._is_fresh_for_capsule(fresh_observation, capsule):
            return self._assessment(
                capsule.task_state,
                SupervisorRecoveryDisposition.REQUIRE_FRESH_OBSERVATION,
                True,
            )
        return self._assessment(
            capsule.task_state,
            SupervisorRecoveryDisposition.REPLAN_REQUIRED,
            False,
        )

    def commit_async_result(
        self,
        *,
        capsule: TaskCapsule,
        origin_runtime_instance_id: str,
        apply_current: Callable[[], None],
    ) -> AsyncCommitDisposition:
        self._require_running()
        origin = _identifier(origin_runtime_instance_id, "origin_runtime_instance_id")
        latest = self.load_task_capsule(
            task_id=capsule.task_id,
            session_id=capsule.session_ref.session_id,
        )
        if (
            origin != self.runtime_ref.runtime_instance_id
            or latest.last_runtime_instance_id != self.runtime_ref.runtime_instance_id
            or latest.capsule_id != capsule.capsule_id
            or latest.revision != capsule.revision
        ):
            self._append_trace(
                latest.task_id,
                latest.trace_id,
                "runtime.old-result-dropped",
                attributes=(("commit_disposition", AsyncCommitDisposition.STALE_DROPPED.value),),
            )
            return AsyncCommitDisposition.STALE_DROPPED
        apply_current()
        return AsyncCommitDisposition.COMMITTED

    def clean_shutdown(self) -> RuntimeTermination:
        self._require_running()
        self.lifecycle_state = RuntimeLifecycleState.QUIESCING
        self._persist_runtime_event(
            self.runtime_ref,
            "QUIESCING",
            RuntimeLifecycleState.QUIESCING,
            predecessor_runtime_id=None,
        )
        self._persist_runtime_event(
            self.runtime_ref,
            "CLEAN_STOP",
            RuntimeLifecycleState.STOPPED,
            predecessor_runtime_id=None,
        )
        self.lifecycle_state = RuntimeLifecycleState.STOPPED
        with self._active_lock:
            if self._active_stores.get(self.store) is self:
                del self._active_stores[self.store]
        return RuntimeTermination.CLEAN_STOP

    def _require_running(self) -> None:
        if not self._started or self.lifecycle_state is not RuntimeLifecycleState.RUNNING:
            raise RuntimeStateError("RuntimeSupervisor is not running")

    @staticmethod
    def _assessment(
        state: TaskExecutionState,
        disposition: SupervisorRecoveryDisposition,
        fresh_required: bool,
    ) -> RuntimeRecoveryAssessment:
        return RuntimeRecoveryAssessment(disposition, state, fresh_required)

    @staticmethod
    def _is_fresh_for_capsule(observation: ObservationRef | None, capsule: TaskCapsule) -> bool:
        return bool(
            isinstance(observation, ObservationRef)
            and observation.task_id == capsule.task_id
            and observation.session_id in (None, capsule.session_ref.session_id)
            and observation.freshness is ObservationFreshness.FRESH
            and observation.observed_at_ms is not None
            and observation.observed_at_ms > capsule.updated_at_ms
        )

    @staticmethod
    def _session_descriptor(session: SessionRef) -> ArtifactDescriptor:
        task_id = session.owner_task_id or SYSTEM_TASK_ID
        return ArtifactDescriptor(
            ref=ArtifactRef(
                f"session-record.{session.session_id}",
                task_id,
                session.session_id,
            ),
            artifact_kind="runtime.session",
            producer="runtime.supervisor",
            created_at_ms=session.created_at_ms,
            sensitivity=SensitivityClass.PRIVATE,
            lifetime=ArtifactLifetime.DURABLE,
            opaque_locator=session.session_id,
            metadata=(
                ("session_schema", session.schema_version),
                ("owner_task_id", _none(session.owner_task_id)),
                ("created_at_ms", str(session.created_at_ms)),
            ),
        )

    @staticmethod
    def _session_from_descriptor(descriptor: ArtifactDescriptor) -> SessionRef:
        if descriptor.artifact_kind != "runtime.session" or descriptor.ref.session_id is None:
            raise RuntimeCapsuleError("durable record is not a SessionRef")
        metadata = dict(descriptor.metadata)
        if set(metadata) != {"session_schema", "owner_task_id", "created_at_ms"}:
            raise RuntimeCapsuleError("SessionRef durable fields do not match its schema")
        try:
            return SessionRef(
                descriptor.ref.session_id,
                int(metadata["created_at_ms"]),
                _from_none(metadata["owner_task_id"]),
                metadata["session_schema"],
            )
        except (TypeError, ValueError, RuntimePolicyError) as exc:
            raise RuntimeCapsuleError("SessionRef durable record is invalid") from exc

    def _persist_capsule(self, capsule: TaskCapsule, event_name: str) -> None:
        descriptor = capsule.to_artifact_descriptor()
        event = TraceEvent(
            event_id=f"trace-event.{descriptor.ref.artifact_id}",
            task_id=capsule.task_id,
            trace_id=capsule.trace_id,
            event_name=event_name,
            observed_timestamp_ms=capsule.updated_at_ms,
            step_id=capsule.last_step_id,
            execution_id=capsule.last_execution_id,
            receipt_refs=(capsule.last_receipt_ref,) if capsule.last_receipt_ref else (),
            artifact_refs=(descriptor.ref,),
            observation_refs=(capsule.last_observation_ref,) if capsule.last_observation_ref else (),
            verifier_result="HISTORICAL" if capsule.verifier_evidence_ref else None,
            attributes=(
                ("runtime_instance_id", capsule.last_runtime_instance_id),
                ("task_state", capsule.task_state.value),
                ("capsule_revision", str(capsule.revision)),
                ("recovery_required", "true" if capsule.recovery_required else "false"),
            ),
        )
        self.store.record_artifact_and_trace(descriptor, event)

    def _task_capsules(self, task_id: str, session_id: str) -> tuple[TaskCapsule, ...]:
        descriptors = self.store.list_artifacts(task_id, session_id=session_id)
        capsules: list[TaskCapsule] = []
        for descriptor in descriptors:
            if descriptor.artifact_kind == "runtime.task-capsule":
                capsules.append(TaskCapsule.from_artifact_descriptor(descriptor))
        return tuple(capsules)

    def _persist_runtime_event(
        self,
        runtime_ref: RuntimeInstanceRef,
        event_type: str,
        lifecycle_state: RuntimeLifecycleState,
        *,
        predecessor_runtime_id: str | None,
    ) -> None:
        event_lower = event_type.casefold().replace("_", "-")
        timestamp = self._now_ms()
        descriptor = ArtifactDescriptor(
            ref=ArtifactRef(
                f"runtime-event.{runtime_ref.runtime_instance_id}.{event_lower}",
                SYSTEM_TASK_ID,
            ),
            artifact_kind="runtime.lifecycle",
            producer="runtime.supervisor",
            created_at_ms=timestamp,
            sensitivity=SensitivityClass.PRIVATE,
            lifetime=ArtifactLifetime.DURABLE,
            opaque_locator=runtime_ref.runtime_instance_id,
            metadata=(
                ("runtime_schema", runtime_ref.schema_version),
                ("runtime_instance_id", runtime_ref.runtime_instance_id),
                ("runtime_started_at_ms", str(runtime_ref.started_at_ms)),
                ("event_type", event_type),
                ("lifecycle_state", lifecycle_state.value),
                ("predecessor_runtime_id", _none(predecessor_runtime_id)),
            ),
        )
        trace = TraceEvent(
            event_id=f"trace-event.{descriptor.ref.artifact_id}",
            task_id=SYSTEM_TASK_ID,
            trace_id=f"trace.{runtime_ref.runtime_instance_id}",
            event_name=f"runtime.{event_lower}",
            observed_timestamp_ms=timestamp,
            artifact_refs=(descriptor.ref,),
            attributes=(
                ("runtime_instance_id", runtime_ref.runtime_instance_id),
                ("lifecycle_state", lifecycle_state.value),
            ),
        )
        self.store.record_artifact_and_trace(descriptor, trace)

    def _runtime_descriptors(self) -> tuple[ArtifactDescriptor, ...]:
        return tuple(
            descriptor
            for descriptor in self.store.list_artifacts(SYSTEM_TASK_ID)
            if descriptor.artifact_kind == "runtime.lifecycle"
        )

    def _latest_runtime_start(self) -> RuntimeInstanceRef | None:
        starts = []
        for descriptor in self._runtime_descriptors():
            metadata = dict(descriptor.metadata)
            if metadata.get("event_type") == "STARTED":
                try:
                    starts.append(
                        (
                            descriptor.created_at_ms,
                            descriptor.ref.artifact_id,
                            RuntimeInstanceRef(
                                metadata["runtime_instance_id"],
                                int(metadata["runtime_started_at_ms"]),
                                metadata["runtime_schema"],
                            ),
                        )
                    )
                except (KeyError, TypeError, ValueError, RuntimePolicyError) as exc:
                    raise RuntimeCapsuleError("runtime lifecycle evidence is invalid") from exc
        return None if not starts else max(starts, key=lambda item: (item[0], item[1]))[2]

    def _runtime_has_terminal_event(self, runtime_instance_id: str) -> bool:
        for descriptor in self._runtime_descriptors():
            metadata = dict(descriptor.metadata)
            if metadata.get("runtime_instance_id") == runtime_instance_id and metadata.get("event_type") in {
                "CLEAN_STOP",
                "INTERRUPTED",
            }:
                return True
        return False

    def _append_trace(
        self,
        task_id: str,
        trace_id: str,
        event_name: str,
        *,
        attributes: tuple[tuple[str, str], ...],
    ) -> None:
        self.store.append_trace_event(
            TraceEvent(
                event_id=self._id_factory("trace-event"),
                task_id=task_id,
                trace_id=trace_id,
                event_name=event_name,
                observed_timestamp_ms=self._now_ms(),
                attributes=attributes,
            )
        )


__all__ = [
    "CAPSULE_SCHEMA_VERSION",
    "MAX_RECOVERY_ATTEMPTS",
    "CapsuleEvidenceSummary",
    "CapsuleBoundary",
    "RestartReconciliationRequiredError",
    "RuntimeCapsuleError",
    "RuntimeInstanceRef",
    "RuntimeLifecycleState",
    "RuntimeOwnershipConflictError",
    "RuntimePolicyError",
    "RuntimeRecoveryAssessment",
    "RuntimeStateError",
    "RuntimeStartup",
    "RuntimeSupervisor",
    "RuntimeTermination",
    "SessionRef",
    "SupervisorRecoveryDisposition",
    "TaskCapsule",
]
