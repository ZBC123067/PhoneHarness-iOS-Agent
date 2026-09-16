#!/usr/bin/env python3
"""Static privacy and boundary tests for TEST-28 Personal Intelligence Core.

These tests never contact an iPhone.  They use only temporary stores and
synthetic allow-listed metadata to prove the Personal Intelligence Core remains
an advisory summary layer rather than a task transcript or decision maker.
"""

from __future__ import annotations

import json
import stat
import tempfile
import unittest
from pathlib import Path

from phoneharness_agent import (
    AgentMemoryLayer,
    AgentMemoryStore,
    DecisionEvidenceLayer,
    PersonalIntelligenceCore,
    PersonalIntelligencePolicyError,
)


FORBIDDEN_KEYS = frozenset(
    {
        "goal",
        "app_identity",
        "app_id",
        "bundle_id",
        "ui",
        "coordinate",
        "coordinates",
        "rect",
        "screenshot",
        "ocr",
        "input",
        "clipboard",
        "raw_mcp_response",
        "raw_response",
        "plan",
        "action",
        "password",
        "private_message",
    }
)


def keys_in(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(keys_in(item) for item in value.values())) if value else set()
    if isinstance(value, (list, tuple)):
        return set().union(*(keys_in(item) for item in value)) if value else set()
    return set()


class PersonalIntelligenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "private" / "memory-v1.jsonl"
        self.store = AgentMemoryStore(self.path)
        self.core = PersonalIntelligenceCore(self.store)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_preference_requires_explicit_confirmation_and_allow_list(self) -> None:
        with self.assertRaises(PersonalIntelligencePolicyError):
            self.core.record_confirmed_preference(
                model="preference",
                preference_key="privacy_retention",
                preference_value="minimal",
                confirmed_by_user=False,
            )
        with self.assertRaises(PersonalIntelligencePolicyError):
            self.core.record_confirmed_preference(
                model="preference",
                preference_key="privacy_retention",
                preference_value="retain_everything",
                confirmed_by_user=True,
            )

    def test_preference_decision_and_communication_models_are_separate(self) -> None:
        self.core.record_confirmed_preference(
            model="preference",
            preference_key="privacy_retention",
            preference_value="standard",
            confirmed_by_user=True,
            recorded_at=10,
        )
        self.core.record_confirmed_preference(
            model="preference",
            preference_key="privacy_retention",
            preference_value="minimal",
            confirmed_by_user=True,
            recorded_at=11,
        )
        self.core.record_confirmed_preference(
            model="decision_preference",
            preference_key="candidate_priority",
            preference_value="reliability_first",
            confirmed_by_user=True,
            recorded_at=12,
        )
        self.core.record_confirmed_preference(
            model="communication_style",
            preference_key="instruction_format",
            preference_value="stepwise",
            confirmed_by_user=True,
            recorded_at=13,
        )
        context = self.core.advisory_context()
        self.assertEqual([{"preference_key": "privacy_retention", "preference_value": "minimal", "confirmed_at": 11}], context["preference_model"])
        self.assertEqual([{"preference_key": "candidate_priority", "preference_value": "reliability_first", "confirmed_at": 12}], context["decision_preference_model"])
        self.assertEqual([{"preference_key": "instruction_format", "preference_value": "stepwise", "confirmed_at": 13}], context["communication_style_model"])

    def test_habits_are_verified_aggregate_statistics(self) -> None:
        with self.assertRaises(PersonalIntelligencePolicyError):
            self.core.record_verified_habit(habit_id="read_only_observation", verifier_passed=False)
        self.core.record_verified_habit(habit_id="read_only_observation", verifier_passed=True, recorded_at=20)
        self.core.record_verified_habit(habit_id="read_only_observation", verifier_passed=True, recorded_at=21)
        self.assertEqual(
            [{"habit_id": "read_only_observation", "verified_count": 2, "last_verified": 21}],
            self.core.advisory_context()["habit_model"],
        )

    def test_task_summaries_require_completed_verifier_passed_result(self) -> None:
        with self.assertRaises(PersonalIntelligencePolicyError):
            self.core.record_successful_task_summary(
                summary_type="read_only_observation",
                task_completed=True,
                verifier_passed=False,
            )
        self.core.record_successful_task_summary(
            summary_type="read_only_observation",
            task_completed=True,
            verifier_passed=True,
            recorded_at=30,
        )
        self.assertEqual(
            [{"summary_type": "read_only_observation", "completed_at": 30}],
            self.core.advisory_context()["successful_task_summaries"],
        )

    def test_decision_evidence_requires_confirmed_metadata_and_aggregates(self) -> None:
        evidence = DecisionEvidenceLayer(self.store)
        with self.assertRaises(PersonalIntelligencePolicyError):
            evidence.record_confirmed_result(
                source_type="skill_package",
                lifecycle="AVAILABLE",
                outcome="passed",
                confidence=0.8,
                duration_ms=10,
                result_confirmed=False,
            )
        evidence.record_confirmed_result(
            source_type="skill_package",
            lifecycle="AVAILABLE",
            outcome="passed",
            confidence=0.8,
            duration_ms=10,
            result_confirmed=True,
            recorded_at=40,
        )
        evidence.record_confirmed_result(
            source_type="skill_package",
            lifecycle="AVAILABLE",
            outcome="failed",
            confidence=0.4,
            duration_ms=30,
            result_confirmed=True,
            recorded_at=41,
        )
        self.assertEqual(
            [
                {
                    "source_type": "skill_package",
                    "lifecycle": "AVAILABLE",
                    "selection_count": 2,
                    "success_count": 1,
                    "failure_count": 1,
                    "mean_confidence": 0.6,
                    "mean_duration_ms": 20.0,
                    "last_recorded_at": 41,
                }
            ],
            evidence.summary(),
        )

    def test_invalid_personal_record_with_private_content_is_ignored(self) -> None:
        poisoned = {
            "schema_version": "3.0",
            "memory_version": "test-28.0",
            "record_id": "poisoned",
            "recorded_at": 1,
            "record_type": "personal_preference",
            "write_boundary": "explicit_user_confirmation",
            "model": "preference",
            "preference_key": "privacy_retention",
            "preference_value": "minimal",
            "goal": "must-never-persist",
        }
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path.write_text(json.dumps(poisoned) + "\n", encoding="utf-8")
        self.path.chmod(0o600)
        context = self.core.advisory_context()
        self.assertEqual([], context["preference_model"])
        self.assertFalse(FORBIDDEN_KEYS.intersection(keys_in(context)))

    def test_store_keeps_existing_memory_schemas_when_test_28_records_append(self) -> None:
        AgentMemoryLayer(self.store).record_task_completion(
            task_state="completed",
            completion_result="passed",
            verifier_passed=True,
            recorded_at=50,
        )
        self.core.record_verified_habit(habit_id="semantic_verification", verifier_passed=True, recorded_at=51)
        records = self.store._read_records()
        self.assertTrue(any(record.get("schema_version") == "2.0" for record in records))
        self.assertTrue(any(record.get("schema_version") == "3.0" for record in records))

    def test_private_file_modes_are_preserved(self) -> None:
        self.core.record_verified_habit(habit_id="semantic_verification", verifier_passed=True)
        self.assertEqual(0o700, stat.S_IMODE(self.path.parent.stat().st_mode))
        self.assertEqual(0o600, stat.S_IMODE(self.path.stat().st_mode))

    def test_advisory_context_has_no_decision_or_execution_interface(self) -> None:
        context = self.core.advisory_context()
        self.assertEqual("advisory_only", context["mode"])
        self.assertEqual("none", context["decision_effect"])
        self.assertTrue(context["requires_explicit_planner_opt_in"])
        self.assertTrue(context["requires_fresh_observation"])
        self.assertTrue(context["requires_solution_evaluation"])
        self.assertTrue(context["requires_risk_controller"])
        self.assertTrue(context["requires_verifier"])
        for forbidden_name in ("client", "plan", "select", "execute", "verify", "assess", "call_tool"):
            self.assertFalse(hasattr(self.core, forbidden_name), forbidden_name)

    def test_all_exposed_summaries_exclude_private_or_replayable_data(self) -> None:
        self.core.record_confirmed_preference(
            model="communication_style",
            preference_key="detail_level",
            preference_value="balanced",
            confirmed_by_user=True,
        )
        self.core.record_verified_habit(habit_id="read_only_observation", verifier_passed=True)
        self.core.record_successful_task_summary(
            summary_type="capability_evaluation",
            task_completed=True,
            verifier_passed=True,
        )
        self.core.record_decision_evidence(
            source_type="external_tool",
            lifecycle="VERIFIED",
            outcome="passed",
            confidence=0.9,
            duration_ms=100,
            result_confirmed=True,
        )
        context = self.core.advisory_context()
        self.assertFalse(FORBIDDEN_KEYS.intersection(keys_in(context)))
        serialized = json.dumps(context, ensure_ascii=False)
        self.assertNotIn("must-never-persist", serialized)
        self.assertNotIn("raw_mcp_response", serialized)


if __name__ == "__main__":
    unittest.main(verbosity=2)
