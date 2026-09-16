#!/usr/bin/env python3
"""Static boundary tests for TEST-29 Semantic UI Graph."""

from __future__ import annotations

import inspect
import json
import unittest

from phoneharness_agent import (
    GUIStateTracker,
    Observation,
    SemanticUIGraph,
    SemanticUIGraphBuilder,
    SemanticUIGraphError,
)


FORBIDDEN_SERIALIZED_FIELDS = (
    '"screenshot"',
    '"coordinate"',
    '"coordinates"',
    '"rect"',
    '"frame"',
    '"raw_ax"',
    '"ocr_text"',
    '"ui_dump"',
    '"raw_response"',
    '"mcp_response"',
    '"element_id"',
    '"binding_id"',
    '"index"',
    '"label"',
    '"value"',
    '"password"',
    '"input"',
)


def observation(
    elements: tuple[dict[str, object], ...],
    *,
    source: str = "AX",
    confidence: float = 0.95,
    timestamp: int = 100,
) -> Observation:
    return Observation(
        source=source,
        timestamp=timestamp,
        confidence=confidence,
        elements=elements,
        semantic_labels=tuple(sorted({str(element["role"]) for element in elements})),
    )


class SemanticUIGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = SemanticUIGraphBuilder()

    def test_ax_graph_has_exact_aggregate_schema_and_no_element_identity(self) -> None:
        graph = self.builder.build(
            observation(
                (
                    {"role": "search_field", "interactive": True},
                    {"role": "button", "interactive": True},
                    {"role": "text", "interactive": False},
                )
            )
        )
        schema = graph.schema()
        self.assertEqual("AX", schema["source"])
        self.assertEqual("verified", schema["state"])
        self.assertEqual(
            {"graph_version", "source", "timestamp", "confidence", "state", "nodes", "edges"},
            set(schema),
        )
        self.assertEqual("page", schema["nodes"][0]["type"])
        self.assertEqual("search", schema["nodes"][0]["role"])
        self.assertEqual("screen_context", schema["nodes"][0]["capability"])
        self.assertEqual(
            {"type", "role", "capability", "state", "confidence", "source", "timestamp", "count"},
            set(schema["nodes"][0]),
        )
        self.assertEqual(4, len(schema["nodes"]))
        self.assertEqual(3, len(schema["edges"]))
        graph.validate_public_schema()

    def test_supported_sources_remain_provenance_only_and_non_ax_is_ambiguous(self) -> None:
        for source in ("AX", "Vision", "OCR", "VLM"):
            graph = self.builder.build(
                observation(({"role": "button", "interactive": True},), source=source)
            )
            self.assertEqual(source, graph.source)
            self.assertEqual("verified" if source == "AX" else "ambiguous", graph.state)
            self.assertTrue(all(node["source"] == source for node in graph.nodes))

    def test_low_confidence_ax_never_claims_verified_grounding(self) -> None:
        graph = self.builder.build(
            observation(({"role": "button", "interactive": True},), confidence=0.30)
        )
        self.assertEqual("ambiguous", graph.state)
        self.assertTrue(all(node["state"] == "ambiguous" for node in graph.nodes))

    def test_empty_safe_observation_is_insufficient_not_a_fake_action_target(self) -> None:
        graph = self.builder.build(observation(tuple(), confidence=0.70))
        self.assertEqual("insufficient", graph.state)
        self.assertEqual(1, len(graph.nodes))
        self.assertEqual([], graph.schema()["edges"])

    def test_schema_rejects_private_or_replay_capable_node_fields(self) -> None:
        graph = self.builder.build(observation(({"role": "button", "interactive": True},)))
        unsafe_node = dict(graph.nodes[0])
        unsafe_node["rect"] = {"x": 1, "y": 2}
        unsafe_graph = SemanticUIGraph(
            graph_version=graph.graph_version,
            source=graph.source,
            timestamp=graph.timestamp,
            confidence=graph.confidence,
            state=graph.state,
            nodes=(unsafe_node,) + graph.nodes[1:],
            edges=graph.edges,
        )
        with self.assertRaisesRegex(SemanticUIGraphError, "unsupported fields"):
            unsafe_graph.validate_public_schema()

    def test_serialized_graph_excludes_private_data_and_action_bindings(self) -> None:
        graph = self.builder.build(
            observation(({"role": "text_field", "interactive": True}, {"role": "button", "interactive": False}))
        )
        serialized = json.dumps(graph.schema(), ensure_ascii=False).casefold()
        for forbidden in FORBIDDEN_SERIALIZED_FIELDS:
            self.assertNotIn(forbidden, serialized)

    def test_state_tracker_emits_only_safe_aggregate_delta_and_expires_history(self) -> None:
        tracker = GUIStateTracker(max_history=2, ttl_seconds=10)
        first = self.builder.build(
            observation(({"role": "search_field", "interactive": True},), timestamp=100)
        )
        first_delta = tracker.record(first)
        self.assertEqual(1, first_delta.history_size)
        self.assertEqual(["search"], list(first_delta.added_roles))
        self.assertEqual([], list(first_delta.removed_roles))

        second = self.builder.build(
            observation(({"role": "switch", "interactive": True},), timestamp=105)
        )
        second_delta = tracker.record(second)
        self.assertTrue(second_delta.state_changed is False)
        self.assertEqual(["toggle"], list(second_delta.added_roles))
        self.assertEqual(["search"], list(second_delta.removed_roles))
        self.assertEqual(2, second_delta.history_size)

        third = self.builder.build(
            observation(({"role": "text", "interactive": False},), timestamp=116)
        )
        third_delta = tracker.record(third)
        self.assertEqual(1, third_delta.history_size)
        self.assertEqual(["inspect"], list(third_delta.added_roles))
        self.assertEqual([], list(third_delta.removed_roles))
        third_delta.validate_public_schema(maximum_history=2)

    def test_tracker_capacity_is_bounded_and_out_of_range_configuration_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            GUIStateTracker(max_history=0)
        with self.assertRaises(ValueError):
            GUIStateTracker(ttl_seconds=0)
        tracker = GUIStateTracker(max_history=2, ttl_seconds=30)
        for timestamp in (100, 101, 102):
            delta = tracker.record(
                self.builder.build(observation(({"role": "button", "interactive": True},), timestamp=timestamp))
            )
        self.assertEqual(2, delta.history_size)
        older_graph = self.builder.build(
            observation(({"role": "button", "interactive": True},), timestamp=101)
        )
        with self.assertRaisesRegex(SemanticUIGraphError, "non-decreasing"):
            tracker.record(older_graph)

    def test_graph_layer_has_no_device_or_runtime_action_interface(self) -> None:
        for instance in (self.builder, GUIStateTracker()):
            for forbidden_name in (
                "client",
                "observe",
                "call_tool",
                "execute",
                "plan",
                "select",
                "assess",
                "verify",
                "persist",
                "save",
            ):
                self.assertFalse(hasattr(instance, forbidden_name), forbidden_name)
        source = inspect.getsource(SemanticUIGraphBuilder) + inspect.getsource(GUIStateTracker)
        for forbidden_symbol in ("MCPClient", "DynamicPlanner", "RiskController", "PlanExecutor", "SkillRegistry"):
            self.assertNotIn(forbidden_symbol, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
