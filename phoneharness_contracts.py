#!/usr/bin/env python3
"""Immutable, non-authoritative contracts for PhoneHarness Stage 3.

These value objects describe observations, targets, candidates, decisions,
artifacts, context projections, and bounded semantic programs. They do not
authorize, bind, dispatch, execute, persist, retry, or verify device actions.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import re
from typing import Any, ClassVar, Iterable, Mapping


class ContractValidationError(ValueError):
    """A Stage-3 contract is malformed, ambiguous, or outside its bounds."""


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_AUTHORITY_FIELDS = frozenset(
    {
        "authorized",
        "authorization",
        "authorization_ticket",
        "binding",
        "binding_id",
        "executor_authority",
        "executor_port",
        "raw_provider",
        "raw_executor",
    }
)
_FORBIDDEN_SECRET_FIELDS = frozenset(
    {
        "secret",
        "password",
        "passcode",
        "token",
        "credential",
        "private_key",
        "authorization_header",
    }
)


def _identifier(value: Any, field_name: str) -> str:
    normalized = str(value or "").strip()
    if _IDENTIFIER.fullmatch(normalized) is None:
        raise ContractValidationError(f"{field_name} must be an opaque bounded identifier")
    return normalized


def _optional_identifier(value: Any, field_name: str) -> str | None:
    return None if value is None else _identifier(value, field_name)


def _bounded_text(value: Any, field_name: str, *, maximum: int = 256) -> str:
    normalized = " ".join(str(value or "").split())
    if not normalized or len(normalized) > maximum:
        raise ContractValidationError(f"{field_name} must be non-empty bounded text")
    return normalized


def _positive_int(value: Any, field_name: str, *, allow_zero: bool = False) -> int:
    minimum = 0 if allow_zero else 1
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ContractValidationError(f"{field_name} is outside its allowed range")
    return value


def _strict_payload(payload: Any, *, required: set[str], optional: set[str] = set()) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ContractValidationError("serialized contract must be an object")
    keys = set(payload)
    if not required.issubset(keys) or not keys.issubset(required | optional):
        raise ContractValidationError("serialized contract fields do not match its schema")
    if keys & _FORBIDDEN_AUTHORITY_FIELDS:
        raise ContractValidationError("serialized contract cannot carry authority fields")
    return payload


def _metadata(
    value: Mapping[str, Any] | Iterable[tuple[str, Any]],
    field_name: str,
    *,
    maximum_items: int = 16,
) -> tuple[tuple[str, str], ...]:
    items = value.items() if isinstance(value, Mapping) else value
    normalized: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw_key, raw_value in items:
        key = _identifier(raw_key, f"{field_name} key")
        if key.casefold() in _FORBIDDEN_AUTHORITY_FIELDS | _FORBIDDEN_SECRET_FIELDS:
            raise ContractValidationError(f"{field_name} cannot contain authority or secret fields")
        if key in seen:
            raise ContractValidationError(f"{field_name} cannot contain duplicate keys")
        seen.add(key)
        normalized.append((key, _bounded_text(raw_value, f"{field_name} value")))
    if len(normalized) > maximum_items:
        raise ContractValidationError(f"{field_name} exceeds its bounded size")
    return tuple(sorted(normalized))


def _identifier_tuple(values: Iterable[str], field_name: str, *, maximum: int = 32) -> tuple[str, ...]:
    normalized = tuple(_identifier(value, field_name) for value in values)
    if len(normalized) > maximum or len(normalized) != len(set(normalized)):
        raise ContractValidationError(f"{field_name} must be bounded and unique")
    return normalized


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


class ObservationFreshness(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ObservationRef:
    observation_id: str
    producer: str
    task_id: str
    session_id: str | None = None
    generation: int | None = None
    observed_at_ms: int | None = None
    freshness: ObservationFreshness = ObservationFreshness.UNKNOWN
    schema_version: str = "phoneharness.observation-ref.v1"

    def __post_init__(self) -> None:
        if self.schema_version != "phoneharness.observation-ref.v1":
            raise ContractValidationError("unsupported ObservationRef schema version")
        for name in ("observation_id", "producer", "task_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(self, "session_id", _optional_identifier(self.session_id, "session_id"))
        if self.generation is not None:
            _positive_int(self.generation, "generation", allow_zero=True)
        if self.observed_at_ms is not None:
            _positive_int(self.observed_at_ms, "observed_at_ms", allow_zero=True)
        try:
            object.__setattr__(self, "freshness", ObservationFreshness(self.freshness))
        except ValueError as exc:
            raise ContractValidationError("unsupported observation freshness") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "observation_id": self.observation_id,
            "producer": self.producer,
            "task_id": self.task_id,
            "session_id": self.session_id,
            "generation": self.generation,
            "observed_at_ms": self.observed_at_ms,
            "freshness": self.freshness.value,
        }

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ObservationRef":
        data = _strict_payload(
            payload,
            required={
                "schema_version",
                "observation_id",
                "producer",
                "task_id",
                "session_id",
                "generation",
                "observed_at_ms",
                "freshness",
            },
        )
        return cls(**data)


@dataclass(frozen=True)
class ObservedTargetRef:
    target_id: str
    observation_ref: ObservationRef
    target_kind: str
    semantic_role: str
    capability_hint: str | None = None
    metadata: tuple[tuple[str, str], ...] = ()
    schema_version: str = "phoneharness.observed-target-ref.v1"

    def __post_init__(self) -> None:
        if self.schema_version != "phoneharness.observed-target-ref.v1":
            raise ContractValidationError("unsupported ObservedTargetRef schema version")
        if not isinstance(self.observation_ref, ObservationRef):
            raise ContractValidationError("ObservedTargetRef requires ObservationRef")
        for name in ("target_id", "target_kind", "semantic_role"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(self, "capability_hint", _optional_identifier(self.capability_hint, "capability_hint"))
        object.__setattr__(self, "metadata", _metadata(self.metadata, "target metadata"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "target_id": self.target_id,
            "observation_ref": self.observation_ref.to_dict(),
            "target_kind": self.target_kind,
            "semantic_role": self.semantic_role,
            "capability_hint": self.capability_hint,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class CandidateRef:
    candidate_set_id: str
    candidate_id: str
    schema_version: str = "phoneharness.candidate-ref.v1"

    def __post_init__(self) -> None:
        if self.schema_version != "phoneharness.candidate-ref.v1":
            raise ContractValidationError("unsupported CandidateRef schema version")
        object.__setattr__(self, "candidate_set_id", _identifier(self.candidate_set_id, "candidate_set_id"))
        object.__setattr__(self, "candidate_id", _identifier(self.candidate_id, "candidate_id"))

    def to_dict(self) -> dict[str, str]:
        return {
            "schema_version": self.schema_version,
            "candidate_set_id": self.candidate_set_id,
            "candidate_id": self.candidate_id,
        }


@dataclass(frozen=True)
class ActionCandidate:
    ref: CandidateRef
    capability_intent: str
    observation_ref: ObservationRef
    target_ref: ObservedTargetRef | None = None
    reason_code: str | None = None
    confidence: float | None = None
    decision_provider: str | None = None
    metadata: tuple[tuple[str, str], ...] = ()
    schema_version: str = "phoneharness.action-candidate.v1"

    def __post_init__(self) -> None:
        if self.schema_version != "phoneharness.action-candidate.v1":
            raise ContractValidationError("unsupported ActionCandidate schema version")
        if not isinstance(self.ref, CandidateRef) or not isinstance(self.observation_ref, ObservationRef):
            raise ContractValidationError("ActionCandidate requires typed references")
        object.__setattr__(self, "capability_intent", _identifier(self.capability_intent, "capability_intent"))
        object.__setattr__(self, "reason_code", _optional_identifier(self.reason_code, "reason_code"))
        object.__setattr__(self, "decision_provider", _optional_identifier(self.decision_provider, "decision_provider"))
        if self.confidence is not None and (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not 0.0 <= float(self.confidence) <= 1.0
        ):
            raise ContractValidationError("candidate confidence must be advisory and bounded")
        if self.target_ref is not None:
            if not isinstance(self.target_ref, ObservedTargetRef):
                raise ContractValidationError("candidate target must use ObservedTargetRef")
            if self.target_ref.observation_ref != self.observation_ref:
                raise ContractValidationError("candidate target must share its observation reference")
        object.__setattr__(self, "metadata", _metadata(self.metadata, "candidate metadata"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ref": self.ref.to_dict(),
            "capability_intent": self.capability_intent,
            "observation_ref": self.observation_ref.to_dict(),
            "target_ref": self.target_ref.to_dict() if self.target_ref else None,
            "reason_code": self.reason_code,
            "confidence": self.confidence,
            "decision_provider": self.decision_provider,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ActionCandidateSet:
    candidate_set_id: str
    observation_ref: ObservationRef
    context_ref: str
    candidates: tuple[ActionCandidate, ...]
    maximum_candidates: int = 32
    schema_version: str = "phoneharness.action-candidate-set.v1"

    def __post_init__(self) -> None:
        if self.schema_version != "phoneharness.action-candidate-set.v1":
            raise ContractValidationError("unsupported ActionCandidateSet schema version")
        object.__setattr__(self, "candidate_set_id", _identifier(self.candidate_set_id, "candidate_set_id"))
        object.__setattr__(self, "context_ref", _identifier(self.context_ref, "context_ref"))
        if not isinstance(self.observation_ref, ObservationRef):
            raise ContractValidationError("ActionCandidateSet requires ObservationRef")
        object.__setattr__(self, "candidates", tuple(self.candidates))
        _positive_int(self.maximum_candidates, "maximum_candidates")
        if self.maximum_candidates > 32 or len(self.candidates) > self.maximum_candidates:
            raise ContractValidationError("candidate set exceeds its bounded size")
        identifiers: list[str] = []
        for candidate in self.candidates:
            if not isinstance(candidate, ActionCandidate):
                raise ContractValidationError("candidate set contains an untyped candidate")
            if candidate.ref.candidate_set_id != self.candidate_set_id:
                raise ContractValidationError("candidate belongs to a different candidate set")
            if candidate.observation_ref != self.observation_ref:
                raise ContractValidationError("candidate belongs to a different observation")
            identifiers.append(candidate.ref.candidate_id)
        if len(identifiers) != len(set(identifiers)):
            raise ContractValidationError("candidate IDs must be unique")

    def contains(self, ref: CandidateRef) -> bool:
        return ref.candidate_set_id == self.candidate_set_id and any(
            candidate.ref == ref for candidate in self.candidates
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "candidate_set_id": self.candidate_set_id,
            "observation_ref": self.observation_ref.to_dict(),
            "context_ref": self.context_ref,
            "maximum_candidates": self.maximum_candidates,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


@dataclass(frozen=True, init=False)
class DecisionEnvelope:
    decision_id: str
    selected_candidate_ref: CandidateRef
    observation_ref: ObservationRef
    decision_source: str
    reason_code: str | None = None
    confidence: float | None = None
    schema_version: str = "phoneharness.decision-envelope.v1"

    def __init__(
        self,
        *,
        decision_id: str,
        candidate_set: ActionCandidateSet,
        selected_candidate_ref: CandidateRef,
        decision_source: str,
        reason_code: str | None = None,
        confidence: float | None = None,
        schema_version: str = "phoneharness.decision-envelope.v1",
    ) -> None:
        if not isinstance(candidate_set, ActionCandidateSet) or not candidate_set.contains(selected_candidate_ref):
            raise ContractValidationError("decision must select an existing candidate")
        object.__setattr__(self, "decision_id", decision_id)
        object.__setattr__(self, "selected_candidate_ref", selected_candidate_ref)
        object.__setattr__(self, "observation_ref", candidate_set.observation_ref)
        object.__setattr__(self, "decision_source", decision_source)
        object.__setattr__(self, "reason_code", reason_code)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "schema_version", schema_version)
        self._validate()

    def _validate(self) -> None:
        if self.schema_version != "phoneharness.decision-envelope.v1":
            raise ContractValidationError("unsupported DecisionEnvelope schema version")
        if not isinstance(self.selected_candidate_ref, CandidateRef) or not isinstance(
            self.observation_ref, ObservationRef
        ):
            raise ContractValidationError("DecisionEnvelope requires typed references")
        object.__setattr__(self, "decision_id", _identifier(self.decision_id, "decision_id"))
        object.__setattr__(self, "decision_source", _identifier(self.decision_source, "decision_source"))
        object.__setattr__(self, "reason_code", _optional_identifier(self.reason_code, "reason_code"))
        if self.confidence is not None and (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not 0.0 <= float(self.confidence) <= 1.0
        ):
            raise ContractValidationError("decision confidence must be advisory and bounded")

    @classmethod
    def select(
        cls,
        *,
        decision_id: str,
        candidate_set: ActionCandidateSet,
        selected_candidate_ref: CandidateRef,
        decision_source: str,
        reason_code: str | None = None,
        confidence: float | None = None,
    ) -> "DecisionEnvelope":
        return cls(
            decision_id=decision_id,
            candidate_set=candidate_set,
            selected_candidate_ref=selected_candidate_ref,
            decision_source=decision_source,
            reason_code=reason_code,
            confidence=confidence,
        )

    def validate_against(self, candidate_set: ActionCandidateSet) -> None:
        if self.observation_ref != candidate_set.observation_ref or not candidate_set.contains(
            self.selected_candidate_ref
        ):
            raise ContractValidationError("decision does not match its candidate set")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "decision_id": self.decision_id,
            "selected_candidate_ref": self.selected_candidate_ref.to_dict(),
            "observation_ref": self.observation_ref.to_dict(),
            "decision_source": self.decision_source,
            "reason_code": self.reason_code,
            "confidence": self.confidence,
        }


class ArtifactLifetime(str, Enum):
    EPHEMERAL = "EPHEMERAL"
    SESSION = "SESSION"
    DURABLE = "DURABLE"


class SensitivityClass(str, Enum):
    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"
    SENSITIVE = "SENSITIVE"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    NEVER_MODEL_VISIBLE = "NEVER_MODEL_VISIBLE"


@dataclass(frozen=True)
class ArtifactRef:
    artifact_id: str
    task_id: str
    session_id: str | None = None
    schema_version: str = "phoneharness.artifact-ref.v1"

    def __post_init__(self) -> None:
        if self.schema_version != "phoneharness.artifact-ref.v1":
            raise ContractValidationError("unsupported ArtifactRef schema version")
        object.__setattr__(self, "artifact_id", _identifier(self.artifact_id, "artifact_id"))
        object.__setattr__(self, "task_id", _identifier(self.task_id, "task_id"))
        object.__setattr__(self, "session_id", _optional_identifier(self.session_id, "session_id"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "artifact_id": self.artifact_id,
            "task_id": self.task_id,
            "session_id": self.session_id,
        }


@dataclass(frozen=True)
class ArtifactDescriptor:
    ref: ArtifactRef
    artifact_kind: str
    producer: str
    created_at_ms: int
    sensitivity: SensitivityClass
    lifetime: ArtifactLifetime
    observation_ref: ObservationRef | None = None
    content_digest: str | None = None
    opaque_locator: str | None = None
    metadata: tuple[tuple[str, str], ...] = ()
    schema_version: str = "phoneharness.artifact-descriptor.v1"

    def __post_init__(self) -> None:
        if self.schema_version != "phoneharness.artifact-descriptor.v1":
            raise ContractValidationError("unsupported ArtifactDescriptor schema version")
        if not isinstance(self.ref, ArtifactRef):
            raise ContractValidationError("ArtifactDescriptor requires ArtifactRef")
        object.__setattr__(self, "artifact_kind", _identifier(self.artifact_kind, "artifact_kind"))
        object.__setattr__(self, "producer", _identifier(self.producer, "producer"))
        _positive_int(self.created_at_ms, "created_at_ms", allow_zero=True)
        try:
            object.__setattr__(self, "sensitivity", SensitivityClass(self.sensitivity))
            object.__setattr__(self, "lifetime", ArtifactLifetime(self.lifetime))
        except ValueError as exc:
            raise ContractValidationError("unsupported artifact classification") from exc
        if self.observation_ref is not None:
            if not isinstance(self.observation_ref, ObservationRef):
                raise ContractValidationError("artifact observation provenance must use ObservationRef")
            if self.observation_ref.task_id != self.ref.task_id:
                raise ContractValidationError("artifact and observation task scopes do not match")
        if self.content_digest is not None and _DIGEST.fullmatch(self.content_digest) is None:
            raise ContractValidationError("artifact content digest must be lowercase SHA-256")
        object.__setattr__(self, "opaque_locator", _optional_identifier(self.opaque_locator, "opaque_locator"))
        object.__setattr__(self, "metadata", _metadata(self.metadata, "artifact metadata"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ref": self.ref.to_dict(),
            "artifact_kind": self.artifact_kind,
            "producer": self.producer,
            "created_at_ms": self.created_at_ms,
            "sensitivity": self.sensitivity.value,
            "lifetime": self.lifetime.value,
            "observation_ref": self.observation_ref.to_dict() if self.observation_ref else None,
            "content_digest": self.content_digest,
            "opaque_locator": self.opaque_locator,
            "metadata": dict(self.metadata),
        }

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())

    def model_projection(self) -> dict[str, Any]:
        result = {
            "ref": self.ref.to_dict(),
            "artifact_kind": self.artifact_kind,
            "producer": self.producer,
            "sensitivity": self.sensitivity.value,
            "lifetime": self.lifetime.value,
            "model_visible": self.sensitivity is SensitivityClass.PUBLIC,
        }
        if self.sensitivity is SensitivityClass.PUBLIC:
            result["metadata"] = dict(self.metadata)
        return result


@dataclass(frozen=True)
class RuntimeContextProjection:
    projection_id: str
    task_id: str
    goal_ref: str
    folded_state: str
    active_observation_ref: ObservationRef | None = None
    recent_step_refs: tuple[str, ...] = ()
    candidate_set_ref: str | None = None
    artifact_refs: tuple[ArtifactRef, ...] = ()
    failure_context_refs: tuple[str, ...] = ()
    available_capability_view_ref: str | None = None
    schema_version: str = "phoneharness.runtime-context-projection.v1"

    def __post_init__(self) -> None:
        if self.schema_version != "phoneharness.runtime-context-projection.v1":
            raise ContractValidationError("unsupported RuntimeContextProjection schema version")
        for name in ("projection_id", "task_id", "goal_ref", "folded_state"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        if self.active_observation_ref is not None:
            if not isinstance(self.active_observation_ref, ObservationRef):
                raise ContractValidationError("active observation must use ObservationRef")
            if self.active_observation_ref.task_id != self.task_id:
                raise ContractValidationError("context observation belongs to a different task")
        object.__setattr__(self, "recent_step_refs", _identifier_tuple(self.recent_step_refs, "step ref", maximum=16))
        object.__setattr__(self, "candidate_set_ref", _optional_identifier(self.candidate_set_ref, "candidate_set_ref"))
        object.__setattr__(
            self,
            "failure_context_refs",
            _identifier_tuple(self.failure_context_refs, "failure context ref", maximum=8),
        )
        object.__setattr__(
            self,
            "available_capability_view_ref",
            _optional_identifier(self.available_capability_view_ref, "available_capability_view_ref"),
        )
        object.__setattr__(self, "artifact_refs", tuple(self.artifact_refs))
        artifact_ids: list[str] = []
        for ref in self.artifact_refs:
            if not isinstance(ref, ArtifactRef) or ref.task_id != self.task_id:
                raise ContractValidationError("context artifacts must be typed and task-scoped")
            artifact_ids.append(ref.artifact_id)
        if len(artifact_ids) > 16 or len(artifact_ids) != len(set(artifact_ids)):
            raise ContractValidationError("context artifact refs must be bounded and unique")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "projection_id": self.projection_id,
            "task_id": self.task_id,
            "goal_ref": self.goal_ref,
            "folded_state": self.folded_state,
            "active_observation_ref": self.active_observation_ref.to_dict() if self.active_observation_ref else None,
            "recent_step_refs": list(self.recent_step_refs),
            "candidate_set_ref": self.candidate_set_ref,
            "artifact_refs": [ref.to_dict() for ref in self.artifact_refs],
            "failure_context_refs": list(self.failure_context_refs),
            "available_capability_view_ref": self.available_capability_view_ref,
            "authority": "none",
            "canonical_runtime_truth": False,
        }


class SemanticProgramNodeType(str, Enum):
    SEQUENCE = "sequence"
    IF = "if"
    FOR_EACH = "for_each"
    BOUNDED_WHILE = "bounded_while"
    VARIABLE = "variable"
    CHECKPOINT = "checkpoint"
    CALL_SKILL = "call_skill"
    CALL_TOOL = "call_tool"
    WAIT_FOR = "wait_for"
    VERIFY = "verify"
    RECOVER = "recover"
    RETURN = "return"


@dataclass(frozen=True)
class SemanticProgramNode:
    node_id: str
    node_type: SemanticProgramNodeType
    arguments: tuple[tuple[str, str], ...] = ()
    children: tuple["SemanticProgramNode", ...] = ()
    maximum_iterations: int | None = None

    _REQUIRED_ARGUMENTS: ClassVar[dict[SemanticProgramNodeType, frozenset[str]]] = {
        SemanticProgramNodeType.SEQUENCE: frozenset(),
        SemanticProgramNodeType.IF: frozenset({"condition_ref"}),
        SemanticProgramNodeType.FOR_EACH: frozenset({"collection_ref", "variable_name"}),
        SemanticProgramNodeType.BOUNDED_WHILE: frozenset({"condition_ref"}),
        SemanticProgramNodeType.VARIABLE: frozenset({"variable_name", "value_ref"}),
        SemanticProgramNodeType.CHECKPOINT: frozenset({"artifact_ref"}),
        SemanticProgramNodeType.CALL_SKILL: frozenset({"skill_id"}),
        SemanticProgramNodeType.CALL_TOOL: frozenset({"capability_id", "operation"}),
        SemanticProgramNodeType.WAIT_FOR: frozenset({"condition_ref"}),
        SemanticProgramNodeType.VERIFY: frozenset({"verifier_id"}),
        SemanticProgramNodeType.RECOVER: frozenset({"recovery_policy"}),
        SemanticProgramNodeType.RETURN: frozenset({"result_ref"}),
    }

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_id", _identifier(self.node_id, "node_id"))
        try:
            object.__setattr__(self, "node_type", SemanticProgramNodeType(self.node_type))
        except ValueError as exc:
            raise ContractValidationError("unknown semantic program node type") from exc
        object.__setattr__(self, "arguments", _metadata(self.arguments, "program arguments", maximum_items=12))
        object.__setattr__(self, "children", tuple(self.children))
        argument_keys = frozenset(dict(self.arguments))
        required = self._REQUIRED_ARGUMENTS[self.node_type]
        if not required.issubset(argument_keys):
            raise ContractValidationError("semantic program node is missing required arguments")
        structural = {
            SemanticProgramNodeType.SEQUENCE,
            SemanticProgramNodeType.IF,
            SemanticProgramNodeType.FOR_EACH,
            SemanticProgramNodeType.BOUNDED_WHILE,
        }
        if self.node_type is SemanticProgramNodeType.SEQUENCE and not self.children:
            raise ContractValidationError("sequence requires at least one child")
        if self.node_type is SemanticProgramNodeType.IF and len(self.children) not in {1, 2}:
            raise ContractValidationError("if requires one or two bounded branches")
        if self.node_type in {SemanticProgramNodeType.FOR_EACH, SemanticProgramNodeType.BOUNDED_WHILE}:
            if len(self.children) != 1:
                raise ContractValidationError("bounded loop requires exactly one body")
            if self.maximum_iterations is None:
                raise ContractValidationError("loop requires an explicit maximum iteration count")
            _positive_int(self.maximum_iterations, "maximum_iterations")
            if self.maximum_iterations > 32:
                raise ContractValidationError("loop bound exceeds the contract maximum")
        elif self.maximum_iterations is not None:
            raise ContractValidationError("non-loop node cannot carry an iteration bound")
        if self.node_type not in structural and self.children:
            raise ContractValidationError("leaf semantic program node cannot contain children")
        if any(not isinstance(child, SemanticProgramNode) for child in self.children):
            raise ContractValidationError("semantic program children must be typed nodes")

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type.value,
            "arguments": dict(self.arguments),
            "children": [child.to_dict() for child in self.children],
            "maximum_iterations": self.maximum_iterations,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SemanticProgramNode":
        data = _strict_payload(
            payload,
            required={"node_id", "node_type", "arguments", "children", "maximum_iterations"},
        )
        if not isinstance(data["children"], list):
            raise ContractValidationError("semantic program children must be a list")
        return cls(
            node_id=data["node_id"],
            node_type=data["node_type"],
            arguments=data["arguments"],
            children=tuple(cls.from_dict(child) for child in data["children"]),
            maximum_iterations=data["maximum_iterations"],
        )


@dataclass(frozen=True)
class SemanticTaskProgram:
    program_id: str
    task_id: str
    root: SemanticProgramNode
    maximum_nodes: int = 128
    maximum_depth: int = 16
    schema_version: str = "phoneharness.semantic-task-program.v1"

    def __post_init__(self) -> None:
        if self.schema_version != "phoneharness.semantic-task-program.v1":
            raise ContractValidationError("unsupported SemanticTaskProgram schema version")
        object.__setattr__(self, "program_id", _identifier(self.program_id, "program_id"))
        object.__setattr__(self, "task_id", _identifier(self.task_id, "task_id"))
        if not isinstance(self.root, SemanticProgramNode):
            raise ContractValidationError("semantic task program requires a typed root")
        _positive_int(self.maximum_nodes, "maximum_nodes")
        _positive_int(self.maximum_depth, "maximum_depth")
        if self.maximum_nodes > 128 or self.maximum_depth > 16:
            raise ContractValidationError("semantic task program exceeds contract bounds")
        identifiers: list[str] = []

        def visit(node: SemanticProgramNode, depth: int) -> None:
            if depth > self.maximum_depth:
                raise ContractValidationError("semantic task program exceeds maximum depth")
            identifiers.append(node.node_id)
            if len(identifiers) > self.maximum_nodes:
                raise ContractValidationError("semantic task program exceeds maximum nodes")
            for child in node.children:
                visit(child, depth + 1)

        visit(self.root, 1)
        if len(identifiers) != len(set(identifiers)):
            raise ContractValidationError("semantic task program node IDs must be unique")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "program_id": self.program_id,
            "task_id": self.task_id,
            "maximum_nodes": self.maximum_nodes,
            "maximum_depth": self.maximum_depth,
            "root": self.root.to_dict(),
            "authority": "none",
            "executable": False,
        }

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SemanticTaskProgram":
        data = _strict_payload(
            payload,
            required={"schema_version", "program_id", "task_id", "maximum_nodes", "maximum_depth", "root"},
            optional={"authority", "executable"},
        )
        if data.get("authority") not in {None, "none"} or data.get("executable") not in {None, False}:
            raise ContractValidationError("semantic program cannot carry execution authority")
        return cls(
            schema_version=data["schema_version"],
            program_id=data["program_id"],
            task_id=data["task_id"],
            maximum_nodes=data["maximum_nodes"],
            maximum_depth=data["maximum_depth"],
            root=SemanticProgramNode.from_dict(data["root"]),
        )


@dataclass(frozen=True)
class ConstrainedGenerationContract:
    maximum_nodes: int = 128
    maximum_depth: int = 16
    maximum_loop_iterations: int = 32
    schema_version: str = "phoneharness.constrained-generation.v1"

    def __post_init__(self) -> None:
        if self.schema_version != "phoneharness.constrained-generation.v1":
            raise ContractValidationError("unsupported constrained-generation schema version")
        for name, maximum in (
            ("maximum_nodes", 128),
            ("maximum_depth", 16),
            ("maximum_loop_iterations", 32),
        ):
            value = getattr(self, name)
            _positive_int(value, name)
            if value > maximum:
                raise ContractValidationError(f"{name} exceeds the supported contract")

    def validate(self, program: SemanticTaskProgram) -> None:
        if not isinstance(program, SemanticTaskProgram):
            raise ContractValidationError("generation output must be a SemanticTaskProgram")
        if program.maximum_nodes > self.maximum_nodes or program.maximum_depth > self.maximum_depth:
            raise ContractValidationError("generated program exceeds generation bounds")

        def visit(node: SemanticProgramNode) -> None:
            if node.maximum_iterations is not None and node.maximum_iterations > self.maximum_loop_iterations:
                raise ContractValidationError("generated loop exceeds generation bounds")
            for child in node.children:
                visit(child)

        visit(program.root)

    def json_schema(self) -> dict[str, Any]:
        """Return a deterministic JSON-Schema-compatible generation surface."""

        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": self.schema_version,
            "type": "object",
            "required": ["schema_version", "program_id", "task_id", "maximum_nodes", "maximum_depth", "root"],
            "additionalProperties": False,
            "properties": {
                "schema_version": {"const": "phoneharness.semantic-task-program.v1"},
                "program_id": {"type": "string"},
                "task_id": {"type": "string"},
                "maximum_nodes": {"type": "integer", "minimum": 1, "maximum": self.maximum_nodes},
                "maximum_depth": {"type": "integer", "minimum": 1, "maximum": self.maximum_depth},
                "root": {"$ref": "#/$defs/node"},
            },
            "$defs": {
                "node": {
                    "type": "object",
                    "required": ["node_id", "node_type", "arguments", "children", "maximum_iterations"],
                    "additionalProperties": False,
                    "properties": {
                        "node_id": {"type": "string"},
                        "node_type": {"enum": [kind.value for kind in SemanticProgramNodeType]},
                        "arguments": {"type": "object"},
                        "children": {"type": "array", "items": {"$ref": "#/$defs/node"}},
                        "maximum_iterations": {
                            "type": ["integer", "null"],
                            "minimum": 1,
                            "maximum": self.maximum_loop_iterations,
                        },
                    },
                }
            },
        }
