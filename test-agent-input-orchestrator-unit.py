#!/usr/bin/env python3
"""Batch 1E P5 strategy-only tests.

The orchestrator chooses a bounded strategy from already-observed keyboard
metadata. It has no client, transport, binding, Risk, Ledger, or verifier.
"""

from __future__ import annotations

import inspect
import json
import unittest

from phoneharness_agent import InputTextActionBindingError, InputTextOrchestrator


class StrategySelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.orchestrator = InputTextOrchestrator()

    def test_ascii_apple_keyboard_prefers_s1_then_s4(self) -> None:
        plan = self.orchestrator.prepare("abc", keyboard="apple_qwerty")
        self.assertEqual(("s1_keycode", "s4_clipboard"), plan.strategies)

    def test_cjk_uses_s4_candidate(self) -> None:
        plan = self.orchestrator.prepare("你好", keyboard="apple_qwerty")
        self.assertEqual(("s4_clipboard",), plan.strategies)

    def test_unknown_keyboard_uses_s4_candidate(self) -> None:
        plan = self.orchestrator.prepare("abc", keyboard="unknown")
        self.assertEqual(("s4_clipboard",), plan.strategies)

    def test_sensitive_ascii_permits_s1_only(self) -> None:
        plan = self.orchestrator.prepare("abc", keyboard="apple_qwerty", sensitive=True)
        self.assertEqual(("s1_keycode",), plan.strategies)

    def test_sensitive_cjk_has_no_safe_candidate(self) -> None:
        plan = self.orchestrator.prepare("你好", keyboard="apple_qwerty", sensitive=True)
        self.assertEqual((), plan.strategies)

    def test_overlong_ascii_skips_s1(self) -> None:
        plan = self.orchestrator.prepare("a" * 33, keyboard="apple_qwerty")
        self.assertEqual(("s4_clipboard",), plan.strategies)

    def test_pinyin_keyboard_permits_s1_for_short_ascii(self) -> None:
        plan = self.orchestrator.prepare("abc", keyboard="apple_pinyin_9key")
        self.assertEqual(("s1_keycode", "s4_clipboard"), plan.strategies)

    def test_summary_contains_no_raw_text(self) -> None:
        plan = self.orchestrator.prepare("secret-text", keyboard="apple_qwerty")
        summary = json.dumps(plan.summary(), sort_keys=True)
        self.assertNotIn("secret-text", summary)
        self.assertIn("text_sha16", summary)

    def test_summary_has_no_execution_authority(self) -> None:
        plan = self.orchestrator.prepare("abc", keyboard="apple_qwerty")
        self.assertEqual("none", plan.summary()["execution_authority"])

    def test_orchestrator_has_no_client_constructor_argument(self) -> None:
        self.assertEqual([], list(inspect.signature(InputTextOrchestrator).parameters))

    def test_orchestrator_source_has_no_tool_call(self) -> None:
        self.assertNotIn("call_tool", inspect.getsource(InputTextOrchestrator))

    def test_empty_text_is_rejected(self) -> None:
        with self.assertRaises(InputTextActionBindingError):
            self.orchestrator.prepare("", keyboard="apple_qwerty")

    def test_missing_keyboard_is_rejected(self) -> None:
        with self.assertRaises(InputTextActionBindingError):
            self.orchestrator.prepare("abc", keyboard="")


if __name__ == "__main__":
    unittest.main()
