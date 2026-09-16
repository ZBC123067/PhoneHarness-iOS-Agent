#!/usr/bin/env python3
"""Static, metadata-only contracts for TEST-41 Intelligence Orchestration.

The suite exercises no MCP client, model provider, App Intent, Shortcut, iOS
device, persistent store, Planner, Risk Controller, Executor, or Verifier.
"""

from __future__ import annotations

import inspect
import json
import unittest

from phoneharness_agent import (
    CapabilityCatalog,
    CapabilityDefinition,
    CapabilityEvaluator,
    CapabilityEvidence,
    CapabilityMethodDefinition,
    CapabilityMethodRegistry,
    IntelligenceCapabilityProfile,
    IntelligenceOrchestrationLayer,
    IntelligenceOrchestrationRequest,
    PermissionDecision,
    SkillAdvisoryProfile,
    SkillManifest,
    TaskClassifier,
    TokenBudgetPolicy,
)


FORBIDDEN_KEYS = frozenset(
    {
        "goal",
        "query",
        "prompt",
        "document",
        "content",
        "screenshot",
        "ocr",
        "coordinate",
        "rect",
        "ui",
        "password",
        "token",
        "raw_mcp",
        "response",
        "action",
    }
)


def verified_evidence() -> CapabilityEvidence:
    return CapabilityEvidence(success_count=8, failure_count=1, confidence=0.91, last_verified=100)


def catalog() -> CapabilityCatalog:
    return CapabilityCatalog(
        (
            CapabilityDefinition(
                capability_id="capability.generic.search.v1",
                name="generic_search",
                description="generic_search_capability",
                version="1.0.0",
                source_type="skill_package",
                lifecycle="PREFERRED",
                required_tools=frozenset(),
                required_permissions=("permission.generic",),
                risk_level="interaction",
                preconditions=(),
                verifier="result_visible",
                dependencies=(),
                platform_support=("macos_host",),
                evidence=verified_evidence(),
            ),
        )
    )


def methods() -> CapabilityMethodRegistry:
    registry = CapabilityMethodRegistry(catalog())
    for method_id, method_type in (
        ("method.generic.appintent.v1", "app_intent"),
        ("method.generic.shortcut.v1", "apple_shortcut"),
        ("method.generic.api.v1", "official_api"),
        ("method.generic.mcp.v1", "mcp"),
        ("method.generic.ax.v1", "ax_automation"),
        ("method.generic.vision.v1", "vision_automation"),
    ):
        registry.register(
            CapabilityMethodDefinition(
                method_id=method_id,
                capability_id="capability.generic.search.v1",
                name="generic_search_method",
                purpose="generic_search",
                version="1.0.0",
                method_type=method_type,
                source="built_in",
                lifecycle="ACTIVE",
                availability="available",
                required_permissions=("permission.generic",),
                risk_level="interaction",
                input_schema=("query_reference",),
                output_schema=("result_state",),
                verifier="result_visible",
                platform_support=("macos_host",),
                evidence=verified_evidence(),
                verification_status="device_pass",
                latency_class="fast",
            )
        )
    return registry


def capability_evaluation():
    return CapabilityEvaluator().evaluate(
        catalog(),
        available_tools=(),
        available_permissions=("permission.generic",),
        available_platforms=("macos_host",),
    )


def allowed_permission() -> PermissionDecision:
    return PermissionDecision(
        eligible=True,
        reason_codes=("permission_granted",),
        identity_id="identity.test",
        ownership_ref="ownership.test",
        consent_id="consent.test",
        action="answer",
        effective_expires_at=None,
        policy_version="test",
    )


def denied_permission() -> PermissionDecision:
    return PermissionDecision(
        eligible=False,
        reason_codes=("consent_denied",),
        identity_id=None,
        ownership_ref=None,
        consent_id=None,
        action=None,
        effective_expires_at=None,
        policy_version="test",
    )


def profile(
    profile_id: str,
    source_kind: str,
    *,
    success: float = 0.80,
    privacy: tuple[str, ...] = ("public_metadata",),
    offline: bool = True,
    tokens: int = 0,
    cost: str = "none",
) -> IntelligenceCapabilityProfile:
    return IntelligenceCapabilityProfile(
        profile_id=profile_id,
        source_kind=source_kind,
        available=True,
        predicted_success=success,
        latency_class="fast",
        cost_class=cost,
        offline_available=offline,
        allowed_privacy_classes=privacy,
        estimated_token_upper_bound=tokens,
        evidence=verified_evidence(),
    )


