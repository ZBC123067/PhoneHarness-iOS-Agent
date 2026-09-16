#!/usr/bin/env python3
"""Static boundary tests for TEST-16 Risk Controller.

These tests do not contact the device. They prove that the Mac-side executor
does not call an MCP tool before the Risk Controller permits the plan.
"""

from __future__ import annotations

import unittest

from phoneharness_agent import DynamicPlanner, PlanExecutor, RiskController, Snapshot


TOOLS = {"describe_screen", "tap_element", "input_text", "type_text", "press_key"}


def snapshot_with(*elements: dict[str, object]) -> Snapshot:
    return Snapshot(
        frontmost_name="Test App",
        frontmost_bundle_id="example.test",
        element_count=len(elements),
        source="accessibility",
        elements=tuple(elements),
    )


def high_risk_plan(action: str = "send_message", tool: str = "tap_element") -> dict[str, object]:
    return {
        "status": "ready",
        "selected_tools": [tool],
        "skill_selection": {
            "status": "ready",
            "selected_tools": [tool],
            "skill": {
                "name": "synthetic_high_risk_skill",
                "risk_level": "high_risk",
                "allowed_tools": [tool],
            },
        },
        "risk_actions": [action],
        "steps": [{"id": "synthetic-action", "tool": tool, "arguments": {}}],
        "verification": {"kind": "observation_nonempty"},
    }


class NeverCallClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        self.calls.append((name, arguments))
        raise AssertionError("Risk Controller should have blocked before a tool call")

    def describe(self, include_ocr: bool = False) -> Snapshot:
        raise AssertionError("Risk Controller should have blocked before verification")


class RiskControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.controller = RiskController()

    def test_read_only_skill_is_allowed_without_authorization(self) -> None:
        plan = DynamicPlanner().plan("描述当前屏幕", TOOLS, snapshot_with({"text": "Home", "clickable": True}))
        assessment = self.controller.assess(plan, now=100)
        self.assertEqual("allowed", assessment["status"])
        self.assertEqual("not_required", assessment["authorization"]["status"])
        self.assertEqual(["describe_screen"], assessment["step_tools"])

    def test_high_risk_action_requires_matching_explicit_authorization(self) -> None:
        assessment = self.controller.assess(high_risk_plan(), now=100)
        self.assertEqual("authorization_required", assessment["status"])
        self.assertTrue(assessment["authorization_required"])
        self.assertEqual("missing", assessment["authorization"]["status"])

    def test_explicit_authorization_is_bound_and_single_use(self) -> None:
        plan = high_risk_plan()
        authorization = self.controller.authorize(plan, "confirmed-by-test", now=100, ttl_seconds=30)
        allowed = self.controller.assess(plan, authorization, consume_authorization=True, now=101)
        reused = self.controller.assess(plan, authorization, now=102)
        self.assertEqual("allowed", allowed["status"])
        self.assertTrue(allowed["authorization"]["consumed"])
        self.assertEqual("authorization_required", reused["status"])
        self.assertEqual("already_consumed", reused["authorization"]["status"])

    def test_authorization_cannot_be_reused_for_another_action(self) -> None:
        authorization = self.controller.authorize(high_risk_plan("send_message"), "confirmed-by-test", now=100)
        assessment = self.controller.assess(high_risk_plan("transfer"), authorization, now=101)
        self.assertEqual("authorization_required", assessment["status"])
        self.assertEqual("action_mismatch", assessment["authorization"]["status"])

    def test_expired_authorization_is_rejected(self) -> None:
        plan = high_risk_plan()
        authorization = self.controller.authorize(plan, "confirmed-by-test", now=100, ttl_seconds=1)
        assessment = self.controller.assess(plan, authorization, now=101)
        self.assertEqual("authorization_required", assessment["status"])
        self.assertEqual("expired", assessment["authorization"]["status"])

    def test_forbidden_low_level_tool_is_never_authorizable(self) -> None:
        plan = high_risk_plan(tool="run_command")
        assessment = self.controller.assess(plan, now=100)
        self.assertEqual("blocked", assessment["status"])
        self.assertEqual("forbidden_low_level_tool", assessment["reason"])
        self.assertEqual(["run_command"], assessment["forbidden_tools"])
        with self.assertRaises(ValueError):
            self.controller.authorize(plan, "confirmed-by-test", now=100)

    def test_plan_cannot_forge_a_tool_outside_skill_selection(self) -> None:
        plan = high_risk_plan()
        plan["selected_tools"] = ["input_text"]
        assessment = self.controller.assess(plan, now=100)
        self.assertEqual("blocked", assessment["status"])
        self.assertEqual("plan_tool_selection_mismatch", assessment["reason"])

    def test_high_risk_skill_must_declare_an_action_type(self) -> None:
        plan = high_risk_plan()
        del plan["risk_actions"]
        assessment = self.controller.assess(plan, now=100)
        self.assertEqual("blocked", assessment["status"])
        self.assertEqual("high_risk_skill_missing_declared_action", assessment["reason"])

    def test_executor_blocks_before_any_device_tool_call(self) -> None:
        client = NeverCallClient()
        execution = PlanExecutor(client, self.controller).execute(high_risk_plan())
        self.assertEqual("blocked", execution["status"])
        self.assertEqual([], execution["executed_steps"])
        self.assertEqual("authorization_required", execution["risk_assessment"]["status"])
        self.assertEqual([], client.calls)


if __name__ == "__main__":
    unittest.main(verbosity=2)
