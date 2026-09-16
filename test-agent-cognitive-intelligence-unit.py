#!/usr/bin/env python3
"""Focused TEST-43 static coverage for bounded cognitive intelligence."""

from __future__ import annotations

import unittest

from phoneharness_agent import (
    CapabilityCatalog,
    CapabilityCompositionEngine,
    CapabilityDefinition,
    CapabilityDiscoveryEngine,
    CapabilityEvaluator,
    CapabilityEvidence,
    CapabilityConceptBinding,
    CognitiveConcept,
    CognitiveEvidence,
    CognitiveIntelligencePolicyError,
    CognitiveRelationship,
    ExperienceReinforcementAdvisor,
    PermissionDecision,
    SemanticCapabilityGraph,
    SkillEvolutionAdvisor,
    TechnologyRadarProposal,
)


READ_PERMISSION = PermissionDecision(
    True, ("approved",), "identity.test43", "ownership.test43", "consent.test43", "READ", None, "test-36.0"
)
CREATE_RULE_PERMISSION = PermissionDecision(
    True, ("approved",), "identity.test43", "ownership.test43", "consent.test43", "CREATE_RULE", None, "test-36.0"
)
DENIED_PERMISSION = PermissionDecision(
    False, ("default_deny",), "identity.test43", "ownership.test43", "consent.test43", "READ", None, "test-36.0"
)


