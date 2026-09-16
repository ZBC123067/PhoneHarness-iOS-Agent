#!/usr/bin/env python3
"""Static contract tests for TEST-35 Knowledge Retrieval & Context Engine.

All fixtures are synthetic and Mac-local. These tests never call MCP, read a
device screen, invoke a Planner, or create or execute an automation.
"""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from phoneharness_agent import (
    AnswerPreparation,
    DeterministicEntityAliasResolver,
    KnowledgeFact,
    KnowledgeFactProvenance,
    KnowledgeIntent,
    KnowledgeRetrievalContextEngine,
    KnowledgeRetrievalContextPolicyError,
    KnowledgeUnderstandingLayer,
    KnowledgeUnderstandingPolicyError,
    PersonalKnowledgeFoundation,
)


FORBIDDEN_KEYS = frozenset(
    {
        "goal", "plan", "screenshot", "coordinate", "coordinates", "rect", "ocr", "raw_ax",
        "raw_mcp_response", "input", "password", "private_message", "app_identity", "bundle_id",
        "path", "filename", "content_fingerprint", "knowledge_id", "entity_id", "source_artifact_id",
        "source", "source_type", "request", "request_text",
    }
)


def keys_in(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(keys_in(item) for item in value.values())) if value else set()
    if isinstance(value, (list, tuple)):
        return set().union(*(keys_in(item) for item in value)) if value else set()
    return set()


class KnowledgeRetrievalContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name) / "knowledge-v1"
        self.sources = Path(self.temporary_directory.name) / "sources"
        self.sources.mkdir()
        self.foundation = PersonalKnowledgeFoundation(self.root)
        self.layer = KnowledgeUnderstandingLayer(self.foundation)
        self.engine = KnowledgeRetrievalContextEngine(self.layer)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def source(self, name: str, payload: bytes) -> Path:
        path = self.sources / name
        path.write_bytes(payload)
        return path

    def import_rates(self, payload: bytes, *, imported_at: int = 100):
        artifact = self.foundation.import_file(
            self.source("rates.csv", payload),
            category="business",
            confidence=0.90,
            priority=2,
            confirmed_by_user=True,
            imported_at=imported_at,
        )
        self.assertEqual(
            "PUBLISHED",
            self.layer.understand(artifact, entity_type="rate", confirmed_by_user=True, processed_at=imported_at + 1).status,
        )
        return artifact

    def test_alias_resolution_returns_safe_rate_context_with_two_time_axes(self) -> None:
        self.import_rates(b"POL,POD,container,currency,amount\nMYBTU,CNSHA,20GP,USD,1200\n")

        result = self.engine.prepare("BTU -> Shanghai 20GP USD rate?", confirmed_by_user=True, queried_at=110)

        self.assertEqual("READY", result.status)
        self.assertEqual("rate_lookup", result.intent_kind)
        self.assertEqual(1, len(result.facts))
        fact = result.facts[0]
        self.assertEqual("1200", fact.fields["amount"])
        self.assertEqual("IMPORTED_DATA", fact.provenance.source_class)
        self.assertEqual("imported_data:v1", fact.provenance.source_reference)
        self.assertEqual({"from": 100, "until": None, "status": "current"}, fact.provenance.valid_time)
        self.assertEqual({"learned_at": 101, "last_verified": 101}, fact.provenance.knowledge_time)

    def test_alias_resolver_is_deterministic_and_does_not_fuzzy_match(self) -> None:
        resolver = DeterministicEntityAliasResolver()

        self.assertEqual("MYBTU", resolver.canonicalize("POL", "民都鲁"))
        self.assertEqual("MYBTU", resolver.canonicalize("POD", "BTU"))
        self.assertEqual("CNSHA", resolver.canonicalize("POD", "上海"))
        self.assertEqual("QINGDAO", resolver.canonicalize("POD", "青岛"))
        self.assertIsNone(resolver.canonicalize("POL", "Bintul"))
        self.assertIsNone(resolver.canonicalize("container", "20GP"))

    def test_qingdao_alias_supports_a_bounded_rate_query(self) -> None:
        self.import_rates(
            b"POL,POD,container,currency,amount\n"
            b"Bintulu,Qingdao,20GP,USD,1\n"
            b"Bintulu,Qingdao,40HQ,USD,2\n"
        )

        result = self.engine.prepare("民都鲁到青岛20GP报价", confirmed_by_user=True, queried_at=110)

        self.assertEqual("READY", result.status)
        self.assertEqual("MYBTU", result.facts[0].fields["POL"])
        self.assertEqual("QINGDAO", result.facts[0].fields["POD"])
        self.assertEqual("20GP", result.facts[0].fields["container"])

    def test_imported_port_names_are_canonicalized_for_chinese_rate_queries(self) -> None:
        self.import_rates(
            b"POL,POD,container,currency,amount\n"
            b"Bintulu,Shanghai,20GP,USD,1\n"
            b"Bintulu,Shanghai,40HQ,USD,2\n"
        )

        result = self.engine.prepare("民都鲁到上海20GP报价", confirmed_by_user=True, queried_at=110)

        self.assertEqual("READY", result.status)
        self.assertEqual("MYBTU", result.facts[0].fields["POL"])
        self.assertEqual("CNSHA", result.facts[0].fields["POD"])

    def test_missing_container_needs_clarification_without_guessing(self) -> None:
        self.import_rates(
            b"POL,POD,container,currency,amount\nMYBTU,CNSHA,20GP,USD,1200\nMYBTU,CNSHA,40HQ,USD,1800\n"
        )

        result = self.engine.prepare("BTU -> Shanghai rate?", confirmed_by_user=True, queried_at=110)

        self.assertEqual("NEEDS_CLARIFICATION", result.status)
        self.assertEqual((), result.facts)
        self.assertEqual(["container"], result.clarification["missing_dimensions"])
        self.assertEqual(["20GP", "40HQ"], result.clarification["available_values"]["container"])

    def test_unknown_intent_is_non_executable_and_does_not_retain_request_text(self) -> None:
        request = "this private wording is not a supported knowledge query"
        result = self.engine.prepare(request, confirmed_by_user=True, queried_at=110)
        summary = result.summary()

        self.assertEqual("NEEDS_CLARIFICATION", result.status)
        self.assertEqual((), result.facts)
        self.assertNotIn(request, str(summary))
        self.assertFalse(FORBIDDEN_KEYS.intersection(keys_in(summary)))

    def test_explicit_confirmation_is_required(self) -> None:
        with self.assertRaises(KnowledgeRetrievalContextPolicyError):
            self.engine.prepare("BTU -> Shanghai 20GP rate", confirmed_by_user=False, queried_at=110)

    def test_historical_source_version_is_retained_but_old_fact_is_not_current(self) -> None:
        artifact = self.import_rates(b"POL,POD,container,currency,amount\nMYBTU,CNSHA,20GP,USD,1200\n")
        updated = self.foundation.update_file(
            artifact.knowledge_id,
            self.source("rates-update.csv", b"POL,POD,container,currency,amount\nMYBTU,CNSHA,20GP,USD,1350\n"),
            confidence=0.95,
            priority=2,
            confirmed_by_user=True,
            imported_at=120,
        )
        self.assertEqual(
            "PUBLISHED",
            self.layer.understand(updated, entity_type="rate", confirmed_by_user=True, processed_at=121).status,
        )

        result = self.engine.prepare("BTU -> Shanghai 20GP USD rate", confirmed_by_user=True, queried_at=122)

        self.assertEqual("READY", result.status)
        self.assertEqual("1350", result.facts[0].fields["amount"])
        self.assertEqual("imported_data:v2", result.facts[0].provenance.source_reference)
        self.assertEqual(120, result.facts[0].provenance.valid_time["from"])
        self.assertEqual(121, result.facts[0].provenance.knowledge_time["learned_at"])
        records = self.layer._store.records("entities")
        self.assertEqual(2, len(records))
        self.assertEqual("1200", records[0]["attributes"]["amount"])

    def test_source_precedence_does_not_promote_owner_import_to_user_confirmed(self) -> None:
        self.import_rates(b"POL,POD,container,currency,amount\nMYBTU,CNSHA,20GP,USD,1200\n")
        imported = self.layer.query("rate", confirmed_by_user=True, queried_at=110)[0]
        official = replace(imported, source_type="official_data", version=2, last_verified=100)

        selected = self.engine._resolve_candidates((imported, official))
        output = self.engine._to_fact(imported, self._rate_profile())

        self.assertEqual((official,), selected)
        self.assertEqual("IMPORTED_DATA", output.provenance.source_class)
        self.assertNotEqual("USER_CONFIRMED", output.provenance.source_class)

    def test_same_precedence_same_identity_disagreement_is_conflicted(self) -> None:
        provenance = KnowledgeFactProvenance(
            "IMPORTED_DATA", "imported_data:v1", 0.90, "owner_confirmed", "current",
            {"from": 100, "until": None, "status": "current"}, {"learned_at": 101, "last_verified": 101},
        )
        first = KnowledgeFact("rate", {"POL": "MYBTU", "POD": "CNSHA", "container": "20GP", "currency": "USD", "amount": "1200"}, provenance)
        second = KnowledgeFact("rate", {"POL": "MYBTU", "POD": "CNSHA", "container": "20GP", "currency": "USD", "amount": "1300"}, provenance)

        self.assertEqual("CONFLICTED", self.engine._ambiguity_status((first, second), self._rate_profile()))

    def test_quarantined_semantic_conflict_blocks_matching_retrieval(self) -> None:
        self.import_rates(b"POL,POD,container,currency,amount\nMYBTU,QINGDAO,20GP,USD,1\n")
        conflicting = self.foundation.import_file(
            self.source("conflict.csv", b"POL,POD,container,currency,amount\nMYBTU,QINGDAO,20GP,USD,2\n"),
            category="business",
            confidence=0.90,
            priority=2,
            confirmed_by_user=True,
            imported_at=102,
        )
        result = self.layer.understand(conflicting, entity_type="rate", confirmed_by_user=True, processed_at=103)

        answer = self.engine.prepare("民都鲁到青岛20GP报价", confirmed_by_user=True, queried_at=110)

        self.assertEqual("CONFLICTED", result.status)
        self.assertEqual("CONFLICTED", answer.status)
        self.assertEqual((), answer.facts)

    def test_same_precedence_newer_verified_fact_wins_deterministically(self) -> None:
        self.import_rates(b"POL,POD,container,currency,amount\nMYBTU,CNSHA,20GP,USD,1200\n")
        older = self.layer.query("rate", confirmed_by_user=True, queried_at=110)[0]
        newer = replace(older, version=2, last_verified=120, knowledge_time=120)

        selected = self.engine._resolve_candidates((older, newer), self._rate_profile())

        self.assertEqual((newer,), selected)

    def test_declared_relationship_query_is_bounded_and_exact(self) -> None:
        self.import_rates(b"POL,POD,container,currency,amount\nMYBTU,CNSHA,20GP,USD,1200\n")

        matches = self.layer.query_declared_relationship(
            "rate",
            relationship_type="rate_applies_to_route",
            object_kind="route",
            object_value="MYBTU>CNSHA",
            confirmed_by_user=True,
            queried_at=110,
        )

        self.assertEqual(1, len(matches))
        with self.assertRaises(KnowledgeUnderstandingPolicyError):
            self.layer.query_declared_relationship(
                "rate",
                relationship_type="unbounded_traversal",
                object_kind="route",
                object_value="MYBTU>CNSHA",
                confirmed_by_user=True,
                queried_at=110,
            )

    def test_schedule_and_customer_profiles_are_read_only_context_only(self) -> None:
        schedule = self.foundation.import_file(
            self.source("schedule.json", b'{"schedules":[{"vessel":"North Star","voyage":"ns001","POL":"MYBTU","POD":"CNSHA","ETD":"2026-09-01","ETA":"2026-09-05"}]}'),
            category="business", confidence=0.90, priority=2, confirmed_by_user=True, imported_at=100,
        )
        customer = self.foundation.import_file(
            self.source("customer.json", b'{"company":"Example Logistics","preference":"weekly update","language":"en","communication_style":"concise"}'),
            category="customer", confidence=0.90, priority=2, confirmed_by_user=True, imported_at=101,
        )
        self.layer.understand(schedule, entity_type="schedule", confirmed_by_user=True, processed_at=102)
        self.layer.understand(customer, entity_type="customer", confirmed_by_user=True, processed_at=103)

        schedule_result = self.engine.prepare_intent(
            KnowledgeIntent("schedule_lookup", {"POL": "BTU", "POD": "SHA"}), confirmed_by_user=True, queried_at=110
        )
        customer_result = self.engine.prepare_intent(
            KnowledgeIntent("customer_communication_assistance", {"company": "Example Logistics"}),
            confirmed_by_user=True, queried_at=110,
        )

        self.assertEqual("READY", schedule_result.status)
        self.assertEqual({"vessel", "voyage", "POL", "POD", "ETD", "ETA"}, set(schedule_result.facts[0].fields))
        self.assertFalse(schedule_result.requires_user_review)
        self.assertEqual("READY", customer_result.status)
        self.assertTrue(customer_result.requires_user_review)
        self.assertEqual({"company", "preference", "language", "communication_style"}, set(customer_result.facts[0].fields))

    def test_answer_preparation_schema_is_private_and_non_executable(self) -> None:
        self.import_rates(b"POL,POD,container,currency,amount\nMYBTU,CNSHA,20GP,USD,1200\n")
        result = self.engine.prepare("BTU -> Shanghai 20GP USD rate", confirmed_by_user=True, queried_at=110)
        summary = result.summary()

        self.assertIsInstance(result, AnswerPreparation)
        self.assertFalse(FORBIDDEN_KEYS.intersection(keys_in(summary)))
        self.assertEqual("none", summary["automation_effect"])
        self.assertEqual("none", summary["planner_access"])
        self.assertEqual("none", summary["mcp_access"])
        self.assertEqual("none", summary["memory_write"])

    @staticmethod
    def _rate_profile() -> dict[str, object]:
        from phoneharness_agent import KnowledgeRequirementsCatalog

        return KnowledgeRequirementsCatalog.profile("rate_lookup")


if __name__ == "__main__":
    unittest.main()