def active_skill_profile() -> SkillAdvisoryProfile:
    return SkillAdvisoryProfile(
        manifest=SkillManifest(
            skill_id="generic.search.skill.v1",
            name="generic_search_skill",
            description="generic_search_skill",
            version="1.0.0",
            domain="general",
            source="built_in",
            trust_state="trusted",
            lifecycle="ACTIVE",
            required_capabilities=("capability.generic.search.v1",),
            dependencies=(),
            requested_permissions=("permission.generic",),
            risk_level="interaction",
            verifier="result_visible",
            platform_support=("macos_host",),
            evidence=verified_evidence(),
            verification_status="device_pass",
        ),
        supported_task_classes=("device_operation",),
        predicted_success=0.90,
    )


def request(
    *,
    permission: PermissionDecision | None = None,
    profiles: tuple[IntelligenceCapabilityProfile, ...] | None = None,
    data_class: str = "public_metadata",
    offline: bool = False,
    confidence: float = 0.90,
    repeatability: str = "unlikely",
    teaching_available: bool = False,
    token_budget: TokenBudgetPolicy | None = None,
) -> IntelligenceOrchestrationRequest:
    return IntelligenceOrchestrationRequest(
        intent_kind="search_current",
        capability_evaluation=capability_evaluation(),
        permission_decision=allowed_permission() if permission is None else permission,
        available_permissions=("permission.generic",),
        available_platforms=("macos_host",),
        task_complexity="high",
        aggregate_confidence=confidence,
        risk_level="interaction",
        task_repeatability=repeatability,
        trust_tier="low",
        preference="experience_first",
        teaching_available=teaching_available,
        data_class=data_class,
        offline_mode=offline,
        token_budget=token_budget if token_budget is not None else TokenBudgetPolicy(10000, "high"),
        intelligence_profiles=profiles
        if profiles is not None
        else (profile("profile.local.rule.v1", "local_rule", success=0.92),),
        skill_profiles=(active_skill_profile(),),
    )


def keys_in(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(keys_in(item) for item in value.values())) if value else set()
    if isinstance(value, (list, tuple)):
        return set().union(*(keys_in(item) for item in value)) if value else set()
    return set()


class IntelligenceOrchestrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.layer = IntelligenceOrchestrationLayer(methods())

    def test_task_classification_uses_only_bounded_intent_kind(self) -> None:
        classification = TaskClassifier().classify("search_current").summary()
        self.assertEqual("device_operation", classification["task_class"])
        self.assertEqual("classified", classification["status"])
        self.assertNotIn("query", classification)
        self.assertNotIn("goal", classification)

        unknown = TaskClassifier().classify("unsupported").summary()
        self.assertEqual("needs_clarification", unknown["status"])
        self.assertEqual("unknown", unknown["task_class"])
        self.assertEqual("unknown", unknown["intent_kind"])

    def test_capability_skill_and_method_advice_are_explainable_and_non_authoritative(self) -> None:
        result = self.layer.recommend(request()).summary()
        self.assertEqual("recommended", result["status"])
        self.assertEqual("capability.generic.search.v1", result["solution_evaluation"]["recommendation"]["capability_id"])
        self.assertEqual("generic.search.skill.v1", result["skill_advisory"]["recommended_skill"]["skill_id"])
        self.assertEqual("planner_skill_registry", result["skill_advisory"]["next_gate"])
        self.assertEqual("app_intent", result["method_advisory"]["recommended_method"]["method_type"])
        self.assertEqual("planner_risk_executor_verifier", result["next_gate"])
        self.assertEqual("none", result["execution_authority"])

    def test_method_advisory_uses_existing_registry_health_without_new_router(self) -> None:
        registry = self.layer._method_registry
        for timestamp in (200, 201, 202):
            registry.record_health(
                "method.generic.appintent.v1",
                platform="macos_host",
                compatibility="compatible",
                verification_status="static_pass",
                passed=False,
                failure_category="verifier_failed",
                validated_at=timestamp,
            )
        for timestamp in (203, 204, 205):
            registry.record_health(
                "method.generic.mcp.v1",
                platform="macos_host",
                compatibility="compatible",
                verification_status="device_pass",
                passed=True,
                validated_at=timestamp,
            )
        result = self.layer.recommend(request()).summary()
        self.assertEqual("method.generic.mcp.v1", result["method_advisory"]["recommended_method"]["method_id"])
        self.assertIn("method_health_applied", result["method_advisory"]["reason_codes"])
        self.assertEqual("none", result["execution_authority"])

    def test_official_api_is_a_declared_execution_method_not_a_client(self) -> None:
        self.assertIn("official_api", CapabilityMethodRegistry.METHOD_TYPES)
        recommendation = methods().recommend(
            "capability.generic.search.v1",
            available_permissions=("permission.generic",),
            available_platforms=("macos_host",),
        )
        types = {candidate["method_type"] for candidate in recommendation["candidates"]}
        self.assertIn("official_api", types)
        self.assertNotIn("call_api", CapabilityMethodRegistry.__dict__)

    def test_permission_denial_blocks_before_solution_method_or_router_work(self) -> None:
        result = self.layer.recommend(request(permission=denied_permission())).summary()
        self.assertEqual("blocked", result["status"])
        self.assertEqual(["permission_denied"], result["reason_codes"])
        self.assertIsNone(result["solution_evaluation"])
        self.assertIsNone(result["method_advisory"])
        self.assertIsNone(result["intelligence_path"])

    def test_business_data_never_enters_cloud_escalation(self) -> None:
        result = self.layer.recommend(
            request(
                data_class="business",
                profiles=(
                    profile(
                        "profile.cloud.expert.v1",
                        "cloud_model",
                        success=0.99,
                        privacy=("public_metadata", "business"),
                        offline=False,
                        tokens=5000,
                        cost="high",
                    ),
                    profile(
                        "profile.local.knowledge.v1",
                        "private_knowledge",
                        success=0.82,
                        privacy=("business",),
                    ),
                ),
            )
        ).summary()
        self.assertEqual("recommended", result["status"])
        self.assertEqual("deterministic_capability", result["intelligence_path"]["recommended_source"])
        self.assertFalse(result["privacy"]["cloud_eligible"])
        self.assertIsNone(result["cloud_approval"])

    def test_cloud_route_generates_approval_contract_without_provider_call(self) -> None:
        result = self.layer.recommend(
            request(
                profiles=(
                    profile("profile.local.small.v1", "local_small_model", success=0.68),
                    profile(
                        "profile.cloud.expert.v1",
                        "cloud_model",
                        success=0.95,
                        offline=False,
                        tokens=5000,
                        cost="high",
                    ),
                ),
            )
        ).summary()
        self.assertEqual("needs_cloud_approval", result["status"])
        self.assertEqual("pending_approval", result["cloud_approval"]["status"])
        self.assertEqual("profile.cloud.expert.v1", result["cloud_approval"]["profile_id"])
        self.assertEqual("none", result["cloud_approval"]["provider_call_authority"])
        self.assertEqual(["approve_once", "decline", "teach"], result["cloud_approval"]["allowed_user_decisions"])

    def test_offline_mode_returns_offline_limited_instead_of_silently_using_cloud(self) -> None:
        result = self.layer.recommend(
            request(
                offline=True,
                profiles=(
                    profile(
                        "profile.cloud.expert.v1",
                        "cloud_model",
                        success=0.95,
                        offline=False,
                        tokens=5000,
                        cost="high",
                    ),
                ),
            )
        ).summary()
        self.assertEqual("offline_limited", result["status"])
        self.assertIsNone(result["intelligence_path"])

    def test_token_budget_excludes_cloud_candidate(self) -> None:
        result = self.layer.recommend(
            request(
                profiles=(
                    profile(
                        "profile.cloud.expert.v1",
                        "cloud_model",
                        success=0.95,
                        offline=False,
                        tokens=5000,
                        cost="high",
                    ),
                ),
                token_budget=TokenBudgetPolicy(100, "high"),
            )
        ).summary()
        self.assertEqual("blocked", result["status"])
        self.assertIsNone(result["cloud_approval"])

    def test_human_teaching_is_an_advisory_not_a_learning_or_action_call(self) -> None:
        result = self.layer.recommend(
            request(
                confidence=0.40,
                repeatability="likely",
                teaching_available=True,
                profiles=(
                    profile("profile.local.small.v1", "local_small_model", success=0.45),
                    profile("profile.teaching.v1", "human_teaching_request", success=1.0),
                ),
            )
        ).summary()
        self.assertEqual("needs_human_teaching", result["status"])
        self.assertEqual("human_teaching_request", result["intelligence_path"]["recommended_source"])
        self.assertEqual("none", result["execution_authority"])

    def test_public_result_has_no_private_or_action_fields_and_layer_has_no_runtime_port(self) -> None:
        result = self.layer.recommend(request()).summary()
        self.assertFalse(FORBIDDEN_KEYS.intersection(keys_in(result)))
        self.assertNotIn("hello123", json.dumps(result, ensure_ascii=False))
        for forbidden_name in (
            "client",
            "planner",
            "risk_controller",
            "executor",
            "verifier",
            "select",
            "execute",
            "call_tool",
            "run_model",
            "run_shortcut",
            "run_app_intent",
        ):
            self.assertFalse(hasattr(self.layer, forbidden_name), forbidden_name)
        source = inspect.getsource(IntelligenceOrchestrationLayer)
        self.assertNotIn("MCPClient(", source)
        self.assertNotIn("SkillRegistry(", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
