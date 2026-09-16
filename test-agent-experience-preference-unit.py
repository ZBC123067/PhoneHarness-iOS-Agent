#!/usr/bin/env python3
"""Static contract tests for TEST-39 Experience & Preference Learning.

All data is synthetic, opaque metadata in a temporary Mac-hosted directory.
These tests do not instantiate an MCP client, contact an iPhone, invoke a
model, or execute an action.
"""

from __future__ import annotations

import inspect
import json
import stat
import tempfile
import unittest
from pathlib import Path

from phoneharness_agent import (
    ExperiencePreferenceEngine,
    ExperiencePreferencePolicyError,
    ExperiencePreferenceStateError,
    IdentityConsentFoundation,
    PermissionRequest,
)


OWNER = "experience-owner-token-0001"
OTHER_OWNER = "experience-owner-token-9999"
IDENTITY_ID = "person.experience.owner"
OWNERSHIP_REF = "knowledge.personal.experience"
WORKSPACE_REF = "workspace.personal.experience"
CONSENT_ID = "consent.personal.experience"
PURPOSE_CODE = "experience.learn"

FORBIDDEN_KEYS = frozenset(
    {
        "goal",
        "message",
        "conversation",
        "content",
        "screenshot",
        "coordinate",
        "coordinates",
        "rect",
        "ui",
        "ocr",
        "raw_ax",
        "raw_mcp_response",
        "input",
        "clipboard",
        "password",
        "token",
        "tool_arguments",
        "action_arguments",
        "replay",
        "steps",
        "script",
    }
)


def keys_in(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(keys_in(item) for item in value.values())) if value else set()
    if isinstance(value, (tuple, list)):
        return set().union(*(keys_in(item) for item in value)) if value else set()
    return set()


class ExperiencePreferenceEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        base = Path(self.temporary_directory.name)
        self.root = base / "experience-preference"
        self.engine = ExperiencePreferenceEngine(self.root)
        self.foundation = IdentityConsentFoundation(base / "identity-consent")
        self.foundation.create_identity(
            identity_id=IDENTITY_ID,
            identity_kind="PERSONAL",
            claims={"preferred_language": "zh-Hans"},
            confirmed_by_user=True,
            created_at=100,
        )
        self.foundation.classify_ownership(
            ownership_ref=OWNERSHIP_REF,
            ownership_class="PERSONAL",
            controlling_identity_id=IDENTITY_ID,
            confirmed_by_user=True,
            classified_at=101,
        )
        self.foundation.set_workspace_permissions(
            workspace_ref=WORKSPACE_REF,
            permission_actions=("READ", "TRAIN_MEMORY", "CREATE_RULE"),
            confirmed_by_user=True,
            recorded_at=102,
        )
        self.foundation.grant_consent(
            consent_id=CONSENT_ID,
            identity_id=IDENTITY_ID,
            ownership_ref=OWNERSHIP_REF,
            purpose_code=PURPOSE_CODE,
            audience_scope="owner_only",
            permission_actions=("READ", "TRAIN_MEMORY", "CREATE_RULE"),
            consent_uses=("LEARN", "TRAIN_MEMORY"),
            retention_category="until_revoked",
            confirmed_by_user=True,
            created_at=103,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def permission(self, action: str, consent_use: str, *, evaluated_at: int = 110):
        return self.foundation.resolve_permission(
            PermissionRequest(
                identity_id=IDENTITY_ID,
                ownership_ref=OWNERSHIP_REF,
                ownership_class="PERSONAL",
                workspace_ref=WORKSPACE_REF,
                purpose_code=PURPOSE_CODE,
                audience_scope="owner_only",
                action=action,
                consent_use=consent_use,
                risk_policy_allows=True,
            ),
            evaluated_at=evaluated_at,
        )

    def create_candidate(
        self,
        *,
        experience_type: str = "PREFERENCE",
        category: str = "reply_style",
        source_kind: str = "EXPLICIT_PREFERENCE",
        now: int = 120,
        event_id: str | None = None,
        expires_at: int | None = None,
    ) -> dict[str, object]:
        return self.engine.create_candidate(
            OWNER,
            owner_ref=OWNERSHIP_REF,
            experience_type=experience_type,
            category=category,
            source_kind=source_kind,
            lineage_ref="lineage.experience.safe",
            permission=self.permission("TRAIN_MEMORY", "TRAIN_MEMORY"),
            confidence=500,
            now=now,
            event_id=event_id,
            expires_at=expires_at,
        )

    def activate(self, candidate: dict[str, object], *, start: int = 121) -> dict[str, object]:
        experience_id = str(candidate["experience_id"])
        write_permission = self.permission("TRAIN_MEMORY", "TRAIN_MEMORY")
        self.engine.collect_evidence(
            experience_id,
            OWNER,
            observed_count=5,
            matching_outcome_count=4,
            failure_count=1,
            evidence_confidence=800,
            verifier_confirmed=True,
            permission=write_permission,
            now=start,
        )
        self.engine.begin_validation(
            experience_id,
            OWNER,
            permission=write_permission,
            now=start + 1,
        )
        self.engine.record_validation(
            experience_id,
            OWNER,
            verifier_passed=True,
            permission=write_permission,
            now=start + 2,
        )
        self.engine.confirm_activation(
            experience_id,
            OWNER,
            confirmed_by_user=True,
            permission=write_permission,
            now=start + 3,
        )
        return self.engine.activate_advisory(
            experience_id,
            OWNER,
            permission=write_permission,
            now=start + 4,
        )

    def test_preference_requires_confirmed_verification_before_becoming_advisory(self) -> None:
        candidate = self.create_candidate()
        experience_id = str(candidate["experience_id"])
        write_permission = self.permission("TRAIN_MEMORY", "TRAIN_MEMORY")
        self.engine.collect_evidence(
            experience_id,
            OWNER,
            observed_count=1,
            matching_outcome_count=1,
            failure_count=0,
            evidence_confidence=900,
            verifier_confirmed=True,
            permission=write_permission,
            now=121,
        )
        self.engine.begin_validation(experience_id, OWNER, permission=write_permission, now=122)
        self.engine.record_validation(
            experience_id,
            OWNER,
            verifier_passed=True,
            permission=write_permission,
            now=123,
        )
        with self.assertRaises(ExperiencePreferencePolicyError):
            self.engine.activate_advisory(experience_id, OWNER, permission=write_permission, now=124)

        self.engine.confirm_activation(
            experience_id,
            OWNER,
            confirmed_by_user=True,
            permission=write_permission,
            now=124,
        )
        active = self.engine.activate_advisory(experience_id, OWNER, permission=write_permission, now=125)

        self.assertEqual("ACTIVE_ADVISORY", active["state"])
        self.assertEqual("none", active["decision_effect"])
        self.assertEqual("none", active["automation_effect"])
        self.assertEqual(1, active["frequency"]["user_confirmation_count"])

    def test_behavior_pattern_requires_verifier_confirmed_aggregate_evidence(self) -> None:
        with self.assertRaises(ExperiencePreferencePolicyError):
            self.create_candidate(
                experience_type="BEHAVIOR_PATTERN",
                category="frequent_quote_workflow",
                source_kind="USER_CORRECTION",
            )
        candidate = self.create_candidate(
            experience_type="BEHAVIOR_PATTERN",
            category="frequent_quote_workflow",
            source_kind="VERIFIER_CONFIRMED_OUTCOME",
        )
        with self.assertRaises(ExperiencePreferencePolicyError):
            self.engine.collect_evidence(
                str(candidate["experience_id"]),
                OWNER,
                observed_count=3,
                matching_outcome_count=3,
                failure_count=0,
                evidence_confidence=800,
                verifier_confirmed=False,
                permission=self.permission("TRAIN_MEMORY", "TRAIN_MEMORY"),
                now=121,
            )
        active = self.activate(candidate)
        self.assertEqual("BEHAVIOR_PATTERN", active["experience_type"])
        self.assertEqual(5, active["frequency"]["observed_count"])
        self.assertEqual(4, active["frequency"]["matching_outcome_count"])

    def test_rejected_validation_returns_to_candidate_without_guessing(self) -> None:
        candidate = self.create_candidate()
        experience_id = str(candidate["experience_id"])
        write_permission = self.permission("TRAIN_MEMORY", "TRAIN_MEMORY")
        self.engine.collect_evidence(
            experience_id,
            OWNER,
            observed_count=2,
            matching_outcome_count=1,
            failure_count=1,
            evidence_confidence=500,
            verifier_confirmed=True,
            permission=write_permission,
            now=121,
        )
        self.engine.begin_validation(experience_id, OWNER, permission=write_permission, now=122)
        rejected = self.engine.record_validation(
            experience_id,
            OWNER,
            verifier_passed=False,
            permission=write_permission,
            now=123,
        )

        self.assertEqual("CANDIDATE", rejected["state"])
        self.assertEqual("REJECTED", rejected["validation_status"])
        self.assertEqual("validation_rejected", rejected["last_reason_code"])
        with self.assertRaises(ExperiencePreferenceStateError):
            self.engine.confirm_activation(
                experience_id,
                OWNER,
                confirmed_by_user=True,
                permission=write_permission,
                now=124,
            )

    def test_procedure_candidate_only_creates_a_non_executable_graduation_handoff(self) -> None:
        candidate = self.create_candidate(
            experience_type="PROCEDURE_CANDIDATE",
            category="routine_quote_preparation",
            source_kind="TEACHING_HANDOFF",
        )
        active = self.activate(candidate)
        handoff = self.engine.graduation_handoff(
            str(active["experience_id"]),
            OWNER,
            permission=self.permission("CREATE_RULE", "LEARN"),
        )

        self.assertTrue(handoff["requires_test32_validation"])
        self.assertFalse(handoff["capability_created"])
        self.assertEqual("none", handoff["automation_effect"])
        source = inspect.getsource(ExperiencePreferenceEngine)
        for forbidden in ("MCPClient(", "call_tool(", "PlanExecutor(", "execute_", "launch_app("):
            self.assertNotIn(forbidden, source)

    def test_revoked_consent_blocks_future_history_and_advisory_reads(self) -> None:
        active = self.activate(self.create_candidate())
        experience_id = str(active["experience_id"])
        allowed_read = self.permission("READ", "LEARN")
        self.assertGreaterEqual(len(self.engine.history(experience_id, OWNER, permission=allowed_read)), 1)
        self.assertEqual(1, len(self.engine.advisory_context(OWNER, permission=allowed_read)["experience_summaries"]))

        self.foundation.revoke_consent(
            consent_id=CONSENT_ID,
            reason_code="owner.revoked",
            confirmed_by_user=True,
            revoked_at=200,
        )
        denied_read = self.permission("READ", "LEARN", evaluated_at=201)
        self.assertFalse(denied_read.eligible)
        with self.assertRaises(ExperiencePreferencePolicyError):
            self.engine.history(experience_id, OWNER, permission=denied_read)
        with self.assertRaises(ExperiencePreferencePolicyError):
            self.engine.advisory_context(OWNER, permission=denied_read)
        self.assertGreaterEqual(len(self.engine.store.audit_events()), 1)

    def test_private_storage_is_atomic_idempotent_and_redacted(self) -> None:
        first = self.create_candidate(event_id="event.experience.create")
        duplicate = self.create_candidate(
            category="different_safe_category",
            event_id="event.experience.create",
        )
        path = self.root / "experience-ledger-v1.json"
        raw = path.read_text(encoding="utf-8")
        persisted = json.loads(raw)

        self.assertEqual(first["experience_id"], duplicate["experience_id"])
        self.assertEqual(1, len(persisted["payload"]["histories"]))
        self.assertEqual(0o700, stat.S_IMODE(self.root.stat().st_mode))
        self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))
        self.assertEqual(0o600, stat.S_IMODE((self.root / ".experience-ledger-v1.json.lock").stat().st_mode))
        self.assertFalse(FORBIDDEN_KEYS.intersection(keys_in(persisted)))
        for forbidden_value in (OWNER, "different_safe_category", "raw private message", "0.50,0.80"):
            self.assertNotIn(forbidden_value, raw)

    def test_expiry_owner_and_invalid_reference_fail_closed(self) -> None:
        candidate = self.create_candidate(expires_at=130)
        experience_id = str(candidate["experience_id"])
        with self.assertRaises(ExperiencePreferencePolicyError):
            self.engine.collect_evidence(
                experience_id,
                OTHER_OWNER,
                observed_count=1,
                matching_outcome_count=1,
                failure_count=0,
                evidence_confidence=900,
                verifier_confirmed=True,
                permission=self.permission("TRAIN_MEMORY", "TRAIN_MEMORY"),
                now=121,
            )
        expired = self.engine.expire_due(experience_id, OWNER, now=130)
        self.assertEqual("EXPIRED", expired["state"])
        with self.assertRaises(ExperiencePreferenceStateError):
            self.engine.begin_validation(
                experience_id,
                OWNER,
                permission=self.permission("TRAIN_MEMORY", "TRAIN_MEMORY"),
                now=131,
            )
        with self.assertRaises(ExperiencePreferencePolicyError):
            self.create_candidate(category="raw category with spaces")


if __name__ == "__main__":
    unittest.main(verbosity=2)
