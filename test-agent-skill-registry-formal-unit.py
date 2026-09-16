#!/usr/bin/env python3
"""Static contract tests for TEST-19 Skill Registry formalization.

These tests never contact the iPhone.  The separate TEST-19 runner is the
focused real-device gate for the generic foreground-browser search Skill.
"""

from __future__ import annotations

import unittest

from phoneharness_agent import (
    DynamicPlanner,
    Intent,
    PlanExecutor,
    SkillDefinition,
    SkillRegistry,
    Snapshot,
)


TOOLS = {"describe_screen", "tap_element", "input_text", "type_text", "press_key", "launch_app"}
PLATFORMS = {"macos_host", "ios_mcp"}
PERMISSIONS = {"mcp.read_screen", "mcp.foreground_interaction"}


def snapshot_with(*elements: dict[str, object]) -> Snapshot:
    return Snapshot(
        frontmost_name="Test Browser",
        frontmost_bundle_id="example.browser",
        element_count=len(elements),
        source="accessibility",
        elements=tuple(elements),
    )


def skill(
    skill_id: str,
    *,
    name: str = "test_skill",
    intent: str = "observe",
    dependencies: tuple[str, ...] = (),
    status: str = "active",
    risk_level: str = "read_only",
    allowed_tools: frozenset[str] = frozenset({"describe_screen"}),
    required_tools: frozenset[str] = frozenset({"describe_screen"}),
    required_capabilities: tuple[str, ...] = ("screen_observation",),
    required_permissions: tuple[str, ...] = ("mcp.read_screen",),
) -> SkillDefinition:
    return SkillDefinition(
        skill_id=skill_id,
        name=name,
        description="Static declarative test fixture.",
        version="1.2.3",
        status=status,
        intent_kinds=(intent,),
        required_capabilities=required_capabilities,
        required_tools=required_tools,
        allowed_tools=allowed_tools,
        required_permissions=required_permissions,
        risk_level=risk_level,
        preconditions=("fresh_screen_observation",),
        executor="planner_steps_v1",
        verifier="observation_nonempty",
        dependencies=dependencies,
        platform_support=("macos_host", "ios_mcp"),
        stop_conditions=("screen_observation_unavailable",),
        rollback="none_read_only",
    )


class RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        self.calls.append((name, arguments))
        return {}

    def describe(self, include_ocr: bool = False) -> Snapshot:
        self.calls.append(("describe_screen", {"include_ocr": include_ocr}))
        return snapshot_with({"text": "safe", "clickable": True})


class FormalSkillRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = SkillRegistry()

    def test_contract_has_formal_metadata_and_no_replay_data(self) -> None:
        contract = self.registry.get("browser.search_current_page.v1")
        self.assertIsNotNone(contract)
        required = {
            "skill_id",
            "name",
            "description",
            "version",
            "status",
            "required_tools",
            "required_permissions",
            "risk_level",
            "preconditions",
            "verifier",
            "dependencies",
            "platform_support",
            "last_verified",
        }
        self.assertTrue(required.issubset(contract or {}))
        self.assertEqual("1.0.0", contract["version"])
        self.assertEqual("active", contract["status"])
        self.assertIn("launch_app", contract["allowed_tools"])
        serialized = str(contract).lower()
        for prohibited in ("bundle_id", "coordinate", "rect", "screenshot", "raw_response"):
            self.assertNotIn(prohibited, serialized)

    def test_query_and_verification_audit_are_bounded(self) -> None:
        matches = self.registry.query(intent_kind="search_current", status="active")
        self.assertEqual(["browser.search_current_page.v1"], [entry["skill_id"] for entry in matches])
        record = self.registry.record_verification(
            "browser.search_current_page.v1",
            status="device_pass",
            verifier="visible_text_contains",
            evidence_scope="browser_search_low_risk",
            verified_at=123,
        )
        self.assertEqual(123, record["verified_at"])
        contract = self.registry.get("browser.search_current_page.v1")
        self.assertEqual(record, contract["last_verified"])
        self.assertNotIn("PhoneHarness", str(contract))

    def test_missing_permission_blocks_before_tool_selection(self) -> None:
        selection = self.registry.select(
            Intent("search_current", "PhoneHarness"),
            TOOLS,
            snapshot_with({"text": "Search", "clickable": True}),
            available_permissions={"mcp.read_screen"},
            available_platforms=PLATFORMS,
        )
        self.assertEqual("blocked", selection["status"])
        self.assertEqual(["mcp.foreground_interaction"], selection["permission_check"]["missing"])
        self.assertEqual({}, selection["tool_selection"])

    def test_disabled_dependency_blocks_selection(self) -> None:
        parent = skill("test.parent.v1", name="parent", intent="verify_visible", status="disabled")
        child = skill("test.child.v1", name="child", dependencies=("test.parent.v1",))
        registry = SkillRegistry((parent, child))
        selection = registry.select(
            Intent("observe"),
            TOOLS,
            snapshot_with({"text": "Home", "clickable": True}),
            available_permissions=PERMISSIONS,
            available_platforms=PLATFORMS,
        )
        self.assertEqual("blocked", selection["status"])
        self.assertEqual("disabled", selection["dependency_check"][0]["status"])

    def test_missing_and_cyclic_dependencies_are_rejected_on_registration(self) -> None:
        with self.assertRaisesRegex(ValueError, "dependency is not registered"):
            SkillRegistry((skill("test.child.v1", dependencies=("test.missing.v1",)),))

        first = skill("test.first.v1", name="first", dependencies=("test.second.v1",))
        second = skill("test.second.v1", name="second", dependencies=("test.first.v1",))
        with self.assertRaisesRegex(ValueError, "acyclic"):
            SkillRegistry._validate_dependency_graph((first, second))

    def test_invalid_formal_skill_is_rejected(self) -> None:
        invalid = skill("INVALID", name="invalid")
        with self.assertRaisesRegex(ValueError, "stable lowercase"):
            SkillRegistry((invalid,))

    def test_risk_rejection_stops_before_any_mcp_call(self) -> None:
        client = RecordingClient()
        plan = {
            "status": "ready",
            "selected_tools": ["tap_element"],
            "skill_selection": {
                "status": "ready",
                "selected_tools": ["tap_element"],
                "skill": {
                    "skill_id": "test.risk.v1",
                    "name": "risk_fixture",
                    "risk_level": "high_risk",
                    "allowed_tools": ["tap_element"],
                },
            },
            "risk_actions": ["send_message"],
            "steps": [{"id": "send", "tool": "tap_element", "arguments": {}}],
            "verification": {"kind": "observation_nonempty"},
        }
        result = PlanExecutor(client).execute(plan)
        self.assertEqual("blocked", result["status"])
        self.assertEqual("authorization_required", result["risk_assessment"]["status"])
        self.assertEqual([], client.calls)

    def test_planner_keeps_browser_search_skill_before_tools(self) -> None:
        plan = DynamicPlanner().plan(
            "在当前页面搜索 PhoneHarness",
            TOOLS,
            snapshot_with({"text": "Search", "clickable": True}),
        )
        self.assertEqual("ready", plan["status"])
        contract = plan["skill_selection"]["skill"]
        self.assertEqual("browser.search_current_page.v1", contract["skill_id"])
        self.assertEqual("interaction", contract["risk_level"])
        self.assertEqual(["describe_screen", "tap_element", "input_text", "press_key"], plan["selected_tools"])
        self.assertTrue(plan["skill_selection"]["permission_check"]["passed"])
        self.assertTrue(plan["skill_selection"]["platform_check"]["passed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
