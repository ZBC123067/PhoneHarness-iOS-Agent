#!/usr/bin/env python3
"""Static contract tests for TEST-40.1 Visual Intelligence Foundation.

The suite uses synthetic Semantic UI Graphs only. It does not capture an
image, invoke OCR, contact an iPhone, call MCP, execute an action, or create a
replayable procedure.
"""

from __future__ import annotations

import unittest

from phoneharness_agent import (
    ActiveVisionStateError,
    ActiveVisionStateMachine,
    ObservationProviderRouter,
    SemanticUIGraph,
    VISUAL_INTELLIGENCE_FOUNDATION_VERSION,
    VisualDomainResolver,
    VisualDomainSignal,
    VisualEvidence,
    VisualIntelligenceFoundation,
    VisualIntelligencePolicyError,
    VisualMemoryInterface,
)


FORBIDDEN_KEYS = frozenset(
    {
        "screenshot",
        "image",
        "thumbnail",
        "embedding",
        "ocr",
        "raw_ocr",
        "text",
        "label",
        "coordinate",
        "coordinates",
        "rect",
        "geometry",
        "ui",
        "ui_dump",
        "app",
        "bundle_id",
        "input",
        "password",
        "mcp",
        "raw_mcp_response",
        "action",
        "selector",
        "tool_arguments",
        "replay_steps",
    }
)


def keys_in(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(keys_in(item) for item in value.values())) if value else set()
    if isinstance(value, (tuple, list)):
        return set().union(*(keys_in(item) for item in value)) if value else set()
    return set()


def graph(
    *,
    source: str = "AX",
    timestamp: int = 100,
    confidence: float = 0.95,
    state: str = "verified",
) -> SemanticUIGraph:
    affordance_state = "actionable" if state == "verified" else state
    semantic_graph = SemanticUIGraph(
        graph_version="test-29.0",
        source=source,
        timestamp=timestamp,
        confidence=confidence,
        state=state,
        nodes=(
            {
                "type": "page",
                "role": "search",
                "capability": "screen_context",
                "state": state,
                "confidence": confidence,
                "source": source,
                "timestamp": timestamp,
                "count": 1,
            },
            {
                "type": "affordance",
                "role": "search",
                "capability": "search_content",
                "state": affordance_state,
                "confidence": confidence,
                "source": source,
                "timestamp": timestamp,
                "count": 1,
            },
        ),
        edges=(
            {
                "from_type": "page",
                "from_role": "search",
                "relation": "contains",
                "to_type": "affordance",
                "to_role": "search",
                "confidence": confidence,
                "source": source,
                "timestamp": timestamp,
            },
        ),
    )
    semantic_graph.validate_public_schema()
    return semantic_graph


class VisualIntelligenceFoundationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.resolver = VisualDomainResolver({"domain_alpha", "domain_beta"})
        self.memory = VisualMemoryInterface()
        self.foundation = VisualIntelligenceFoundation(domain_resolver=self.resolver, visual_memory=self.memory)

    @staticmethod
    def alpha_signal(*, confidence: float = 0.93, timestamp: int = 100) -> VisualDomainSignal:
        return VisualDomainSignal(
            domain="domain_alpha",
            source_type="Vision",
            confidence=confidence,
            timestamp=timestamp,
        )

    def test_candidate_has_safe_confidence_entity_domain_and_evidence(self) -> None:
        candidate = self.foundation.interpret(graph(), domain_signals=(self.alpha_signal(),))
        summary = candidate.schema()
        self.assertEqual(VISUAL_INTELLIGENCE_FOUNDATION_VERSION, summary["visual_intelligence_version"])
        self.assertEqual("READY", summary["status"])
        self.assertEqual("domain_alpha", summary["domain"])
        self.assertEqual(("screen_context", "interaction_affordance"), candidate.detected_entity_types)
        self.assertEqual({"AX", "Vision"}, set(summary["source_types"]))
        self.assertFalse(FORBIDDEN_KEYS.intersection(keys_in(summary)))
        self.assertGreaterEqual(summary["confidence"], self.foundation.MIN_READY_CONFIDENCE)
        self.assertEqual("semantic_graph", summary["evidence"][0]["evidence_class"])

    def test_low_confidence_returns_needs_confirmation_without_guessing(self) -> None:
        candidate = self.foundation.interpret(
            graph(confidence=0.40), domain_signals=(self.alpha_signal(confidence=0.95),)
        )
        self.assertEqual("NEEDS_CONFIRMATION", candidate.status)
        self.assertIn("low_visual_confidence", candidate.reason_codes)
        self.assertFalse(self.memory.patterns())

    def test_conflicting_domain_signals_return_needs_confirmation(self) -> None:
        candidate = self.foundation.interpret(
            graph(),
            domain_signals=(
                self.alpha_signal(confidence=0.93),
                VisualDomainSignal("domain_beta", "OCR", 0.92, 100),
            ),
        )
        self.assertEqual("NEEDS_CONFIRMATION", candidate.status)
        self.assertEqual("UNKNOWN_DOMAIN", candidate.domain)
        self.assertIn("conflicting_domain_signals", candidate.reason_codes)

    def test_unregistered_domain_signal_cannot_be_promoted(self) -> None:
        candidate = self.foundation.interpret(
            graph(),
            domain_signals=(VisualDomainSignal("unregistered_domain", "Vision", 0.98, 100),),
        )
        self.assertEqual("NEEDS_CONFIRMATION", candidate.status)
        self.assertEqual("UNKNOWN_DOMAIN", candidate.domain)
        self.assertIn("unregistered_domain_signal", candidate.reason_codes)

    def test_evidence_schema_rejects_content_like_entity_metadata(self) -> None:
        with self.assertRaises(VisualIntelligencePolicyError):
            VisualEvidence(
                source_type="Vision",
                confidence=0.90,
                timestamp=100,
                entity_type="private_message",
                evidence_class="semantic_graph",
            ).validate_public_schema()

    def test_visual_memory_stores_only_ready_aggregate_pattern_metadata(self) -> None:
        candidate = self.foundation.interpret(graph(), domain_signals=(self.alpha_signal(),))
        pattern = self.memory.record_pattern(candidate, pattern_class="search")
        summary = pattern.schema()
        self.assertEqual(1, summary["observed_count"])
        self.assertEqual("domain_alpha", summary["domain"])
        self.assertFalse(FORBIDDEN_KEYS.intersection(keys_in(summary)))
        self.assertEqual((pattern,), self.memory.patterns())

    def test_visual_memory_rejects_unconfirmed_or_raw_pattern_data(self) -> None:
        pending = self.foundation.interpret(graph(), domain_signals=())
        with self.assertRaises(VisualIntelligencePolicyError):
            self.memory.record_pattern(pending, pattern_class="search")
        with self.assertRaises(VisualIntelligencePolicyError):
            self.memory.record_pattern(
                self.foundation.interpret(graph(), domain_signals=(self.alpha_signal(),)),
                pattern_class="private_message",
            )

    def test_active_vision_state_machine_requires_explicit_non_executing_transitions(self) -> None:
        state = ActiveVisionStateMachine()
        self.assertEqual("OFF", state.state)
        state.request(timestamp=10)
        state.begin_observation(timestamp=11)
        state.begin_task_execution(timestamp=12)
        state.begin_verification(timestamp=13)
        state.stop(timestamp=14)
        state.reset(timestamp=15)
        self.assertEqual("OFF", state.state)
        self.assertEqual(
            ("OFF", "USER_REQUESTED", "ACTIVE_OBSERVATION", "TASK_EXECUTION", "VERIFY", "STOP", "OFF"),
            tuple(item["state"] for item in state.history()),
        )
        with self.assertRaises(ActiveVisionStateError):
            state.begin_verification(timestamp=16)

    def test_visual_objects_have_no_observation_or_execution_authority(self) -> None:
        for value in (self.foundation, self.resolver, self.memory, ActiveVisionStateMachine()):
            for forbidden_name in (
                "client",
                "mcp",
                "observe",
                "describe",
                "plan",
                "risk",
                "execute",
                "call_tool",
                "tap",
                "input",
                "launch",
            ):
                self.assertFalse(hasattr(value, forbidden_name), forbidden_name)

    def test_existing_provider_order_is_not_changed(self) -> None:
        self.assertEqual(("AX", "Vision", "OCR", "VLM"), ObservationProviderRouter.PROVIDER_ORDER)

    def test_foundation_requires_existing_safe_semantic_graph(self) -> None:
        with self.assertRaises(VisualIntelligencePolicyError):
            self.foundation.interpret({"source": "AX"})  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main(verbosity=2)
