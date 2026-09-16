#!/usr/bin/env python3
"""Static boundary tests for TEST-27 Solution Evaluation Layer.

These tests never contact an iPhone.  They prove that TEST-27 receives only
TEST-26 candidate metadata and returns transparent advisory scores.
"""

from __future__ import annotations

import json
import unittest

from phoneharness_agent import (
    DEFAULT_SKILL_PERMISSIONS,
    DEFAULT_SKILL_PLATFORMS,
    CapabilityCatalog,
    CapabilityDefinition,
    CapabilityEvaluator,
    CapabilityEvidence,
    CapabilityIntelligenceLayer,
    SkillRegistry,
    SolutionEvaluationError,
    SolutionEvaluationLayer,
    SolutionEvaluationPolicy,
    SolutionEvaluator,
)


TOOLS = frozenset({"describe_screen", "tap_element", "input_text", "type_text", "press_key"})
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
        "raw_mcp_response",
        "raw_response",
        "plan",
        "action",
    }
)


def capability(
    suffix: str,
    *,
    source_type: str = "skill_package",
    lifecycle: str = "DISCOVERED",
    required_tools: frozenset[str] = frozenset({"describe_screen"}),
    risk_level: str = "read_only",
    dependencies: tuple[str, ...] = (),
    evidence: CapabilityEvidence | None = None,
) -> CapabilityDefinition:
    return CapabilityDefinition(
        capability_id="capability.solution.%s" % suffix,
        name="solution_%s" % suffix,
        description="Declarative TEST-27 candidate with no task or UI data.",
        version="1.0.0",
        source_type=source_type,
        lifecycle=lifecycle,
        required_tools=required_tools,
        required_permissions=("mcp.read_screen",),
        risk_level=risk_level,
        preconditions=("fresh_observation",),
        verifier="observation_nonempty",
        dependencies=dependencies,
        platform_support=("macos_host", "ios_mcp"),
        evidence=CapabilityEvidence() if evidence is None else evidence,
    )


def evaluate_catalog(catalog: CapabilityCatalog):
    return CapabilityEvaluator().evaluate(
        catalog,
        available_tools=TOOLS,
        available_permissions=DEFAULT_SKILL_PERMISSIONS,
        available_platforms=DEFAULT_SKILL_PLATFORMS,
    )


def keys_in(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(keys_in(item) for item in value.values())) if value else set()
    if isinstance(value, (list, tuple)):
        return set().union(*(keys_in(item) for item in value)) if value else set()
    return set()


