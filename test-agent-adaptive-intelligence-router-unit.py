#!/usr/bin/env python3
"""Static contract tests for TEST-30 Adaptive Intelligence Router.

These tests prove that the Router only ranks sanitized metadata.  They never
contact the iPhone, run a model, or invoke any action-capable runtime layer.
"""

from __future__ import annotations

import inspect
import json
import unittest

from phoneharness_agent import (
    ADAPTIVE_INTELLIGENCE_SOURCES,
    AdaptiveIntelligenceRouter,
    AdaptiveIntelligenceRouterError,
    CapabilityEvidence,
    IntelligenceRoutingRequest,
    IntelligenceSourceProfile,
    SolutionEvaluation,
    SolutionEvaluationPolicy,
)


FORBIDDEN_KEYS = frozenset(
    {
        "goal",
        "app",
        "bundle_id",
        "ui",
        "coordinate",
        "rect",
        "screenshot",
        "ocr",
        "input",
        "clipboard",
        "password",
        "token",
        "prompt",
        "raw_mcp",
        "response",
        "plan",
        "action",
    }
)


def verified_evidence() -> CapabilityEvidence:
    return CapabilityEvidence(success_count=3, failure_count=0, confidence=0.90, last_verified=100)


def profile(
    source: str,
    *,
    available: bool = True,
    predicted_success: float = 0.80,
    latency_class: str = "standard",
    cost_class: str = "low",
    evidence: CapabilityEvidence | None = None,
) -> IntelligenceSourceProfile:
    return IntelligenceSourceProfile(
        source=source,
        available=available,
        predicted_success=predicted_success,
        latency_class=latency_class,
        cost_class=cost_class,
        evidence=CapabilityEvidence() if evidence is None else evidence,
    )


def recommended_solution() -> SolutionEvaluation:
    return SolutionEvaluation(
        status="recommended",
        policy=SolutionEvaluationPolicy(),
        candidates=(),
        recommended_capability_id="capability.test.safe",
        recommendation_reason_codes=("test_only",),
    )


def unresolved_solution() -> SolutionEvaluation:
    return SolutionEvaluation(
        status="no_eligible_candidates",
        policy=SolutionEvaluationPolicy(),
        candidates=(),
        recommended_capability_id=None,
        recommendation_reason_codes=("test_only",),
    )


def request(
    profiles: tuple[IntelligenceSourceProfile, ...],
    *,
    confidence: float = 0.90,
    privacy_class: str = "cloud_approved",
    risk_level: str = "read_only",
    repeatability: str = "unlikely",
    trust_tier: str = "low",
    preference: str = "experience_first",
    teaching_available: bool = False,
) -> IntelligenceRoutingRequest:
    return IntelligenceRoutingRequest(
        task_complexity="medium",
        aggregate_confidence=confidence,
        risk_level=risk_level,
        task_repeatability=repeatability,
        privacy_class=privacy_class,
        trust_tier=trust_tier,
        preference=preference,
        teaching_available=teaching_available,
        source_profiles=profiles,
    )


def keys_in(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(keys_in(item) for item in value.values())) if value else set()
    if isinstance(value, (list, tuple)):
        return set().union(*(keys_in(item) for item in value)) if value else set()
    return set()


class AdaptiveIntelligenceRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = AdaptiveIntelligenceRouter()

    def test_all_supported_sources_are_finite_and_explicit(self) -> None:
        self.assertEqual(
            {
                "deterministic_capability",
                "native_shortcut",
                "learned_workflow",
                "learned_skill",
                "local_model",
                "hybrid_model",
                "cloud_model",
                "human_teaching_request",
            },
            set(ADAPTIVE_INTELLIGENCE_SOURCES),
        )

    def test_verified_deterministic_capability_wins_a_materially_equivalent_choice(self) -> None:
        result = self.router.recommend(
            recommended_solution(),
            request(
                (
                    profile(
                        "deterministic_capability",
                        predicted_success=0.92,
                        latency_class="fast",
                        cost_class="none",
                        evidence=verified_evidence(),
                    ),
                    profile("cloud_model", predicted_success=0.95, latency_class="slow", cost_class="high"),
                )
            ),
        ).summary()
        self.assertEqual("recommended", result["status"])
        self.assertEqual("deterministic_capability", result["recommended_source"])
        self.assertEqual("cloud_model", result["fallback_source"])
        self.assertIn("deterministic_evidence_verified", result["reason_codes"])
        self.assertFalse(result["requires_confirmation"])

    def test_higher_predicted_success_beats_lower_cost(self) -> None:
        result = self.router.recommend(
            recommended_solution(),
            request(
                (
                    profile("local_model", predicted_success=0.76, latency_class="fast", cost_class="none"),
                    profile("cloud_model", predicted_success=0.90, latency_class="slow", cost_class="high"),
                )
            ),
        ).summary()
        self.assertEqual("cloud_model", result["recommended_source"])
        self.assertEqual("cloud_minimum_context", result["privacy_boundary"])

    def test_low_confidence_repeatable_unknown_path_recommends_human_teaching(self) -> None:
        result = self.router.recommend(
            unresolved_solution(),
            request(
                (
                    profile("local_model", predicted_success=0.45),
                    profile("human_teaching_request", predicted_success=1.0, cost_class="none"),
                ),
                confidence=0.40,
                repeatability="likely",
                teaching_available=True,
            ),
        ).summary()
        self.assertEqual("needs_human_teaching", result["status"])
        self.assertEqual("human_teaching_request", result["recommended_source"])
        self.assertEqual("local_model", result["fallback_source"])
        self.assertIn("low_confidence", result["reason_codes"])
        self.assertIn("task_repeatable", result["reason_codes"])
        self.assertTrue(result["requires_confirmation"])

    def test_cloud_paths_are_rejected_without_cloud_approval(self) -> None:
        result = self.router.recommend(
            unresolved_solution(),
            request(
                (profile("cloud_model", predicted_success=0.95),),
                privacy_class="sensitive",
            ),
        ).summary()
        self.assertEqual("blocked", result["status"])
        self.assertIsNone(result["recommended_source"])
        self.assertEqual(["privacy_cloud_blocked"], result["reason_codes"])

    def test_learned_sources_require_verified_aggregate_evidence(self) -> None:
        result = self.router.recommend(
            recommended_solution(),
            request(
                (
                    profile("learned_skill", predicted_success=0.99),
                    profile("local_model", predicted_success=0.80),
                )
            ),
        ).summary()
        self.assertEqual("local_model", result["recommended_source"])

    def test_learned_source_can_be_selected_after_verified_evidence(self) -> None:
        result = self.router.recommend(
            recommended_solution(),
            request(
                (
                    profile("learned_workflow", predicted_success=0.92, evidence=verified_evidence()),
                    profile("local_model", predicted_success=0.80),
                )
            ),
        ).summary()
        self.assertEqual("learned_workflow", result["recommended_source"])
        self.assertIn("learned_evidence_verified", result["reason_codes"])

    def test_trust_tier_only_signals_confirmation_and_critical_fails_closed(self) -> None:
        medium = self.router.recommend(
            recommended_solution(),
            request(
                (profile("local_model", predicted_success=0.85),),
                trust_tier="medium",
            ),
        ).summary()
        self.assertEqual("recommended", medium["status"])
        self.assertTrue(medium["requires_confirmation"])

        critical = self.router.recommend(
            recommended_solution(),
            request(
                (profile("local_model", predicted_success=0.85),),
                trust_tier="critical",
            ),
        ).summary()
        self.assertEqual("blocked", critical["status"])
        self.assertIsNone(critical["recommended_source"])
        self.assertEqual(["critical_action_blocked"], critical["reason_codes"])

    def test_invalid_metadata_and_duplicate_sources_are_rejected(self) -> None:
        with self.assertRaises(AdaptiveIntelligenceRouterError):
            profile("unsupported_source")
        with self.assertRaises(AdaptiveIntelligenceRouterError):
            request((profile("local_model"), profile("local_model")))
        with self.assertRaises(AdaptiveIntelligenceRouterError):
            request((profile("local_model"),), privacy_class="raw_screen_data")
        with self.assertRaises(AdaptiveIntelligenceRouterError):
            self.router.recommend({"status": "recommended"}, request((profile("local_model"),)))  # type: ignore[arg-type]

    def test_public_contract_contains_only_safe_recommendation_metadata(self) -> None:
        summary = self.router.recommend(
            recommended_solution(),
            request((profile("local_model", predicted_success=0.85),)),
        ).summary()
        self.assertEqual(
            {
                "adaptive_intelligence_router_version",
                "status",
                "recommended_source",
                "confidence",
                "reason_codes",
                "fallback_source",
                "requires_confirmation",
                "privacy_boundary",
            },
            set(summary),
        )
        self.assertFalse(FORBIDDEN_KEYS.intersection(keys_in(summary)))
        self.assertNotIn("hello123", json.dumps(summary, ensure_ascii=False))

    def test_router_exposes_no_runtime_or_action_interface(self) -> None:
        for forbidden_name in (
            "client",
            "plan",
            "select",
            "execute",
            "verify",
            "call_tool",
            "run_model",
            "run_shortcut",
            "run_workflow",
        ):
            self.assertFalse(hasattr(self.router, forbidden_name), forbidden_name)
        source = inspect.getsource(AdaptiveIntelligenceRouter)
        for forbidden_reference in ("MCPClient", "DynamicPlanner", "RiskController", "PlanExecutor", "Verifier"):
            self.assertNotIn(forbidden_reference, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
