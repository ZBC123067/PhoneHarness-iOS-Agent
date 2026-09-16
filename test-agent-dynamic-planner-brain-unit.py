#!/usr/bin/env python3
"""TEST-53 Dynamic Planner / Agent Brain V1 host-only gates."""

from __future__ import annotations

import json
import inspect
import unittest
from dataclasses import replace

from phoneharness_agent import (
    CapabilityCatalog,
    CapabilityEvidence,
    CapabilityMethodDefinition,
    CapabilityMethodRegistry,
    DynamicPlan,
    DynamicPlanner,
    PlannerAuthorizationFact,
    PlannerConstraintState,
    PlannerFailureEvidence,
    PlannerInput,
    PlannerProposal,
    PlanValidator,
    SkillDefinition,
    SkillRegistry,
)


PERMISSIONS = ("mcp.read_screen", "mcp.foreground_interaction")
PLATFORMS = ("macos_host", "ios_mcp")


def active_method(method_id: str, capability_id: str, confidence: float) -> CapabilityMethodDefinition:
    return CapabilityMethodDefinition(
        method_id=method_id,
        capability_id=capability_id,
        name=method_id.removeprefix("method.").replace(".", "_"),
        purpose="planner_test_method",
        version="1.0.0",
        method_type="mcp",
        source="built_in",
        lifecycle="ACTIVE",
        availability="available",
        required_permissions=("mcp.read_screen",),
        risk_level="read_only",
        input_schema=(),
        output_schema=("semantic_observation",),
        verifier="observation_nonempty",
        platform_support=PLATFORMS,
        evidence=CapabilityEvidence(success_count=2, confidence=confidence, last_verified=100),
        verification_status="device_pass",
    )


def runtime_input(
    intent: str,
    *,
    tools: tuple[str, ...],
    constraints: tuple[PlannerConstraintState, ...],
    authorization_facts: tuple[PlannerAuthorizationFact, ...] = (),
    methods: bool = False,
    registry: SkillRegistry | None = None,
    goal_class: str | None = None,
) -> PlannerInput:
    skill_registry = registry or SkillRegistry()
    catalog = CapabilityCatalog.from_skill_registry(skill_registry)
    method_registry = None
    if methods:
        capability_id = "capability.screen.observe.v1"
        method_registry = CapabilityMethodRegistry(
            catalog,
            (
                active_method("method.observe.primary.v1", capability_id, 0.95),
                active_method("method.observe.secondary.v1", capability_id, 0.80),
            ),
        )
    return PlannerInput.from_runtime(
        request_id="request.test53.001",
        goal_class=goal_class or intent,
        normalized_intent=intent,
        task_context_ref="context.test53.001",
        context_version=1,
        capability_catalog=catalog,
        skill_registry=skill_registry,
        method_registry=method_registry,
        available_tools=tools,
        available_permissions=PERMISSIONS,
        available_platforms=PLATFORMS,
        constraints=constraints,
        authorization_facts=authorization_facts,
    )


