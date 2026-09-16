#!/usr/bin/env python3
"""Static privacy and boundary tests for TEST-31 Human Teaching Layer.

The suite uses only synthetic phrases and temporary Mac storage. It never
contacts an iPhone, creates a capability, creates a Shortcut, learns a raw
workflow, calls a model, or invokes an action-capable runtime layer.
"""

from __future__ import annotations

import json
import stat
import tempfile
import unittest
from pathlib import Path

from phoneharness_agent import (
    AgentMemoryStore,
    HumanTeachingLayer,
    HumanTeachingPolicyError,
    TeachingRuleOutline,
)


FORBIDDEN_KEYS = frozenset(
    {
        "message",
        "goal",
        "app",
        "bundle_id",
        "ui",
        "coordinate",
        "coordinates",
        "rect",
        "screenshot",
        "ocr",
        "input",
        "clipboard",
        "password",
        "private_message",
        "raw_mcp_response",
        "raw_response",
        "plan",
        "action",
    }
)


def keys_in(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(keys_in(item) for item in value.values())) if value else set()
    if isinstance(value, (list, tuple)):
        return set().union(*(keys_in(item) for item in value)) if value else set()
    return set()


class HumanTeachingLayerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "private" / "memory-v1.jsonl"
        self.store = AgentMemoryStore(self.path)
        self.layer = HumanTeachingLayer(self.store)
        self.outline = TeachingRuleOutline(
            rule_type="reusable_handling",
            candidate_kind="local_rule",
            risk_level="read_only",
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def teaching_proposal(self):
        intent = self.layer.detect_intent("以后都这样处理")
        return self.layer.propose(intent, self.outline)

    def test_detects_teaching_normal_and_ambiguous_intent_without_retaining_message(self) -> None:
        teaching = self.layer.detect_intent("记住这个流程")
        normal = self.layer.detect_intent("帮我做一次")
        ambiguous = self.layer.detect_intent("以后都这样处理，但这次只做一次")
        self.assertEqual("teaching", teaching.intent)
        self.assertEqual("normal_request", normal.intent)
        self.assertEqual("ambiguous", ambiguous.intent)
        self.assertFalse(FORBIDDEN_KEYS.intersection(keys_in(teaching.summary())))
        self.assertEqual([], self.store._read_records())

    def test_only_explicit_teaching_intent_can_create_a_proposal(self) -> None:
        normal = self.layer.detect_intent("帮我做一次")
        with self.assertRaises(HumanTeachingPolicyError):
            self.layer.propose(normal, self.outline)
        proposal = self.teaching_proposal()
        self.assertEqual("awaiting_confirmation", proposal.status)
        self.assertTrue(proposal.summary()["requires_explicit_user_confirmation"])
        self.assertFalse(proposal.summary()["retained"])
        self.assertEqual([], self.store._read_records())

    def test_confirmation_creates_only_a_pending_candidate(self) -> None:
        candidate = self.layer.confirm(self.teaching_proposal(), confirmed_by_user=True)
        summary = candidate.summary()
        self.assertEqual("pending_validation", summary["status"])
        self.assertTrue(summary["requires_validation"])
        self.assertIsNone(summary["possible_upgrade"])
        self.assertEqual([], self.store._read_records())

    def test_rejected_proposal_never_becomes_a_validatable_candidate(self) -> None:
        candidate = self.layer.confirm(self.teaching_proposal(), confirmed_by_user=False)
        self.assertEqual("rejected", candidate.status)
        with self.assertRaises(HumanTeachingPolicyError):
            self.layer.record_validation(candidate, verifier_passed=True, confidence=0.9)
        self.assertEqual([], self.store._read_records())

    def test_verified_candidate_persists_only_safe_aggregate_metadata(self) -> None:
        candidate = self.layer.confirm(self.teaching_proposal(), confirmed_by_user=True)
        validated = self.layer.record_validation(
            candidate,
            verifier_passed=True,
            confidence=0.9,
            validated_at=100,
        )
        self.assertEqual("validated", validated.status)
        self.assertEqual("local_rule", validated.summary()["possible_upgrade"])
        context = self.layer.advisory_context()
        self.assertEqual("candidate_only", context["mode"])
        self.assertEqual("none", context["decision_effect"])
        self.assertEqual(
            [
                {
                    "rule_type": "reusable_handling",
                    "candidate_kind": "local_rule",
                    "risk_level": "read_only",
                    "validated_count": 1,
                    "failed_count": 0,
                    "mean_confidence": 0.9,
                    "last_validated_at": 100,
                    "promotion_requires_future_review": True,
                }
            ],
            context["validated_candidate_summaries"],
        )
        self.assertFalse(FORBIDDEN_KEYS.intersection(keys_in(context)))

    def test_failed_validation_is_classified_but_not_upgrade_eligible(self) -> None:
        candidate = self.layer.confirm(self.teaching_proposal(), confirmed_by_user=True)
        failed = self.layer.record_validation(
            candidate,
            verifier_passed=False,
            confidence=0.2,
            validated_at=101,
        )
        self.assertEqual("validation_failed", failed.status)
        self.assertIsNone(failed.summary()["possible_upgrade"])
        record = self.store._read_records()[0]
        self.assertEqual("classified_result", record["write_boundary"])
        self.assertEqual("failed", record["validation_status"])

    def test_invalid_outline_message_and_confidence_are_rejected(self) -> None:
        with self.assertRaises(HumanTeachingPolicyError):
            TeachingRuleOutline("unknown", "local_rule", "read_only")
        with self.assertRaises(HumanTeachingPolicyError):
            self.layer.detect_intent("x" * (self.layer.MAX_MESSAGE_CHARACTERS + 1))
        candidate = self.layer.confirm(self.teaching_proposal(), confirmed_by_user=True)
        with self.assertRaises(HumanTeachingPolicyError):
            self.layer.record_validation(candidate, verifier_passed=True, confidence=1.1)

    def test_poisoned_or_private_records_are_ignored(self) -> None:
        poisoned = {
            "schema_version": "4.0",
            "memory_version": "test-31.0",
            "record_id": "poisoned",
            "recorded_at": 1,
            "record_type": "teaching_capability_candidate",
            "write_boundary": "verifier_pass",
            "rule_type": "reusable_handling",
            "candidate_kind": "local_rule",
            "risk_level": "read_only",
            "validation_status": "passed",
            "confidence": 0.8,
            "screenshot": "must-not-be-read",
        }
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path.write_text(json.dumps(poisoned) + "\n", encoding="utf-8")
        self.path.chmod(0o600)
        self.assertEqual([], self.layer.advisory_context()["validated_candidate_summaries"])

    def test_private_store_modes_and_existing_records_are_preserved(self) -> None:
        self.layer.record_validation(
            self.layer.confirm(self.teaching_proposal(), confirmed_by_user=True),
            verifier_passed=True,
            confidence=0.8,
        )
        self.assertEqual(0o700, stat.S_IMODE(self.path.parent.stat().st_mode))
        self.assertEqual(0o600, stat.S_IMODE(self.path.stat().st_mode))
        self.assertTrue(any(record.get("schema_version") == "4.0" for record in self.store._read_records()))

    def test_layer_and_candidate_only_expose_future_runtime_gates(self) -> None:
        candidate = self.layer.confirm(self.teaching_proposal(), confirmed_by_user=True)
        for forbidden_name in ("client", "execute", "select", "plan", "call_tool", "register", "create_shortcut"):
            self.assertFalse(hasattr(self.layer, forbidden_name), forbidden_name)
        summary = candidate.summary()
        self.assertTrue(summary["requires_planner"])
        self.assertTrue(summary["requires_risk_controller"])
        self.assertTrue(summary["requires_executor"])
        self.assertTrue(summary["requires_verifier"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
