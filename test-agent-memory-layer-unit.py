#!/usr/bin/env python3
"""Static schema, privacy, and boundary tests for TEST-20 Memory Layer."""

from __future__ import annotations

import json
import stat
import tempfile
import unittest
from pathlib import Path

from phoneharness_agent import AgentMemoryLayer, AgentMemoryStore, MemoryPolicyError


class AgentMemoryLayerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "private" / "memory-v1.jsonl"
        self.store = AgentMemoryStore(self.path)
        self.memory = AgentMemoryLayer(self.store)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_task_memory_requires_verified_completed_task(self) -> None:
        with self.assertRaises(MemoryPolicyError):
            self.memory.record_task_completion(
                task_state="running",
                completion_result="passed",
                verifier_passed=True,
                recorded_at=100,
            )
        with self.assertRaises(MemoryPolicyError):
            self.memory.record_task_completion(
                task_state="completed",
                completion_result="passed",
                verifier_passed=False,
                recorded_at=100,
            )

        entry = self.memory.record_task_completion(
            task_state="completed",
            completion_result="passed",
            verifier_passed=True,
            recorded_at=101,
        )
        context = self.memory.planner_context()

        self.assertEqual("task_memory", entry["record_type"])
        self.assertEqual("task_completed", entry["write_boundary"])
        self.assertEqual(
            [{"task_state": "completed", "completion_result": "passed", "error_type": None, "recorded_at": 101}],
            context["task_memory"],
        )
        self.assertEqual(0o700, stat.S_IMODE(self.path.parent.stat().st_mode))
        self.assertEqual(0o600, stat.S_IMODE(self.path.stat().st_mode))

    def test_classified_error_is_the_only_non_pass_task_write(self) -> None:
        with self.assertRaises(MemoryPolicyError):
            self.memory.record_classified_task_error(
                task_state="failed",
                error_type="full raw error text must never persist",
                recorded_at=100,
            )
        error = self.memory.record_classified_task_error(
            task_state="blocked",
            error_type="risk_rejected",
            recorded_at=101,
        )
        self.assertEqual("classified_error", error["write_boundary"])
        self.assertEqual("risk_rejected", self.memory.planner_context()["task_memory"][0]["error_type"])

    def test_skill_memory_aggregates_verified_success_and_classified_failure(self) -> None:
        self.memory.record_skill_verification(
            skill_id="screen.observe.v1",
            version="1.0.0",
            verifier_passed=True,
            recorded_at=100,
        )
        self.memory.record_skill_verification(
            skill_id="screen.observe.v1",
            version="1.0.0",
            verifier_passed=False,
            error_type="verification_failed",
            recorded_at=101,
        )
        self.memory.record_skill_verification(
            skill_id="screen.observe.v1",
            version="1.0.0",
            verifier_passed=True,
            recorded_at=102,
        )

        summary = self.memory.planner_context()["skill_memory"]
        self.assertEqual(1, len(summary))
        self.assertEqual("screen.observe.v1", summary[0]["skill_id"])
        self.assertEqual(3, summary[0]["use_count"])
        self.assertEqual(2, summary[0]["success_count"])
        self.assertEqual(1, summary[0]["failure_count"])
        self.assertEqual({"status": "passed", "recorded_at": 102}, summary[0]["last_verified"])

    def test_environment_memory_requires_verifier_pass_and_keeps_only_safe_metadata(self) -> None:
        with self.assertRaises(MemoryPolicyError):
            self.memory.record_verified_environment(
                platform_support=("macos_host", "ios_mcp"),
                verified_capabilities=("screen_observation",),
                available_tools=("describe_screen",),
                verifier_passed=False,
                recorded_at=100,
            )

        self.memory.record_verified_environment(
            platform_support=("macos_host", "ios_mcp"),
            verified_capabilities=("screen_observation",),
            available_tools=("describe_screen", "get_frontmost_app"),
            verifier_passed=True,
            recorded_at=101,
        )
        environment = self.memory.planner_context()["environment_memory"]
        self.assertEqual(["macos_host", "ios_mcp"], environment["platform_support"])
        self.assertEqual(["screen_observation"], environment["verified_capabilities"])
        self.assertEqual(["describe_screen", "get_frontmost_app"], environment["available_tools"])

    def test_formal_schema_rejects_forbidden_or_extra_data_on_read(self) -> None:
        poisoned = {
            "schema_version": "2.0",
            "memory_version": "test-20.0",
            "record_id": "00000000-0000-0000-0000-000000000000",
            "recorded_at": 100,
            "record_type": "task_memory",
            "write_boundary": "task_completed",
            "task_state": "completed",
            "completion_result": "passed",
            "error_type": None,
            "goal": "private goal must not be accepted",
        }
        self.path.parent.mkdir(mode=0o700, parents=True)
        self.path.write_text(json.dumps(poisoned) + "\n", encoding="utf-8")
        self.path.chmod(0o600)

        context = self.memory.planner_context()
        self.assertEqual([], context["task_memory"])
        self.assertIsNone(context["environment_memory"])

    def test_planner_context_is_explicit_advisory_only_and_has_no_replay_data(self) -> None:
        self.memory.record_task_completion(
            task_state="completed",
            completion_result="passed",
            verifier_passed=True,
            recorded_at=100,
        )
        context = self.memory.planner_context()
        encoded = json.dumps(context, sort_keys=True)

        self.assertEqual("advisory_only", context["mode"])
        self.assertEqual("none", context["decision_effect"])
        self.assertTrue(context["requires_fresh_observation"])
        self.assertTrue(context["requires_skill_registry"])
        self.assertTrue(context["requires_risk_controller"])
        self.assertTrue(context["requires_verifier"])
        for forbidden in (
            "goal",
            "plan",
            "steps",
            "coordinates",
            "rect",
            "screenshot",
            "ocr",
            "input",
            "clipboard",
            "response",
            "selected_tools",
        ):
            self.assertNotIn(forbidden, encoded)

    def test_same_store_keeps_legacy_test14_records_out_of_test20_context(self) -> None:
        legacy = self.store.record_plan(
            {
                "status": "ready",
                "intent": "observe",
                "observation": {"frontmost": {"name": "Private App", "bundle_id": "com.example.private"}},
                "selected_tools": ["describe_screen"],
            }
        )
        self.memory.record_task_completion(
            task_state="completed",
            completion_result="passed",
            verifier_passed=True,
            recorded_at=101,
        )

        self.assertEqual(legacy["record_id"], self.store.recent(limit=1)[0]["record_id"])
        context = self.memory.planner_context()
        self.assertEqual(1, len(context["task_memory"]))
        self.assertNotIn("com.example.private", json.dumps(context, sort_keys=True))


if __name__ == "__main__":
    unittest.main(verbosity=2)
