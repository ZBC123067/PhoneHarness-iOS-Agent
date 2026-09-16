#!/usr/bin/env python3
"""Static boundary tests for TEST-24 Semantic Observation Planner integration."""

from __future__ import annotations

import json
import unittest

from phoneharness_agent import (
    DynamicPlanner,
    Observation,
    PlannerSemanticContext,
    SemanticObservation,
    Snapshot,
    build_semantic_plan,
)


TOOLS = {"describe_screen", "tap_element", "input_text", "type_text", "press_key"}
FORBIDDEN_FIELDS = frozenset(
    {
        "elements",
        "text",
        "label",
        "value",
        "password",
        "input",
        "rect",
        "frame",
        "tap",
        "screenshot",
        "ocr",
        "raw_response",
        "frontmost",
        "bundle_id",
        "coordinate",
    }
)


def context(*, confidence: float = 0.9) -> PlannerSemanticContext:
    return PlannerSemanticContext.from_semantic_observation(
        SemanticObservation(
            source="AX",
            timestamp=123,
            confidence=confidence,
            page_type="content",
            intents=(
                {"intent": "activate", "count": 2, "actionable": True},
                {"intent": "inspect", "count": 3, "actionable": False},
            ),
            actionable=True,
        )
    )


class SemanticPlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.planner = DynamicPlanner()

    def test_context_schema_is_exactly_aggregate_only(self) -> None:
        schema = context().schema()
        self.assertEqual(
            {"context_version", "source", "timestamp", "confidence", "page_type", "intents", "actionable"},
            set(schema),
        )
        serialized = json.dumps(schema, ensure_ascii=False).casefold()
        for forbidden in FORBIDDEN_FIELDS:
            self.assertNotIn('"%s"' % forbidden, serialized)

    def test_semantic_entry_point_rejects_snapshot_and_raw_observation_inputs(self) -> None:
        raw_snapshot = Snapshot(
            frontmost_name="Private App",
            frontmost_bundle_id="private.example",
            element_count=1,
            source="accessibility",
            elements=({"text": "private", "rect": {"x": 1}},),
        )
        with self.assertRaisesRegex(ValueError, "only PlannerSemanticContext"):
            self.planner.plan_from_semantic_context("描述当前屏幕", TOOLS, raw_snapshot)  # type: ignore[arg-type]
        raw_observation = Observation(
            source="AX",
            timestamp=123,
            confidence=0.9,
            elements=({"role": "button", "interactive": True},),
            semantic_labels=("button",),
        )
        with self.assertRaisesRegex(ValueError, "only PlannerSemanticContext"):
            self.planner.plan_from_semantic_context("描述当前屏幕", TOOLS, raw_observation)  # type: ignore[arg-type]

    def test_read_only_planner_path_uses_only_safe_context(self) -> None:
        semantic_context = context()
        plan = self.planner.plan_from_semantic_context("描述当前屏幕", TOOLS, semantic_context)
        self.assertEqual("ready", plan["status"])
        self.assertEqual(["describe_screen"], plan["selected_tools"])
        self.assertEqual(["describe_screen"], [step["tool"] for step in plan["steps"]])
        self.assertEqual(semantic_context.schema(), plan["semantic_context"])
        self.assertNotIn("observation", plan)

    def test_semantic_adapter_exposes_no_ui_elements_to_skill_registry(self) -> None:
        adapter = context().registry_snapshot()
        self.assertEqual(tuple(), adapter.elements)
        self.assertEqual("", adapter.frontmost_name)
        self.assertEqual("", adapter.frontmost_bundle_id)
        self.assertEqual(5, adapter.element_count)
        self.assertEqual("AX", adapter.source)

    def test_private_semantic_context_is_rejected_before_planning(self) -> None:
        private_context = PlannerSemanticContext(
            context_version="test-24.0",
            source="AX",
            timestamp=123,
            confidence=0.9,
            page_type="content",
            intents=({"intent": "activate", "count": 1, "actionable": True, "rect": {"x": 1}},),
            actionable=True,
        )
        with self.assertRaisesRegex(Exception, "unsupported fields"):
            self.planner.plan_from_semantic_context("描述当前屏幕", TOOLS, private_context)

    def test_non_read_only_goal_is_blocked_without_interaction_tool_selection(self) -> None:
        plan = self.planner.plan_from_semantic_context("在当前页面搜索 PhoneHarness", TOOLS, context())
        self.assertEqual("blocked", plan["status"])
        self.assertEqual([], plan["selected_tools"])
        self.assertEqual([], plan["steps"])

    def test_low_confidence_context_is_blocked_before_skill_selection(self) -> None:
        plan = self.planner.plan_from_semantic_context("描述当前屏幕", TOOLS, context(confidence=0.24))
        self.assertEqual("blocked", plan["status"])
        self.assertEqual({}, plan["skill_selection"])
        self.assertEqual([], plan["steps"])

    def test_live_integration_uses_only_the_semantic_context_api(self) -> None:
        class SemanticOnlyClient:
            def list_tools(self) -> set[str]:
                return set(TOOLS)

            def observe_planner_context(self) -> PlannerSemanticContext:
                return context()

            def describe(self, include_ocr: bool = False) -> Snapshot:
                del include_ocr
                raise AssertionError("TEST-24 must not call the legacy raw describe API")

        plan = build_semantic_plan(SemanticOnlyClient(), "描述当前屏幕")  # type: ignore[arg-type]
        self.assertEqual("ready", plan["status"])
        self.assertEqual(context().schema(), plan["semantic_context"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
