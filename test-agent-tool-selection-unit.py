#!/usr/bin/env python3
"""Static policy tests for TEST-12 Dynamic Tool Selection."""

from __future__ import annotations

import unittest

from phoneharness_agent import DynamicToolSelector
from phoneharness_agent import MCPClient


class DynamicToolSelectorTests(unittest.TestCase):
    def test_prefers_describe_screen_for_observation(self) -> None:
        selection = DynamicToolSelector({"describe_screen", "get_ui_elements"}).select("screen_observation")
        self.assertEqual("ready", selection["status"])
        self.assertEqual(["describe_screen"], selection["selected_tools"])

    def test_frontmost_context_falls_back_to_describe_screen(self) -> None:
        selection = DynamicToolSelector({"describe_screen"}).select("frontmost_context")
        self.assertEqual("ready", selection["status"])
        self.assertEqual(["describe_screen"], selection["selected_tools"])

    def test_text_entry_uses_input_then_type_fallback(self) -> None:
        preferred = DynamicToolSelector({"input_text", "type_text"}).select("text_entry")
        fallback = DynamicToolSelector({"type_text"}).select("text_entry")
        self.assertEqual(["input_text"], preferred["selected_tools"])
        self.assertEqual(["type_text"], fallback["selected_tools"])

    def test_semantic_activation_never_downgrades_to_coordinates(self) -> None:
        selection = DynamicToolSelector({"tap_screen"}).select("semantic_activate")
        self.assertEqual("blocked", selection["status"])
        self.assertEqual([], selection["selected_tools"])

    def test_high_risk_tool_is_not_automatically_selectable(self) -> None:
        assessment = DynamicToolSelector({"run_command"}).assess_tool("run_command")
        self.assertEqual("denied", assessment["automatic_selection"])

    def test_null_required_schema_is_treated_as_empty(self) -> None:
        client = MCPClient()
        original_rpc = client._rpc
        try:
            client._rpc = lambda method, params: {
                "tools": [{"name": "describe_screen", "description": "observe", "inputSchema": {"required": None}}]
            }
            descriptors = client.list_tool_descriptors()
        finally:
            client._rpc = original_rpc
        self.assertEqual((), descriptors["describe_screen"].required_arguments)


if __name__ == "__main__":
    unittest.main(verbosity=2)