class SolutionEvaluationTests(unittest.TestCase):
    def test_existing_skill_capabilities_are_scored_without_selecting_tools(self) -> None:
        capability_evaluation = CapabilityIntelligenceLayer.from_skill_registry(SkillRegistry()).evaluate_candidates(
            available_tools=TOOLS
        )
        result = SolutionEvaluationLayer().evaluate_candidates(capability_evaluation).summary()
        self.assertEqual("recommended", result["status"])
        self.assertEqual("capability.screen.observe.v1", result["recommendation"]["capability_id"])
        self.assertEqual(5, result["candidate_count"])
        self.assertEqual(3, result["eligible_candidate_count"])
        self.assertTrue(result["recommendation"]["requires_risk_controller"])
        self.assertTrue(result["recommendation"]["requires_verifier"])

    def test_policy_exposes_all_weights_scales_and_downstream_gates(self) -> None:
        summary = SolutionEvaluationPolicy().summary()
        self.assertEqual(
            {"lifecycle", "evidence", "source", "simplicity", "risk_exposure"},
            set(summary["weights"]),
        )
        self.assertEqual(1.0, sum(summary["weights"].values()))
        self.assertEqual(
            {"lifecycle", "source_type", "risk_level"},
            set(summary["score_scales"]),
        )
        self.assertTrue(all(summary["downstream_gates"].values()))

    def test_ineligible_candidates_are_reported_but_never_scored_or_recommended(self) -> None:
        catalog = CapabilityCatalog((capability("missing", required_tools=frozenset({"not_available"})),))
        result = SolutionEvaluator().evaluate(evaluate_catalog(catalog)).summary()
        self.assertEqual("no_eligible_candidates", result["status"])
        candidate_summary = result["candidates"][0]
        self.assertIsNone(candidate_summary["score"])
        self.assertIsNone(candidate_summary["rank"])
        self.assertIn("ineligible_capability", candidate_summary["reason_codes"])
        self.assertIsNone(result["recommendation"])

    def test_equal_candidates_fail_closed_as_ambiguous(self) -> None:
        catalog = CapabilityCatalog((capability("tieone"), capability("tietwo")))
        result = SolutionEvaluator().evaluate(evaluate_catalog(catalog)).summary()
        self.assertEqual("ambiguous", result["status"])
        self.assertIsNone(result["recommendation"])
        self.assertEqual([1, 2], [candidate["rank"] for candidate in result["candidates"]])

    def test_aggregate_evidence_changes_score_without_exposing_task_data(self) -> None:
        verified = capability(
            "verified",
            lifecycle="VERIFIED",
            evidence=CapabilityEvidence(success_count=3, failure_count=0, confidence=0.9, last_verified=100),
        )
        catalog = CapabilityCatalog((capability("baseline"), verified))
        result = SolutionEvaluator().evaluate(evaluate_catalog(catalog)).summary()
        self.assertEqual("capability.solution.verified", result["recommendation"]["capability_id"])
        selected = result["candidates"][0]
        self.assertGreater(selected["score_components"]["evidence"], 0.5)
        self.assertIn("evidence_aggregate_verified", selected["reason_codes"])

    def test_contract_simplicity_is_explicit_and_never_an_execution_instruction(self) -> None:
        base = capability("base")
        dependent = capability("dependent", dependencies=(base.capability_id,))
        catalog = CapabilityCatalog((base, dependent))
        result = SolutionEvaluator().evaluate(evaluate_catalog(catalog)).summary()
        self.assertEqual("capability.solution.base", result["recommendation"]["capability_id"])
        self.assertGreater(result["candidates"][0]["score_components"]["simplicity"], result["candidates"][1]["score_components"]["simplicity"])
        self.assertTrue(result["candidates"][0]["requires_downstream_planner"])
        self.assertTrue(result["candidates"][0]["requires_executor"])

    def test_risk_exposure_is_scored_but_not_approved(self) -> None:
        read_only = capability("readonly")
        interactive = capability("interaction", risk_level="interaction")
        catalog = CapabilityCatalog((read_only, interactive))
        result = SolutionEvaluator().evaluate(evaluate_catalog(catalog)).summary()
        self.assertEqual("capability.solution.readonly", result["recommendation"]["capability_id"])
        self.assertIn("risk_read_only_requires_downstream_assessment", result["candidates"][0]["reason_codes"])
        self.assertTrue(result["recommendation"]["requires_risk_controller"])

    def test_invalid_policy_and_non_capability_input_are_rejected(self) -> None:
        with self.assertRaises(SolutionEvaluationError):
            SolutionEvaluationPolicy(lifecycle_weight=0.4)
        with self.assertRaises(SolutionEvaluationError):
            SolutionEvaluationPolicy(tie_epsilon=-0.01)
        with self.assertRaises(SolutionEvaluationError):
            SolutionEvaluator().evaluate({"candidates": []})  # type: ignore[arg-type]

    def test_serialized_result_contains_no_raw_observation_or_task_data(self) -> None:
        capability_evaluation = CapabilityIntelligenceLayer.from_skill_registry(SkillRegistry()).evaluate_candidates(
            available_tools=TOOLS
        )
        summary = SolutionEvaluationLayer().evaluate_candidates(capability_evaluation).summary()
        self.assertFalse(FORBIDDEN_KEYS.intersection(keys_in(summary)))
        serialized = json.dumps(summary, ensure_ascii=False)
        self.assertNotIn("raw_mcp_response", serialized)
        self.assertNotIn("screenshot", serialized)

    def test_layer_has_no_runtime_or_execution_interface(self) -> None:
        layer = SolutionEvaluationLayer()
        for forbidden_name in ("client", "plan", "select", "execute", "verify", "assess", "call_tool"):
            self.assertFalse(hasattr(layer, forbidden_name), forbidden_name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
