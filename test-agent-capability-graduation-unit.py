#!/usr/bin/env python3
"""Static privacy, lifecycle, and trust tests for TEST-32.

These tests use only synthetic, allow-listed metadata in a temporary private
memory file. They never contact an iPhone and never create or execute a Skill,
Shortcut, Workflow, local rule, planner action, or MCP call.
"""

from __future__ import annotations

import json
import stat
import tempfile
import unittest
from pathlib import Path

from phoneharness_agent import (
    CAPABILITY_GRADUATION_VERSION,
    AgentMemoryStore,
    CapabilityGraduationEngine,
    CapabilityGraduationPolicyError,
    HumanTeachingLayer,
    TeachingRuleOutline,
)


FORBIDDEN_KEYS = frozenset(
    {
        "goal",
        "message",
        "app",
        "app_identity",
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
        "rule_text",
        "workflow_steps",
    }
)


def keys_in(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(keys_in(item) for item in value.values())) if value else set()
    if isinstance(value, (list, tuple)):
        return set().union(*(keys_in(item) for item in value)) if value else set()
    return set()


class CapabilityGraduationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "private" / "memory-v1.jsonl"
        self.store = AgentMemoryStore(self.path)
        self.engine = CapabilityGraduationEngine(self.store)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def discovered_candidate(self, *, risk_level: str = "read_only", frequency: int = 2):
        return self.engine.discover(
            capability_kind="local_rule",
            risk_level=risk_level,
            observed_frequency=frequency,
            discovered_at=10,
        )

    def nominated_candidate(self, *, risk_level: str = "read_only", frequency: int = 2):
        return self.engine.nominate_candidate(
            self.discovered_candidate(risk_level=risk_level, frequency=frequency),
            confirmed_by_user=True,
            nominated_at=11,
        )

    def test_discovery_is_transient_until_owner_nominates_candidate(self) -> None:
        discovered = self.discovered_candidate()
        self.assertEqual("DISCOVERED", discovered.lifecycle)
        self.assertEqual([], self.store._read_records())
        candidate = self.engine.nominate_candidate(discovered, confirmed_by_user=True, nominated_at=11)
        self.assertEqual("CANDIDATE", candidate.lifecycle)
        self.assertEqual(1, candidate.user_confirmation_count)
        record = self.store._read_records()[0]
        self.assertEqual("explicit_user_confirmation", record["write_boundary"])
        self.assertEqual("CANDIDATE", record["lifecycle"])

    def test_lifecycle_transitions_are_explicit_and_illegal_shortcuts_fail(self) -> None:
        candidate = self.nominated_candidate()
        with self.assertRaises(CapabilityGraduationPolicyError):
            self.engine.activate(candidate, confirmed_by_user=True)
        teaching = self.engine.begin_teaching(candidate, confirmed_by_user=True, teaching_at=12)
        validating = self.engine.submit_for_validation(teaching, confirmed_by_user=True, submitted_at=13)
        self.assertEqual("VALIDATING", validating.lifecycle)
        with self.assertRaises(CapabilityGraduationPolicyError):
            self.engine.nominate_candidate(validating, confirmed_by_user=True)
        retired = self.engine.deprecate(
            validating,
            reason_code="owner_retired",
            confirmed_by_user=True,
            deprecated_at=14,
        )
        self.assertEqual("DEPRECATED", retired.lifecycle)
        with self.assertRaises(CapabilityGraduationPolicyError):
            self.engine.deprecate(retired, reason_code="owner_retired", confirmed_by_user=True)

    def test_human_teaching_import_requires_test31_validated_candidate_and_stays_non_executable(self) -> None:
        teaching_layer = HumanTeachingLayer(self.store)
        proposal = teaching_layer.propose(
            teaching_layer.detect_intent("以后都这样处理"),
            TeachingRuleOutline("reusable_handling", "local_rule", "read_only"),
        )
        validated = teaching_layer.record_validation(
            teaching_layer.confirm(proposal, confirmed_by_user=True),
            verifier_passed=True,
            confidence=0.90,
            validated_at=20,
        )
        imported = self.engine.import_validated_teaching(validated, imported_at=21)
        self.assertEqual("human_teaching", imported.origin)
        self.assertEqual("VALIDATING", imported.lifecycle)
        trusted = self.engine.record_validation(
            imported,
            verifier_passed=True,
            confidence=0.95,
            validated_at=22,
        )
        self.assertEqual("TRUSTED", trusted.lifecycle)
        active = self.engine.activate(trusted, confirmed_by_user=True, activated_at=23)
        reopened = self.engine.begin_revalidation(active, confirmed_by_user=True, reopened_at=24)
        self.assertEqual("VALIDATING", reopened.lifecycle)
        self.assertEqual(1, reopened.trust_level)
        summary = active.summary()
        self.assertEqual("ACTIVE", summary["lifecycle"])
        self.assertFalse(summary["capability_created"])
        self.assertEqual("none", summary["automation_effect"])

    def test_failed_validation_cannot_graduate_or_activate(self) -> None:
        validating = self.engine.begin_validation(self.nominated_candidate(), opened_at=30)
        result = self.engine.record_validation(
            validating,
            verifier_passed=False,
            confidence=0.20,
            validated_at=31,
        )
        assessment = self.engine.assess_trust(result)
        self.assertEqual("VALIDATING", result.lifecycle)
        self.assertFalse(assessment.eligible_for_trusted)
        self.assertIn("failure_evidence_present", assessment.reason_codes)
        with self.assertRaises(CapabilityGraduationPolicyError):
            self.engine.activate(result, confirmed_by_user=True)

    def test_high_risk_never_gains_automatic_authority(self) -> None:
        validating = self.engine.begin_validation(
            self.nominated_candidate(risk_level="high_risk", frequency=3),
            opened_at=40,
        )
        for timestamp in (41, 42, 43):
            validating = self.engine.record_validation(
                validating,
                verifier_passed=True,
                confidence=0.95,
                validated_at=timestamp,
            )
        self.assertEqual("TRUSTED", validating.lifecycle)
        assessment = self.engine.assess_trust(validating)
        self.assertEqual(2, assessment.trust_level)
        self.assertTrue(assessment.requires_explicit_user_confirmation)
        self.assertEqual(0, assessment.summary()["effective_automation_level"])
        with self.assertRaises(CapabilityGraduationPolicyError):
            self.engine.activate(validating, confirmed_by_user=False)
        active = self.engine.activate(validating, confirmed_by_user=True, activated_at=44)
        with self.assertRaises(CapabilityGraduationPolicyError):
            self.engine.begin_revalidation(active, confirmed_by_user=False)

    def test_advisory_context_is_aggregate_only_and_has_no_decision_effect(self) -> None:
        validating = self.engine.begin_validation(self.nominated_candidate(), opened_at=50)
        trusted = self.engine.record_validation(
            validating,
            verifier_passed=True,
            confidence=0.90,
            validated_at=51,
        )
        context = self.engine.advisory_context()
        self.assertEqual(CAPABILITY_GRADUATION_VERSION, context["capability_graduation_version"])
        self.assertEqual("lifecycle_only", context["mode"])
        self.assertEqual("none", context["decision_effect"])
        self.assertEqual("none", context["automation_effect"])
        self.assertNotIn(trusted.graduation_id, json.dumps(context, ensure_ascii=False))
        self.assertFalse(FORBIDDEN_KEYS.intersection(keys_in(context)))

    def test_poisoned_or_private_record_is_not_exposed(self) -> None:
        poisoned = {
            "schema_version": "5.0",
            "memory_version": "test-32.0",
            "record_id": "poisoned",
            "recorded_at": 1,
            "record_type": "capability_graduation_state",
            "write_boundary": "verifier_pass",
            "graduation_id": "opaque",
            "capability_kind": "local_rule",
            "origin": "human_teaching",
            "risk_level": "read_only",
            "lifecycle": "VALIDATING",
            "validation_state": "passed",
            "success_count": 1,
            "failure_count": 0,
            "user_confirmation_count": 1,
            "frequency_count": 1,
            "confidence_total": 0.9,
            "last_verified_at": 1,
            "trust_level": 1,
            "created_at": 1,
            "updated_at": 1,
            "screenshot": "must-not-be-read",
        }
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path.write_text(json.dumps(poisoned) + "\n", encoding="utf-8")
        self.path.chmod(0o600)
        self.assertEqual([], self.engine.advisory_context()["capability_summaries"])

    def test_private_persistence_modes_and_schema_reload_are_preserved(self) -> None:
        self.engine.begin_validation(self.nominated_candidate(), opened_at=60)
        self.assertEqual(0o700, stat.S_IMODE(self.path.parent.stat().st_mode))
        self.assertEqual(0o600, stat.S_IMODE(self.path.stat().st_mode))
        self.assertTrue(
            any(record.get("memory_version") == CAPABILITY_GRADUATION_VERSION for record in self.store._read_records())
        )

    def test_invalid_confirmation_metadata_and_trust_inputs_are_rejected(self) -> None:
        with self.assertRaises(CapabilityGraduationPolicyError):
            self.engine.discover(
                capability_kind="local_rule",
                risk_level="read_only",
                observed_frequency=0,
            )
        discovered = self.discovered_candidate()
        with self.assertRaises(CapabilityGraduationPolicyError):
            self.engine.nominate_candidate(discovered, confirmed_by_user=False)
        validating = self.engine.begin_validation(self.nominated_candidate(), opened_at=70)
        with self.assertRaises(CapabilityGraduationPolicyError):
            self.engine.record_validation(validating, verifier_passed=True, confidence=1.1)

    def test_engine_has_no_runtime_or_capability_mutation_interface(self) -> None:
        for forbidden_name in (
            "client",
            "mcp",
            "call_tool",
            "execute",
            "plan",
            "select",
            "register",
            "create_shortcut",
            "create_skill",
            "modify_skill",
            "run_workflow",
            "route",
        ):
            self.assertFalse(hasattr(self.engine, forbidden_name), forbidden_name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
