#!/usr/bin/env python3
"""Host-only semantic UI contracts over S4-M0 observation freshness.

These types describe current structured UI evidence. They cannot authorize,
bind, dispatch, retry, verify semantic success, or mutate device state.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import math
import re
from typing import Any, Callable, Iterable, Mapping

from phoneharness_contracts import (
    ActionCandidate,
    ActionCandidateSet,
    CandidateRef,
    ObservationRef,
    ObservedTargetRef,
)
from phoneharness_multistep import RecoveryRoute, WaitAssessment
from phoneharness_observation import (
    FreshnessRequirement,
    FreshnessState,
    ObservationNotFound,
    ObservationScope,
    ObservationSnapshot,
    ObservationTracker,
)


UI_OBJECT_SCHEMA = "phoneharness.ui-object.v1"
SEMANTIC_TARGET_DESCRIPTOR_SCHEMA = "phoneharness.semantic-target-descriptor.v1"
SEMANTIC_RESOLUTION_SCHEMA = "phoneharness.semantic-resolution.v1"
LEGAL_OPERATION_SCHEMA = "phoneharness.legal-operation.v1"
LEGAL_OPERATION_SET_SCHEMA = "phoneharness.dynamic-legal-operation-set.v1"
PREDISPATCH_VALIDATION_SCHEMA = "phoneharness.predispatch-validation.v1"
SEMANTIC_WAIT_CONDITION_SCHEMA = "phoneharness.semantic-wait-condition.v1"
SEMANTIC_STATE_EVIDENCE_SCHEMA = "phoneharness.semantic-state-evidence.v1"
MAX_TEXT_LENGTH = 256
MAX_CONTEXT_ITEMS = 16
MAX_OPERATIONS = 16

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")


class SemanticUIError(RuntimeError):
    """Base class for bounded semantic UI failures."""


class SemanticUIPolicyError(SemanticUIError):
    """A semantic UI contract is malformed or outside its policy."""


class ResolutionState(str, Enum):
    RESOLVED_UNIQUE = "RESOLVED_UNIQUE"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_FOUND = "NOT_FOUND"
    STALE = "STALE"
    REOBSERVE_REQUIRED = "REOBSERVE_REQUIRED"
    OCR_REQUIRED = "OCR_REQUIRED"
    VISION_REQUIRED = "VISION_REQUIRED"
    UNRESOLVED = "UNRESOLVED"


class EscalationRequirement(str, Enum):
    NONE = "NONE"
    OCR_REQUIRED = "OCR_REQUIRED"
    VISION_REQUIRED = "VISION_REQUIRED"
    UNRESOLVED = "UNRESOLVED"


class LegalOperationKind(str, Enum):
    READ = "READ"
    ACTIVATE = "ACTIVATE"
    SET_TEXT = "SET_TEXT"
    TOGGLE = "TOGGLE"
    SELECT = "SELECT"


class PreDispatchStatus(str, Enum):
    PASS = "PASS"
    REOBSERVE_REQUIRED = "REOBSERVE_REQUIRED"
    TARGET_CHANGED = "TARGET_CHANGED"
    TARGET_MISSING = "TARGET_MISSING"
    TARGET_AMBIGUOUS = "TARGET_AMBIGUOUS"
    OPERATION_NO_LONGER_LEGAL = "OPERATION_NO_LONGER_LEGAL"
    NOT_ACTIONABLE = "NOT_ACTIONABLE"
    SCOPE_CHANGED = "SCOPE_CHANGED"
    CAPABILITY_UNREGISTERED = "CAPABILITY_UNREGISTERED"
    BINDING_INCOMPATIBLE = "BINDING_INCOMPATIBLE"
    SECURE_UI_REQUIRES_USER = "SECURE_UI_REQUIRES_USER"


class SemanticWaitKind(str, Enum):
    TARGET_EXISTS = "TARGET_EXISTS"
    TARGET_DISAPPEARS = "TARGET_DISAPPEARS"
    TARGET_ENABLED = "TARGET_ENABLED"
    STATE_EQUALS = "STATE_EQUALS"


def _identifier(value: Any, field_name: str) -> str:
    normalized = str(value or "").strip()
    if _IDENTIFIER.fullmatch(normalized) is None:
        raise SemanticUIPolicyError(f"{field_name} must be an opaque bounded identifier")
    return normalized


def _optional_text(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).split())
    if not normalized or len(normalized) > MAX_TEXT_LENGTH:
        raise SemanticUIPolicyError(f"{field_name} must be bounded text")
    return normalized


def _optional_bool(value: Any, field_name: str) -> bool | None:
    if value is not None and not isinstance(value, bool):
        raise SemanticUIPolicyError(f"{field_name} must be boolean or unknown")
    return value


def _identifier_tuple(values: Iterable[str], field_name: str) -> tuple[str, ...]:
    normalized = tuple(_identifier(value, field_name) for value in values)
    if len(normalized) > MAX_CONTEXT_ITEMS or len(normalized) != len(set(normalized)):
        raise SemanticUIPolicyError(f"{field_name} must be bounded and unique")
    return normalized


def _properties(values: Mapping[str, Any] | Iterable[tuple[str, Any]]) -> tuple[tuple[str, str], ...]:
    items = values.items() if isinstance(values, Mapping) else values
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw_key, raw_value in items:
        key = _identifier(raw_key, "semantic property")
        value = _optional_text(raw_value, "semantic property value")
        if value is None or key in seen:
            raise SemanticUIPolicyError("semantic properties must be unique and non-empty")
        seen.add(key)
        result.append((key, value))
    if len(result) > MAX_CONTEXT_ITEMS:
        raise SemanticUIPolicyError("semantic properties exceed their bound")
    return tuple(sorted(result))


@dataclass(frozen=True)
class UIBounds:
    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        for name in ("x", "y", "width", "height"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise SemanticUIPolicyError(f"{name} must be finite")
        if self.width < 0 or self.height < 0:
            raise SemanticUIPolicyError("bounds dimensions cannot be negative")


@dataclass(frozen=True)
class UIObject:
    object_id: str
    observation_ref: ObservationRef
    observation_epoch: int
    role: str
    app_id: str
    source: str
    label: str | None = None
    value: str | None = None
    accessibility_identifier: str | None = None
    enabled: bool | None = None
    selected: bool | None = None
    focused: bool | None = None
    editable: bool | None = None
    actionable: bool | None = None
    bounds: UIBounds | None = None
    hierarchy_context: tuple[str, ...] = ()
    capability_ids: tuple[str, ...] = ()
    secure_ui: bool = False
    schema_version: str = UI_OBJECT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != UI_OBJECT_SCHEMA:
            raise SemanticUIPolicyError("unsupported UIObject schema")
        if not isinstance(self.observation_ref, ObservationRef):
            raise SemanticUIPolicyError("UIObject requires ObservationRef")
        for name in ("object_id", "role", "app_id", "source"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        if isinstance(self.observation_epoch, bool) or not isinstance(self.observation_epoch, int) or self.observation_epoch <= 0:
            raise SemanticUIPolicyError("observation_epoch must be positive")
        for name in ("label", "value", "accessibility_identifier"):
            object.__setattr__(self, name, _optional_text(getattr(self, name), name))
        for name in ("enabled", "selected", "focused", "editable", "actionable"):
            object.__setattr__(self, name, _optional_bool(getattr(self, name), name))
        if self.bounds is not None and not isinstance(self.bounds, UIBounds):
            raise SemanticUIPolicyError("bounds must use UIBounds")
        object.__setattr__(self, "hierarchy_context", _identifier_tuple(self.hierarchy_context, "hierarchy context"))
        object.__setattr__(self, "capability_ids", _identifier_tuple(self.capability_ids, "capability_id"))
        if not isinstance(self.secure_ui, bool):
            raise SemanticUIPolicyError("secure_ui must be boolean")

    def audit(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "observation_id": self.observation_ref.observation_id,
            "epoch": self.observation_epoch,
            "role": self.role,
            "app_id": self.app_id,
            "actionability_known": self.actionable is not None,
            "authorization": False,
            "binding": False,
        }


@dataclass(frozen=True)
class SemanticTargetDescriptor:
    target_ref: ObservedTargetRef
    app_id: str
    role: str
    label: str | None = None
    accessibility_identifier: str | None = None
    value: str | None = None
    hierarchy_context: tuple[str, ...] = ()
    schema_version: str = SEMANTIC_TARGET_DESCRIPTOR_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != SEMANTIC_TARGET_DESCRIPTOR_SCHEMA:
            raise SemanticUIPolicyError("unsupported semantic target descriptor schema")
        if not isinstance(self.target_ref, ObservedTargetRef):
            raise SemanticUIPolicyError("semantic target requires ObservedTargetRef")
        for name in ("app_id", "role"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        for name in ("label", "accessibility_identifier", "value"):
            object.__setattr__(self, name, _optional_text(getattr(self, name), name))
        object.__setattr__(self, "hierarchy_context", _identifier_tuple(self.hierarchy_context, "hierarchy context"))
        if self.accessibility_identifier is None and self.label is None:
            raise SemanticUIPolicyError("semantic target requires an identifier or label")
        if self.target_ref.semantic_role != self.role:
            raise SemanticUIPolicyError("semantic target role must match its frozen target reference")

    @classmethod
    def from_ui_object(
        cls,
        target_ref: ObservedTargetRef,
        ui_object: UIObject,
        *,
        include_value: bool = False,
    ) -> "SemanticTargetDescriptor":
        if not isinstance(include_value, bool):
            raise SemanticUIPolicyError("include_value must be boolean")
        return cls(
            target_ref,
            ui_object.app_id,
            ui_object.role,
            ui_object.label,
            ui_object.accessibility_identifier,
            ui_object.value if include_value else None,
            ui_object.hierarchy_context,
        )


@dataclass(frozen=True)
class SemanticResolution:
    state: ResolutionState
    prior_target_ref: ObservedTargetRef
    current_target_ref: ObservedTargetRef | None = None
    ui_object: UIObject | None = None
    escalation: EscalationRequirement = EscalationRequirement.NONE
    schema_version: str = SEMANTIC_RESOLUTION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != SEMANTIC_RESOLUTION_SCHEMA:
            raise SemanticUIPolicyError("unsupported semantic resolution schema")
        object.__setattr__(self, "state", ResolutionState(self.state))
        object.__setattr__(self, "escalation", EscalationRequirement(self.escalation))
        if not isinstance(self.prior_target_ref, ObservedTargetRef):
            raise SemanticUIPolicyError("resolution requires prior target reference")
        if self.state is ResolutionState.RESOLVED_UNIQUE:
            if not isinstance(self.current_target_ref, ObservedTargetRef) or not isinstance(self.ui_object, UIObject):
                raise SemanticUIPolicyError("unique resolution requires current target and UIObject")
        elif self.current_target_ref is not None or self.ui_object is not None:
            raise SemanticUIPolicyError("failed resolution cannot expose a selected target")


class SemanticTargetResolver:
    """Resolve semantic identity against one fresh structured observation."""

    def __init__(self, tracker: ObservationTracker) -> None:
        if not isinstance(tracker, ObservationTracker):
            raise SemanticUIPolicyError("resolver requires ObservationTracker")
        self.tracker = tracker

    def resolve(
        self,
        descriptor: SemanticTargetDescriptor,
        snapshot: ObservationSnapshot,
        ui_objects: Iterable[UIObject],
        *,
        expected_scope: ObservationScope,
        structured_source_complete: bool = True,
        ocr_available: bool = False,
        vision_available: bool = False,
    ) -> SemanticResolution:
        if not isinstance(descriptor, SemanticTargetDescriptor) or not isinstance(snapshot, ObservationSnapshot):
            raise SemanticUIPolicyError("resolution requires typed descriptor and snapshot")
        assessment = self.tracker.assess(
            snapshot,
            FreshnessRequirement.current_epoch(),
            expected_scope=expected_scope,
        )
        if not assessment.satisfies:
            state = ResolutionState.STALE if assessment.state in {FreshnessState.STALE, FreshnessState.INVALIDATED} else ResolutionState.REOBSERVE_REQUIRED
            return SemanticResolution(state, descriptor.target_ref)
        if (
            descriptor.target_ref.observation_ref.task_id != snapshot.observation_ref.task_id
            or descriptor.target_ref.observation_ref.session_id != snapshot.observation_ref.session_id
            or expected_scope.frontmost_app_id != descriptor.app_id
        ):
            return SemanticResolution(ResolutionState.REOBSERVE_REQUIRED, descriptor.target_ref)
        objects = tuple(ui_objects)
        if any(
            not isinstance(item, UIObject)
            or item.observation_ref != snapshot.observation_ref
            or item.observation_epoch != snapshot.epoch.value
            for item in objects
        ):
            return SemanticResolution(ResolutionState.REOBSERVE_REQUIRED, descriptor.target_ref)
        if descriptor.accessibility_identifier is None and not descriptor.hierarchy_context:
            return SemanticResolution(ResolutionState.REOBSERVE_REQUIRED, descriptor.target_ref)
        matches = tuple(item for item in objects if self._matches(descriptor, item))
        if len(matches) > 1:
            return SemanticResolution(ResolutionState.AMBIGUOUS, descriptor.target_ref)
        if not matches:
            if structured_source_complete:
                return SemanticResolution(ResolutionState.NOT_FOUND, descriptor.target_ref)
            if ocr_available:
                return SemanticResolution(
                    ResolutionState.OCR_REQUIRED,
                    descriptor.target_ref,
                    escalation=EscalationRequirement.OCR_REQUIRED,
                )
            if vision_available:
                return SemanticResolution(
                    ResolutionState.VISION_REQUIRED,
                    descriptor.target_ref,
                    escalation=EscalationRequirement.VISION_REQUIRED,
                )
            return SemanticResolution(
                ResolutionState.UNRESOLVED,
                descriptor.target_ref,
                escalation=EscalationRequirement.UNRESOLVED,
            )
        current = matches[0]
        target = ObservedTargetRef(
            current.object_id,
            current.observation_ref,
            descriptor.target_ref.target_kind,
            current.role,
            capability_hint=current.capability_ids[0] if current.capability_ids else None,
            metadata=(("app_id", current.app_id), ("source", current.source)),
        )
        return SemanticResolution(ResolutionState.RESOLVED_UNIQUE, descriptor.target_ref, target, current)

    @staticmethod
    def _matches(descriptor: SemanticTargetDescriptor, item: UIObject) -> bool:
        if item.app_id != descriptor.app_id or item.role != descriptor.role:
            return False
        if descriptor.accessibility_identifier is not None:
            if item.accessibility_identifier != descriptor.accessibility_identifier:
                return False
        else:
            if item.label != descriptor.label or item.hierarchy_context != descriptor.hierarchy_context:
                return False
        if descriptor.value is not None and item.value != descriptor.value:
            return False
        return True


@dataclass(frozen=True)
class LegalOperation:
    operation_id: str
    kind: LegalOperationKind
    capability_id: str
    target_ref: ObservedTargetRef
    requires_actionable: bool
    mutation_capable: bool
    parameter_schema: tuple[str, ...] = ()
    verification_expectation: str = "semantic.state.current"
    schema_version: str = LEGAL_OPERATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != LEGAL_OPERATION_SCHEMA:
            raise SemanticUIPolicyError("unsupported LegalOperation schema")
        object.__setattr__(self, "operation_id", _identifier(self.operation_id, "operation_id"))
        object.__setattr__(self, "kind", LegalOperationKind(self.kind))
        object.__setattr__(self, "capability_id", _identifier(self.capability_id, "capability_id"))
        if not isinstance(self.target_ref, ObservedTargetRef):
            raise SemanticUIPolicyError("legal operation requires ObservedTargetRef")
        if not isinstance(self.requires_actionable, bool) or not isinstance(self.mutation_capable, bool):
            raise SemanticUIPolicyError("legal operation flags must be boolean")
        object.__setattr__(self, "parameter_schema", _identifier_tuple(self.parameter_schema, "parameter"))
        object.__setattr__(
            self,
            "verification_expectation",
            _identifier(self.verification_expectation, "verification_expectation"),
        )

    def audit(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "kind": self.kind.value,
            "capability_id": self.capability_id,
            "authorization": False,
            "dispatch": False,
        }


@dataclass(frozen=True)
class DynamicLegalOperationSet:
    operation_set_id: str
    observation_ref: ObservationRef
    target_ref: ObservedTargetRef
    operations: tuple[LegalOperation, ...]
    schema_version: str = LEGAL_OPERATION_SET_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != LEGAL_OPERATION_SET_SCHEMA:
            raise SemanticUIPolicyError("unsupported legal operation set schema")
        object.__setattr__(self, "operation_set_id", _identifier(self.operation_set_id, "operation_set_id"))
        if not isinstance(self.observation_ref, ObservationRef) or not isinstance(self.target_ref, ObservedTargetRef):
            raise SemanticUIPolicyError("legal operation set requires typed references")
        operations = tuple(self.operations)
        if len(operations) > MAX_OPERATIONS or any(not isinstance(item, LegalOperation) for item in operations):
            raise SemanticUIPolicyError("legal operation set must be bounded and typed")
        if len({item.operation_id for item in operations}) != len(operations):
            raise SemanticUIPolicyError("legal operation IDs must be unique")
        if any(item.target_ref != self.target_ref for item in operations):
            raise SemanticUIPolicyError("legal operations must share the current target")
        object.__setattr__(self, "operations", operations)


class DynamicLegalOperationBuilder:
    """Derive current semantic possibility without consulting authorization."""

    _CAPABILITIES = {
        LegalOperationKind.READ: "capability.ui.read.v1",
        LegalOperationKind.ACTIVATE: "capability.ui.activate.v1",
        LegalOperationKind.SET_TEXT: "capability.ui.set-text.v1",
        LegalOperationKind.TOGGLE: "capability.ui.toggle.v1",
        LegalOperationKind.SELECT: "capability.ui.select.v1",
    }

    def __init__(self, tracker: ObservationTracker) -> None:
        if not isinstance(tracker, ObservationTracker):
            raise SemanticUIPolicyError("legal operation builder requires ObservationTracker")
        self.tracker = tracker

    def build(
        self,
        ui_object: UIObject,
        target_ref: ObservedTargetRef,
        registered_capabilities: Iterable[str],
    ) -> DynamicLegalOperationSet:
        if not isinstance(ui_object, UIObject) or not isinstance(target_ref, ObservedTargetRef):
            raise SemanticUIPolicyError("legal operations require UIObject and target reference")
        if ui_object.observation_ref != target_ref.observation_ref:
            raise SemanticUIPolicyError("legal operations require one observation")
        capabilities = frozenset(_identifier(value, "registered capability") for value in registered_capabilities)
        operations: list[LegalOperation] = []

        try:
            snapshot = self.tracker.snapshot(ui_object.observation_ref)
        except ObservationNotFound:
            snapshot = None
        current = snapshot is not None and self.tracker.assess(
            snapshot,
            FreshnessRequirement.current_epoch(),
            expected_scope=snapshot.scope,
        ).satisfies
        current = bool(
            current
            and snapshot is not None
            and ui_object.observation_epoch == snapshot.epoch.value
            and snapshot.scope.frontmost_app_id == ui_object.app_id
        )

        def add(kind: LegalOperationKind, *, mutation: bool, actionable: bool, parameters: tuple[str, ...] = ()) -> None:
            capability = self._CAPABILITIES[kind]
            if capability in capabilities and capability in ui_object.capability_ids:
                operations.append(
                    LegalOperation(
                        f"operation.{kind.value.lower()}",
                        kind,
                        capability,
                        target_ref,
                        actionable,
                        mutation,
                        parameters,
                    )
                )

        if current:
            add(LegalOperationKind.READ, mutation=False, actionable=False)
        actionable = ui_object.enabled is True and ui_object.actionable is True
        if current and actionable and ui_object.role in {"button", "link", "control"}:
            add(LegalOperationKind.ACTIVATE, mutation=True, actionable=True)
        if current and actionable and ui_object.role in {"switch", "checkbox"}:
            add(LegalOperationKind.TOGGLE, mutation=True, actionable=True)
        if current and actionable and ui_object.role in {"menu_item", "option", "radio"}:
            add(LegalOperationKind.SELECT, mutation=True, actionable=True)
        if (
            current
            and actionable
            and ui_object.editable is True
            and ui_object.role in {"text_field", "text_view", "search_field"}
            and not ui_object.secure_ui
        ):
            add(LegalOperationKind.SET_TEXT, mutation=True, actionable=True, parameters=("text",))
        return DynamicLegalOperationSet(
            "legal-operations."
            + hashlib.sha256(
                f"{ui_object.observation_ref.observation_id}:{ui_object.object_id}".encode("utf-8")
            ).hexdigest()[:24],
            ui_object.observation_ref,
            target_ref,
            tuple(operations),
        )


class ActionCandidateFactory:
    """Produce frozen S3-M0 candidates from current legal operations."""

    @staticmethod
    def _metadata(operation: LegalOperation) -> tuple[tuple[str, str], ...]:
        values = [
            ("legal_operation_id", operation.operation_id),
            ("operation_kind", operation.kind.value),
            ("requires_actionable", str(operation.requires_actionable).lower()),
            ("mutation_capable", str(operation.mutation_capable).lower()),
            ("verification_expectation", operation.verification_expectation),
        ]
        if operation.parameter_schema:
            values.append(("parameter_schema", ",".join(operation.parameter_schema)))
        return tuple(values)

    def build(
        self,
        operation_set: DynamicLegalOperationSet,
        *,
        candidate_set_id: str,
        context_ref: str,
    ) -> ActionCandidateSet:
        if not isinstance(operation_set, DynamicLegalOperationSet):
            raise SemanticUIPolicyError("candidate production requires legal operation set")
        set_id = _identifier(candidate_set_id, "candidate_set_id")
        candidates = tuple(
            ActionCandidate(
                CandidateRef(set_id, f"candidate.{index:02d}"),
                operation.capability_id,
                operation_set.observation_ref,
                target_ref=operation_set.target_ref,
                reason_code="semantic.operation.current",
                decision_provider="s4.semantic-ui",
                metadata=self._metadata(operation),
            )
            for index, operation in enumerate(operation_set.operations, start=1)
        )
        return ActionCandidateSet(set_id, operation_set.observation_ref, context_ref, candidates)


@dataclass(frozen=True)
class PreDispatchValidation:
    status: PreDispatchStatus
    ready: bool
    resolution_state: ResolutionState
    current_target_ref: ObservedTargetRef | None = None
    operation_set: DynamicLegalOperationSet | None = None
    schema_version: str = PREDISPATCH_VALIDATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != PREDISPATCH_VALIDATION_SCHEMA:
            raise SemanticUIPolicyError("unsupported predispatch schema")
        object.__setattr__(self, "status", PreDispatchStatus(self.status))
        object.__setattr__(self, "resolution_state", ResolutionState(self.resolution_state))
        if not isinstance(self.ready, bool) or self.ready != (self.status is PreDispatchStatus.PASS):
            raise SemanticUIPolicyError("predispatch readiness is inconsistent")
        if self.ready and (
            not isinstance(self.current_target_ref, ObservedTargetRef)
            or not isinstance(self.operation_set, DynamicLegalOperationSet)
        ):
            raise SemanticUIPolicyError("successful predispatch requires current target and operations")

    def audit(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "ready": self.ready,
            "authorization": False,
            "dispatch": False,
        }


class PreDispatchValidator:
    """Fail-closed semantic choke point immediately before governed mutation."""

    _RESOLUTION_FAILURES = {
        ResolutionState.AMBIGUOUS: PreDispatchStatus.TARGET_AMBIGUOUS,
        ResolutionState.NOT_FOUND: PreDispatchStatus.TARGET_MISSING,
        ResolutionState.STALE: PreDispatchStatus.REOBSERVE_REQUIRED,
        ResolutionState.REOBSERVE_REQUIRED: PreDispatchStatus.REOBSERVE_REQUIRED,
        ResolutionState.OCR_REQUIRED: PreDispatchStatus.REOBSERVE_REQUIRED,
        ResolutionState.VISION_REQUIRED: PreDispatchStatus.REOBSERVE_REQUIRED,
        ResolutionState.UNRESOLVED: PreDispatchStatus.REOBSERVE_REQUIRED,
    }

    def __init__(
        self,
        tracker: ObservationTracker,
        resolver: SemanticTargetResolver | None = None,
        operation_builder: DynamicLegalOperationBuilder | None = None,
    ) -> None:
        if not isinstance(tracker, ObservationTracker):
            raise SemanticUIPolicyError("predispatch validator requires ObservationTracker")
        if resolver is not None and not isinstance(resolver, SemanticTargetResolver):
            raise SemanticUIPolicyError("predispatch resolver must use SemanticTargetResolver")
        if operation_builder is not None and not isinstance(operation_builder, DynamicLegalOperationBuilder):
            raise SemanticUIPolicyError("predispatch operation builder has the wrong type")
        if resolver is not None and resolver.tracker is not tracker:
            raise SemanticUIPolicyError("predispatch resolver must share its freshness tracker")
        if operation_builder is not None and operation_builder.tracker is not tracker:
            raise SemanticUIPolicyError("predispatch operation builder must share its freshness tracker")
        self.tracker = tracker
        self.resolver = resolver or SemanticTargetResolver(tracker)
        self.operation_builder = operation_builder or DynamicLegalOperationBuilder(tracker)

    def validate(
        self,
        descriptor: SemanticTargetDescriptor,
        required_operation: LegalOperation,
        snapshot: ObservationSnapshot,
        ui_objects: Iterable[UIObject],
        *,
        expected_scope: ObservationScope,
        registered_capabilities: Iterable[str],
        binding_capability_id: str,
    ) -> PreDispatchValidation:
        if not isinstance(descriptor, SemanticTargetDescriptor) or not isinstance(required_operation, LegalOperation):
            raise SemanticUIPolicyError("predispatch requires typed target and operation")
        if not isinstance(snapshot, ObservationSnapshot) or not isinstance(expected_scope, ObservationScope):
            raise SemanticUIPolicyError("predispatch requires typed observation scope")
        if required_operation.target_ref != descriptor.target_ref:
            return PreDispatchValidation(
                PreDispatchStatus.TARGET_CHANGED,
                False,
                ResolutionState.REOBSERVE_REQUIRED,
            )
        if snapshot.scope != expected_scope:
            return PreDispatchValidation(
                PreDispatchStatus.SCOPE_CHANGED,
                False,
                ResolutionState.REOBSERVE_REQUIRED,
            )
        resolution = self.resolver.resolve(
            descriptor,
            snapshot,
            ui_objects,
            expected_scope=expected_scope,
        )
        if resolution.state is not ResolutionState.RESOLVED_UNIQUE:
            return PreDispatchValidation(
                self._RESOLUTION_FAILURES[resolution.state],
                False,
                resolution.state,
            )
        assert resolution.ui_object is not None and resolution.current_target_ref is not None
        capabilities = frozenset(_identifier(value, "registered capability") for value in registered_capabilities)
        if required_operation.capability_id not in capabilities:
            return PreDispatchValidation(
                PreDispatchStatus.CAPABILITY_UNREGISTERED,
                False,
                resolution.state,
            )
        if resolution.ui_object.secure_ui and required_operation.kind is LegalOperationKind.SET_TEXT:
            return PreDispatchValidation(
                PreDispatchStatus.SECURE_UI_REQUIRES_USER,
                False,
                resolution.state,
            )
        if required_operation.requires_actionable and resolution.ui_object.actionable is not True:
            return PreDispatchValidation(
                PreDispatchStatus.NOT_ACTIONABLE,
                False,
                resolution.state,
            )
        operation_set = self.operation_builder.build(
            resolution.ui_object,
            resolution.current_target_ref,
            capabilities,
        )
        matching = tuple(
            operation
            for operation in operation_set.operations
            if operation.kind is required_operation.kind
            and operation.capability_id == required_operation.capability_id
            and operation.requires_actionable == required_operation.requires_actionable
            and operation.mutation_capable == required_operation.mutation_capable
            and operation.parameter_schema == required_operation.parameter_schema
            and operation.verification_expectation == required_operation.verification_expectation
        )
        if not matching:
            return PreDispatchValidation(
                PreDispatchStatus.OPERATION_NO_LONGER_LEGAL,
                False,
                resolution.state,
            )
        if _identifier(binding_capability_id, "binding_capability_id") != required_operation.capability_id:
            return PreDispatchValidation(
                PreDispatchStatus.BINDING_INCOMPATIBLE,
                False,
                resolution.state,
            )
        return PreDispatchValidation(
            PreDispatchStatus.PASS,
            True,
            resolution.state,
            resolution.current_target_ref,
            operation_set,
        )


@dataclass(frozen=True)
class SemanticStateEvidence:
    evidence_id: str
    observation_ref: ObservationRef
    observation_epoch: int
    app_id: str
    role: str
    properties: tuple[tuple[str, str], ...]
    schema_version: str = SEMANTIC_STATE_EVIDENCE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != SEMANTIC_STATE_EVIDENCE_SCHEMA:
            raise SemanticUIPolicyError("unsupported semantic state evidence schema")
        object.__setattr__(self, "evidence_id", _identifier(self.evidence_id, "evidence_id"))
        if not isinstance(self.observation_ref, ObservationRef):
            raise SemanticUIPolicyError("semantic state evidence requires ObservationRef")
        if isinstance(self.observation_epoch, bool) or not isinstance(self.observation_epoch, int) or self.observation_epoch <= 0:
            raise SemanticUIPolicyError("observation_epoch must be positive")
        object.__setattr__(self, "app_id", _identifier(self.app_id, "app_id"))
        object.__setattr__(self, "role", _identifier(self.role, "role"))
        object.__setattr__(self, "properties", _properties(self.properties))

    @classmethod
    def from_ui_object(cls, evidence_id: str, ui_object: UIObject) -> "SemanticStateEvidence":
        values = {
            "enabled": str(ui_object.enabled).upper() if ui_object.enabled is not None else "UNKNOWN",
            "selected": str(ui_object.selected).upper() if ui_object.selected is not None else "UNKNOWN",
            "focused": str(ui_object.focused).upper() if ui_object.focused is not None else "UNKNOWN",
            "editable": str(ui_object.editable).upper() if ui_object.editable is not None else "UNKNOWN",
            "actionable": str(ui_object.actionable).upper() if ui_object.actionable is not None else "UNKNOWN",
        }
        if ui_object.value is not None and not ui_object.secure_ui:
            values["value"] = ui_object.value
        return cls(
            evidence_id,
            ui_object.observation_ref,
            ui_object.observation_epoch,
            ui_object.app_id,
            ui_object.role,
            tuple(values.items()),
        )

    def proves(self, required: Mapping[str, Any]) -> bool:
        available = dict(self.properties)
        return all(available.get(_identifier(key, "required property")) == _optional_text(value, "required value") for key, value in required.items())

    def equivalent_to(self, other: "SemanticStateEvidence", required_keys: Iterable[str]) -> bool:
        if not isinstance(other, SemanticStateEvidence) or self.app_id != other.app_id or self.role != other.role:
            return False
        left = dict(self.properties)
        right = dict(other.properties)
        keys = _identifier_tuple(required_keys, "required key")
        return all(left.get(key) == right.get(key) for key in keys)


@dataclass(frozen=True)
class SemanticWaitCondition:
    condition_ref: str
    kind: SemanticWaitKind
    descriptor: SemanticTargetDescriptor
    max_evaluations: int
    expected_value: str | None = None
    schema_version: str = SEMANTIC_WAIT_CONDITION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != SEMANTIC_WAIT_CONDITION_SCHEMA:
            raise SemanticUIPolicyError("unsupported semantic wait condition schema")
        object.__setattr__(self, "condition_ref", _identifier(self.condition_ref, "condition_ref"))
        object.__setattr__(self, "kind", SemanticWaitKind(self.kind))
        if not isinstance(self.descriptor, SemanticTargetDescriptor):
            raise SemanticUIPolicyError("semantic wait requires target descriptor")
        if isinstance(self.max_evaluations, bool) or not isinstance(self.max_evaluations, int) or not 1 <= self.max_evaluations <= 32:
            raise SemanticUIPolicyError("semantic wait budget must be between 1 and 32")
        object.__setattr__(self, "expected_value", _optional_text(self.expected_value, "expected_value"))
        if self.kind is SemanticWaitKind.STATE_EQUALS and self.expected_value is None:
            raise SemanticUIPolicyError("STATE_EQUALS requires expected_value")


class SemanticWaitResolver:
    """Bounded, observation-backed adapter for the frozen S3-M9 wait seam."""

    def __init__(
        self,
        resolver: SemanticTargetResolver,
        observation_supplier: Callable[[], tuple[ObservationSnapshot, ObservationScope, tuple[UIObject, ...]]],
        conditions: Iterable[SemanticWaitCondition],
    ) -> None:
        if not isinstance(resolver, SemanticTargetResolver) or not callable(observation_supplier):
            raise SemanticUIPolicyError("semantic wait requires resolver and observation supplier")
        self.resolver = resolver
        self.observation_supplier = observation_supplier
        condition_values = tuple(conditions)
        if any(not isinstance(condition, SemanticWaitCondition) for condition in condition_values):
            raise SemanticUIPolicyError("semantic wait conditions must be typed")
        self.conditions = {condition.condition_ref: condition for condition in condition_values}
        if not self.conditions or len(self.conditions) > 32:
            raise SemanticUIPolicyError("semantic wait conditions must be bounded")
        if len(self.conditions) != len(condition_values):
            raise SemanticUIPolicyError("semantic wait condition refs must be unique")
        self._evaluations: dict[str, int] = {}

    def __call__(self, condition_ref: str, _variables: Mapping[str, str]) -> WaitAssessment:
        reference = _identifier(condition_ref, "condition_ref")
        condition = self.conditions.get(reference)
        if condition is None:
            return WaitAssessment(False, "semantic-wait.condition-unknown", RecoveryRoute.FAIL_SAFE)
        count = self._evaluations.get(reference, 0) + 1
        self._evaluations[reference] = count
        if count > condition.max_evaluations:
            return WaitAssessment(False, "semantic-wait.budget-exhausted", RecoveryRoute.FAIL_SAFE)
        snapshot, scope, objects = self.observation_supplier()
        resolution = self.resolver.resolve(condition.descriptor, snapshot, objects, expected_scope=scope)
        ready = False
        if condition.kind is SemanticWaitKind.TARGET_DISAPPEARS:
            ready = resolution.state is ResolutionState.NOT_FOUND
        elif resolution.state is ResolutionState.RESOLVED_UNIQUE and resolution.ui_object is not None:
            if condition.kind is SemanticWaitKind.TARGET_EXISTS:
                ready = True
            elif condition.kind is SemanticWaitKind.TARGET_ENABLED:
                ready = resolution.ui_object.enabled is True
            elif condition.kind is SemanticWaitKind.STATE_EQUALS:
                ready = resolution.ui_object.value == condition.expected_value
        evidence = f"semantic-wait.{reference}.{'ready' if ready else 'pending'}"
        return WaitAssessment(ready, evidence, RecoveryRoute.M7_INTERVENTION)


__all__ = [
    "ActionCandidateFactory",
    "DynamicLegalOperationBuilder",
    "DynamicLegalOperationSet",
    "EscalationRequirement",
    "LegalOperation",
    "LegalOperationKind",
    "PreDispatchStatus",
    "PreDispatchValidation",
    "PreDispatchValidator",
    "ResolutionState",
    "SemanticResolution",
    "SemanticStateEvidence",
    "SemanticTargetDescriptor",
    "SemanticTargetResolver",
    "SemanticUIError",
    "SemanticUIPolicyError",
    "SemanticWaitCondition",
    "SemanticWaitKind",
    "SemanticWaitResolver",
    "UIBounds",
    "UIObject",
]
