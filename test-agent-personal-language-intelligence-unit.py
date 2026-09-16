#!/usr/bin/env python3
"""Focused TEST-44.2 contracts for private Personal Language Intelligence.

All language examples are synthetic.  The suite uses no screenshot capture,
OCR adapter, MCP client, device action, model, network, or cloud service.
"""

from __future__ import annotations

import inspect
import json
import stat
import tempfile
import unittest
from pathlib import Path

from phoneharness_agent import (
    CognitiveConcept,
    CognitiveEvidence,
    CognitiveRelationship,
    IdentityConsentFoundation,
    LanguageEncounterCandidate,
    LanguagePriorityPolicy,
    PermissionDecision,
    PermissionRequest,
    PersonalLanguageIntelligencePolicyError,
    PersonalLanguageKnowledgeEngine,
    SemanticCapabilityGraph,
)


OWNER_TOKEN = "language-owner-token-0001"
IDENTITY_ID = "identity.language.owner"
OWNERSHIP_REF = "ownership.language.personal"
WORKSPACE_REF = "workspace.language.personal"
CONSENT_ID = "consent.language.personal"
PURPOSE_CODE = "language.learn"

FORBIDDEN_KEYS = frozenset(
    {
        "screenshot", "image", "pixels", "ocr", "raw_ocr", "ocr_text", "coordinate", "coordinates",
        "rect", "layout", "ui", "raw_ax", "raw_mcp_response", "mcp", "input", "password", "token",
        "session_id", "source_path", "filename", "goal", "plan", "action", "replay", "steps",
    }
)


def keys_in(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(keys_in(item) for item in value.values())) if value else set()
    if isinstance(value, (tuple, list)):
        return set().union(*(keys_in(item) for item in value)) if value else set()
    return set()


class PersonalLanguageKnowledgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        base = Path(self.temporary_directory.name)
        self.engine = PersonalLanguageKnowledgeEngine(base / "language")
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
            permission_actions=("READ", "TRAIN_MEMORY"),
            confirmed_by_user=True,
            recorded_at=102,
        )
        self.foundation.grant_consent(
            consent_id=CONSENT_ID,
            identity_id=IDENTITY_ID,
            ownership_ref=OWNERSHIP_REF,
            purpose_code=PURPOSE_CODE,
            audience_scope="owner_only",
            permission_actions=("READ", "TRAIN_MEMORY"),
            consent_uses=("LEARN", "TRAIN_MEMORY"),
            retention_category="until_revoked",
            confirmed_by_user=True,
            created_at=103,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def permission(self, action: str, consent_use: str, *, evaluated_at: int = 110) -> PermissionDecision:
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

    @staticmethod
    def candidate(*, confidence: int = 950, term: str = "FT") -> LanguageEncounterCandidate:
        return LanguageEncounterCandidate(
            candidate_id="languagecandidate." + ("a" * 32),
            canonical_term=term,
            meaning="免箱期",
            language="en",
            domain="shipping",
            term_concept_id="concept.ftx",
            detected_language_confidence=980,
            context_confidence=confidence,
            source_type="visual_session",
            created_at=120,
        )

    @staticmethod
    def graph(*, conflicted: bool = False) -> SemanticCapabilityGraph:
        graph = SemanticCapabilityGraph()
        evidence = CognitiveEvidence(confirmation_count=1, verified_count=1, confidence=0.95, last_verified=120)
        for concept_id, concept_type in (
            ("concept.ftx", "term"),
            ("concept.free-time", "meaning"),
            ("concept.full-time", "meaning"),
        ):
            graph.register_concept(
                CognitiveConcept(
                    concept_id=concept_id,
                    domain="shipping",
                    concept_type=concept_type,
                    status="VALIDATED",
                    source_class="teaching_confirmed",
                    source_ref="teaching.language.v1",
                    confidence=0.95,
                    created_at=120,
                )
            )
        graph.register_relationship(
            CognitiveRelationship(
                relationship_id="relation.ftx-free-time",
                subject_concept_id="concept.ftx",
                relationship_type="contextual_meaning",
                object_concept_id="concept.free-time",
                domain="shipping",
                status="VALIDATED",
                source_class="teaching_confirmed",
                source_ref="teaching.language.v1",
                evidence=evidence,
                created_at=120,
            )
        )
        if conflicted:
            graph.register_relationship(
                CognitiveRelationship(
                    relationship_id="relation.ftx-full-time",
                    subject_concept_id="concept.ftx",
                    relationship_type="contextual_meaning",
                    object_concept_id="concept.full-time",
                    domain="shipping",
                    status="VALIDATED",
                    source_class="teaching_confirmed",
                    source_ref="teaching.language.v1",
                    evidence=evidence,
                    created_at=120,
                )
            )
        return graph

    def add(self, *, event_id: str = "event.language.add") -> dict[str, object]:
        return self.engine.apply_choice(
            self.candidate(),
            OWNER_TOKEN,
            graph=self.graph(),
            permission=self.permission("TRAIN_MEMORY", "TRAIN_MEMORY"),
            context_permission=self.permission("READ", "LEARN"),
            choice="ADD",
            confirmed_by_user=True,
            work_relevance=900,
            difficulty=700,
            now=130,
            event_id=event_id,
        )

    def test_domain_context_overrides_generic_translation_only_when_validated(self) -> None:
        preview = self.engine.preview(
            self.candidate(),
            graph=self.graph(),
            permission=self.permission("READ", "LEARN"),
        )
        self.assertEqual("READY_TO_CONFIRM", preview["status"])
        self.assertEqual(["concept.free-time"], preview["context_resolution"]["resolved_meaning_concept_ids"])
        self.assertEqual("ft", preview["learning"]["canonical_term"])
        self.assertEqual("免箱期", preview["learning"]["meaning"])
        self.assertFalse(FORBIDDEN_KEYS.intersection(keys_in(preview)))

    def test_low_confidence_or_conflict_needs_confirmation_without_guessing(self) -> None:
        low_confidence = self.engine.preview(
            self.candidate(confidence=799),
            graph=self.graph(),
            permission=self.permission("READ", "LEARN"),
        )
        conflict = self.engine.preview(
            self.candidate(),
            graph=self.graph(conflicted=True),
            permission=self.permission("READ", "LEARN"),
        )
        self.assertEqual("NEEDS_CONFIRMATION", low_confidence["status"])
        self.assertEqual([], low_confidence["context_resolution"]["resolved_meaning_concept_ids"])
        self.assertEqual("NEEDS_CONFIRMATION", conflict["status"])
        self.assertEqual([], conflict["context_resolution"]["resolved_meaning_concept_ids"])

    def test_add_writes_only_confirmed_semantic_learning_data(self) -> None:
        stored = self.add()
        self.assertEqual("ACTIVE", stored["state"])
        self.assertEqual("ft", stored["canonical_term"])
        self.assertEqual("免箱期", stored["meaning"])
        self.assertEqual("visual_session", stored["source_type"])
        self.assertFalse(stored["visual_content_retained"])
        self.assertEqual("none", stored["execution_authority"])
        self.assertFalse(FORBIDDEN_KEYS.intersection(keys_in(stored)))

        storage = json.loads((self.engine.root / "personal-language-v1.json").read_text(encoding="utf-8"))
        serialized = json.dumps(storage, ensure_ascii=False)
        self.assertNotIn("screenshot", serialized)
        self.assertNotIn("raw_ocr", serialized)
        self.assertNotIn("visualsession", serialized)
        self.assertEqual(0o700, stat.S_IMODE(self.engine.root.stat().st_mode))
        self.assertEqual(0o600, stat.S_IMODE((self.engine.root / "personal-language-v1.json").stat().st_mode))

    def test_ignore_and_auto_similar_do_not_persist_uncontrolled_learning(self) -> None:
        ignored = self.engine.apply_choice(
            self.candidate(), OWNER_TOKEN, graph=self.graph(), permission=self.permission("TRAIN_MEMORY", "TRAIN_MEMORY"),
            context_permission=self.permission("READ", "LEARN"),
            choice="IGNORE", confirmed_by_user=False, work_relevance=900, difficulty=700, now=130,
        )
        pending = self.engine.apply_choice(
            self.candidate(), OWNER_TOKEN, graph=self.graph(), permission=self.permission("TRAIN_MEMORY", "TRAIN_MEMORY"),
            context_permission=self.permission("READ", "LEARN"),
            choice="AUTO_LEARN_SIMILAR", confirmed_by_user=True, work_relevance=900, difficulty=700, now=131,
        )
        self.assertFalse(ignored["record_persisted"])
        self.assertFalse(pending["record_persisted"])
        self.assertEqual("NEEDS_CONFIRMATION", pending["status"])
        self.assertEqual((), self.engine.learning_queue(OWNER_TOKEN, permission=self.permission("READ", "LEARN"), now=132))

    def test_priority_reflects_frequency_relevance_and_mastery_reduction(self) -> None:
        stored = self.add()
        record_id = str(stored["record_id"])
        initial_score = int(stored["priority"]["score"])
        for index in range(5):
            stored = self.engine.review(
                record_id,
                OWNER_TOKEN,
                permission=self.permission("TRAIN_MEMORY", "TRAIN_MEMORY"),
                outcome="RECALLED",
                now=140 + index,
                event_id="event.language.review%d" % index,
            )
        self.assertEqual("MASTERED", stored["learning_stage"])
        self.assertEqual(900, stored["mastery"])
        self.assertLess(int(stored["priority"]["score"]), initial_score)
        self.assertEqual("learning_queue_only", stored["priority"]["decision_effect"])

    def test_forget_removes_semantic_content_and_blocks_future_retrieval(self) -> None:
        stored = self.add()
        forgotten = self.engine.forget(
            str(stored["record_id"]),
            OWNER_TOKEN,
            permission=self.permission("TRAIN_MEMORY", "TRAIN_MEMORY"),
            confirmed_by_user=True,
            now=160,
            event_id="event.language.forget",
        )
        self.assertEqual("FORGOTTEN", forgotten["status"])
        self.assertTrue(forgotten["retrieval_blocked"])
        self.assertTrue(forgotten["language_data_removed"])
        self.assertEqual((), self.engine.learning_queue(OWNER_TOKEN, permission=self.permission("READ", "LEARN"), now=161))
        payload = json.loads((self.engine.root / "personal-language-v1.json").read_text(encoding="utf-8"))["payload"]
        record = payload["records"][0]
        self.assertIsNone(record["canonical_term"])
        self.assertIsNone(record["meaning"])
        self.assertIsNone(record["term_key_digest"])
        self.assertNotIn("ft", json.dumps(record, ensure_ascii=False).lower())

    def test_permission_and_raw_visual_input_bypasses_are_rejected(self) -> None:
        denied = PermissionDecision(False, ("default_deny",), IDENTITY_ID, OWNERSHIP_REF, CONSENT_ID, "TRAIN_MEMORY", None, "test-36.0")
        with self.assertRaises(PersonalLanguageIntelligencePolicyError):
            self.engine.apply_choice(
                self.candidate(), OWNER_TOKEN, graph=self.graph(), permission=denied,
                context_permission=self.permission("READ", "LEARN"),
                choice="ADD", confirmed_by_user=True, work_relevance=900, difficulty=700, now=130,
            )
        with self.assertRaises(PersonalLanguageIntelligencePolicyError):
            LanguageEncounterCandidate(
                candidate_id="languagecandidate." + ("b" * 32),
                canonical_term="FT", meaning="免箱期", language="en", domain="shipping", term_concept_id="concept.ft",
                detected_language_confidence=900, context_confidence=900, source_type="ocr", created_at=120,
            ).validate()
        with self.assertRaises(TypeError):
            LanguageEncounterCandidate(  # type: ignore[call-arg]
                candidate_id="languagecandidate." + ("c" * 32), canonical_term="FT", meaning="免箱期", language="en",
                domain="shipping", term_concept_id="concept.ft", detected_language_confidence=900,
                context_confidence=900, source_type="visual_session", created_at=120, raw_ocr="forbidden",
            )

    def test_engine_has_no_device_model_or_runtime_execution_interface(self) -> None:
        source = inspect.getsource(PersonalLanguageKnowledgeEngine)
        for forbidden in (
            "MCPClient(", "call_tool(", "PlanExecutor(", "execute_", "launch_app(", "open_url(",
            "urllib.request", "cloud_model",
        ):
            self.assertNotIn(forbidden, source)
        self.assertFalse(hasattr(self.engine, "client"))
        self.assertFalse(hasattr(self.engine, "execute"))
        self.assertFalse(hasattr(self.engine, "plan"))

    def test_priority_is_bounded_and_deterministic(self) -> None:
        result = LanguagePriorityPolicy.evaluate(
            encounter_count=1000,
            user_confirmation_count=2,
            work_relevance=1000,
            difficulty=1000,
            mastery=0,
        )
        self.assertEqual(950, result["score"])
        self.assertEqual("HIGH", result["priority"])
        with self.assertRaises(PersonalLanguageIntelligencePolicyError):
            LanguagePriorityPolicy.evaluate(
                encounter_count=0, user_confirmation_count=0, work_relevance=1001, difficulty=0, mastery=0,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
