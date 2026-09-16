#!/usr/bin/env python3
"""Static boundary tests for TEST-11 planner decisions.

These tests do not contact the device. The separate TEST-11 entry point is the
real-device gate.
"""

from __future__ import annotations

import unittest

from phoneharness_agent import DynamicPlanner, Snapshot


TOOLS = {"describe_screen", "tap_element", "input_text", "type_text", "press_key"}


def snapshot_with(*elements: dict[str, object]) -> Snapshot:
    return Snapshot(
        frontmost_name="Test App",
        frontmost_bundle_id="example.test",
        element_count=len(elements),
        source="accessibility",
        elements=tuple(elements),
    )


class DynamicPlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.planner = DynamicPlanner()

    def test_observation_goal_is_read_only(self) -> None:
        plan = self.planner.plan("描述当前屏幕", TOOLS, snapshot_with({"text": "Settings", "clickable": True}))
        self.assertEqual("ready", plan["status"])
        self.assertEqual(["describe_screen"], plan["selected_tools"])
        self.assertEqual("describe_screen", plan["steps"][0]["tool"])

    def test_search_selects_only_live_semantic_control(self) -> None:
        plan = self.planner.plan(
            "在当前页面搜索 PhoneHarness",
            TOOLS,
            snapshot_with({"text": "Search or enter website name", "clickable": True}),
        )
        self.assertEqual("ready", plan["status"])
        self.assertEqual("tap_element", plan["steps"][0]["tool"])
        self.assertEqual("Search or enter website name", plan["steps"][0]["arguments"]["text"])
        self.assertNotIn("launch_app", plan["selected_tools"])
        action_steps = str(plan["steps"])
        self.assertNotIn("bundle_id", action_steps)
        self.assertNotIn("coordinate", action_steps.lower())
        self.assertGreater(plan["verification"]["timeout_seconds"], 0)

    def test_search_accepts_generic_address_and_search_bar_label(self) -> None:
        plan = self.planner.plan(
            "在当前页面搜索 PhoneHarness",
            TOOLS,
            snapshot_with({"text": "地址和搜索栏", "clickable": True}),
        )
        self.assertEqual("ready", plan["status"])
        self.assertEqual("地址和搜索栏", plan["steps"][0]["arguments"]["text"])

    def test_search_refuses_ambiguous_controls(self) -> None:
        plan = self.planner.plan(
            "在当前页面搜索 PhoneHarness",
            TOOLS,
            snapshot_with(
                {"text": "Search", "clickable": True},
                {"text": "Address", "clickable": True},
            ),
        )
        self.assertEqual("blocked", plan["status"])
        self.assertEqual([], plan["steps"])

    def test_search_refuses_non_search_text_field(self) -> None:
        plan = self.planner.plan(
            "在当前页面搜索 PhoneHarness",
            TOOLS,
            snapshot_with({"text": "文本", "clickable": True}),
        )
        self.assertEqual("blocked", plan["status"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
