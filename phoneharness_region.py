#!/usr/bin/env python3
"""Region runtime and Smart Screenshot backend foundation over frozen contracts.

S4-M3 Host-only composition: a single active rectangular RegionOfInterest with
its own RegionGeneration (distinct from S4-M0 observation epoch/generation),
analysis tickets gated by the frozen S3-M2 owner-generation commit mechanism,
and region results composed from frozen S4-M2 perception evidence. The backend
is observation/understanding only: it cannot authorize, bind, dispatch,
verify, retry, or mutate device state, and it persists nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import re
import time
from typing import Any, Callable, Iterable, Mapping

from phoneharness_async import (
    AsyncCommitDisposition,
    AsyncTaskErrorCode,
    AsyncTaskRef,
    AsyncTaskRegistry,
    AsyncTaskResult,
    AsyncTaskState,
    AsyncTaskTransitionError,
    AsyncWorkResult,
)
from phoneharness_contracts import ObservationRef
from phoneharness_observation import FreshnessRequirement, ObservationError, ObservationScope, ObservationTracker
from phoneharness_perception import (
    PerceptionLayer,
    PerceptionOrchestrator,
    PerceptionOutcome,
    PerceptionProviderOutcome,
)
from phoneharness_semantic_ui import UIBounds, UIObject


REGION_SCHEMA = "phoneharness.region.v1"
REGION_REF_SCHEMA = "phoneharness.region-ref.v1"
REGION_RESULT_SCHEMA = "phoneharness.region-analysis-result.v1"
REGION_DELTA_SCHEMA = "phoneharness.region-delta.v1"
REGION_COORDINATE_SPACE = "screen_points"
REGION_TASK_KIND = "region.analysis"
MIN_REGION_EDGE_POINTS = 8.0
MAX_REGION_EDGE_POINTS = 32768.0
MAX_GENERATION = 2_147_483_647
DELTA_POLICY_V1 = "ALWAYS_REANALYZE"

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class RegionRuntimeError(RuntimeError):
    """Base class for bounded region-runtime failures."""


class RegionPolicyError(RegionRuntimeError):
    """A region contract or lifecycle transition violated its bounded policy."""


def _identifier(value: Any, field_name: str) -> str:
    normalized = str(value or "").strip()
    if _IDENTIFIER.fullmatch(normalized) is None:
        raise RegionPolicyError(f"{field_name} must be an opaque bounded identifier")
    return normalized


def _timestamp(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RegionPolicyError(f"{field_name} must be a non-negative integer")
    return value


def _new_identifier(prefix: str) -> str:
    return f"{prefix}.{__import__('uuid').uuid4().hex}"


@dataclass(frozen=True)
class RegionGeneration:
    """Version of the selected region; never an observation epoch or generation."""

    value: int

    def __post_init__(self) -> None:
        if isinstance(self.value, bool) or not isinstance(self.value, int) or not 1 <= self.value <= MAX_GENERATION:
            raise RegionPolicyError("region generation must be a positive bounded integer")

    @classmethod
    def initial(cls) -> "RegionGeneration":
        return cls(1)

    def advanced(self) -> "RegionGeneration":
        if self.value >= MAX_GENERATION:
            raise RegionPolicyError("region generation is exhausted")
        return RegionGeneration(self.value + 1)

    def audit(self) -> dict[str, Any]:
        return {
            "generation": self.value,
            "observation_epoch": None,
            "observation_generation": None,
            "authority": False,
        }


def ensure_inside_frame(bounds: UIBounds, *, display_width: float, display_height: float) -> None:
    """Validate region containment in the display frame; never clip silently."""

    for name, number in (("display_width", display_width), ("display_height", display_height)):
        if isinstance(number, bool) or not isinstance(number, (int, float)) or float(number) <= 0.0:
            raise RegionPolicyError(f"{name} must be positive")
    if bounds.x < 0.0 or bounds.y < 0.0:
        raise RegionPolicyError("region origin must be inside the display frame")
    if bounds.x + bounds.width > float(display_width) + 1e-6:
        raise RegionPolicyError("region exceeds the display frame width")
    if bounds.y + bounds.height > float(display_height) + 1e-6:
        raise RegionPolicyError("region exceeds the display frame height")


def intersects(a: UIBounds, b: UIBounds) -> bool:
    """Deterministic strict rectangle overlap; contribution evidence only."""

    overlap_width = min(a.x + a.width, b.x + b.width) - max(a.x, b.x)
    overlap_height = min(a.y + a.height, b.y + b.height) - max(a.y, b.y)
    return overlap_width > 0.0 and overlap_height > 0.0


def _raw_rect_intersects(rect: Any, region_bounds: UIBounds) -> bool:
    if not isinstance(rect, Mapping):
        return False
    values = {}
    for key in ("x", "y", "width", "height"):
        number = rect.get(key)
        if isinstance(number, bool) or not isinstance(number, (int, float)):
            return False
        values[key] = float(number)
    try:
        return intersects(UIBounds(values["x"], values["y"], values["width"], values["height"]), region_bounds)
    except Exception:
        return False


@dataclass(frozen=True)
class RegionOfInterest:
    """Immutable single-active rectangular region in canonical screen points."""

    region_id: str
    generation: RegionGeneration
    bounds: UIBounds
    coordinate_space: str = REGION_COORDINATE_SPACE
    created_at_ms: int = 0

    def __post_init__(self) -> None:
        if self.coordinate_space != REGION_COORDINATE_SPACE:
            raise RegionPolicyError("region geometry must use the canonical screen-point space")
        object.__setattr__(self, "region_id", _identifier(self.region_id, "region_id"))
        if not isinstance(self.generation, RegionGeneration):
            raise RegionPolicyError("region requires a typed RegionGeneration")
        if not isinstance(self.bounds, UIBounds):
            raise RegionPolicyError("region requires typed UIBounds geometry")
        for edge in (self.bounds.width, self.bounds.height):
            if edge < MIN_REGION_EDGE_POINTS:
                raise RegionPolicyError("region edge is below the minimum useful size")
            if edge > MAX_REGION_EDGE_POINTS:
                raise RegionPolicyError("region edge exceeds the supported bound")
        object.__setattr__(self, "created_at_ms", _timestamp(self.created_at_ms, "created_at_ms"))

    def audit(self) -> dict[str, Any]:
        return {
            "region_id": self.region_id,
            "generation": self.generation.value,
            "coordinate_space": self.coordinate_space,
            "authorization": False,
            "binding": False,
            "dispatch": False,
        }


@dataclass(frozen=True)
class RegionRef:
    """Non-authoritative binding of a result/request to a region version."""

    region_id: str
    generation: RegionGeneration
    observation_ref: ObservationRef | None = None
    session_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "region_id", _identifier(self.region_id, "region_id"))
        if not isinstance(self.generation, RegionGeneration):
            raise RegionPolicyError("region reference requires a typed RegionGeneration")
        if self.observation_ref is not None and not isinstance(self.observation_ref, ObservationRef):
            raise RegionPolicyError("region reference observation must use ObservationRef")
        if self.session_id is not None:
            object.__setattr__(self, "session_id", _identifier(self.session_id, "session_id"))

    def audit(self) -> dict[str, Any]:
        return {
            "region_id": self.region_id,
            "generation": self.generation.value,
            "authorization": False,
            "binding": False,
            "execution_permission": False,
            "action_candidate": False,
        }


class RegionAnalysisStatus(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    STALE_DROPPED = "STALE_DROPPED"
    FAILED = "FAILED"
    SECURE_BLOCKED = "SECURE_BLOCKED"


@dataclass(frozen=True)
class RegionAnalysisTicket:
    """Non-authoritative binding of one analysis attempt to a region version."""

    ticket_id: str
    region_ref: RegionRef
    async_task_ref: AsyncTaskRef | None
    observation_ref: ObservationRef | None
    expected_scope: ObservationScope | None
    session_id: str | None
    session_active: Callable[[], bool] | None
    started_at_ms: int

    def audit(self) -> dict[str, Any]:
        return {
            "ticket_id": self.ticket_id,
            "region_id": self.region_ref.region_id,
            "generation": self.region_ref.generation.value,
            "authorization": False,
            "dispatch": False,
        }


@dataclass(frozen=True)
class RegionAnalysisResult:
    """Region analysis outcome composed from frozen evidence; never authoritative."""

    status: RegionAnalysisStatus
    region_ref: RegionRef
    observation_ref: ObservationRef | None
    evidence: Any | None
    sources: tuple[str, ...]
    ui_object_count: int
    providers: tuple[Any, ...] = ()
    resolution: Any | None = None
    fail_reason: str | None = None
    commit_disposition: str | None = None
    created_at_ms: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", RegionAnalysisStatus(self.status))
        if not isinstance(self.region_ref, RegionRef):
            raise RegionPolicyError("region result requires a typed RegionRef")
        if self.observation_ref is not None and not isinstance(self.observation_ref, ObservationRef):
            raise RegionPolicyError("region result observation must use ObservationRef")
        if self.status is RegionAnalysisStatus.READY and self.observation_ref is None:
            raise RegionPolicyError("ready region result requires an observation binding")
        sources = tuple(self.sources)
        if len(sources) > 4 or any(not isinstance(item, str) or not item for item in sources):
            raise RegionPolicyError("region result sources must be bounded")
        object.__setattr__(self, "sources", sources)
        if isinstance(self.ui_object_count, bool) or not isinstance(self.ui_object_count, int) or self.ui_object_count < 0:
            raise RegionPolicyError("region result ui object count is invalid")
        if self.fail_reason is not None:
            object.__setattr__(self, "fail_reason", _identifier(self.fail_reason, "fail_reason"))
        if self.commit_disposition is not None:
            object.__setattr__(self, "commit_disposition", _identifier(self.commit_disposition, "commit_disposition"))
        object.__setattr__(self, "created_at_ms", _timestamp(self.created_at_ms, "created_at_ms"))

    def content_digest(self) -> str:
        """Digest of the redacted result content; excludes observation identity."""

        payload = {
            "region_id": self.region_ref.region_id,
            "generation": self.region_ref.generation.value,
            "sources": list(self.sources),
            "ui_object_count": self.ui_object_count,
            "block_count": self.evidence.block_count if self.evidence is not None else 0,
            "secure_surface": bool(getattr(self.evidence, "secure_surface", False)),
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        ).hexdigest()

    def audit(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "region_id": self.region_ref.region_id,
            "generation": self.region_ref.generation.value,
            "authorization": False,
            "binding": False,
            "dispatch": False,
            "semantic_success": False,
        }

    def summary(self) -> dict[str, Any]:
        return {
            "region_id": self.region_ref.region_id,
            "generation": self.region_ref.generation.value,
            "status": self.status.value,
            "sources": list(self.sources),
            "ui_object_count": self.ui_object_count,
            "block_count": self.evidence.block_count if self.evidence is not None else 0,
            "observation_id": self.observation_ref.observation_id if self.observation_ref else None,
            "fail_reason": self.fail_reason,
            "text_content": None,
            "geometry": None,
        }


@dataclass(frozen=True)
class RegionBackendState:
    """Non-authoritative backend state projection for the future S6-M7 UX."""

    has_active_region: bool
    region_id: str | None
    generation: int | None
    geometry: UIBounds | None
    coordinate_space: str
    last_accepted_status: str
    last_result_observation_id: str | None
    stale_dropped_count: int
    failed_count: int
    secure_blocked_count: int

    def audit(self) -> dict[str, Any]:
        return {
            "single_active_region": True,
            "authorization": False,
            "binding": False,
            "dispatch": False,
        }


class RegionRuntime:
    """Single-active-region lifecycle with its own generation counter."""

    def __init__(
        self,
        *,
        async_registry: AsyncTaskRegistry | None = None,
        now_ms: Callable[[], int] | None = None,
        id_factory: Callable[[str], str] = _new_identifier,
    ) -> None:
        if async_registry is not None and not isinstance(async_registry, AsyncTaskRegistry):
            raise RegionPolicyError("region runtime requires the frozen S3-M2 async registry")
        self.async_registry = async_registry
        self._now_ms = now_ms or (lambda: time.time_ns() // 1_000_000)
        self._id_factory = id_factory
        self._active: RegionOfInterest | None = None
        self._generation: RegionGeneration | None = None
        self._owner_task_id: str | None = None
        self._retired_region_ids: set[str] = set()
        self._closed = False
        self._last_accepted_status = "NONE"
        self._last_result_observation_id: str | None = None
        self._stale_dropped_count = 0
        self._failed_count = 0
        self._secure_blocked_count = 0

    def create(self, bounds: UIBounds, *, display_width: float, display_height: float) -> RegionOfInterest:
        self._ensure_active_lifecycle()
        if self._active is not None:
            raise RegionPolicyError("single active region: delete the current region first")
        ensure_inside_frame(bounds, display_width=display_width, display_height=display_height)
        generation = RegionGeneration.initial()
        candidate_id = self._id_factory("region")
        if candidate_id in self._retired_region_ids:
            raise RegionPolicyError("region identity reuse is not permitted across incarnations")
        region = RegionOfInterest(
            candidate_id, generation, bounds, created_at_ms=self._now_ms()
        )
        self._active = region
        self._generation = generation
        self._owner_task_id = f"region.{region.region_id}"
        return region

    def update_geometry(
        self, region_id: str, bounds: UIBounds, *, display_width: float, display_height: float
    ) -> RegionOfInterest:
        self._require_active(region_id)
        ensure_inside_frame(bounds, display_width=display_width, display_height=display_height)
        return self._promote(bounds)

    def reset(self, region_id: str) -> RegionOfInterest:
        self._require_active(region_id)
        return self._promote(self._active.bounds)

    def delete(self, region_id: str) -> None:
        self._require_active(region_id)
        if self.async_registry is not None and self._owner_task_id:
            try:
                self.async_registry.deactivate_owner(self._owner_task_id)
            except Exception:
                pass
        self._retired_region_ids.add(self._active.region_id)
        self._active = None
        self._generation = None
        self._owner_task_id = None

    def close(self) -> None:
        """End this runtime lifecycle and release incarnation tombstones."""

        if self._closed:
            return
        if self.async_registry is not None and self._owner_task_id:
            try:
                self.async_registry.deactivate_owner(self._owner_task_id)
            except Exception:
                pass
        self._active = None
        self._generation = None
        self._owner_task_id = None
        self._retired_region_ids.clear()
        self._closed = True

    def current(self) -> RegionOfInterest | None:
        return self._active

    def current_generation(self, region_id: str) -> RegionGeneration | None:
        if self._active is None or self._active.region_id != _identifier(region_id, "region_id"):
            return None
        return self._generation

    def register_analysis(self, region: RegionOfInterest, *, async_task_id: str, trace_id: str) -> AsyncTaskRef | None:
        if self.async_registry is None:
            return None
        if self._active is None or region.region_id != self._active.region_id or region.generation != self._generation:
            raise RegionPolicyError("analysis must target the current active region generation")
        ref = AsyncTaskRef(
            _identifier(async_task_id, "async_task_id"),
            self._owner_task_id,
            region.generation.value,
            REGION_TASK_KIND,
            self._now_ms(),
        )
        self.async_registry.register(ref, trace_id=trace_id, step_id=None, execution_id=None)
        self.async_registry.mark_running(async_task_id)
        return ref

    def finalize_analysis(
        self,
        async_task_ref: AsyncTaskRef | None,
        *,
        succeeded: bool,
        disposition: AsyncCommitDisposition,
        reason: str | None = None,
    ) -> None:
        if self.async_registry is None or async_task_ref is None:
            return
        metadata = (("status", "STALE_DROPPED" if not succeeded else "READY"),)
        if reason:
            metadata = metadata + (("reason", reason[:120]),)
        if disposition is AsyncCommitDisposition.CANCELLED:
            try:
                self.async_registry.finalize(
                    AsyncTaskResult(
                        async_task_ref,
                        AsyncTaskState.CANCELLED,
                        AsyncCommitDisposition.CANCELLED,
                        started_at_ms=self._now_ms(),
                        ended_at_ms=self._now_ms(),
                        error_code=AsyncTaskErrorCode.CANCELLED,
                        safe_message=(reason or "region analysis cancelled")[:120],
                    )
                )
            except Exception:
                pass
            return
        if succeeded:
            result = AsyncTaskResult(
                async_task_ref,
                __import__("phoneharness_async", fromlist=["AsyncTaskState"]).AsyncTaskState.SUCCEEDED,
                disposition,
                started_at_ms=self._now_ms(),
                ended_at_ms=self._now_ms(),
                value=AsyncWorkResult(safe_metadata=metadata, dispatch_count=0),
                trace_id=None,
            )
            self.async_registry.finalize(result)
        else:
            result = AsyncTaskResult(
                async_task_ref,
                __import__("phoneharness_async", fromlist=["AsyncTaskState"]).AsyncTaskState.FAILED,
                AsyncCommitDisposition.FAILED,
                started_at_ms=self._now_ms(),
                ended_at_ms=self._now_ms(),
                error_code=AsyncTaskErrorCode.TASK_FAILURE,
                safe_message=(reason or "region analysis failed")[:120],
            )
            try:
                self.async_registry.finalize(result)
            except AsyncTaskTransitionError:
                pass

    def record_result(self, result: RegionAnalysisResult) -> None:
        if result.status is RegionAnalysisStatus.READY:
            self._last_accepted_status = "READY"
            self._last_result_observation_id = (
                result.observation_ref.observation_id if result.observation_ref else None
            )
        elif result.status is RegionAnalysisStatus.STALE_DROPPED:
            self._stale_dropped_count += 1
        elif result.status is RegionAnalysisStatus.FAILED:
            self._failed_count += 1
        elif result.status is RegionAnalysisStatus.SECURE_BLOCKED:
            self._secure_blocked_count += 1

    def region_state(self) -> RegionBackendState:
        return RegionBackendState(
            has_active_region=self._active is not None,
            region_id=self._active.region_id if self._active else None,
            generation=self._generation.value if self._generation else None,
            geometry=self._active.bounds if self._active else None,
            coordinate_space=REGION_COORDINATE_SPACE,
            last_accepted_status=self._last_accepted_status,
            last_result_observation_id=self._last_result_observation_id,
            stale_dropped_count=self._stale_dropped_count,
            failed_count=self._failed_count,
            secure_blocked_count=self._secure_blocked_count,
        )

    def _require_active(self, region_id: str) -> None:
        self._ensure_active_lifecycle()
        if self._active is None or self._active.region_id != _identifier(region_id, "region_id"):
            raise RegionPolicyError("region is not the current active region")

    def _ensure_active_lifecycle(self) -> None:
        if self._closed:
            raise RegionPolicyError("region runtime lifecycle is closed")

    def _promote(self, bounds: UIBounds) -> RegionOfInterest:
        generation = self._generation.advanced()
        region = RegionOfInterest(self._active.region_id, generation, bounds, created_at_ms=self._now_ms())
        self._active = region
        self._generation = generation
        if self.async_registry is not None and self._owner_task_id:
            try:
                self.async_registry.advance_owner_generation(self._owner_task_id, generation.value)
            except Exception:
                pass
        return region


@dataclass(frozen=True)
class RegionDeltaSnapshot:
    """Minimal structured/result-digest delta contract; optimization only."""

    region_id: str
    previous_generation: int | None
    current_generation: int | None
    previous_observation_id: str | None
    current_observation_id: str | None
    previous_digest: str | None
    current_digest: str | None
    comparable: bool
    equal: bool
    optimization_eligible: bool
    policy: str = DELTA_POLICY_V1

    def audit(self) -> dict[str, Any]:
        return {
            "delta_is_freshness": False,
            "equal_proves_world_unchanged": False,
            "equal_is_authorization": False,
            "bypasses_fresh_observation": False,
            "authorization": False,
        }

    @classmethod
    def assess(cls, previous: RegionAnalysisResult | None, current: RegionAnalysisResult | None) -> "RegionDeltaSnapshot":
        comparable = (
            previous is not None
            and current is not None
            and previous.status is RegionAnalysisStatus.READY
            and current.status is RegionAnalysisStatus.READY
            and previous.region_ref.region_id == current.region_ref.region_id
            and previous.region_ref.generation.value == current.region_ref.generation.value
        )
        equal = bool(
            comparable
            and previous.content_digest() == current.content_digest()
        )
        return cls(
            previous.region_ref.region_id if previous else "",
            previous.region_ref.generation.value if previous else None,
            current.region_ref.generation.value if current else None,
            previous.observation_ref.observation_id if previous and previous.observation_ref else None,
            current.observation_ref.observation_id if current and current.observation_ref else None,
            previous.content_digest() if previous and previous.status is RegionAnalysisStatus.READY else None,
            current.content_digest() if current and current.status is RegionAnalysisStatus.READY else None,
            comparable,
            equal,
            False,
        )


class RegionAnalyzer:
    """Structured-first region analysis reusing the frozen S4-M2 orchestrator.

    The delegate is an instance of the frozen ``PerceptionOrchestrator`` class
    with region-scoped provider callables; no second orchestrator
    implementation exists. Region OCR/Vision payloads are filtered to the
    active region and stamped with its region_id before normalization.
    """

    def __init__(
        self,
        *,
        tracker: ObservationTracker,
        runtime: RegionRuntime,
        ocr_capture: Callable[[ObservationScope, str], Mapping[str, Any]] | None = None,
        vision_capture: Callable[[ObservationScope, str], Mapping[str, Any]] | None = None,
        ocr_source: str = "ocr.visionframework",
        vision_source: str = "vision.provider",
        now_ms: Callable[[], int] | None = None,
        id_factory: Callable[[str], str] = _new_identifier,
    ) -> None:
        if not isinstance(tracker, ObservationTracker):
            raise RegionPolicyError("region analyzer requires ObservationTracker")
        if not isinstance(runtime, RegionRuntime):
            raise RegionPolicyError("region analyzer requires RegionRuntime")
        self.tracker = tracker
        self.runtime = runtime
        self._screen_ocr = ocr_capture
        self._screen_vision = vision_capture
        self._active_region: RegionOfInterest | None = None
        self._finalized: dict[str, RegionAnalysisResult] = {}
        self._evidence_lineage: dict[int, str] = {}
        self._now_ms = now_ms or (lambda: time.time_ns() // 1_000_000)
        self._id_factory = id_factory
        self.orchestrator = PerceptionOrchestrator(
            tracker,
            ocr_capture=self._region_ocr_capture,
            vision_capture=self._region_vision_capture,
            ocr_source=ocr_source,
            vision_source=vision_source,
            now_ms=now_ms or (lambda: time.time_ns() // 1_000_000),
        )

    def _region_ocr_capture(self, scope: ObservationScope, trace_id: str) -> Mapping[str, Any]:
        if self._screen_ocr is None:
            raise RegionPolicyError("region OCR provider is not configured")
        payload = self._screen_ocr(scope, trace_id)
        region = self._active_region
        if region is None or not isinstance(payload, Mapping):
            return payload
        texts = payload.get("texts")
        if not isinstance(texts, list):
            return payload
        filtered = []
        for raw in texts:
            if not isinstance(raw, Mapping) or not _raw_rect_intersects(raw.get("rect"), region.bounds):
                continue
            filtered.append({**raw, "region_id": region.region_id})
        return {**payload, "texts": filtered}

    def _region_vision_capture(self, scope: ObservationScope, trace_id: str) -> Mapping[str, Any]:
        if self._screen_vision is None:
            raise RegionPolicyError("region vision provider is not configured")
        payload = self._screen_vision(scope, trace_id)
        region = self._active_region
        if region is None or not isinstance(payload, Mapping):
            return payload
        regions = payload.get("regions")
        if not isinstance(regions, list):
            return payload
        filtered = [
            raw
            for raw in regions
            if isinstance(raw, Mapping) and _raw_rect_intersects(raw.get("rect"), region.bounds)
        ]
        return {**payload, "regions": filtered}

    def begin_analysis(
        self,
        region: RegionOfInterest,
        *,
        observation_ref: ObservationRef | None,
        expected_scope: ObservationScope | None = None,
        session_id: str | None = None,
        session_active: Callable[[], bool] | None = None,
        trace_id: str,
    ) -> RegionAnalysisTicket:
        current = self.runtime.current()
        if current is None or current.region_id != region.region_id or current.generation != region.generation:
            raise RegionPolicyError("analysis must target the current active region generation")
        if session_active is not None and not session_active():
            raise RegionPolicyError("region session is not active")
        async_task_id = self._id_factory("asynctask")
        async_ref = self.runtime.register_analysis(
            region, async_task_id=async_task_id, trace_id=trace_id
        )
        return RegionAnalysisTicket(
            ticket_id=self._id_factory("regionticket"),
            region_ref=RegionRef(region.region_id, region.generation, observation_ref, session_id),
            async_task_ref=async_ref,
            observation_ref=observation_ref,
            expected_scope=expected_scope,
            session_id=session_id,
            session_active=session_active,
            started_at_ms=self._now_ms(),
        )

    def complete_analysis(
        self,
        ticket: RegionAnalysisTicket,
        outcome: PerceptionOutcome | None,
        *,
        evidence: Any | None = None,
        error: str | None = None,
        secure_blocked: bool = False,
    ) -> RegionAnalysisResult:
        """Evaluate one analysis attempt exactly once; the first terminal wins."""

        finalized = self._finalized.get(ticket.ticket_id)
        if finalized is not None:
            return finalized

        def result(status: RegionAnalysisStatus, *, evidence_override=None, sources=(), outcome_ref=None, reason=None, disposition=None):
            evidence_value = evidence_override or evidence or (outcome.evidence if outcome is not None else None)
            observation = outcome_ref or (outcome.evidence.observation_ref if outcome is not None and outcome.evidence is not None else ticket.observation_ref)
            built = RegionAnalysisResult(
                status,
                ticket.region_ref,
                observation,
                evidence_value,
                sources,
                outcome.ui_object_count if outcome is not None else 0,
                tuple(outcome.providers) if outcome is not None else (),
                outcome.resolution if outcome is not None else None,
                reason,
                disposition,
                self._now_ms(),
            )
            self.runtime.record_result(built)
            self._finalized[ticket.ticket_id] = built
            self._forget_evidence_lineage(ticket.ticket_id)
            return built

        def drop(reason: str, disposition: AsyncCommitDisposition | None = None):
            effective = disposition or AsyncCommitDisposition.STALE_DROPPED
            self.runtime.finalize_analysis(
                ticket.async_task_ref, succeeded=True, disposition=effective, reason=reason
            )
            return result(
                RegionAnalysisStatus.STALE_DROPPED, reason=reason, disposition=effective.value
            )

        if ticket.session_active is not None and not ticket.session_active():
            return drop("SESSION_INACTIVE", AsyncCommitDisposition.OWNER_GONE)
        current = self.runtime.current()
        if (
            current is None
            or current.region_id != ticket.region_ref.region_id
            or current.generation.value != ticket.region_ref.generation.value
        ):
            return drop("REGION_GENERATION_SUPERSEDED")
        if ticket.async_task_ref is not None and self.runtime.async_registry is not None:
            disposition = self.runtime.async_registry.commit_disposition(ticket.async_task_ref)
            if disposition is not AsyncCommitDisposition.COMMITTED:
                return drop(disposition.value, disposition)
            if self.runtime.async_registry.cancellation_requested(ticket.async_task_ref.async_task_id):
                return drop("CANCELLED", AsyncCommitDisposition.CANCELLED)
        if ticket.observation_ref is not None and ticket.expected_scope is not None:
            assessment = self.tracker.assess(
                ticket.observation_ref,
                FreshnessRequirement.current_epoch(),
                expected_scope=ticket.expected_scope,
            )
            if not assessment.satisfies:
                return drop(f"OBSERVATION_{assessment.reason.value}")
        evidence_value = evidence or (outcome.evidence if outcome is not None else None)
        if evidence_value is not None and ticket.observation_ref is not None:
            evidence_observation = getattr(evidence_value, "observation_ref", None)
            if evidence_observation is not None and evidence_observation != ticket.observation_ref:
                if not self._evidence_matches_ticket_lineage(ticket, evidence_value, evidence_observation):
                    return drop("PROVENANCE_OBSERVATION_MISMATCH")
            if getattr(evidence_value, "secure_surface", False):
                self.runtime.finalize_analysis(
                    ticket.async_task_ref,
                    succeeded=True,
                    disposition=AsyncCommitDisposition.COMMITTED,
                    reason="SECURE_BLOCKED",
                )
                return result(
                    RegionAnalysisStatus.SECURE_BLOCKED,
                    sources=("SECURE",),
                    outcome_ref=ticket.observation_ref,
                    reason="SECURE_BLOCKED",
                )
        if secure_blocked or (outcome is not None and (outcome.secure_surface or outcome.fail_closed_reason == "SECURE_SURFACE")):
            self.runtime.finalize_analysis(
                ticket.async_task_ref,
                succeeded=True,
                disposition=AsyncCommitDisposition.COMMITTED,
                reason="SECURE_BLOCKED",
            )
            return result(
                RegionAnalysisStatus.SECURE_BLOCKED,
                sources=("SECURE",),
                outcome_ref=ticket.observation_ref,
                reason="SECURE_BLOCKED",
            )
        if error is None and outcome is None and evidence_value is not None:
            built = result(
                RegionAnalysisStatus.READY,
                sources=(getattr(evidence_value, "source", "region.analysis"),),
                outcome_ref=ticket.observation_ref,
            )
            self.runtime.finalize_analysis(ticket.async_task_ref, succeeded=True, disposition=AsyncCommitDisposition.COMMITTED)
            return built
        if error is not None or outcome is None:
            reason = error or "ANALYSIS_NO_OUTCOME"
            self.runtime.finalize_analysis(
                ticket.async_task_ref, succeeded=False, disposition=AsyncCommitDisposition.FAILED, reason=reason
            )
            return result(RegionAnalysisStatus.FAILED, reason=reason, disposition="FAILED")
        if outcome.layer is PerceptionLayer.UNRESOLVED:
            reason = outcome.fail_closed_reason or "REGION_UNRESOLVED"
            self.runtime.finalize_analysis(
                ticket.async_task_ref, succeeded=False, disposition=AsyncCommitDisposition.FAILED, reason=reason
            )
            return result(RegionAnalysisStatus.FAILED, sources=(outcome.layer.value,), outcome_ref=ticket.observation_ref, reason=reason)
        built = result(RegionAnalysisStatus.READY, sources=(outcome.layer.value,), outcome_ref=ticket.observation_ref)
        self.runtime.finalize_analysis(ticket.async_task_ref, succeeded=True, disposition=AsyncCommitDisposition.COMMITTED)
        return built

    def analyze(
        self,
        region: RegionOfInterest,
        *,
        structured_snapshot: Any,
        structured_objects: Iterable[UIObject],
        expected_scope: ObservationScope,
        descriptor: Any | None = None,
        structured_complete: bool = False,
        trace_id: str,
        session_id: str | None = None,
        session_active: Callable[[], bool] | None = None,
        secure_surface: bool = False,
        include_ocr: bool = True,
    ) -> RegionAnalysisResult:
        if secure_surface:
            ticket = self.begin_analysis(
                region,
                observation_ref=getattr(structured_snapshot, "observation_ref", None),
                expected_scope=expected_scope,
                session_id=session_id,
                session_active=session_active,
                trace_id=trace_id,
            )
            return self.complete_analysis(ticket, None, secure_blocked=True)
        self._active_region = region
        try:
            ticket = self.begin_analysis(
                region,
                observation_ref=getattr(structured_snapshot, "observation_ref", None),
                expected_scope=expected_scope,
                session_id=session_id,
                session_active=session_active,
                trace_id=trace_id,
            )
            region_objects = tuple(
                item
                for item in structured_objects
                if isinstance(item, UIObject) and item.bounds is not None and intersects(item.bounds, region.bounds)
            )
            if descriptor is not None:
                outcome = self.orchestrator.resolve_target(
                    descriptor,
                    structured_snapshot,
                    region_objects,
                    expected_scope=expected_scope,
                    structured_complete=bool(region_objects) and bool(structured_complete),
                    trace_id=trace_id,
                )
            else:
                outcome = self.orchestrator.understand(
                    structured_snapshot,
                    region_objects,
                    expected_scope=expected_scope,
                    include_ocr=include_ocr,
                    trace_id=trace_id,
                )
            if outcome.evidence is not None:
                self._evidence_lineage[id(outcome.evidence)] = ticket.ticket_id
            return self.complete_analysis(ticket, outcome)
        finally:
            self._active_region = None

    def _evidence_matches_ticket_lineage(
        self,
        ticket: RegionAnalysisTicket,
        evidence: Any,
        evidence_observation: ObservationRef,
    ) -> bool:
        if self._evidence_lineage.get(id(evidence)) != ticket.ticket_id:
            return False
        try:
            snapshot = self.tracker.snapshot(evidence_observation)
        except ObservationError:
            return False
        expected = ticket.expected_scope
        if expected is None:
            return False
        scope = snapshot.scope
        if not (
            scope.task_id == expected.task_id
            and scope.session_id == expected.session_id
            and scope.runtime_instance_id == expected.runtime_instance_id
            and scope.frontmost_app_id == expected.frontmost_app_id
            and scope.process_instance_ref == expected.process_instance_ref
        ):
            return False
        assessment = self.tracker.assess(
            evidence_observation,
            FreshnessRequirement.current_epoch(),
            expected_scope=scope,
        )
        if not assessment.satisfies:
            return False
        frame_digest = getattr(evidence, "frame_digest", None)
        return frame_digest is None or frame_digest == snapshot.fingerprint

    def _forget_evidence_lineage(self, ticket_id: str) -> None:
        for evidence_id, owner_ticket_id in tuple(self._evidence_lineage.items()):
            if owner_ticket_id == ticket_id:
                del self._evidence_lineage[evidence_id]


__all__ = [
    "DELTA_POLICY_V1",
    "REGION_COORDINATE_SPACE",
    "RegionAnalysisResult",
    "RegionAnalysisStatus",
    "RegionAnalysisTicket",
    "RegionAnalyzer",
    "RegionBackendState",
    "RegionDeltaSnapshot",
    "RegionGeneration",
    "RegionOfInterest",
    "RegionPolicyError",
    "RegionRef",
    "RegionRuntime",
    "RegionRuntimeError",
    "ensure_inside_frame",
    "intersects",
]