class DynamicPlannerBrainUnitTests(unittest.TestCase):
    def test_typed_input_and_plan_are_privacy_safe(self) -> None:
        planner_input = runtime_input(
            "observe",
            tools=("describe_screen",),
            constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
        )
        plan = DynamicPlanner().plan_dynamic(planner_input)

        self.assertIsInstance(plan, DynamicPlan)
        self.assertEqual("READY", plan.status)
        self.assertEqual(1, plan.planning_revision)
        self.assertEqual("risk_controller", plan.next_gate)
        self.assertEqual("none", plan.execution_authority)
        encoded = json.dumps(plan.audit(), sort_keys=True)
        for forbidden in ("password", "token", "screenshot", "coordinate", "raw_ax", '"tool"', '"command"'):
            self.assertNotIn(forbidden, encoded.casefold())

    def test_observation_plan_uses_registered_skill_and_capability(self) -> None:
        plan = DynamicPlanner().plan_dynamic(
            runtime_input(
                "observe",
                tools=("describe_screen",),
                constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
            )
        )
        self.assertEqual("screen.observe.v1", plan.steps[0].skill_id)
        self.assertEqual("capability.screen.observe.v1", plan.steps[0].capability_id)
        self.assertEqual("observation_nonempty", plan.steps[0].verification_requirement)

    def test_public_destination_plan_uses_existing_maps_skill(self) -> None:
        plan = DynamicPlanner().plan_dynamic(
            runtime_input(
                "map_link",
                goal_class="navigate_public_destination",
                tools=("open_url",),
                constraints=(PlannerConstraintState("nonempty_public_destination", "SATISFIED"),),
            )
        )
        self.assertEqual("READY", plan.status)
        self.assertEqual("maps.open_native_link.v1", plan.steps[-1].skill_id)
        self.assertEqual("interaction", plan.steps[-1].risk_class)

    def test_installed_app_plan_uses_existing_launch_skill(self) -> None:
        plan = DynamicPlanner().plan_dynamic(
            runtime_input(
                "launch_installed_app",
                tools=("launch_app",),
                constraints=(PlannerConstraintState("nonempty_query", "SATISFIED"),),
            )
        )
        self.assertEqual("READY", plan.status)
        self.assertEqual("apps.launch_installed.v1", plan.steps[-1].skill_id)
        self.assertEqual("frontmost_bound_app", plan.completion_criteria)

    def test_read_only_verification_goal_has_no_mutation_authority(self) -> None:
        plan = DynamicPlanner().plan_dynamic(
            runtime_input(
                "verify_visible",
                tools=("describe_screen",),
                constraints=(
                    PlannerConstraintState("fresh_screen_observation", "SATISFIED"),
                    PlannerConstraintState("nonempty_query", "SATISFIED"),
                ),
            )
        )
        self.assertEqual("READY", plan.status)
        self.assertEqual("read_only", plan.steps[-1].risk_class)
        self.assertEqual("visible_text_contains", plan.steps[-1].expected_observation)

    def test_provider_contract_is_replaceable_but_typed(self) -> None:
        class FixedProvider:
            def propose(self, planner_input: PlannerInput) -> PlannerProposal:
                return PlannerProposal(("screen.observe.v1",), ("fixture_provider",))

        planner_input = runtime_input(
            "observe",
            tools=("describe_screen",),
            constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
        )
        plan = DynamicPlanner().plan_dynamic(planner_input, provider=FixedProvider())
        self.assertEqual("READY", plan.status)
        self.assertIn("fixture_provider", plan.reason_codes)


class DynamicPlannerBrainIntegrationTests(unittest.TestCase):
    def test_method_health_selects_best_eligible_method(self) -> None:
        planner_input = runtime_input(
            "observe",
            tools=("describe_screen",),
            constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
            methods=True,
        )
        plan = DynamicPlanner().plan_dynamic(planner_input)
        self.assertEqual("method.observe.primary.v1", plan.steps[0].method_id)
        self.assertEqual(("method.observe.secondary.v1",), plan.steps[0].fallback_candidates)

    def test_replan_uses_fresh_context_and_an_untried_method(self) -> None:
        planner = DynamicPlanner()
        planner_input = runtime_input(
            "observe",
            tools=("describe_screen",),
            constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
            methods=True,
        )
        first = planner.plan_dynamic(planner_input)
        failure = PlannerFailureEvidence(
            failed_step_id=first.steps[0].step_id,
            reason_code="method_failure",
            evidence_status="VERIFIED_FAILURE",
            attempted_method_id=first.steps[0].method_id,
            fresh_observation_ref="observation.test53.002",
            context_version=2,
            recoverable=True,
        )
        replanned = planner.replan_dynamic(first, planner_input, failure)

        self.assertEqual("READY", replanned.status)
        self.assertEqual(2, replanned.planning_revision)
        self.assertEqual("method.observe.secondary.v1", replanned.steps[0].method_id)
        self.assertNotEqual(first.plan_id, replanned.plan_id)

    def test_high_risk_skill_requires_confirmation_and_risk_handoff(self) -> None:
        registry = SkillRegistry(
            (
                SkillDefinition(
                    skill_id="account.sensitive_action.v1",
                    name="sensitive_account_action",
                    description="Represent one synthetic high-risk host-only planning contract.",
                    version="1.0.0",
                    status="active",
                    intent_kinds=("sensitive_action",),
                    required_capabilities=("native_link_dispatch",),
                    required_tools=frozenset({"open_url"}),
                    allowed_tools=frozenset({"open_url"}),
                    required_permissions=("mcp.foreground_interaction",),
                    risk_level="high_risk",
                    preconditions=("explicit_target_reference",),
                    executor="planner_steps_v1",
                    verifier="frontmost_app_is",
                    dependencies=(),
                    platform_support=PLATFORMS,
                    stop_conditions=("authorization_unavailable",),
                    rollback="no_automatic_rollback",
                ),
            )
        )
        plan = DynamicPlanner().plan_dynamic(
            runtime_input(
                "sensitive_action",
                tools=("open_url",),
                constraints=(PlannerConstraintState("explicit_target_reference", "SATISFIED"),),
                registry=registry,
            )
        )
        self.assertEqual("READY", plan.status)
        self.assertEqual("REQUIRED", plan.steps[0].confirmation_requirement)
        self.assertTrue(plan.risk_handoff_required)
        self.assertEqual("risk_controller", plan.next_gate)

    def test_plan_validator_reports_machine_readable_cycle(self) -> None:
        planner_input = runtime_input(
            "observe",
            tools=("describe_screen",),
            constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
        )
        plan = DynamicPlanner().plan_dynamic(planner_input)
        cyclic_step = replace(plan.steps[0], dependencies=(plan.steps[0].step_id,))
        result = PlanValidator().validate(replace(plan, steps=(cyclic_step,)), planner_input)
        self.assertFalse(result.passed)
        self.assertIn("dependency_cycle", result.reason_codes)