class CognitiveIntelligenceTests(unittest.TestCase):
    @staticmethod
    def graph() -> SemanticCapabilityGraph:
        graph = SemanticCapabilityGraph()
        evidence = CognitiveEvidence(confirmation_count=1, verified_count=1, confidence=0.92, last_verified=100)
        for concept_id in ("concept.apple", "concept.fruit", "concept.food"):
            graph.register_concept(
                CognitiveConcept(
                    concept_id=concept_id,
                    domain="general",
                    concept_type="entity",
                    status="VALIDATED",
                    source_class="knowledge_confirmed",
                    source_ref="knowledge.general.v1",
                    confidence=0.92,
                    created_at=100,
                )
            )
        graph.register_relationship(
            CognitiveRelationship(
                relationship_id="relation.apple-fruit",
                subject_concept_id="concept.apple",
                relationship_type="is_a",
                object_concept_id="concept.fruit",
                domain="general",
                status="VALIDATED",
                source_class="knowledge_confirmed",
                source_ref="knowledge.general.v1",
                evidence=evidence,
                created_at=100,
            )
        )
        graph.register_relationship(
            CognitiveRelationship(
                relationship_id="relation.fruit-food",
                subject_concept_id="concept.fruit",
                relationship_type="is_a",
                object_concept_id="concept.food",
                domain="general",
                status="VALIDATED",
                source_class="knowledge_confirmed",
                source_ref="knowledge.general.v1",
                evidence=evidence,
                created_at=100,
            )
        )
        return graph

    @staticmethod
    def catalog() -> CapabilityCatalog:
        map_capability = CapabilityDefinition(
            capability_id="capability.travel.map",
            name="Travel map lookup",
            description="A metadata-only mapping capability.",
            version="1.0.0",
            source_type="native_capability_link",
            lifecycle="AVAILABLE",
            required_tools=frozenset(),
            required_permissions=(),
            risk_level="read_only",
            preconditions=(),
            verifier="observation.nonempty",
            dependencies=(),
            platform_support=("macos.host",),
        )
        flight_capability = CapabilityDefinition(
            capability_id="capability.travel.flight",
            name="Travel flight lookup",
            description="A metadata-only flight capability.",
            version="1.0.0",
            source_type="skill_package",
            lifecycle="AVAILABLE",
            required_tools=frozenset(),
            required_permissions=(),
            risk_level="read_only",
            preconditions=(),
            verifier="observation.nonempty",
            dependencies=("capability.travel.map",),
            platform_support=("macos.host",),
        )
        return CapabilityCatalog((map_capability, flight_capability))

    def evaluation(self) -> tuple[CapabilityCatalog, object]:
        catalog = self.catalog()
        evaluation = CapabilityEvaluator().evaluate(
            catalog,
            available_tools=(),
            available_permissions=(),
            available_platforms=("macos.host",),
        )
        return catalog, evaluation

    def test_semantic_taxonomy_expansion_is_validated_and_private(self) -> None:
        result = self.graph().expand_concept("concept.apple", permission=READ_PERMISSION)
        self.assertEqual("READY", result["status"])
        self.assertEqual(["concept.fruit", "concept.food"], result["concept_ids"])
        self.assertEqual("none", result["execution_authority"])
        self.assertNotIn("raw_content", result)

    def test_taxonomy_cycles_and_permission_bypass_are_rejected(self) -> None:
        graph = self.graph()
        result = graph.expand_concept("concept.apple", permission=DENIED_PERMISSION)
        self.assertEqual("BLOCKED", result["status"])
        with self.assertRaises(CognitiveIntelligencePolicyError):
            graph.register_relationship(
                CognitiveRelationship(
                    relationship_id="relation.food-apple",
                    subject_concept_id="concept.food",
                    relationship_type="is_a",
                    object_concept_id="concept.apple",
                    domain="general",
                    status="VALIDATED",
                    source_class="knowledge_confirmed",
                    source_ref="knowledge.general.v1",
                    evidence=CognitiveEvidence(1, 1, 0.91, 101),
                    created_at=101,
                )
            )

    def test_contextual_conflicts_require_confirmation(self) -> None:
        graph = self.graph()
        graph.register_concept(
            CognitiveConcept("concept.ftx", "shipping", "term", "VALIDATED", "teaching_confirmed", "teaching.ft.v1", 0.9, 100)
        )
        graph.register_concept(
            CognitiveConcept("concept.free-time", "shipping", "meaning", "VALIDATED", "teaching_confirmed", "teaching.ft.v1", 0.9, 100)
        )
        graph.register_concept(
            CognitiveConcept("concept.financial-tech", "shipping", "meaning", "VALIDATED", "teaching_confirmed", "teaching.ft.v1", 0.9, 100)
        )
        evidence = CognitiveEvidence(confirmation_count=1, verified_count=1, confidence=0.9, last_verified=100)
        for relation_id, object_id in (
            ("relation.ftx-free-time", "concept.free-time"),
            ("relation.ftx-financial-tech", "concept.financial-tech"),
        ):
            graph.register_relationship(
                CognitiveRelationship(
                    relation_id, "concept.ftx", "contextual_meaning", object_id, "shipping", "VALIDATED",
                    "teaching_confirmed", "teaching.ft.v1", evidence, 100
                )
            )
        result = graph.resolve_contextual_meaning("concept.ftx", domain="shipping", permission=READ_PERMISSION)
        self.assertEqual("NEEDS_CONFIRMATION", result["status"])
        self.assertEqual([], result["concept_ids"])

    def test_capability_discovery_only_returns_validated_semantic_bindings(self) -> None:
        graph = self.graph()
        graph.register_capability_binding(
            CapabilityConceptBinding(
                "binding.apple-map", "concept.apple", "capability.travel.map", "VALIDATED", "catalog.travel.v1",
                CognitiveEvidence(confirmation_count=1, verified_count=1, confidence=0.9, last_verified=100), 100
            )
        )
        catalog, evaluation = self.evaluation()
        result = CapabilityDiscoveryEngine().discover(
            graph, catalog, evaluation, concept_ids=("concept.apple",), permission=READ_PERMISSION
        )
        self.assertEqual("READY", result["status"])
        self.assertEqual(["capability.travel.map"], result["capability_ids"])
        self.assertEqual("none", result["execution_authority"])

    def test_composition_orders_dependencies_but_does_not_plan_or_execute(self) -> None:
        catalog, evaluation = self.evaluation()
        result = CapabilityCompositionEngine().compose(
            catalog, evaluation, task_class="travel.arrangement", capability_ids=("capability.travel.flight",), permission=READ_PERMISSION
        )
        self.assertEqual("READY", result["status"])
        self.assertEqual(["capability.travel.map", "capability.travel.flight"], result["ordered_capability_ids"])
        self.assertTrue(result["planner_must_select_final_skill"])
        self.assertTrue(result["risk_controller_must_authorize"])
        self.assertEqual("none", result["execution_authority"])

    def test_skill_evolution_remains_a_test32_recommendation(self) -> None:
        handoff = {
            "experience_ref": "experience.travel.demo",
            "experience_version": 1,
            "procedure_category": "travel.arrangement",
            "priority": "NORMAL",
            "confidence": 900,
            "evidence_count": 4,
            "requires_test32_validation": True,
            "capability_created": False,
            "automation_effect": "none",
        }
        result = SkillEvolutionAdvisor().recommend(handoff, permission=CREATE_RULE_PERMISSION)
        self.assertEqual("RECOMMEND_TEST32_GRADUATION", result["status"])
        self.assertFalse(result["skill_created"])
        self.assertFalse(result["skill_activated"])
        with self.assertRaises(CognitiveIntelligencePolicyError):
            SkillEvolutionAdvisor().recommend({**handoff, "raw_operation": "forbidden"}, permission=CREATE_RULE_PERMISSION)

    def test_experience_reinforcement_is_advisory_only_and_private(self) -> None:
        summary = {
            "experience_id": "experience.map.preference",
            "experience_type": "PREFERENCE",
            "state": "ACTIVE_ADVISORY",
            "confidence": 900,
            "frequency": {"observed_count": 5, "matching_outcome_count": 4},
            "confirmation_status": "CONFIRMED",
            "validation_status": "VERIFIED",
        }
        result = ExperienceReinforcementAdvisor().advise(summary, method_id="method.map.link", permission=READ_PERMISSION)
        self.assertEqual("ADVISORY", result["status"])
        self.assertFalse(result["method_selected"])
        self.assertEqual("advisory_only", result["decision_effect"])
        with self.assertRaises(CognitiveIntelligencePolicyError):
            ExperienceReinforcementAdvisor().advise({**summary, "raw_goal": "forbidden"}, method_id="method.map.link", permission=READ_PERMISSION)

    def test_technology_radar_is_a_human_approval_proposal_only(self) -> None:
        proposal = TechnologyRadarProposal(
            proposal_id="proposal.local-graph",
            source_class="framework",
            license_class="apache-2.0",
            recommendation="research_only",
            ios17_compatibility="host_only",
            roothide_compatibility="not_applicable",
            migration_cost="medium",
            security_impact="review_required",
            status="candidate",
        ).summary()
        self.assertTrue(proposal["requires_human_approval"])
        self.assertEqual("none", proposal["implementation_authority"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
