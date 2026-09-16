#!/usr/bin/env python3
"""Static boundary tests for TEST-13 goal decomposition."""

from __future__ import annotations

import unittest

from phoneharness_agent import GoalDecomposer, GoalSequenceExecutor, Snapshot


class FakeClient:
    def __init__(self, visible_text: str = "微信", frontmost_name: str = "Test App") -> None:
        self.visible_text = visible_text
        self.frontmost_name = frontmost_name
        self.calls: list[tuple[str, dict[str, object]]] = []

    def list_tools(self) -> set[str]:
        return {"describe_screen"}

    def describe(self, include_ocr: bool = False) -> Snapshot:
        return Snapshot(
            frontmost_name=self.frontmost_name,
            frontmost_bundle_id="example.test",
            element_count=1,
            source="accessibility",
            elements=({"text": self.visible_text, "clickable": True},),
        )

    def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        self.calls.append((name, arguments))
        return {}


class GoalDecomposerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.decomposer = GoalDecomposer()

    def test_creates_ordered_dependency_chain(self) -> None:
        result = self.decomposer.decompose("依次执行：描述当前屏幕；验证当前屏幕包含 微信")
        self.assertEqual("ready", result["status"])
        self.assertEqual(["subgoal-1", "subgoal-2"], [item["id"] for item in result["subgoals"]])
        self.assertEqual([], result["subgoals"][0]["depends_on"])
        self.assertEqual(["subgoal-1"], result["subgoals"][1]["depends_on"])

    def test_rejects_implicit_sequence(self) -> None:
        result = self.decomposer.decompose("描述当前屏幕，然后验证当前屏幕包含 微信")
        self.assertEqual("blocked", result["status"])
        self.assertEqual([], result["subgoals"])

    def test_rejects_unsupported_subgoal_before_execution(self) -> None:
        result = self.decomposer.decompose("依次执行：描述当前屏幕；打开设置")
        self.assertEqual("blocked", result["status"])
        self.assertEqual([], result["subgoals"])

    def test_rejects_empty_or_excessive_sequences(self) -> None:
        empty = self.decomposer.decompose("依次执行：描述当前屏幕；；验证当前屏幕包含 微信")
        excessive = self.decomposer.decompose(
            "依次执行：描述当前屏幕；描述当前屏幕；描述当前屏幕；描述当前屏幕；描述当前屏幕"
        )
        self.assertEqual("blocked", empty["status"])
        self.assertEqual("blocked", excessive["status"])

    def test_execution_replans_each_subgoal_and_preserves_order(self) -> None:
        decomposition = self.decomposer.decompose("依次执行：描述当前屏幕；验证当前屏幕包含 微信")
        client = FakeClient()
        execution = GoalSequenceExecutor(client).execute(decomposition)
        self.assertEqual("passed", execution["status"])
        self.assertEqual(["subgoal-1", "subgoal-2"], execution["completed_subgoals"])
        self.assertEqual(2, len(execution["subgoals"]))
        self.assertGreaterEqual(len(client.calls), 2)

    def test_execution_stops_after_failed_subgoal(self) -> None:
        decomposition = self.decomposer.decompose("依次执行：验证当前屏幕包含 不存在；描述当前屏幕")
        execution = GoalSequenceExecutor(FakeClient()).execute(decomposition)
        self.assertEqual("failed", execution["status"])
        self.assertEqual("subgoal-1", execution["failed_subgoal"])
        self.assertEqual([], execution["completed_subgoals"])
        self.assertEqual(1, len(execution["subgoals"]))

    def test_verification_accepts_structured_frontmost_name(self) -> None:
        decomposition = self.decomposer.decompose("依次执行：验证当前屏幕包含 Example App；描述当前屏幕")
        client = FakeClient(visible_text="unrelated", frontmost_name="Example App")
        execution = GoalSequenceExecutor(client).execute(decomposition)
        self.assertEqual("passed", execution["status"])
        self.assertEqual(["subgoal-1", "subgoal-2"], execution["completed_subgoals"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