class DynamicPlannerBrainE2ETests(unittest.TestCase):
    def test_registered_runtime_to_validated_risk_handoff(self) -> None:
        planner_input = runtime_input(
            "observe",
            tools=("describe_screen",),
            constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
            methods=True,
        )
        plan = DynamicPlanner().plan_dynamic(planner_input)
        validation = PlanValidator().validate(plan, planner_input)

        self.assertTrue(validation.passed)
        self.assertEqual("READY", plan.status)
        self.assertEqual("risk_controller", plan.next_gate)
        self.assertTrue(plan.risk_handoff_required)
        self.assertEqual("none", plan.execution_authority)
        self.assertEqual("method.observe.primary.v1", plan.steps[0].method_id)


class DynamicPlannerBrainNegativeTests(unittest.TestCase):
    def test_unknown_skill_injection_is_blocked(self) -> None:
        class UnknownSkillProvider:
            def propose(self, planner_input: PlannerInput) -> PlannerProposal:
                return PlannerProposal(("forged.skill.v1",), ("external_candidate",))

        planner_input = runtime_input(
            "observe",
            tools=("describe_screen",),
            constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
        )
        plan = DynamicPlanner().plan_dynamic(planner_input, provider=UnknownSkillProvider())
        self.assertEqual("BLOCKED", plan.status)
        self.assertIn("unknown_skill", plan.validation_reason_codes)

    def test_stale_precondition_is_blocked(self) -> None:
        plan = DynamicPlanner().plan_dynamic(
            runtime_input(
                "observe",
                tools=("describe_screen",),
                constraints=(PlannerConstraintState("fresh_screen_observation", "STALE"),),
            )
        )
        self.assertEqual("BLOCKED", plan.status)
        self.assertIn("precondition_not_satisfied", plan.validation_reason_codes)

    def test_capability_tampering_is_rejected(self) -> None:
        planner_input = runtime_input(
            "observe",
            tools=("describe_screen",),
            constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
        )
        plan = DynamicPlanner().plan_dynamic(planner_input)
        tampered = replace(plan.steps[0], capability_id="capability.forged.v1")
        result = PlanValidator().validate(replace(plan, steps=(tampered,)), planner_input)
        self.assertFalse(result.passed)
        self.assertIn("unknown_capability", result.reason_codes)

    def test_high_risk_plan_without_confirmation_policy_is_rejected(self) -> None:
        registry = SkillRegistry(
            (
                SkillDefinition(
                    skill_id="account.synthetic_high_risk.v1",
                    name="synthetic_high_risk",
                    description="Synthetic policy-only high-risk Skill for validator coverage.",
                    version="1.0.0",
                    status="active",
                    intent_kinds=("synthetic_high_risk",),
                    required_capabilities=("native_link_dispatch",),
                    required_tools=frozenset({"open_url"}),
                    allowed_tools=frozenset({"open_url"}),
                    required_permissions=("mcp.foreground_interaction",),
                    risk_level="high_risk",
                    preconditions=("explicit_target_reference",),
                    executor="planner_steps_v1",
                    verifier="frontmost_app_is",
                    dependencies=(),
                    platform_support=PLATFORMS,
                    stop_conditions=("authorization_unavailable",),
                    rollback="no_automatic_rollback",
                ),
            )
        )
        planner_input = runtime_input(
            "synthetic_high_risk",
            tools=("open_url",),
            constraints=(PlannerConstraintState("explicit_target_reference", "SATISFIED"),),
            registry=registry,
        )
        plan = DynamicPlanner().plan_dynamic(planner_input)
        weakened = replace(plan.steps[0], confirmation_requirement="NOT_REQUIRED")
        result = PlanValidator().validate(replace(plan, steps=(weakened,)), planner_input)
        self.assertFalse(result.passed)
        self.assertIn("high_risk_confirmation_missing", result.reason_codes)

    def test_replan_without_fresh_observation_is_blocked(self) -> None:
        planner = DynamicPlanner()
        planner_input = runtime_input(
            "observe",
            tools=("describe_screen",),
            constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
            methods=True,
        )
        first = planner.plan_dynamic(planner_input)
        failure = PlannerFailureEvidence(
            failed_step_id=first.steps[0].step_id,
            reason_code="method_failure",
            evidence_status="VERIFIED_FAILURE",
            attempted_method_id=first.steps[0].method_id,
            fresh_observation_ref="observation.test53.same",
            context_version=1,
            recoverable=True,
        )
        replanned = planner.replan_dynamic(first, planner_input, failure)
        self.assertEqual("BLOCKED", replanned.status)
        self.assertIn("fresh_observation_required", replanned.validation_reason_codes)

    def test_missing_dependency_step_is_rejected(self) -> None:
        planner_input = runtime_input(
            "verify_visible",
            tools=("describe_screen",),
            constraints=(
                PlannerConstraintState("fresh_screen_observation", "SATISFIED"),
                PlannerConstraintState("nonempty_query", "SATISFIED"),
            ),
        )
        plan = DynamicPlanner().plan_dynamic(planner_input)
        result = PlanValidator().validate(replace(plan, steps=(plan.steps[-1],)), planner_input)
        self.assertFalse(result.passed)
        self.assertIn("missing_dependency", result.reason_codes)

    def test_missing_verifier_requirement_is_rejected(self) -> None:
        planner_input = runtime_input(
            "observe",
            tools=("describe_screen",),
            constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
        )
        plan = DynamicPlanner().plan_dynamic(planner_input)
        weakened = replace(plan.steps[0], verification_requirement="")
        result = PlanValidator().validate(replace(plan, steps=(weakened,)), planner_input)
        self.assertFalse(result.passed)
        self.assertIn("missing_verifier_requirement", result.reason_codes)


