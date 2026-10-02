#!/usr/bin/env python3
"""Governed OCR / vision perception composition over frozen S4-M0/S4-M1 contracts.

This Host-only module normalizes ephemeral OCR/vision provider output into
observation-scoped semantic evidence and feeds the existing S4-M1 semantic UI
machinery. Raw OCR tap points are quarantined at this boundary: they are never
semantic identity, candidates, bindings, authorization, or dispatch
instructions. This module cannot authorize, bind, dispatch, verify, retry, or
mutate device state, and it persists nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re
import time
from typing import Any, Callable, Iterable, Mapping

from phoneharness_contracts import ObservedTargetRef
from phoneharness_observation import (
    InvalidationReason,
    ObservationScope,
    ObservationStateConflict,
    ObservationTracker,
)
from phoneharness_semantic_ui import (
    ActionCandidateFactory,
    DynamicLegalOperationBuilder,
    EscalationRequirement,
    ResolutionState,
    SemanticResolution,
    SemanticTargetDescriptor,
    SemanticTargetResolver,
    SemanticUIError,
    UIBounds,
    UIObject,
)


PERCEPTION_SCHEMA = "phoneharness.perception.v1"
READ_CAPABILITY = "capability.ui.read.v1"
MAX_TEXT_LENGTH = 256
MAX_BLOCKS = 64
MAX_REGIONS = 64
MAX_LATENCY_MS = 60000

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")

SAFE_VISION_ROLES = frozenset(
    {"text", "text_field", "button", "link", "switch", "checkbox", "menu_item", "option", "radio", "image", "other"}
)


class PerceptionError(RuntimeError):
    """Base class for bounded perception-composition failures."""


class PerceptionPolicyError(PerceptionError):
    """Perception input or composition violated its bounded policy."""


class PerceptionLayer(str, Enum):
    STRUCTURED = "STRUCTURED"
    OCR = "OCR"
    VISION = "VISION"
    UNRESOLVED = "UNRESOLVED"


def _identifier(value: Any, field_name: str) -> str:
    normalized = str(value or "").strip()
    if _IDENTIFIER.fullmatch(normalized) is None:
        raise PerceptionPolicyError(f"{field_name} must be an opaque bounded identifier")
    return normalized


def _optional_identifier(value: Any, field_name: str) -> str | None:
    return None if value is None else _identifier(value, field_name)


def _normalized_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _confidence(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.0 <= float(value) <= 1.0:
        raise PerceptionPolicyError("perception confidence must be within 0.0 through 1.0")
    return float(value)


def _optional_provider_confidence(value: Any) -> float:
    return 0.0 if value is None else _confidence(value)


def _bounded_int(value: Any, field_name: str, *, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise PerceptionPolicyError(f"{field_name} is outside its bounded range")
    return value


def _bounds_from_rect(rect: Any) -> UIBounds:
    if not isinstance(rect, Mapping):
        raise PerceptionPolicyError("perception bounds must be a mapping")
    values = {}
    for key in ("x", "y", "width", "height"):
        number = rect.get(key)
        if isinstance(number, bool) or not isinstance(number, (int, float)):
            raise PerceptionPolicyError("perception bounds require finite numbers")
        values[key] = float(number)
    return UIBounds(values["x"], values["y"], values["width"], values["height"])


def _canonical_digest(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class OCRTextBlock:
    """One ephemeral recognized-text block; geometry is supporting evidence only."""

    text: str
    confidence: float
    bounds: UIBounds
    reading_order: int
    source: str
    language: str | None = None
    region_id: str | None = None

    def __post_init__(self) -> None:
        normalized = _normalized_text(self.text)
        if not normalized or len(normalized) > MAX_TEXT_LENGTH:
            raise PerceptionPolicyError("OCR block text must be non-empty bounded text")
        object.__setattr__(self, "text", normalized)
        object.__setattr__(self, "confidence", _confidence(self.confidence))
        if not isinstance(self.bounds, UIBounds):
            raise PerceptionPolicyError("OCR block requires typed bounds")
        object.__setattr__(self, "reading_order", _bounded_int(self.reading_order, "reading_order", maximum=MAX_BLOCKS))
        object.__setattr__(self, "source", _identifier(self.source, "OCR block source"))
        object.__setattr__(self, "language", _optional_identifier(self.language, "OCR language"))
        object.__setattr__(self, "region_id", _optional_identifier(self.region_id, "OCR region"))

    def content_key(self) -> str:
        """Deterministic content key shared by every visual text layer."""

        return "visualtext." + hashlib.sha256(self.text.encode("utf-8")).hexdigest()[:24]

    def audit(self) -> dict[str, Any]:
        return {
            "reading_order": self.reading_order,
            "confidence": self.confidence,
            "tap_point": None,
            "authorization": False,
            "binding": False,
        }


@dataclass(frozen=True)
class OCRFrameCapture:
    """Normalized ephemeral result of one OCR frame; raw tap points are dropped here."""

    source: str
    point_width: float
    point_height: float
    frame_digest: str
    blocks: tuple[OCRTextBlock, ...]
    captured_at_ms: int
    secure_surface: bool = False
    quarantined_tap_point_count: int = 0
    skipped_block_count: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", _identifier(self.source, "OCR frame source"))
        for name in ("point_width", "point_height"):
            number = getattr(self, name)
            if isinstance(number, bool) or not isinstance(number, (int, float)) or float(number) <= 0.0:
                raise PerceptionPolicyError("OCR frame point size must be positive")
        if not _DIGEST.fullmatch(self.frame_digest or ""):
            raise PerceptionPolicyError("OCR frame digest must be lowercase SHA-256")
        blocks = tuple(self.blocks)
        if len(blocks) > MAX_BLOCKS or any(not isinstance(block, OCRTextBlock) for block in blocks):
            raise PerceptionPolicyError("OCR frame blocks must be bounded and typed")
        if not isinstance(self.secure_surface, bool):
            raise PerceptionPolicyError("OCR secure_surface must be boolean")
        object.__setattr__(
            self,
            "quarantined_tap_point_count",
            _bounded_int(self.quarantined_tap_point_count, "quarantined_tap_point_count", maximum=MAX_BLOCKS),
        )
        object.__setattr__(
            self, "skipped_block_count", _bounded_int(self.skipped_block_count, "skipped_block_count", maximum=MAX_BLOCKS)
        )

    def audit(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "block_count": len(self.blocks),
            "quarantined_tap_point_count": self.quarantined_tap_point_count,
            "secure_surface": self.secure_surface,
            "authorization": False,
            "binding": False,
            "dispatch": False,
        }


def normalize_ocr_payload(
    payload: Mapping[str, Any],
    *,
    source: str,
    captured_at_ms: int,
    region_id: str | None = None,
) -> OCRFrameCapture:
    """Adapt the existing device OCR payload shape into the typed ephemeral contract.

    The legacy ``tap`` coordinate emitted with each block is quarantined: it is
    counted and dropped, never carried into typed evidence, candidates, or
    bindings.
    """

    source = _identifier(source, "OCR source")
    if not isinstance(payload, Mapping):
        raise PerceptionPolicyError("OCR payload must be a mapping")
    screen = payload.get("screen")
    if not isinstance(screen, Mapping):
        raise PerceptionPolicyError("OCR payload requires screen point geometry")
    secure_surface = payload.get("secure_surface") is True
    blocks: list[OCRTextBlock] = []
    quarantined = 0
    skipped = 0
    raw_blocks = payload.get("texts")
    if not isinstance(raw_blocks, list) or len(raw_blocks) > MAX_BLOCKS:
        raise PerceptionPolicyError("OCR payload texts must be a bounded list")
    for order, raw in enumerate(raw_blocks):
        if not isinstance(raw, Mapping):
            skipped += 1
            continue
        if "tap" in raw:
            quarantined += 1
        try:
            block = OCRTextBlock(
                text=raw.get("text"),
                confidence=raw.get("confidence", 0.0),
                bounds=_bounds_from_rect(raw.get("rect")),
                reading_order=order,
                source=source,
                language=raw.get("language"),
                region_id=raw.get("region_id") or region_id,
            )
        except (PerceptionError, SemanticUIError):
            skipped += 1
            continue
        blocks.append(block)
    return OCRFrameCapture(
        source,
        float(screen.get("width") or 0.0),
        float(screen.get("height") or 0.0),
        _canonical_digest(payload),
        tuple(blocks),
        captured_at_ms,
        secure_surface,
        quarantined,
        skipped,
    )


@dataclass(frozen=True)
class VisualFrameEvidence:
    """Observation-bound, ephemeral visual evidence; adapted from the legacy pattern.

    It carries provenance, confidence, escalation state, and optional frame
    digest. It never carries authority, text content, tap points, or semantic
    success, and its ``redacted()`` projection follows the existing
    redacted-visual-evidence shape.
    """

    evidence_id: str
    observation_ref: Any
    source: str
    confidence: float
    block_count: int
    escalation: EscalationRequirement
    frame_digest: str | None = None
    secure_surface: bool = False
    entity_type: str = "screen_context"
    evidence_class: str = "semantic_graph"
    timestamp: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_id", _identifier(self.evidence_id, "evidence_id"))
        if self.observation_ref is None:
            raise PerceptionPolicyError("visual frame evidence requires an observation reference")
        object.__setattr__(self, "source", _identifier(self.source, "evidence source"))
        object.__setattr__(self, "confidence", _confidence(self.confidence))
        object.__setattr__(self, "block_count", _bounded_int(self.block_count, "block_count", maximum=MAX_BLOCKS))
        object.__setattr__(self, "escalation", EscalationRequirement(self.escalation))
        if self.frame_digest is not None and not _DIGEST.fullmatch(self.frame_digest):
            raise PerceptionPolicyError("frame digest must be lowercase SHA-256")
        if not isinstance(self.secure_surface, bool):
            raise PerceptionPolicyError("secure_surface must be boolean")
        if self.entity_type not in {"screen_context", "interaction_affordance", "domain_context", "unknown"}:
            raise PerceptionPolicyError("visual evidence entity type is unsupported")
        if self.evidence_class not in {"semantic_graph", "domain_signal"}:
            raise PerceptionPolicyError("visual evidence class is unsupported")
        object.__setattr__(self, "timestamp", _bounded_int(self.timestamp, "timestamp", maximum=2**52))

    def redacted(self) -> dict[str, Any]:
        """Projection matching the existing redacted visual-evidence shape."""

        return {
            "source_type": self.source,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
            "entity_type": self.entity_type,
            "evidence_class": self.evidence_class,
        }

    def audit(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "observation_id": self.observation_ref.observation_id,
            "escalation": self.escalation.value,
            "secure_surface": self.secure_surface,
            "authorization": False,
            "binding": False,
            "semantic_success": False,
        }


@dataclass(frozen=True)
class PerceptionProviderOutcome:
    """Bounded in-memory provider outcome metadata; never a telemetry record."""

    provider: str
    success: bool
    item_count: int
    latency_ms: int | None = None
    confidence: float | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", _identifier(self.provider, "provider"))
        if not isinstance(self.success, bool):
            raise PerceptionPolicyError("provider success must be boolean")
        object.__setattr__(self, "item_count", _bounded_int(self.item_count, "item_count", maximum=MAX_BLOCKS))
        if self.latency_ms is not None:
            object.__setattr__(
                self, "latency_ms", _bounded_int(self.latency_ms, "latency_ms", maximum=MAX_LATENCY_MS)
            )
        if self.confidence is not None:
            object.__setattr__(self, "confidence", _confidence(self.confidence))
        if self.detail is not None:
            detail = _normalized_text(self.detail)
            if not detail or len(detail) > 128:
                raise PerceptionPolicyError("provider detail must be bounded text")
            object.__setattr__(self, "detail", detail)


@dataclass(frozen=True)
class PerceptionOutcome:
    """Typed result of one bounded perception composition; never authoritative."""

    layer: PerceptionLayer
    resolution: SemanticResolution | None
    evidence: VisualFrameEvidence | None
    ui_object_count: int
    providers: tuple[PerceptionProviderOutcome, ...]
    fail_closed_reason: str | None = None
    secure_surface: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "layer", PerceptionLayer(self.layer))
        if self.resolution is not None and not isinstance(self.resolution, SemanticResolution):
            raise PerceptionPolicyError("perception outcome requires typed resolution")
        if self.evidence is not None and not isinstance(self.evidence, VisualFrameEvidence):
            raise PerceptionPolicyError("perception outcome requires typed evidence")
        object.__setattr__(self, "ui_object_count", _bounded_int(self.ui_object_count, "ui_object_count", maximum=MAX_BLOCKS))
        providers = tuple(self.providers)
        if len(providers) > 4 or any(not isinstance(item, PerceptionProviderOutcome) for item in providers):
            raise PerceptionPolicyError("perception providers must be bounded and typed")
        object.__setattr__(self, "providers", providers)
        if not isinstance(self.secure_surface, bool):
            raise PerceptionPolicyError("secure_surface must be boolean")
        if self.fail_closed_reason is not None:
            object.__setattr__(self, "fail_closed_reason", _identifier(self.fail_closed_reason, "fail_closed_reason"))

    def audit(self) -> dict[str, Any]:
        return {
            "layer": self.layer.value,
            "fail_closed": self.fail_closed_reason is not None,
            "secure_surface": self.secure_surface,
            "authorization": False,
            "binding": False,
            "dispatch": False,
            "semantic_success": False,
        }

    def summary(self) -> dict[str, Any]:
        """Redacted read-only understanding projection; no text content."""

        evidence = self.evidence
        return {
            "layer": self.layer.value,
            "escalation": evidence.escalation.value if evidence else EscalationRequirement.NONE.value,
            "block_count": evidence.block_count if evidence else 0,
            "provider_count": len(self.providers),
            "fail_closed": self.fail_closed_reason is not None,
            "secure_surface": self.secure_surface,
            "mutation_candidate_count": 0,
        }


class OCRUIObjectAdapter:
    """Map ephemeral OCR evidence into observation-scoped S4-M1 UIObjects.

    Block identity is derived from the owning observation and reading order and
    never persists across observations. Text content provides the descriptor
    identity key; pure floating text without context is refused.
    """

    def __init__(self, tracker: ObservationTracker) -> None:
        if not isinstance(tracker, ObservationTracker):
            raise PerceptionPolicyError("OCR adapter requires ObservationTracker")
        self.tracker = tracker

    def build(
        self,
        frame: OCRFrameCapture,
        snapshot: Any,
        scope: ObservationScope,
        *,
        require_region_context: bool = False,
    ) -> tuple[tuple[UIObject, ...], int]:
        if frame.secure_surface or snapshot is None:
            return (), 0
        if scope.frontmost_app_id is None:
            raise PerceptionPolicyError("OCR composition requires a frontmost application scope")
        objects: list[UIObject] = []
        uncontextualized = 0
        observation_key = _identifier(snapshot.observation_ref.observation_id, "observation_id")
        for block in frame.blocks:
            if require_region_context and block.region_id is None:
                uncontextualized += 1
                continue
            context = ["ocr", f"order.{block.reading_order:04d}"]
            if block.region_id is not None:
                context.append(f"region.{block.region_id}")
            objects.append(
                UIObject(
                    object_id=f"object.ocrblock.{block.reading_order:04d}.{observation_key}"[:127],
                    observation_ref=snapshot.observation_ref,
                    observation_epoch=snapshot.epoch.value,
                    role="text",
                    app_id=scope.frontmost_app_id,
                    source=block.source,
                    label=block.text,
                    accessibility_identifier=block.content_key(),
                    bounds=block.bounds,
                    hierarchy_context=tuple(context),
                    capability_ids=(READ_CAPABILITY,),
                )
            )
        return tuple(objects), uncontextualized


class VisionUIObjectAdapter:
    """Map normalized, provider-claimed vision regions into S4-M1 UIObjects."""

    def build(
        self,
        payload: Mapping[str, Any],
        snapshot: Any,
        scope: ObservationScope,
        *,
        source: str,
    ) -> tuple[tuple[UIObject, ...], int]:
        if not isinstance(payload, Mapping) or snapshot is None:
            return (), 0
        if scope.frontmost_app_id is None:
            raise PerceptionPolicyError("vision composition requires a frontmost application scope")
        regions = payload.get("regions")
        if not isinstance(regions, list) or len(regions) > MAX_REGIONS:
            raise PerceptionPolicyError("vision payload regions must be a bounded list")
        observation_key = _identifier(snapshot.observation_ref.observation_id, "observation_id")
        objects: list[UIObject] = []
        skipped = 0
        for order, region in enumerate(regions):
            if not isinstance(region, Mapping):
                skipped += 1
                continue
            role = _normalized_text(region.get("role") or "other")
            if role not in SAFE_VISION_ROLES:
                role = "other"
            text = _normalized_text(region.get("text"))
            if not text or len(text) > MAX_TEXT_LENGTH:
                skipped += 1
                continue
            content_key = "visualtext." + hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]
            context = ("vision", f"order.{order:04d}")
            try:
                bounds = _bounds_from_rect(region.get("rect")) if region.get("rect") is not None else None
                confidence = region.get("confidence")
                enabled = region.get("enabled")
                actionable = region.get("actionable")
                editable = region.get("editable")
                capabilities = [READ_CAPABILITY]
                if role in {"button", "link"}:
                    capabilities.append("capability.ui.activate.v1")
                elif role in {"switch", "checkbox"}:
                    capabilities.append("capability.ui.toggle.v1")
                elif role in {"menu_item", "option", "radio"}:
                    capabilities.append("capability.ui.select.v1")
                elif role in {"text_field"}:
                    capabilities.append("capability.ui.set-text.v1")
                objects.append(
                    UIObject(
                        object_id=f"object.visionregion.{order:04d}.{observation_key}"[:127],
                        observation_ref=snapshot.observation_ref,
                        observation_epoch=snapshot.epoch.value,
                        role=role,
                        app_id=scope.frontmost_app_id,
                        source=_identifier(source, "vision source"),
                        label=text or None,
                        accessibility_identifier=content_key,
                        bounds=bounds,
                        enabled=None if enabled is None else bool(enabled),
                        actionable=None if actionable is None else bool(actionable),
                        editable=None if editable is None else bool(editable),
                        hierarchy_context=context,
                        capability_ids=tuple(capabilities),
                        secure_ui=payload.get("secure_surface") is True,
                    )
                )
            except (PerceptionError, SemanticUIError):
                skipped += 1
        return tuple(objects), skipped


def derive_perception_scope(scope: ObservationScope, source: str) -> ObservationScope:
    """Derive a stable perception scope that shares task/session/runtime identity."""

    if not isinstance(scope, ObservationScope):
        raise PerceptionPolicyError("perception scope derivation requires ObservationScope")
    source = _identifier(source, "perception source")
    return ObservationScope(
        f"{scope.scope_id}.{source.split('.')[0]}",
        scope.task_id,
        scope.session_id,
        scope.runtime_instance_id,
        source,
        frontmost_app_id=scope.frontmost_app_id,
        process_instance_ref=scope.process_instance_ref,
    )


class PerceptionOrchestrator:
    """Bounded structured → OCR → vision composition into frozen S4-M1 machinery.

    At most one OCR capture and one vision capture occur per call. The
    orchestrator performs no dispatch, exposes no mutation parameters, and
    returns only typed, non-authoritative evidence and frozen candidate
    contracts.
    """

    def __init__(
        self,
        tracker: ObservationTracker,
        resolver: SemanticTargetResolver | None = None,
        *,
        ocr_capture: Callable[[ObservationScope, str], Mapping[str, Any]] | None = None,
        vision_capture: Callable[[ObservationScope, str], Mapping[str, Any]] | None = None,
        ocr_source: str = "ocr.visionframework",
        vision_source: str = "vision.provider",
        now_ms: Callable[[], int] = lambda: time.time_ns() // 1_000_000,
    ) -> None:
        if not isinstance(tracker, ObservationTracker):
            raise PerceptionPolicyError("orchestrator requires ObservationTracker")
        if resolver is not None and not isinstance(resolver, SemanticTargetResolver):
            raise PerceptionPolicyError("orchestrator resolver must use SemanticTargetResolver")
        if resolver is not None and resolver.tracker is not tracker:
            raise PerceptionPolicyError("orchestrator resolver must share its freshness tracker")
        self.tracker = tracker
        self.resolver = resolver or SemanticTargetResolver(tracker)
        self.ocr_adapter = OCRUIObjectAdapter(tracker)
        self.vision_adapter = VisionUIObjectAdapter()
        self._ocr_capture = ocr_capture
        self._vision_capture = vision_capture
        self._ocr_source = _identifier(ocr_source, "ocr_source")
        self._vision_source = _identifier(vision_source, "vision_source")
        self._now_ms = now_ms
        self._ocr_scope: ObservationScope | None = None
        self._vision_scope: ObservationScope | None = None

    # -- public composition -------------------------------------------------

    def resolve_target(
        self,
        descriptor: SemanticTargetDescriptor,
        structured_snapshot: Any,
        structured_objects: Iterable[UIObject],
        *,
        expected_scope: ObservationScope,
        structured_complete: bool,
        trace_id: str,
    ) -> PerceptionOutcome:
        if not isinstance(descriptor, SemanticTargetDescriptor):
            raise PerceptionPolicyError("orchestrator requires SemanticTargetDescriptor")
        ocr_available = self._ocr_capture is not None
        vision_available = self._vision_capture is not None
        resolution = self.resolver.resolve(
            descriptor,
            structured_snapshot,
            tuple(structured_objects),
            expected_scope=expected_scope,
            structured_source_complete=bool(structured_complete),
            ocr_available=ocr_available,
            vision_available=vision_available,
        )
        if resolution.state is ResolutionState.RESOLVED_UNIQUE:
            return PerceptionOutcome(PerceptionLayer.STRUCTURED, resolution, None, 1, ())
        if resolution.state is not ResolutionState.OCR_REQUIRED:
            return PerceptionOutcome(
                PerceptionLayer.UNRESOLVED,
                resolution,
                None,
                0,
                (),
                fail_closed_reason=self._fail_reason(resolution.state),
            )

        ocr_outcome = self._run_ocr(descriptor, expected_scope, trace_id)
        providers = [ocr_outcome.provider_outcome]
        if ocr_outcome.resolution is not None and ocr_outcome.resolution.state is ResolutionState.RESOLVED_UNIQUE:
            return PerceptionOutcome(
                PerceptionLayer.OCR,
                ocr_outcome.resolution,
                ocr_outcome.evidence,
                ocr_outcome.ui_object_count,
                tuple(providers),
            )
        if ocr_outcome.secure_surface:
            return PerceptionOutcome(
                PerceptionLayer.UNRESOLVED,
                None,
                ocr_outcome.evidence,
                0,
                tuple(providers),
                fail_closed_reason="SECURE_SURFACE",
                secure_surface=True,
            )
        if ocr_outcome.evidence is not None:
            providers.append(
                PerceptionProviderOutcome(
                    self._ocr_source,
                    False,
                    ocr_outcome.evidence.block_count,
                    detail="ocr_target_unresolved",
                )
            )
        if not vision_available:
            return PerceptionOutcome(
                PerceptionLayer.UNRESOLVED,
                ocr_outcome.resolution,
                ocr_outcome.evidence,
                ocr_outcome.ui_object_count,
                tuple(providers),
                fail_closed_reason="VISION_UNAVAILABLE",
                secure_surface=ocr_outcome.secure_surface,
            )
        vision_outcome = self._run_vision(descriptor, expected_scope, trace_id)
        providers.append(vision_outcome.provider_outcome)
        if vision_outcome.resolution is not None and vision_outcome.resolution.state is ResolutionState.RESOLVED_UNIQUE:
            return PerceptionOutcome(
                PerceptionLayer.VISION,
                vision_outcome.resolution,
                vision_outcome.evidence,
                vision_outcome.ui_object_count,
                tuple(providers),
            )
        return PerceptionOutcome(
            PerceptionLayer.UNRESOLVED,
            vision_outcome.resolution or ocr_outcome.resolution,
            vision_outcome.evidence or ocr_outcome.evidence,
            max(vision_outcome.ui_object_count, ocr_outcome.ui_object_count),
            tuple(providers),
            fail_closed_reason=vision_outcome.fail_reason or "VISION_UNRESOLVED",
            secure_surface=vision_outcome.secure_surface or ocr_outcome.secure_surface,
        )

    def understand(
        self,
        structured_snapshot: Any,
        structured_objects: Iterable[UIObject],
        *,
        expected_scope: ObservationScope,
        include_ocr: bool,
        trace_id: str,
    ) -> PerceptionOutcome:
        """Read-only ask-about-screen composition; never produces a candidate."""

        structured = tuple(structured_objects)
        if not include_ocr or self._ocr_capture is None:
            return PerceptionOutcome(PerceptionLayer.STRUCTURED, None, None, len(structured), ())
        ocr_outcome = self._run_ocr(None, expected_scope, trace_id)
        return PerceptionOutcome(
            PerceptionLayer.OCR,
            None,
            ocr_outcome.evidence,
            ocr_outcome.ui_object_count,
            (ocr_outcome.provider_outcome,),
            fail_closed_reason=ocr_outcome.fail_reason,
            secure_surface=ocr_outcome.secure_surface,
        )

    # -- internals -----------------------------------------------------------

    @staticmethod
    def _fail_reason(state: ResolutionState) -> str:
        return {
            ResolutionState.AMBIGUOUS: "TARGET_AMBIGUOUS",
            ResolutionState.NOT_FOUND: "TARGET_MISSING",
            ResolutionState.STALE: "OBSERVATION_STALE",
            ResolutionState.REOBSERVE_REQUIRED: "REOBSERVE_REQUIRED",
            ResolutionState.UNRESOLVED: "PERCEPTION_UNRESOLVED",
        }.get(state, "PERCEPTION_UNRESOLVED")

    def _capture(
        self,
        layer_source: str,
        expected_scope: ObservationScope,
        trace_id: str,
        cached_scope_attr: str,
    ) -> tuple[Any, PerceptionProviderOutcome | None]:
        capture = self._ocr_capture if layer_source == self._ocr_source else self._vision_capture
        if capture is None:
            return None, None
        scope = derive_perception_scope(expected_scope, layer_source)
        cached = getattr(self, cached_scope_attr)
        started = self._now_ms()
        try:
            payload = capture(scope, trace_id)
        except Exception as error:
            elapsed = min(max(self._now_ms() - started, 0), MAX_LATENCY_MS)
            return None, PerceptionProviderOutcome(layer_source, False, 0, elapsed, detail=str(error)[:128])
        elapsed = min(max(self._now_ms() - started, 0), MAX_LATENCY_MS)
        if cached is not None and cached != scope:
            self.tracker.invalidate(
                cached,
                InvalidationReason.FRONTMOST_TRANSITION,
                trace_id=trace_id,
                replacement_scope=scope,
            )
        setattr(self, cached_scope_attr, scope)
        return (payload, scope, elapsed), None

    def _run_ocr(self, structured_descriptor: SemanticTargetDescriptor | None, expected_scope: ObservationScope, trace_id: str):
        return self._run_layer(
            layer_source=self._ocr_source,
            cached_scope_attr="_ocr_scope",
            expected_scope=expected_scope,
            trace_id=trace_id,
            descriptor=structured_descriptor,
        )

    def _run_vision(self, structured_descriptor: SemanticTargetDescriptor | None, expected_scope: ObservationScope, trace_id: str):
        return self._run_layer(
            layer_source=self._vision_source,
            cached_scope_attr="_vision_scope",
            expected_scope=expected_scope,
            trace_id=trace_id,
            descriptor=structured_descriptor,
        )

    def _run_layer(
        self,
        *,
        layer_source: str,
        cached_scope_attr: str,
        expected_scope: ObservationScope,
        trace_id: str,
        descriptor: SemanticTargetDescriptor | None,
    ) -> "_LayerResult":
        capture = self._ocr_capture if layer_source == self._ocr_source else self._vision_capture
        if capture is None:
            return _LayerResult(
                None,
                PerceptionProviderOutcome(layer_source, False, 0, detail="provider_not_configured"),
                None,
                0,
                "PROVIDER_UNAVAILABLE",
                False,
            )
        captured = self._capture(layer_source, expected_scope, trace_id, cached_scope_attr)
        payload_bundle, failure = captured
        if failure is not None or payload_bundle is None:
            return _LayerResult(
                None,
                failure or PerceptionProviderOutcome(layer_source, False, 0, detail="provider_unavailable"),
                None,
                0,
                "PROVIDER_UNAVAILABLE",
                False,
            )
        payload, scope, elapsed = payload_bundle
        is_ocr = layer_source == self._ocr_source
        try:
            if is_ocr:
                frame = normalize_ocr_payload(payload, source=layer_source, captured_at_ms=self._now_ms())
                snapshot = self.tracker.capture(
                    scope,
                    trace_id=trace_id,
                    fingerprint=frame.frame_digest,
                    evidence=(
                        ("frame_digest", frame.frame_digest),
                        ("provider", frame.source),
                        ("block_count", str(len(frame.blocks))),
                    ),
                )
                objects, uncontextualized = self.ocr_adapter.build(frame, snapshot, scope)
                evidence = VisualFrameEvidence(
                    f"evidence.{layer_source}.{frame.frame_digest[:16]}",
                    snapshot.observation_ref,
                    frame.source,
                    max((block.confidence for block in frame.blocks), default=0.0),
                    len(frame.blocks),
                    EscalationRequirement.OCR_REQUIRED,
                    frame.frame_digest,
                    frame.secure_surface,
                    timestamp=frame.captured_at_ms,
                )
            else:
                frame = None
                snapshot = self.tracker.capture(
                    scope,
                    trace_id=trace_id,
                    fingerprint=_canonical_digest(payload),
                    evidence=(("provider", layer_source),),
                )
                objects, uncontextualized = self.vision_adapter.build(payload, snapshot, scope, source=layer_source)
                evidence = VisualFrameEvidence(
                    f"evidence.{layer_source}.{snapshot.observation_ref.observation_id}"[:120],
                    snapshot.observation_ref,
                    layer_source,
                    max(
                        (
                            _optional_provider_confidence(region.get("confidence"))
                            for region in (payload.get("regions") or [])
                            if isinstance(region, Mapping)
                        ),
                        default=0.0,
                    ),
                    len(objects),
                    EscalationRequirement.VISION_REQUIRED,
                    snapshot.fingerprint,
                    payload.get("secure_surface") is True,
                    timestamp=self._now_ms(),
                )
        except (PerceptionError, SemanticUIError) as error:
            return _LayerResult(
                None,
                PerceptionProviderOutcome(layer_source, False, 0, elapsed, detail=str(error)[:128]),
                None,
                0,
                "PROVIDER_PAYLOAD_INVALID",
                False,
            )
        if is_ocr:
            provider_outcome = PerceptionProviderOutcome(
                layer_source, True, len(frame.blocks), elapsed, evidence.confidence,
                detail=f"skipped={frame.skipped_block_count};uncontextualized={uncontextualized}",
            )
            if frame.secure_surface:
                return _LayerResult(None, provider_outcome, evidence, 0, "SECURE_SURFACE", True)
            if descriptor is None:
                return _LayerResult(None, provider_outcome, evidence, len(objects), None, False)
            resolution = self._resolve_on_layer(snapshot, objects, scope, descriptor, "text")
            return _LayerResult(resolution, provider_outcome, evidence, len(objects), None, False)
        provider_outcome = PerceptionProviderOutcome(
            layer_source, True, len(objects), elapsed, evidence.confidence,
            detail=f"skipped={uncontextualized}",
        )
        if evidence.secure_surface:
            return _LayerResult(None, provider_outcome, evidence, 0, "SECURE_SURFACE", True)
        if descriptor is None:
            return _LayerResult(None, provider_outcome, evidence, len(objects), None, False)
        resolution = self._resolve_on_layer(snapshot, objects, scope, descriptor, descriptor.role)
        return _LayerResult(resolution, provider_outcome, evidence, len(objects), None, False)

    def _resolve_on_layer(self, snapshot: Any, objects: tuple[UIObject, ...], scope: ObservationScope, structured_descriptor: SemanticTargetDescriptor, role: str):
        """Resolve the structured descriptor's textual intent on a visual layer.

        Visual layers match by normalized text content key. OCR evidence proves
        text only, so OCR targets are read-only; vision targets keep the
        structured role when the provider claims the same role.
        """

        label = _normalized_text(structured_descriptor.label or "")
        if not label:
            return SemanticResolution(ResolutionState.REOBSERVE_REQUIRED, structured_descriptor.target_ref)
        layer = "ocr" if role == "text" else "vision"
        content_key = "visualtext." + hashlib.sha256(label.encode("utf-8")).hexdigest()[:24]
        prior = ObservedTargetRef(
            f"target.{layer}.{content_key.split('.')[1]}",
            snapshot.observation_ref,
            "ocr.text_block" if layer == "ocr" else "vision.region",
            role,
        )
        layer_descriptor = SemanticTargetDescriptor(
            prior,
            scope.frontmost_app_id,
            role,
            label,
            content_key,
            None,
            (layer,),
        )
        return self.resolver.resolve(
            layer_descriptor,
            snapshot,
            objects,
            expected_scope=scope,
            structured_source_complete=True,
        )

    def candidates_for(self, outcome: PerceptionOutcome, *, candidate_set_id: str, context_ref: str):
        """Produce frozen S3-M0 candidates from a resolved perception outcome."""

        resolution = outcome.resolution
        if resolution is None or resolution.state is not ResolutionState.RESOLVED_UNIQUE:
            raise PerceptionPolicyError("candidates require a uniquely resolved perception outcome")
        if resolution.ui_object is None or resolution.current_target_ref is None:
            raise PerceptionPolicyError("resolved outcome is missing typed target evidence")
        operation_set = DynamicLegalOperationBuilder(self.tracker).build(
            resolution.ui_object,
            resolution.current_target_ref,
            resolution.ui_object.capability_ids,
        )
        return ActionCandidateFactory().build(
            operation_set,
            candidate_set_id=candidate_set_id,
            context_ref=context_ref,
        )


class _LayerResult:
    """Internal single-layer composition result."""

    __slots__ = ("resolution", "provider_outcome", "evidence", "ui_object_count", "fail_reason", "secure_surface")

    def __init__(
        self,
        resolution: SemanticResolution | None,
        provider_outcome: PerceptionProviderOutcome,
        evidence: VisualFrameEvidence | None,
        ui_object_count: int,
        fail_reason: str | None,
        secure_surface: bool,
    ) -> None:
        self.resolution = resolution
        self.provider_outcome = provider_outcome
        self.evidence = evidence
        self.ui_object_count = ui_object_count
        self.fail_reason = fail_reason
        self.secure_surface = secure_surface


__all__ = [
    "OCRFrameCapture",
    "OCRTextBlock",
    "OCRUIObjectAdapter",
    "PerceptionError",
    "PerceptionLayer",
    "PerceptionOrchestrator",
    "PerceptionOutcome",
    "PerceptionPolicyError",
    "PerceptionProviderOutcome",
    "VisionUIObjectAdapter",
    "VisualFrameEvidence",
    "derive_perception_scope",
    "normalize_ocr_payload",
]
