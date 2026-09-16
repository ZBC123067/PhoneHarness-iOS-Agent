#!/usr/bin/env python3
"""Static contract tests for TEST-15 Skill Registry.

These tests do not contact the iPhone. The separate TEST-15 runner validates
the registry against the live PhoneHarness tool contract and a fresh snapshot.
"""

from __future__ import annotations

import unittest

from phoneharness_agent import DynamicPlanner, Intent, SkillDefinition, SkillRegistry, Snapshot


TOOLS = {"describe_screen", "tap_element", "input_text", "type_text", "press_key"}


def snapshot_with(*elements: dict[str, object]) -> Snapshot:
    return Snapshot(
        frontmost_name="Test App",
        frontmost_bundle_id="example.test",
        element_count=len(elements),
        source="accessibility",
        elements=tuple(elements),
    )


class SkillRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = SkillRegistry()

    def test_contracts_declare_all_audit_fields(self) -> None:
        required = {
            "name",
            "intent_kinds",
            "required_capabilities",
            "allowed_tools",
            "risk_level",
            "preconditions",
            "executor",
            "verifier",
            "stop_conditions",
            "rollback",
        }
        contracts = self.registry.contracts()
        self.assertEqual(
            {
                "screen.observe.v1",
                "screen.verify_visible_text.v1",
                "browser.search_current_page.v1",
                "maps.open_native_link.v1",
                "apps.launch_installed.v1",
            },
            {contract["skill_id"] for contract in contracts},
        )
        self.assertTrue(all(required.issubset(contract) for contract in contracts))
        self.assertTrue(all("bundle" not in str(contract).lower() for contract in contracts))
        self.assertTrue(all("coordinate" not in str(contract).lower() for contract in contracts))

    def test_observe_skill_allows_only_read_only_observation(self) -> None:
        selection = self.registry.select(Intent("observe"), TOOLS, snapshot_with({"text": "Home", "clickable": True}))
        self.assertEqual("ready", selection["status"])
        self.assertEqual("observe_current_screen", selection["skill"]["name"])
        self.assertEqual(["describe_screen"], selection["selected_tools"])
        self.assertEqual("read_only", selection["skill"]["risk_level"])

    def test_search_requires_one_observed_semantic_search_control(self) -> None:
        selection = self.registry.select(
            Intent("search_current", "PhoneHarness"),
            TOOLS,
            snapshot_with({"text": "地址和搜索栏", "clickable": True}),
        )
        self.assertEqual("ready", selection["status"])
        self.assertEqual("search_current_screen", selection["skill"]["name"])
        self.assertEqual(["describe_screen", "tap_element", "input_text", "press_key"], selection["selected_tools"])
        self.assertEqual("地址和搜索栏", selection["context"]["search_control_text"])

    def test_search_stops_before_tool_selection_when_control_is_ambiguous(self) -> None:
        selection = self.registry.select(
            Intent("search_current", "PhoneHarness"),
            TOOLS,
            snapshot_with({"text": "Search", "clickable": True}, {"text": "Address", "clickable": True}),
        )
        self.assertEqual("blocked", selection["status"])
        self.assertEqual([], selection["selected_tools"])
        self.assertEqual({}, selection["tool_selection"])
        self.assertIn("single_search_control", selection["reason"])

    def test_registry_rejects_selector_output_outside_skill_allow_list(self) -> None:
        unsafe_contract = SkillDefinition(
            skill_id="test.mismatched_contract.v1",
            name="mismatched_contract",
            description="Static fixture that intentionally rejects the selector result.",
            version="1.0.0",
            status="active",
            intent_kinds=("observe",),
            required_capabilities=("text_entry",),
            required_tools=frozenset(),
            allowed_tools=frozenset({"describe_screen"}),
            required_permissions=("mcp.read_screen",),
            risk_level="read_only",
            preconditions=("fresh_screen_observation",),
            executor="planner_steps_v1",
            verifier="observation_nonempty",
            dependencies=(),
            platform_support=("macos_host", "ios_mcp"),
            stop_conditions=("required_tool_unavailable",),
            rollback="none_read_only",
        )
        selection = SkillRegistry((unsafe_contract,)).select(
            Intent("observe"), {"input_text"}, snapshot_with({"text": "Home", "clickable": True})
        )
        self.assertEqual("blocked", selection["status"])
        self.assertIn("forbids selector result: input_text", selection["reason"])

    def test_planner_records_skill_before_steps(self) -> None:
        plan = DynamicPlanner().plan(
            "在当前页面搜索 PhoneHarness",
            TOOLS,
            snapshot_with({"text": "Search or enter website name", "clickable": True}),
        )
        self.assertEqual("ready", plan["status"])
        self.assertEqual("search_current_screen", plan["skill_selection"]["skill"]["name"])
        self.assertEqual(plan["selected_tools"], plan["skill_selection"]["selected_tools"])
        self.assertEqual("tap_element", plan["steps"][0]["tool"])
        self.assertNotIn("tap_screen", plan["selected_tools"])

    def test_unknown_intent_has_no_skill_and_no_tool(self) -> None:
        selection = self.registry.select(Intent("unsupported"), TOOLS, snapshot_with())
        self.assertEqual("blocked", selection["status"])
        self.assertIsNone(selection["skill"])
        self.assertEqual([], selection["selected_tools"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
