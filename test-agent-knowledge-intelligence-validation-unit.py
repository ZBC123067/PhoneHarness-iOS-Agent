#!/usr/bin/env python3
"""Static contract tests for TEST-35.6 Knowledge Intelligence Validation.

Fixtures intentionally use synthetic, domain-neutral names. They never call
MCP, invoke an action layer, retain document rows, or read an owner dataset.
"""

from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from phoneharness_agent import (
    CandidateSchemaEvidence,
    DomainDetectionEvidence,
    ExtractedEntityEvidence,
    ExtractedRelationshipEvidence,
    KnowledgeFixturePackContractValidator,
    KnowledgeIntelligenceValidationFramework,
    KnowledgeValidationEvidence,
    KnowledgeValidationExpectation,
    KnowledgeValidationOutcome,
    SafeProvenanceEvidence,
    VersionTimelineEvidence,
)


FORBIDDEN_KEYS = frozenset(
    {
        "goal", "plan", "screenshot", "coordinate", "coordinates", "rect", "ocr", "raw_ax",
        "raw_mcp_response", "input", "password", "private_message", "source_path", "filename",
        "document_text", "row_values", "app_identity", "bundle_id",
    }
)


def keys_in(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(keys_in(item) for item in value.values())) if value else set()
    if isinstance(value, (tuple, list)):
        return set().union(*(keys_in(item) for item in value)) if value else set()
    return set()


class KnowledgeIntelligenceValidationFrameworkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.framework = KnowledgeIntelligenceValidationFramework()

    @staticmethod
    def provenance(version: int = 1, *, valid_from: int = 100, valid_until: int | None = None) -> SafeProvenanceEvidence:
        return SafeProvenanceEvidence(
            source_class="IMPORTED_DATA",
            source_reference="imported_data:v%d" % version,
            authority="owner_confirmed",
            confidence=0.90,
            valid_from=valid_from,
            valid_until=valid_until,
            knowledge_time=valid_from + 1,
            last_verified=valid_from + 2,
            version=version,
        )

    def known_evidence(self) -> KnowledgeValidationEvidence:
        schema = CandidateSchemaEvidence(
            status="ACTIVE",
            version=1,
            confidence=0.92,
            requires_owner_confirmation=False,
            entity_types=("RecordAlpha", "RecordBeta"),
            relationship_types=("alpha_relates_to_beta",),
        )
        entities = (
            ExtractedEntityEvidence("entity-alpha-01", "RecordAlpha", ("origin", "amount"), self.provenance()),
            ExtractedEntityEvidence("entity-beta-01", "RecordBeta", ("category", "validity"), self.provenance()),
        )
        relationships = (
            ExtractedRelationshipEvidence(
                "relationship-01", "alpha_relates_to_beta", "RecordAlpha", "RecordBeta", self.provenance()
            ),
        )
        return KnowledgeValidationEvidence(
            domain=DomainDetectionEvidence("KNOWN", 0.92, False),
            schema=schema,
            entities=entities,
            relationships=relationships,
            timelines=(),
            outcome=KnowledgeValidationOutcome("READY", 2, (), 0),
        )

    @staticmethod
    def known_expectation() -> KnowledgeValidationExpectation:
        return KnowledgeValidationExpectation(
            expected_domain_status="KNOWN",
            expected_schema_status="ACTIVE",
            requires_owner_confirmation=False,
            required_entity_types=("RecordAlpha", "RecordBeta"),
            minimum_entity_counts={"RecordAlpha": 1, "RecordBeta": 1},
            required_relationship_types=("alpha_relates_to_beta",),
            expected_outcome_status="READY",
            require_provenance=True,
        )

    def test_domain_agnostic_known_schema_entity_and_relationship_contract_passes(self) -> None:
        report = self.framework.evaluate(self.known_evidence(), self.known_expectation())

        self.assertEqual("PASS", report.status)
        self.assertEqual(8, len(report.passed_checks))
        self.assertEqual((), report.failure_codes)
        self.assertFalse(FORBIDDEN_KEYS.intersection(keys_in(report.summary())))

    def test_unknown_domain_is_safe_only_as_a_confirmable_candidate(self) -> None:
        evidence = KnowledgeValidationEvidence(
            domain=DomainDetectionEvidence("UNKNOWN", 0.44, True),
            schema=CandidateSchemaEvidence("CANDIDATE", 1, 0.44, True, ("RecordGamma",), ()),
            entities=(),
            relationships=(),
            timelines=(),
            outcome=KnowledgeValidationOutcome("NEEDS_CONFIRMATION", 0, (), 0),
        )
        expectation = KnowledgeValidationExpectation(
            expected_domain_status="UNKNOWN",
            expected_schema_status="CANDIDATE",
            requires_owner_confirmation=True,
            required_entity_types=("RecordGamma",),
            minimum_entity_counts={},
            required_relationship_types=(),
            expected_outcome_status="NEEDS_CONFIRMATION",
        )

        report = self.framework.evaluate(evidence, expectation)

        self.assertEqual("PASS", report.status)
        self.assertIn("candidate_schema", report.passed_checks)

    def test_unknown_domain_cannot_auto_activate_or_publish_entities(self) -> None:
        evidence = KnowledgeValidationEvidence(
            domain=DomainDetectionEvidence("UNKNOWN", 0.44, False),
            schema=CandidateSchemaEvidence("ACTIVE", 1, 0.44, False, ("RecordGamma",), ()),
            entities=(ExtractedEntityEvidence("entity-gamma-01", "RecordGamma", ("field",), self.provenance()),),
            relationships=(),
            timelines=(),
            outcome=KnowledgeValidationOutcome("READY", 1, (), 0),
        )
        expectation = KnowledgeValidationExpectation(
            expected_domain_status="UNKNOWN",
            expected_schema_status="CANDIDATE",
            requires_owner_confirmation=True,
            required_entity_types=("RecordGamma",),
            minimum_entity_counts={},
            required_relationship_types=(),
            expected_outcome_status="NEEDS_CONFIRMATION",
        )

        report = self.framework.evaluate(evidence, expectation)

        self.assertEqual("FAIL", report.status)
        self.assertIn("unknown_domain_requires_non_active_candidate", report.failure_codes)

    def test_invalid_provenance_is_rejected_without_exposing_source_data(self) -> None:
        invalid = SafeProvenanceEvidence(
            "IMPORTED_DATA", "/private/source.csv", "owner_confirmed", 0.90, 100, None, 101, 102, 1
        )
        evidence = self.known_evidence()
        evidence = KnowledgeValidationEvidence(
            evidence.domain,
            evidence.schema,
            (ExtractedEntityEvidence("entity-alpha-01", "RecordAlpha", ("origin",), invalid),),
            (),
            (),
            KnowledgeValidationOutcome("READY", 1, (), 0),
        )
        expectation = KnowledgeValidationExpectation(
            expected_domain_status="KNOWN",
            expected_schema_status="ACTIVE",
            requires_owner_confirmation=False,
            required_entity_types=("RecordAlpha",),
            minimum_entity_counts={"RecordAlpha": 1},
            required_relationship_types=(),
            expected_outcome_status="READY",
            require_provenance=True,
        )

        report = self.framework.evaluate(evidence, expectation)

        self.assertEqual("FAIL", report.status)
        self.assertIn("provenance_metadata_is_invalid", report.failure_codes)
        self.assertNotIn("/private/source.csv", json.dumps(report.summary()))

    def test_version_timeline_requires_preserved_history_and_valid_time_order(self) -> None:
        timeline = VersionTimelineEvidence(
            "logical-record-01",
            (
                self.provenance(1, valid_from=100, valid_until=119),
                self.provenance(2, valid_from=120),
            ),
        )
        evidence = self.known_evidence()
        evidence = KnowledgeValidationEvidence(
            evidence.domain, evidence.schema, evidence.entities, evidence.relationships, (timeline,), evidence.outcome
        )
        expectation = KnowledgeValidationExpectation(
            expected_domain_status="KNOWN",
            expected_schema_status="ACTIVE",
            requires_owner_confirmation=False,
            required_entity_types=("RecordAlpha", "RecordBeta"),
            minimum_entity_counts={"RecordAlpha": 1, "RecordBeta": 1},
            required_relationship_types=("alpha_relates_to_beta",),
            expected_outcome_status="READY",
            require_provenance=True,
            require_version_history=True,
        )

        report = self.framework.evaluate(evidence, expectation)

        self.assertEqual("PASS", report.status)
        self.assertIn("version_and_time", report.passed_checks)

    def test_same_priority_conflict_requires_no_selected_entity(self) -> None:
        evidence = self.known_evidence()
        evidence = KnowledgeValidationEvidence(
            evidence.domain,
            evidence.schema,
            evidence.entities,
            evidence.relationships,
            (),
            KnowledgeValidationOutcome("CONFLICTED", 0, (), 1),
        )
        expectation = KnowledgeValidationExpectation(
            expected_domain_status="KNOWN",
            expected_schema_status="ACTIVE",
            requires_owner_confirmation=False,
            required_entity_types=("RecordAlpha", "RecordBeta"),
            minimum_entity_counts={"RecordAlpha": 1, "RecordBeta": 1},
            required_relationship_types=("alpha_relates_to_beta",),
            expected_outcome_status="CONFLICTED",
            expect_unresolved_conflict=True,
        )

        report = self.framework.evaluate(evidence, expectation)

        self.assertEqual("PASS", report.status)
        self.assertIn("conflict_handling", report.passed_checks)

    def test_missing_dimension_requires_clarification_and_no_fact_selection(self) -> None:
        evidence = self.known_evidence()
        evidence = KnowledgeValidationEvidence(
            evidence.domain,
            evidence.schema,
            evidence.entities,
            evidence.relationships,
            (),
            KnowledgeValidationOutcome("NEEDS_CLARIFICATION", 0, ("dimension_beta",), 0),
        )
        expectation = KnowledgeValidationExpectation(
            expected_domain_status="KNOWN",
            expected_schema_status="ACTIVE",
            requires_owner_confirmation=False,
            required_entity_types=("RecordAlpha", "RecordBeta"),
            minimum_entity_counts={"RecordAlpha": 1, "RecordBeta": 1},
            required_relationship_types=("alpha_relates_to_beta",),
            expected_outcome_status="NEEDS_CLARIFICATION",
            clarification_dimensions=("dimension_beta",),
        )

        report = self.framework.evaluate(evidence, expectation)

        self.assertEqual("PASS", report.status)
        self.assertIn("clarification", report.passed_checks)

    def test_fixture_pack_contract_is_generic_and_reports_only_safe_counts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pack = Path(directory) / "fixture-pack.zip"
            expected = {
                "test_objective": "fixture validation",
                "domains": {
                    "domain_one": {"expected_entities": ["RecordAlpha"]},
                    "domain_two": {"expected_behavior": ["request confirmation"]},
                },
                "principles": ["private first"],
            }
            with zipfile.ZipFile(pack, "w") as archive:
                archive.writestr("expected_schema.json", json.dumps(expected))
                archive.writestr("test_cases.md", "generic fixture")
                archive.writestr("one.csv", "first,second\na,b\n")
                archive.writestr("two.csv", "third,fourth\nc,d\n")

            report = KnowledgeFixturePackContractValidator().inspect(pack)

        self.assertEqual("FIXTURE_CONTRACT_PASS", report.status)
        self.assertEqual(2, report.domain_fixture_count)
        self.assertEqual(2, report.tabular_fixture_count)
        self.assertEqual("NOT_EXECUTED", report.runtime_execution)
        self.assertFalse(FORBIDDEN_KEYS.intersection(keys_in(report.summary())))


if __name__ == "__main__":
    unittest.main(verbosity=2)