class DynamicPlannerBrainSecurityTests(unittest.TestCase):
    def test_dynamic_planner_has_no_mcp_or_executor_port(self) -> None:
        source = "\n".join(
            (
                inspect.getsource(DynamicPlanner.plan_dynamic),
                inspect.getsource(DynamicPlanner.replan_dynamic),
            )
        )
        for forbidden in ("MCPClient", "PlanExecutor", "call_tool", "_action_port"):
            self.assertNotIn(forbidden, source)

    def search_input(self, facts: tuple[PlannerAuthorizationFact, ...]) -> PlannerInput:
        return runtime_input(
            "search_current",
            tools=("describe_screen", "tap_element", "input_text", "press_key"),
            constraints=(
                PlannerConstraintState("fresh_screen_observation", "SATISFIED"),
                PlannerConstraintState("nonempty_query", "SATISFIED"),
                PlannerConstraintState("single_search_control", "SATISFIED"),
            ),
            authorization_facts=facts,
        )

    def test_test52_derived_field_state_remains_fail_closed(self) -> None:
        facts = tuple(
            PlannerAuthorizationFact(name, "TRUE", "DERIVED", True)
            for name in ("editable", "secure_false", "enabled", "authorization_grade_visible", "actionable")
        )
        plan = DynamicPlanner().plan_dynamic(self.search_input(facts))
        self.assertEqual("BLOCKED", plan.status)
        self.assertIn("semantic_authorization_not_direct", plan.validation_reason_codes)

    def test_test52_unavailable_field_state_remains_fail_closed(self) -> None:
        facts = tuple(
            PlannerAuthorizationFact(name, "UNAVAILABLE", "UNAVAILABLE", True)
            for name in ("editable", "secure_false", "enabled", "authorization_grade_visible", "actionable")
        )
        plan = DynamicPlanner().plan_dynamic(self.search_input(facts))
        self.assertEqual("BLOCKED", plan.status)
        self.assertIn("semantic_authorization_unavailable", plan.validation_reason_codes)

    def test_forged_device_pass_is_not_direct_provenance(self) -> None:
        with self.assertRaises(ValueError):
            PlannerAuthorizationFact("editable", "TRUE", "DEVICE_PASS", True)

    def test_provider_free_form_tool_injection_is_rejected(self) -> None:
        class MaliciousProvider:
            def propose(self, planner_input: PlannerInput) -> object:
                return {"tool": "run_command", "command": "arbitrary"}

        planner_input = runtime_input(
            "observe",
            tools=("describe_screen",),
            constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
        )
        plan = DynamicPlanner().plan_dynamic(planner_input, provider=MaliciousProvider())
        self.assertEqual("BLOCKED", plan.status)
        self.assertIn("provider_contract_invalid", plan.validation_reason_codes)

    def test_planner_never_exposes_executor_or_mcp_authority(self) -> None:
        planner_input = runtime_input(
            "observe",
            tools=("describe_screen",),
            constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
        )
        encoded = json.dumps(DynamicPlanner().plan_dynamic(planner_input).audit(), sort_keys=True).casefold()
        self.assertNotIn("call_tool", encoded)
        self.assertNotIn("mcpclient", encoded)
        self.assertNotIn("planexecutor", encoded)
        self.assertIn('"execution_authority": "none"', encoded)

    def test_tampered_risk_gate_and_executor_authority_are_rejected(self) -> None:
        planner_input = runtime_input(
            "observe",
            tools=("describe_screen",),
            constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
        )
        plan = DynamicPlanner().plan_dynamic(planner_input)
        tampered = replace(
            plan,
            next_gate="executor",
            risk_handoff_required=False,
            execution_authority="direct",
        )
        result = PlanValidator().validate(tampered, planner_input)
        self.assertFalse(result.passed)
        self.assertIn("risk_controller_bypass", result.reason_codes)
        self.assertIn("unauthorized_executor_access", result.reason_codes)

    def test_risk_constraint_can_deny_interaction_plan(self) -> None:
        planner_input = replace(
            runtime_input(
                "map_link",
                tools=("open_url",),
                constraints=(PlannerConstraintState("nonempty_public_destination", "SATISFIED"),),
            ),
            risk_constraints=("read_only_only",),
        )
        plan = DynamicPlanner().plan_dynamic(planner_input)
        self.assertEqual("BLOCKED", plan.status)
        self.assertIn("risk_constraint_denied", plan.validation_reason_codes)

    def test_replan_limit_prevents_infinite_loop(self) -> None:
        planner = DynamicPlanner()
        planner_input = runtime_input(
            "observe",
            tools=("describe_screen",),
            constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
            methods=True,
        )
        first = planner.plan_dynamic(planner_input)
        first_failure = PlannerFailureEvidence(
            first.steps[0].step_id,
            "method_failure",
            "VERIFIED_FAILURE",
            first.steps[0].method_id,
            "observation.test53.002",
            2,
            True,
        )
        second = planner.replan_dynamic(first, planner_input, first_failure)
        self.assertEqual(2, second.planning_revision)
        self.assertEqual(1, second.replan_count)
        self.assertEqual((first.steps[0].method_id,), second.methods_already_attempted)
        self.assertEqual(1, len(second.prior_step_results))
        second_failure = PlannerFailureEvidence(
            second.steps[0].step_id,
            "method_failure",
            "VERIFIED_FAILURE",
            second.steps[0].method_id,
            "observation.test53.003",
            3,
            True,
        )
        third = planner.replan_dynamic(second, planner_input, second_failure)
        self.assertEqual(3, third.planning_revision)
        self.assertEqual(2, third.replan_count)
        self.assertEqual(2, len(third.prior_step_results))
        third_failure = PlannerFailureEvidence(
            third.steps[0].step_id if third.steps else second.steps[0].step_id,
            "method_failure",
            "VERIFIED_FAILURE",
            third.steps[0].method_id if third.steps else None,
            "observation.test53.004",
            4,
            True,
        )
        blocked = planner.replan_dynamic(third, planner_input, third_failure)
        self.assertEqual("BLOCKED", blocked.status)
        self.assertIn("replan_limit_reached", blocked.validation_reason_codes)
        self.assertEqual(3, blocked.planning_revision)
        self.assertEqual(2, blocked.replan_count)
        self.assertEqual(third.methods_already_attempted, blocked.methods_already_attempted)


if __name__ == "__main__":
    unittest.main(verbosity=2)
