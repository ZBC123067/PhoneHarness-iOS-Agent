#!/usr/bin/env python3
"""Bounded Host async-task foundation for PhoneHarness Stage 3.

This module owns concurrency lifecycle only. It cannot authorize an action,
create a governed binding or executor authority, grant retry, claim rollback,
mark semantic success, or transition the action-obligation ledger.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
import re
import threading
import time
from typing import Any, Awaitable, Callable, Mapping
import uuid

from phoneharness_contracts import ArtifactRef
from phoneharness_store import PhoneHarnessStore, TraceEvent


MAX_SAFE_METADATA_ITEMS = 16
MAX_SAFE_METADATA_VALUE_LENGTH = 256
MAX_SAFE_MESSAGE_LENGTH = 160
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
_SECRET_VALUE_PATTERNS = (
    re.compile(r"(?i)^bearer\s+\S+"),
    re.compile(r"(?i)^(?:sk|ghp|github_pat|xox[baprs])-\S+"),
    re.compile(r"^eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$"),
    re.compile(r"^[0-9a-f]{32}$"),
)
_FORBIDDEN_METADATA_WORDS = frozenset(
    {
        "authorization",
        "binding",
        "credential",
        "executorauthority",
        "executorport",
        "nonce",
        "otp",
        "passcode",
        "password",
        "privatekey",
        "secret",
        "token",
    }
)


class AsyncTaskError(RuntimeError):
    """Base class for deterministic async-task failures."""


class AsyncTaskPolicyError(AsyncTaskError):
    """An async request violated the bounded task contract."""


class AsyncTaskTransitionError(AsyncTaskError):
    """An async lifecycle transition is not legal."""


class AsyncTaskCapacityError(AsyncTaskError):
    """The bounded in-memory registry cannot accept another live task."""


class AsyncTaskNotFoundError(AsyncTaskError):
    """An async task identity is unknown to this scope."""


class AsyncTaskOwnershipError(AsyncTaskError):
    """An owner, parent, or generation relationship is invalid."""


class _AsyncDeadlineExpired(Exception):
    """Private marker separating an owned deadline from provider TimeoutError."""


class AsyncTaskState(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"


class AsyncCommitDisposition(str, Enum):
    COMMITTED = "COMMITTED"
    STALE_DROPPED = "STALE_DROPPED"
    OWNER_GONE = "OWNER_GONE"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class AsyncTaskErrorCode(str, Enum):
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"
    TASK_FAILURE = "TASK_FAILURE"
    INTERNAL_FAILURE = "INTERNAL_FAILURE"


_TERMINAL_STATES = frozenset(
    {
        AsyncTaskState.SUCCEEDED,
        AsyncTaskState.FAILED,
        AsyncTaskState.CANCELLED,
        AsyncTaskState.TIMED_OUT,
    }
)
_TRANSITIONS = {
    AsyncTaskState.PENDING: frozenset(
        {
            AsyncTaskState.RUNNING,
            AsyncTaskState.CANCEL_REQUESTED,
            AsyncTaskState.CANCELLED,
            AsyncTaskState.FAILED,
        }
    ),
    AsyncTaskState.RUNNING: frozenset(
        {
            AsyncTaskState.CANCEL_REQUESTED,
            AsyncTaskState.SUCCEEDED,
            AsyncTaskState.FAILED,
            AsyncTaskState.TIMED_OUT,
        }
    ),
    AsyncTaskState.CANCEL_REQUESTED: frozenset(
        {
            AsyncTaskState.SUCCEEDED,
            AsyncTaskState.FAILED,
            AsyncTaskState.CANCELLED,
            AsyncTaskState.TIMED_OUT,
        }
    ),
    AsyncTaskState.SUCCEEDED: frozenset(),
    AsyncTaskState.FAILED: frozenset(),
    AsyncTaskState.CANCELLED: frozenset(),
    AsyncTaskState.TIMED_OUT: frozenset(),
}


def _identifier(value: Any, field_name: str) -> str:
    normalized = str(value or "").strip()
    if _IDENTIFIER.fullmatch(normalized) is None:
        raise AsyncTaskPolicyError(f"{field_name} must be an opaque bounded identifier")
    return normalized


def _optional_identifier(value: Any, field_name: str) -> str | None:
    return None if value is None else _identifier(value, field_name)


def _positive_generation(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise AsyncTaskPolicyError("generation must be a positive integer")
    return value


def _timestamp(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AsyncTaskPolicyError(f"{field_name} must be a non-negative integer")
    return value


def _safe_metadata(value: Mapping[str, Any] | tuple[tuple[str, Any], ...]) -> tuple[tuple[str, str], ...]:
    if isinstance(value, Mapping):
        items = tuple(value.items())
    elif isinstance(value, tuple):
        items = value
    else:
        raise AsyncTaskPolicyError("safe metadata must be a mapping or canonical pair tuple")
    if len(items) > MAX_SAFE_METADATA_ITEMS:
        raise AsyncTaskPolicyError("safe metadata exceeds its bounded size")
    normalized: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw_key, raw_value in items:
        key = _identifier(raw_key, "safe metadata key")
        if key in seen:
            raise AsyncTaskPolicyError("safe metadata cannot contain duplicate keys")
        seen.add(key)
        words = {part.casefold() for part in re.split(r"[._:-]+", key) if part}
        words.add(re.sub(r"[^a-z0-9]", "", key.casefold()))
        if words & _FORBIDDEN_METADATA_WORDS:
            raise AsyncTaskPolicyError("safe metadata cannot contain authority or secret fields")
        text = " ".join(str(raw_value).split())
        if not text or len(text) > MAX_SAFE_METADATA_VALUE_LENGTH:
            raise AsyncTaskPolicyError("safe metadata values must be bounded non-empty text")
        if any(pattern.search(text) for pattern in _SECRET_VALUE_PATTERNS):
            raise AsyncTaskPolicyError("safe metadata cannot contain secret-shaped values")
        normalized.append((key, text))
    return tuple(sorted(normalized))


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


@dataclass(frozen=True)
class AsyncTaskRef:
    async_task_id: str
    owner_task_id: str
    generation: int
    task_kind: str
    created_at_ms: int
    parent_async_task_id: str | None = None
    schema_version: str = "phoneharness.async-task-ref.v1"

    def __post_init__(self) -> None:
        if self.schema_version != "phoneharness.async-task-ref.v1":
            raise AsyncTaskPolicyError("unsupported AsyncTaskRef schema version")
        object.__setattr__(self, "async_task_id", _identifier(self.async_task_id, "async_task_id"))
        object.__setattr__(self, "owner_task_id", _identifier(self.owner_task_id, "owner_task_id"))
        object.__setattr__(self, "task_kind", _identifier(self.task_kind, "task_kind"))
        object.__setattr__(
            self,
            "parent_async_task_id",
            _optional_identifier(self.parent_async_task_id, "parent_async_task_id"),
        )
        _positive_generation(self.generation)
        _timestamp(self.created_at_ms, "created_at_ms")
        if self.parent_async_task_id == self.async_task_id:
            raise AsyncTaskOwnershipError("an async task cannot own itself")

    def audit(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "async_task_id": self.async_task_id,
            "owner_task_id": self.owner_task_id,
            "parent_async_task_id": self.parent_async_task_id,
            "generation": self.generation,
            "task_kind": self.task_kind,
            "created_at_ms": self.created_at_ms,
            "authority": False,
        }


@dataclass(frozen=True)
class AsyncWorkResult:
    """Bounded operation output before the current-generation commit gate."""

    safe_metadata: tuple[tuple[str, str], ...] = ()
    artifact_ref: ArtifactRef | None = None
    dispatch_count: int = 0
    unknown_outcome: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "safe_metadata", _safe_metadata(self.safe_metadata))
        if self.artifact_ref is not None and not isinstance(self.artifact_ref, ArtifactRef):
            raise AsyncTaskPolicyError("large or durable output must use ArtifactRef")
        if isinstance(self.dispatch_count, bool) or self.dispatch_count not in (0, 1):
            raise AsyncTaskPolicyError("one async task may record at most one governed dispatch")
        if not isinstance(self.unknown_outcome, bool):
            raise AsyncTaskPolicyError("unknown_outcome must be boolean")
        if self.unknown_outcome and self.dispatch_count != 1:
            raise AsyncTaskPolicyError("unknown outcome requires evidence of possible dispatch")


@dataclass(frozen=True)
class AsyncTaskResult:
    task_ref: AsyncTaskRef
    final_state: AsyncTaskState
    commit_disposition: AsyncCommitDisposition
    started_at_ms: int
    ended_at_ms: int
    value: AsyncWorkResult | None = None
    error_code: AsyncTaskErrorCode | None = None
    error_class: str | None = None
    safe_message: str | None = None
    trace_id: str | None = None
    trace_recorded: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.task_ref, AsyncTaskRef):
            raise AsyncTaskPolicyError("AsyncTaskResult requires AsyncTaskRef")
        if self.final_state not in _TERMINAL_STATES:
            raise AsyncTaskPolicyError("AsyncTaskResult requires a terminal concurrency state")
        if not isinstance(self.commit_disposition, AsyncCommitDisposition):
            raise AsyncTaskPolicyError("invalid async result commit disposition")
        _timestamp(self.started_at_ms, "started_at_ms")
        _timestamp(self.ended_at_ms, "ended_at_ms")
        if self.ended_at_ms < self.started_at_ms:
            raise AsyncTaskPolicyError("async result end cannot precede start")
        if self.value is not None and not isinstance(self.value, AsyncWorkResult):
            raise AsyncTaskPolicyError("async result value must use AsyncWorkResult")
        if self.error_code is not None and not isinstance(self.error_code, AsyncTaskErrorCode):
            raise AsyncTaskPolicyError("async result error_code must be typed")
        object.__setattr__(self, "error_class", _optional_identifier(self.error_class, "error_class"))
        object.__setattr__(self, "trace_id", _optional_identifier(self.trace_id, "trace_id"))
        if self.safe_message is not None:
            message = " ".join(str(self.safe_message).split())
            if not message or len(message) > MAX_SAFE_MESSAGE_LENGTH:
                raise AsyncTaskPolicyError("safe async failure message is invalid")
            if any(pattern.search(message) for pattern in _SECRET_VALUE_PATTERNS):
                raise AsyncTaskPolicyError("safe async failure message resembles secret material")
            object.__setattr__(self, "safe_message", message)
        if not isinstance(self.trace_recorded, bool):
            raise AsyncTaskPolicyError("trace_recorded must be boolean")
        if self.final_state is AsyncTaskState.SUCCEEDED:
            if self.value is None or self.error_code is not None:
                raise AsyncTaskPolicyError("successful async result requires a value and no error")
            if self.commit_disposition not in {
                AsyncCommitDisposition.COMMITTED,
                AsyncCommitDisposition.STALE_DROPPED,
                AsyncCommitDisposition.OWNER_GONE,
                AsyncCommitDisposition.SUPERSEDED,
            }:
                raise AsyncTaskPolicyError("successful async result has an invalid commit disposition")
        elif self.value is not None:
            raise AsyncTaskPolicyError("non-success async result cannot contain a result value")
        if self.final_state is AsyncTaskState.CANCELLED:
            if self.commit_disposition is not AsyncCommitDisposition.CANCELLED:
                raise AsyncTaskPolicyError("cancelled async result requires cancelled disposition")
            if self.error_code is not AsyncTaskErrorCode.CANCELLED:
                raise AsyncTaskPolicyError("cancelled async result requires cancellation error code")
        if self.final_state is AsyncTaskState.TIMED_OUT:
            if self.commit_disposition is not AsyncCommitDisposition.FAILED:
                raise AsyncTaskPolicyError("timed-out async result requires failed disposition")
            if self.error_code is not AsyncTaskErrorCode.TIMED_OUT:
                raise AsyncTaskPolicyError("timed-out async result requires timeout error code")
        if self.final_state is AsyncTaskState.FAILED:
            if self.commit_disposition is not AsyncCommitDisposition.FAILED:
                raise AsyncTaskPolicyError("failed async result requires failed disposition")
            if self.error_code not in {
                AsyncTaskErrorCode.TASK_FAILURE,
                AsyncTaskErrorCode.INTERNAL_FAILURE,
            }:
                raise AsyncTaskPolicyError("failed async result requires a typed failure code")

    def audit(self) -> dict[str, Any]:
        return {
            "task_ref": self.task_ref.audit(),
            "final_state": self.final_state.value,
            "commit_disposition": self.commit_disposition.value,
            "unknown_outcome": bool(self.value and self.value.unknown_outcome),
            "dispatch_count": 0 if self.value is None else self.value.dispatch_count,
            "trace_recorded": self.trace_recorded,
            "authorization": False,
            "binding": False,
            "executor_authority": False,
            "semantic_success": False,
            "ledger_verified": False,
            "retry_permitted": False,
            "rollback_proven": False,
        }


@dataclass
class _TaskRecord:
    ref: AsyncTaskRef
    state: AsyncTaskState
    trace_id: str | None
    step_id: str | None
    execution_id: str | None
    result: AsyncTaskResult | None = None


class AsyncTaskRegistry:
    """Bounded in-memory lifecycle registry; durable history belongs to S3-M1."""

    def __init__(self, *, capacity: int = 128) -> None:
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
            raise AsyncTaskPolicyError("registry capacity must be positive")
        self.capacity = capacity
        self._lock = threading.RLock()
        self._records: OrderedDict[str, _TaskRecord] = OrderedDict()
        self._owner_generation: dict[str, int] = {}
        self._owner_active: dict[str, bool] = {}
        self._current: dict[tuple[str, str], str] = {}

    @staticmethod
    def validate_transition(current: AsyncTaskState, destination: AsyncTaskState) -> None:
        if not isinstance(current, AsyncTaskState) or not isinstance(destination, AsyncTaskState):
            raise AsyncTaskTransitionError("async transitions require typed states")
        if destination not in _TRANSITIONS[current]:
            raise AsyncTaskTransitionError(
                f"async task cannot transition from {current.value} to {destination.value}"
            )

    def _record(self, async_task_id: str) -> _TaskRecord:
        try:
            return self._records[async_task_id]
        except KeyError as exc:
            raise AsyncTaskNotFoundError("async task identity is not registered") from exc

    def _evict_terminal_if_needed(self) -> None:
        while len(self._records) >= self.capacity:
            for identifier, record in tuple(self._records.items()):
                if record.state in _TERMINAL_STATES:
                    del self._records[identifier]
                    if self._current.get((record.ref.owner_task_id, record.ref.task_kind)) == identifier:
                        del self._current[(record.ref.owner_task_id, record.ref.task_kind)]
                    break
            else:
                raise AsyncTaskCapacityError("registry capacity is occupied by live tasks")

    def register(
        self,
        ref: AsyncTaskRef,
        *,
        trace_id: str | None,
        step_id: str | None,
        execution_id: str | None,
    ) -> None:
        with self._lock:
            if ref.async_task_id in self._records:
                raise AsyncTaskOwnershipError("async task identity already exists")
            current_generation = self._owner_generation.setdefault(ref.owner_task_id, ref.generation)
            self._owner_active.setdefault(ref.owner_task_id, True)
            if not self._owner_active[ref.owner_task_id]:
                raise AsyncTaskOwnershipError("owner is not active")
            if current_generation != ref.generation:
                raise AsyncTaskOwnershipError("new work must use the current owner generation")
            if ref.parent_async_task_id is not None:
                parent = self._record(ref.parent_async_task_id)
                if parent.ref.owner_task_id != ref.owner_task_id or parent.state in _TERMINAL_STATES:
                    raise AsyncTaskOwnershipError("parent async task is not an active task of this owner")
            self._evict_terminal_if_needed()
            self._records[ref.async_task_id] = _TaskRecord(
                ref=ref,
                state=AsyncTaskState.PENDING,
                trace_id=_optional_identifier(trace_id, "trace_id"),
                step_id=_optional_identifier(step_id, "step_id"),
                execution_id=_optional_identifier(execution_id, "execution_id"),
            )
            self._current[(ref.owner_task_id, ref.task_kind)] = ref.async_task_id

    def state(self, async_task_id: str) -> AsyncTaskState:
        with self._lock:
            return self._record(async_task_id).state

    def result(self, async_task_id: str) -> AsyncTaskResult | None:
        with self._lock:
            return self._record(async_task_id).result

    def mark_running(self, async_task_id: str) -> bool:
        with self._lock:
            record = self._record(async_task_id)
            if record.state is AsyncTaskState.CANCEL_REQUESTED:
                return False
            self.validate_transition(record.state, AsyncTaskState.RUNNING)
            record.state = AsyncTaskState.RUNNING
            return True

    def request_cancel(self, async_task_id: str) -> bool:
        with self._lock:
            record = self._record(async_task_id)
            if record.state in _TERMINAL_STATES or record.state is AsyncTaskState.CANCEL_REQUESTED:
                return False
            self.validate_transition(record.state, AsyncTaskState.CANCEL_REQUESTED)
            record.state = AsyncTaskState.CANCEL_REQUESTED
            return True

    def cancellation_requested(self, async_task_id: str) -> bool:
        with self._lock:
            return self._record(async_task_id).state is AsyncTaskState.CANCEL_REQUESTED

    def descendants(self, async_task_id: str) -> tuple[str, ...]:
        with self._lock:
            pending = [async_task_id]
            found: list[str] = []
            while pending:
                parent = pending.pop()
                children = [
                    record.ref.async_task_id
                    for record in self._records.values()
                    if record.ref.parent_async_task_id == parent and record.state not in _TERMINAL_STATES
                ]
                found.extend(children)
                pending.extend(children)
            return tuple(found)

    def advance_owner_generation(self, owner_task_id: str, generation: int) -> None:
        owner = _identifier(owner_task_id, "owner_task_id")
        next_generation = _positive_generation(generation)
        with self._lock:
            current = self._owner_generation.get(owner)
            if current is None or next_generation <= current:
                raise AsyncTaskOwnershipError("owner generation must advance monotonically")
            self._owner_generation[owner] = next_generation

    def deactivate_owner(self, owner_task_id: str) -> None:
        owner = _identifier(owner_task_id, "owner_task_id")
        with self._lock:
            if owner not in self._owner_generation:
                raise AsyncTaskOwnershipError("owner is unknown")
            self._owner_active[owner] = False

    def commit_disposition(self, ref: AsyncTaskRef) -> AsyncCommitDisposition:
        with self._lock:
            if not self._owner_active.get(ref.owner_task_id, False):
                return AsyncCommitDisposition.OWNER_GONE
            if self._owner_generation.get(ref.owner_task_id) != ref.generation:
                return AsyncCommitDisposition.STALE_DROPPED
            if self._current.get((ref.owner_task_id, ref.task_kind)) != ref.async_task_id:
                return AsyncCommitDisposition.SUPERSEDED
            return AsyncCommitDisposition.COMMITTED

    def finalize(self, result: AsyncTaskResult) -> None:
        with self._lock:
            record = self._record(result.task_ref.async_task_id)
            if record.result is not None:
                return
            self.validate_transition(record.state, result.final_state)
            record.state = result.final_state
            record.result = result

    def active_count(self) -> int:
        with self._lock:
            return sum(record.state not in _TERMINAL_STATES for record in self._records.values())

    def retained_count(self) -> int:
        with self._lock:
            return len(self._records)


@dataclass(frozen=True)
class AsyncTaskContext:
    task_ref: AsyncTaskRef
    effective_deadline: float | None
    _registry: AsyncTaskRegistry = field(repr=False, compare=False)

    @property
    def cancellation_requested(self) -> bool:
        return self._registry.cancellation_requested(self.task_ref.async_task_id)

    async def cancellation_point(self) -> None:
        await asyncio.sleep(0)
        if self.cancellation_requested:
            raise asyncio.CancelledError

    def audit(self) -> dict[str, Any]:
        return {
            "async_task_id": self.task_ref.async_task_id,
            "owner_task_id": self.task_ref.owner_task_id,
            "generation": self.task_ref.generation,
            "effective_deadline_present": self.effective_deadline is not None,
            "authorization": False,
            "binding": False,
            "executor_authority": False,
        }


class AsyncTaskHandle:
    """Opaque task handle; holding it grants no runtime authority."""

    def __init__(self, scope: "AsyncTaskScope", ref: AsyncTaskRef, completion: asyncio.Future[AsyncTaskResult]) -> None:
        self._scope = scope
        self.ref = ref
        self._completion = completion

    @property
    def state(self) -> AsyncTaskState:
        return self._scope.registry.state(self.ref.async_task_id)

    def cancel(self) -> bool:
        return self._scope.cancel(self.ref.async_task_id)

    async def wait(self) -> AsyncTaskResult:
        return await asyncio.shield(self._completion)

    def audit(self) -> dict[str, Any]:
        return {
            "task_ref": self.ref.audit(),
            "state": self.state.value,
            "authorization": False,
            "retry": False,
            "dispatch": False,
        }


Operation = Callable[[AsyncTaskContext], Awaitable[AsyncWorkResult]]
CommitCallback = Callable[[AsyncWorkResult], None]


class AsyncTaskScope:
    """One structured asyncio task scope with bounded current-result commits."""

    def __init__(
        self,
        *,
        owner_task_id: str,
        generation: int,
        trace_id: str | None = None,
        store: PhoneHarnessStore | None = None,
        registry_capacity: int = 128,
    ) -> None:
        self.owner_task_id = _identifier(owner_task_id, "owner_task_id")
        self.generation = _positive_generation(generation)
        self.trace_id = _optional_identifier(trace_id, "trace_id")
        if store is not None and not isinstance(store, PhoneHarnessStore):
            raise AsyncTaskPolicyError("store integration requires PhoneHarnessStore")
        self.store = store
        self.registry = AsyncTaskRegistry(capacity=registry_capacity)
        self._task_group: asyncio.TaskGroup | None = None
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._completions: dict[str, asyncio.Future[AsyncTaskResult]] = {}
        self._entered = False
        self._closing = False

    async def __aenter__(self) -> "AsyncTaskScope":
        if self._entered:
            raise AsyncTaskPolicyError("async task scope cannot be re-entered")
        self._task_group = asyncio.TaskGroup()
        await self._task_group.__aenter__()
        self._entered = True
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool | None:
        self._closing = True
        if exc_type is not None:
            self.cancel_all()
        assert self._task_group is not None
        return await self._task_group.__aexit__(exc_type, exc, traceback)

    def spawn(
        self,
        operation: Operation,
        *,
        task_kind: str,
        parent: AsyncTaskHandle | None = None,
        timeout_seconds: float | None = None,
        commit: CommitCallback | None = None,
        trace_id: str | None = None,
        step_id: str | None = None,
        execution_id: str | None = None,
    ) -> AsyncTaskHandle:
        if not self._entered or self._closing or self._task_group is None:
            raise AsyncTaskPolicyError("async work must be spawned inside an active task scope")
        if not callable(operation):
            raise AsyncTaskPolicyError("async operation must be a callable")
        if timeout_seconds is not None:
            if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
                raise AsyncTaskPolicyError("timeout must be a positive duration")
        parent_id = None
        if parent is not None:
            if not isinstance(parent, AsyncTaskHandle) or parent._scope is not self:
                raise AsyncTaskOwnershipError("parent handle must belong to this task scope")
            parent_id = parent.ref.async_task_id
        ref = AsyncTaskRef(
            async_task_id="async.%s" % uuid.uuid4().hex,
            owner_task_id=self.owner_task_id,
            parent_async_task_id=parent_id,
            generation=self.generation,
            task_kind=task_kind,
            created_at_ms=_now_ms(),
        )
        selected_trace_id = trace_id if trace_id is not None else self.trace_id
        self.registry.register(
            ref,
            trace_id=selected_trace_id,
            step_id=step_id,
            execution_id=execution_id,
        )
        loop = asyncio.get_running_loop()
        completion: asyncio.Future[AsyncTaskResult] = loop.create_future()
        raw_task = self._task_group.create_task(
            self._run(
                ref,
                operation,
                timeout_seconds=None if timeout_seconds is None else float(timeout_seconds),
                commit=commit,
                trace_id=selected_trace_id,
                step_id=step_id,
                execution_id=execution_id,
            ),
            name=ref.async_task_id,
        )
        self._tasks[ref.async_task_id] = raw_task
        self._completions[ref.async_task_id] = completion
        raw_task.add_done_callback(lambda task, task_ref=ref: self._raw_task_done(task_ref, task))
        return AsyncTaskHandle(self, ref, completion)

    async def _run(
        self,
        ref: AsyncTaskRef,
        operation: Operation,
        *,
        timeout_seconds: float | None,
        commit: CommitCallback | None,
        trace_id: str | None,
        step_id: str | None,
        execution_id: str | None,
    ) -> None:
        started_at_ms = _now_ms()
        try:
            if not self.registry.mark_running(ref.async_task_id):
                raise asyncio.CancelledError
            loop = asyncio.get_running_loop()
            deadline = None if timeout_seconds is None else loop.time() + timeout_seconds
            context = AsyncTaskContext(ref, deadline, self.registry)
            if deadline is None:
                value = await operation(context)
            else:
                timeout_context = asyncio.timeout_at(deadline)
                try:
                    async with timeout_context:
                        value = await operation(context)
                except TimeoutError as error:
                    if timeout_context.expired():
                        raise _AsyncDeadlineExpired from error
                    raise
            if not isinstance(value, AsyncWorkResult):
                raise AsyncTaskPolicyError("async operation must return AsyncWorkResult")
            if value.artifact_ref is not None and value.artifact_ref.task_id != ref.owner_task_id:
                raise AsyncTaskOwnershipError("async artifact output must share the owner task scope")
            disposition = self.registry.commit_disposition(ref)
            if disposition is AsyncCommitDisposition.COMMITTED and commit is not None:
                try:
                    commit(value)
                except Exception:
                    self._publish_failure(
                        ref,
                        started_at_ms,
                        AsyncTaskErrorCode.INTERNAL_FAILURE,
                        "ResultCommitError",
                        "current result commit failed",
                        trace_id,
                        step_id,
                        execution_id,
                    )
                    return
            self._publish(
                ref,
                AsyncTaskState.SUCCEEDED,
                disposition,
                started_at_ms,
                value=value,
                trace_id=trace_id,
                step_id=step_id,
                execution_id=execution_id,
            )
        except _AsyncDeadlineExpired:
            self._publish(
                ref,
                AsyncTaskState.TIMED_OUT,
                AsyncCommitDisposition.FAILED,
                started_at_ms,
                error_code=AsyncTaskErrorCode.TIMED_OUT,
                error_class="AsyncDeadlineExceeded",
                safe_message="async task deadline expired",
                trace_id=trace_id,
                step_id=step_id,
                execution_id=execution_id,
            )
        except asyncio.CancelledError:
            self._publish(
                ref,
                AsyncTaskState.CANCELLED,
                AsyncCommitDisposition.CANCELLED,
                started_at_ms,
                error_code=AsyncTaskErrorCode.CANCELLED,
                error_class="CooperativeCancellation",
                safe_message="async task acknowledged cancellation",
                trace_id=trace_id,
                step_id=step_id,
                execution_id=execution_id,
            )
            raise
        except Exception as error:
            self._publish_failure(
                ref,
                started_at_ms,
                AsyncTaskErrorCode.TASK_FAILURE,
                type(error).__name__,
                "async task failed with a sanitized typed error",
                trace_id,
                step_id,
                execution_id,
            )

    def _publish_failure(
        self,
        ref: AsyncTaskRef,
        started_at_ms: int,
        error_code: AsyncTaskErrorCode,
        error_class: str,
        safe_message: str,
        trace_id: str | None,
        step_id: str | None,
        execution_id: str | None,
    ) -> None:
        self._publish(
            ref,
            AsyncTaskState.FAILED,
            AsyncCommitDisposition.FAILED,
            started_at_ms,
            error_code=error_code,
            error_class=error_class if _IDENTIFIER.fullmatch(error_class) else "AsyncTaskFailure",
            safe_message=safe_message,
            trace_id=trace_id,
            step_id=step_id,
            execution_id=execution_id,
        )

    def _publish(
        self,
        ref: AsyncTaskRef,
        final_state: AsyncTaskState,
        disposition: AsyncCommitDisposition,
        started_at_ms: int,
        *,
        value: AsyncWorkResult | None = None,
        error_code: AsyncTaskErrorCode | None = None,
        error_class: str | None = None,
        safe_message: str | None = None,
        trace_id: str | None,
        step_id: str | None,
        execution_id: str | None,
    ) -> None:
        if self.registry.result(ref.async_task_id) is not None:
            return
        ended_at_ms = max(_now_ms(), started_at_ms)
        trace_recorded = self._record_trace(
            ref,
            final_state,
            disposition,
            ended_at_ms,
            value=value,
            error_code=error_code,
            error_class=error_class,
            safe_message=safe_message,
            trace_id=trace_id,
            step_id=step_id,
            execution_id=execution_id,
        )
        result = AsyncTaskResult(
            task_ref=ref,
            final_state=final_state,
            commit_disposition=disposition,
            started_at_ms=started_at_ms,
            ended_at_ms=ended_at_ms,
            value=value,
            error_code=error_code,
            error_class=error_class,
            safe_message=safe_message,
            trace_id=trace_id,
            trace_recorded=trace_recorded,
        )
        self.registry.finalize(result)
        completion = self._completions.get(ref.async_task_id)
        if completion is not None and not completion.done():
            completion.set_result(result)

    def _record_trace(
        self,
        ref: AsyncTaskRef,
        final_state: AsyncTaskState,
        disposition: AsyncCommitDisposition,
        ended_at_ms: int,
        *,
        value: AsyncWorkResult | None,
        error_code: AsyncTaskErrorCode | None,
        error_class: str | None,
        safe_message: str | None,
        trace_id: str | None,
        step_id: str | None,
        execution_id: str | None,
    ) -> bool:
        if self.store is None or trace_id is None:
            return False
        event_name = (
            "async.result.stale_dropped"
            if disposition in {
                AsyncCommitDisposition.STALE_DROPPED,
                AsyncCommitDisposition.OWNER_GONE,
                AsyncCommitDisposition.SUPERSEDED,
            }
            else "async.task.finalized"
        )
        attributes = {
            "async_task_id": ref.async_task_id,
            "async_state": final_state.value,
            "commit_disposition": disposition.value,
            "owner_generation": str(ref.generation),
            "task_kind": ref.task_kind,
            "dispatch_count": str(0 if value is None else value.dispatch_count),
            "unknown_outcome": str(bool(value and value.unknown_outcome)).lower(),
        }
        if ref.parent_async_task_id is not None:
            attributes["parent_async_task_id"] = ref.parent_async_task_id
        try:
            return self.store.append_trace_event(
                TraceEvent(
                    event_id="event.async.%s" % uuid.uuid4().hex,
                    task_id=ref.owner_task_id,
                    trace_id=trace_id,
                    step_id=step_id,
                    execution_id=execution_id,
                    event_name=event_name,
                    observed_timestamp_ms=ended_at_ms,
                    error_code=None if error_code is None else error_code.value,
                    error_class=error_class,
                    safe_message=safe_message,
                    artifact_refs=() if value is None or value.artifact_ref is None else (value.artifact_ref,),
                    attributes=attributes,
                )
            )
        except Exception:
            return False

    def _raw_task_done(self, ref: AsyncTaskRef, raw_task: asyncio.Task[None]) -> None:
        if raw_task.cancelled() and self.registry.result(ref.async_task_id) is None:
            now = _now_ms()
            record = self.registry._record(ref.async_task_id)
            self._publish(
                ref,
                AsyncTaskState.CANCELLED,
                AsyncCommitDisposition.CANCELLED,
                now,
                error_code=AsyncTaskErrorCode.CANCELLED,
                error_class="CooperativeCancellation",
                safe_message="async task acknowledged cancellation before start",
                trace_id=record.trace_id,
                step_id=record.step_id,
                execution_id=record.execution_id,
            )

    def cancel(self, async_task_id: str) -> bool:
        identifiers = (async_task_id,) + self.registry.descendants(async_task_id)
        changed = False
        for identifier in reversed(identifiers):
            requested = self.registry.request_cancel(identifier)
            changed = changed or requested
            raw_task = self._tasks.get(identifier)
            if requested and raw_task is not None:
                raw_task.cancel()
        return changed

    def cancel_all(self) -> int:
        requested = 0
        for identifier in tuple(self._tasks):
            try:
                requested += int(self.cancel(identifier))
            except AsyncTaskNotFoundError:
                continue
        return requested

    def advance_generation(self, generation: int) -> None:
        self.registry.advance_owner_generation(self.owner_task_id, generation)
        self.generation = generation

    def deactivate_owner(self) -> None:
        self.registry.deactivate_owner(self.owner_task_id)
