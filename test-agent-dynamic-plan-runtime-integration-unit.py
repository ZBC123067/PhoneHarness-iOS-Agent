#!/usr/bin/env python3
"""TEST-54 Dynamic Plan governed runtime integration host-only gates."""

from __future__ import annotations

import inspect
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from phoneharness_agent import (
    CapabilityCatalog,
    CapabilityEvidence,
    CapabilityMethodDefinition,
    CapabilityMethodRegistry,
    CompiledDynamicPlanStep,
    CoordinatorOwnershipError,
    CoordinatorStateError,
    CoordinatorStateStore,
    DynamicExecutionEvidence,
    DynamicObservationEvidence,
    DynamicPlanRuntimeCompiler,
    DynamicPlanner,
    DynamicStepStateMachine,
    DynamicVerificationEvidence,
    PlannerAuthorizationFact,
    PlannerConstraintState,
    PlannerInput,
    RiskController,
    SkillDefinition,
    SkillRegistry,
    TaskCoordinator,
)


OWNER = "owner-token-test54-123456789"
PERMISSIONS = ("mcp.read_screen", "mcp.foreground_interaction")
PLATFORMS = ("macos_host", "ios_mcp")


class UnusedReadOnlyRuntime:
    def prepare_goal(self, _goal: str):
        raise AssertionError("legacy read-only admission is not used by TEST-54")


class FakeGovernedDynamicRuntime:
    def __init__(self) -> None:
        self.executor_calls: list[CompiledDynamicPlanStep] = []
        self.observer_calls: list[CompiledDynamicPlanStep] = []
        self.verifier_calls: list[CompiledDynamicPlanStep] = []
        self.execution_results: list[DynamicExecutionEvidence] = []
        self.verification_results: list[DynamicVerificationEvidence] = []

    def execute_dynamic_step(self, step: CompiledDynamicPlanStep) -> DynamicExecutionEvidence:
        self.executor_calls.append(step)
        if self.execution_results:
            return self.execution_results.pop(0)
        return DynamicExecutionEvidence("PASSED", "execution.test54.passed", None, False)

    def observe_dynamic_step(self, step: CompiledDynamicPlanStep) -> DynamicObservationEvidence:
        self.observer_calls.append(step)
        return DynamicObservationEvidence("AVAILABLE", "observation.test54.fresh")

    def verify_dynamic_step(
        self,
        step: CompiledDynamicPlanStep,
        execution: DynamicExecutionEvidence,
        observation: DynamicObservationEvidence,
    ) -> DynamicVerificationEvidence:
        self.verifier_calls.append(step)
        if self.verification_results:
            return self.verification_results.pop(0)
        return DynamicVerificationEvidence(True, "verification.test54.passed", None, False)


def method(method_id: str, capability_id: str, confidence: float) -> CapabilityMethodDefinition:
    return CapabilityMethodDefinition(
        method_id=method_id,
        capability_id=capability_id,
        name=method_id.replace(".", "_"),
        purpose="test54_runtime_method",
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
        evidence=CapabilityEvidence(success_count=3, confidence=confidence, last_verified=100),
        verification_status="device_pass",
    )


def planner_input(
    intent: str,
    *,
    tools: tuple[str, ...],
    constraints: tuple[PlannerConstraintState, ...],
    registry: SkillRegistry | None = None,
    authorization_facts: tuple[PlannerAuthorizationFact, ...] = (),
    with_methods: bool = False,
) -> tuple[PlannerInput, CapabilityCatalog, SkillRegistry]:
    skills = registry or SkillRegistry()
    catalog = CapabilityCatalog.from_skill_registry(skills)
    methods = None
    if with_methods:
        capability_id = "capability.screen.observe.v1"
        methods = CapabilityMethodRegistry(
            catalog,
            (
                method("method.observe.primary.v1", capability_id, 0.95),
                method("method.observe.secondary.v1", capability_id, 0.85),
                method("method.observe.tertiary.v1", capability_id, 0.75),
            ),
        )
    value = PlannerInput.from_runtime(
        request_id="request.test54.001",
        goal_class=intent,
        normalized_intent=intent,
        task_context_ref="context.test54.001",
        context_version=1,
        capability_catalog=catalog,
        skill_registry=skills,
        method_registry=methods,
        available_tools=tools,
        available_permissions=PERMISSIONS,
        available_platforms=PLATFORMS,
        constraints=constraints,
        authorization_facts=authorization_facts,
    )
    return value, catalog, skills


def coordinator_for(
    planner_value: PlannerInput,
    catalog: CapabilityCatalog,
    skills: SkillRegistry,
    runtime: FakeGovernedDynamicRuntime,
    directory: str,
    *,
    risk_actions: dict[str, tuple[str, ...]] | None = None,
) -> TaskCoordinator:
    return TaskCoordinator(
        CoordinatorStateStore(Path(directory) / "coordinator-v1.json"),
        UnusedReadOnlyRuntime(),
        dynamic_runtime=runtime,
        dynamic_compiler=DynamicPlanRuntimeCompiler(catalog, skills, risk_actions or {}),
        dynamic_risk_controller=RiskController(),
    )


class DynamicPlanRuntimeUnitTests(unittest.TestCase):
    def test_compiler_preserves_registered_semantics_without_payload(self) -> None:
        value, catalog, skills = planner_input(
            "observe",
            tools=("describe_screen",),
            constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
        )
        plan = DynamicPlanner().plan_dynamic(value)
        compiled = DynamicPlanRuntimeCompiler(catalog, skills).compile(plan, value)
        self.assertEqual(1, len(compiled))
        self.assertEqual("capability.screen.observe.v1", compiled[0].capability_id)
        self.assertEqual(("describe_screen",), compiled[0].required_tools)
        self.assertEqual("observation_nonempty", compiled[0].verification_requirement)
        self.assertNotIn("arguments", compiled[0].audit())

    def test_step_state_machine_rejects_invalid_transition(self) -> None:
        self.assertEqual("READY", DynamicStepStateMachine.transition("PENDING", "READY"))
        with self.assertRaises(ValueError):
            DynamicStepStateMachine.transition("PENDING", "VERIFIED")

    def test_risk_contract_comes_from_registry_not_planner_label(self) -> None:
        value, catalog, skills = planner_input(
            "map_link",
            tools=("open_url",),
            constraints=(PlannerConstraintState("nonempty_public_destination", "SATISFIED"),),
        )
        plan = DynamicPlanner().plan_dynamic(value)
        compiled = DynamicPlanRuntimeCompiler(catalog, skills).compile(plan, value)[0]
        forged = replace(plan, steps=(replace(plan.steps[0], risk_class="read_only"),))
        with self.assertRaises(ValueError):
            DynamicPlanRuntimeCompiler(catalog, skills).compile(forged, value)
        self.assertEqual("interaction", compiled.risk_plan()["skill_selection"]["skill"]["risk_level"])

    def test_compiled_audit_is_privacy_safe(self) -> None:
        value, catalog, skills = planner_input(
            "launch_installed_app",
            tools=("launch_app",),
            constraints=(PlannerConstraintState("nonempty_query", "SATISFIED"),),
        )
        plan = DynamicPlanner().plan_dynamic(value)
        encoded = repr(DynamicPlanRuntimeCompiler(catalog, skills).compile(plan, value)[0].audit()).casefold()
        for forbidden in ("password", "token", "screenshot", "coordinate", "arguments", "raw"):
            self.assertNotIn(forbidden, encoded)


class DynamicPlanRuntimeIntegrationTests(unittest.TestCase):
    def test_read_only_observation_reaches_verified(self) -> None:
        value, catalog, skills = planner_input(
            "observe",
            tools=("describe_screen",),
            constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
        )
        plan = DynamicPlanner().plan_dynamic(value)
        runtime = FakeGovernedDynamicRuntime()
        with tempfile.TemporaryDirectory() as directory:
            coordinator = coordinator_for(value, catalog, skills, runtime, directory)
            task = coordinator.admit_dynamic_plan(OWNER, plan, value)
            result = coordinator.run_dynamic_step(task["task_id"], OWNER)
        self.assertEqual("DONE", result["status"])
        self.assertEqual("VERIFIED", result["step_state"])
        self.assertEqual(1, len(runtime.executor_calls))
        self.assertEqual(1, len(runtime.verifier_calls))

    def test_registered_launch_and_maps_capabilities_use_same_coordinator(self) -> None:
        scenarios = (
            ("launch_installed_app", ("launch_app",), "nonempty_query"),
            ("map_link", ("open_url",), "nonempty_public_destination"),
        )
        for intent, tools, constraint in scenarios:
            with self.subTest(intent=intent), tempfile.TemporaryDirectory() as directory:
                value, catalog, skills = planner_input(
                    intent,
                    tools=tools,
                    constraints=(PlannerConstraintState(constraint, "SATISFIED"),),
                )
                plan = DynamicPlanner().plan_dynamic(value)
                runtime = FakeGovernedDynamicRuntime()
                coordinator = coordinator_for(value, catalog, skills, runtime, directory)
                task = coordinator.admit_dynamic_plan(OWNER, plan, value)
                result = coordinator.run_dynamic_step(task["task_id"], OWNER)
                self.assertEqual("DONE", result["status"])
                self.assertEqual(1, len(runtime.executor_calls))

    def test_dependency_is_not_ready_until_predecessor_is_verified(self) -> None:
        value, catalog, skills = planner_input(
            "verify_visible",
            tools=("describe_screen",),
            constraints=(
                PlannerConstraintState("fresh_screen_observation", "SATISFIED"),
                PlannerConstraintState("nonempty_query", "SATISFIED"),
            ),
        )
        plan = DynamicPlanner().plan_dynamic(value)
        runtime = FakeGovernedDynamicRuntime()
        with tempfile.TemporaryDirectory() as directory:
            coordinator = coordinator_for(value, catalog, skills, runtime, directory)
            task = coordinator.admit_dynamic_plan(OWNER, plan, value)
            first = coordinator.run_dynamic_step(task["task_id"], OWNER)
            middle = coordinator.inspect_dynamic_task(task["task_id"], OWNER)
            second = coordinator.run_dynamic_step(task["task_id"], OWNER)
        self.assertEqual("VERIFIED", first["step_state"])
        self.assertIn("PENDING", [step["state"] for step in middle["steps"]])
        self.assertEqual("DONE", second["status"])
        self.assertEqual(2, len(runtime.executor_calls))

    def test_verifier_failure_replans_and_stale_revision_cannot_execute(self) -> None:
        value, catalog, skills = planner_input(
            "observe",
            tools=("describe_screen",),
            constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
            with_methods=True,
        )
        first_plan = DynamicPlanner().plan_dynamic(value)
        runtime = FakeGovernedDynamicRuntime()
        runtime.verification_results.append(
            DynamicVerificationEvidence(False, "verification.test54.failed", "verification_failed", True)
        )
        with tempfile.TemporaryDirectory() as directory:
            coordinator = coordinator_for(value, catalog, skills, runtime, directory)
            task = coordinator.admit_dynamic_plan(OWNER, first_plan, value)
            failed = coordinator.run_dynamic_step(task["task_id"], OWNER)
            replanned = coordinator.replan_dynamic_task(
                task["task_id"],
                OWNER,
                DynamicPlanner(),
                value,
                fresh_observation_ref="observation.test54.002",
                context_version=2,
            )
            self.assertEqual("method.observe.secondary.v1", replanned["steps"][0]["method_id"])
            stale = coordinator.run_dynamic_step(
                task["task_id"], OWNER, expected_plan_id=first_plan.plan_id, expected_revision=1
            )
            current = coordinator.run_dynamic_step(
                task["task_id"],
                OWNER,
                expected_plan_id=replanned["plan_id"],
                expected_revision=2,
            )
        self.assertEqual("REPLAN_REQUIRED", failed["step_state"])
        self.assertEqual(2, replanned["planning_revision"])
        self.assertEqual("STALE_PLAN_REVISION", stale["failure_category"])
        self.assertEqual(1, stale["executor_invocation_count"])
        self.assertEqual("DONE", current["status"])

    def test_replan_excludes_verified_skills_instead_of_redispatching(self) -> None:
        registry = SkillRegistry((
            SkillDefinition(
                skill_id="screen.observe.v1",
                name="observe_screen",
                description="TEST-54 replan dependency fixture.",
                version="1.0.0",
                status="active",
                intent_kinds=("observe_dependency",),
                required_capabilities=("screen_observation",),
                required_tools=frozenset({"describe_screen"}),
                allowed_tools=frozenset({"describe_screen"}),
                required_permissions=PERMISSIONS,
                risk_level="read_only",
                preconditions=("fresh_screen_observation",),
                executor="planner_steps_v1",
                verifier="observation_nonempty",
                dependencies=(),
                platform_support=PLATFORMS,
                stop_conditions=("authorization_unavailable",),
                rollback="no_automatic_rollback",
            ),
            SkillDefinition(
                skill_id="account.synthetic_send.v1",
                name="synthetic_send",
                description="TEST-54 replan candidate fixture.",
                version="1.0.0",
                status="active",
                intent_kinds=("synthetic_send",),
                required_capabilities=("message_dispatch",),
                required_tools=frozenset({"open_url"}),
                allowed_tools=frozenset({"open_url"}),
                required_permissions=("mcp.foreground_interaction",),
                risk_level="read_only",
                preconditions=("explicit_target_reference",),
                executor="planner_steps_v1",
                verifier="observation_nonempty",
                dependencies=("screen.observe.v1",),
                platform_support=PLATFORMS,
                stop_conditions=("authorization_unavailable",),
                rollback="no_automatic_rollback",
            ),
        ))
        value, catalog, skills = planner_input(
            "synthetic_send",
            tools=("describe_screen", "open_url"),
            constraints=(
                PlannerConstraintState("fresh_screen_observation", "SATISFIED"),
                PlannerConstraintState("explicit_target_reference", "SATISFIED"),
            ),
            registry=registry,
        )
        first_plan = DynamicPlanner().plan_dynamic(value)
        self.assertEqual(2, len(first_plan.steps))
        runtime = FakeGovernedDynamicRuntime()
        runtime.verification_results.extend((
            DynamicVerificationEvidence(True, "verification.test54.passed", None, False),
            DynamicVerificationEvidence(False, "verification.test54.failed", "verification_failed", True),
        ))
        with tempfile.TemporaryDirectory() as directory:
            coordinator = coordinator_for(value, catalog, skills, runtime, directory)
            task = coordinator.admit_dynamic_plan(OWNER, first_plan, value)
            first_run = coordinator.run_dynamic_step(task["task_id"], OWNER, now=100)
            second_run = coordinator.run_dynamic_step(task["task_id"], OWNER, now=101)
            replanned = coordinator.replan_dynamic_task(
                task["task_id"],
                OWNER,
                DynamicPlanner(),
                value,
                fresh_observation_ref="observation.test54.002",
                context_version=2,
            )
            final_run = coordinator.run_dynamic_step(
                task["task_id"], OWNER, expected_plan_id=replanned["plan_id"], expected_revision=2, now=102
            )
        self.assertEqual("VERIFIED", first_run["step_state"])
        self.assertEqual("REPLAN_REQUIRED", second_run["step_state"])
        self.assertEqual(2, replanned["planning_revision"])
        self.assertEqual(1, len(replanned["steps"]))
        self.assertEqual("account.synthetic_send.v1", replanned["steps"][0]["skill_id"])
        self.assertEqual("DONE", final_run["status"])
        executed_skills = [step.skill_id for step in runtime.executor_calls]
        self.assertEqual(
            ["screen.observe.v1", "account.synthetic_send.v1", "account.synthetic_send.v1"],
            executed_skills,
        )

    def test_high_risk_confirmation_pauses_before_executor(self) -> None:
        registry = SkillRegistry((
            SkillDefinition(
                skill_id="account.synthetic_send.v1",
                name="synthetic_send",
                description="Host-only high-risk confirmation fixture.",
                version="1.0.0",
                status="active",
                intent_kinds=("synthetic_send",),
                required_capabilities=("message_dispatch",),
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
        ))
        value, catalog, skills = planner_input(
            "synthetic_send",
            tools=("open_url",),
            constraints=(PlannerConstraintState("explicit_target_reference", "SATISFIED"),),
            registry=registry,
        )
        plan = DynamicPlanner().plan_dynamic(value)
        runtime = FakeGovernedDynamicRuntime()
        with tempfile.TemporaryDirectory() as directory:
            coordinator = coordinator_for(
                value,
                catalog,
                skills,
                runtime,
                directory,
                risk_actions={"account.synthetic_send.v1": ("send_message",)},
            )
            task = coordinator.admit_dynamic_plan(OWNER, plan, value)
            paused = coordinator.run_dynamic_step(task["task_id"], OWNER, now=100)
            compiled = coordinator.dynamic_compiled_step(task["task_id"], OWNER, plan.steps[0].step_id)
            authorization = coordinator.dynamic_risk_controller.authorize(
                compiled.risk_plan(), "confirmation.test54", now=101
            )
            completed = coordinator.run_dynamic_step(
                task["task_id"], OWNER, authorization=authorization, now=102
            )
        self.assertEqual("CONFIRMATION_REQUIRED", paused["failure_category"])
        self.assertEqual(0, paused["executor_invocation_count"])
        self.assertEqual("DONE", completed["status"])
        self.assertEqual(1, len(runtime.executor_calls))


class DynamicPlanRuntimeNegativeTests(unittest.TestCase):
    def test_unknown_capability_is_blocked_before_runtime(self) -> None:
        value, catalog, skills = planner_input(
            "observe",
            tools=("describe_screen",),
            constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
        )
        plan = DynamicPlanner().plan_dynamic(value)
        forged = replace(plan, steps=(replace(plan.steps[0], capability_id="capability.forged.v1"),))
        runtime = FakeGovernedDynamicRuntime()
        with tempfile.TemporaryDirectory() as directory:
            coordinator = coordinator_for(value, catalog, skills, runtime, directory)
            result = coordinator.admit_dynamic_plan(OWNER, forged, value)
        self.assertEqual("BLOCKED", result["status"])
        self.assertEqual(0, len(runtime.executor_calls))

    def test_failed_dependency_never_executes_dependent_step(self) -> None:
        value, catalog, skills = planner_input(
            "verify_visible",
            tools=("describe_screen",),
            constraints=(
                PlannerConstraintState("fresh_screen_observation", "SATISFIED"),
                PlannerConstraintState("nonempty_query", "SATISFIED"),
            ),
        )
        plan = DynamicPlanner().plan_dynamic(value)
        runtime = FakeGovernedDynamicRuntime()
        runtime.execution_results.append(
            DynamicExecutionEvidence("FAILED", "execution.test54.failed", "execution_failed", False)
        )
        with tempfile.TemporaryDirectory() as directory:
            coordinator = coordinator_for(value, catalog, skills, runtime, directory)
            task = coordinator.admit_dynamic_plan(OWNER, plan, value)
            first = coordinator.run_dynamic_step(task["task_id"], OWNER)
            second = coordinator.run_dynamic_step(task["task_id"], OWNER)
        self.assertEqual("FAILED", first["step_state"])
        self.assertEqual("DEPENDENCY_FAILED", second["failure_category"])
        self.assertEqual(1, len(runtime.executor_calls))

    def test_malformed_runtime_result_fails_closed(self) -> None:
        class MalformedRuntime(FakeGovernedDynamicRuntime):
            def execute_dynamic_step(self, step):
                self.executor_calls.append(step)
                return {"status": "passed", "raw": "model output"}

        value, catalog, skills = planner_input(
            "observe",
            tools=("describe_screen",),
            constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
        )
        plan = DynamicPlanner().plan_dynamic(value)
        runtime = MalformedRuntime()
        with tempfile.TemporaryDirectory() as directory:
            coordinator = coordinator_for(value, catalog, skills, runtime, directory)
            task = coordinator.admit_dynamic_plan(OWNER, plan, value)
            result = coordinator.run_dynamic_step(task["task_id"], OWNER)
        self.assertEqual("BLOCKED", result["status"])
        self.assertEqual("INVALID_RUNTIME_EVIDENCE", result["failure_category"])

    def test_missing_or_malformed_verifier_result_fails_closed(self) -> None:
        class MissingVerifierRuntime(FakeGovernedDynamicRuntime):
            def verify_dynamic_step(self, step, execution, observation):
                self.verifier_calls.append(step)
                return {"passed": True, "authority": "forged"}

        value, catalog, skills = planner_input(
            "observe",
            tools=("describe_screen",),
            constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
        )
        runtime = MissingVerifierRuntime()
        with tempfile.TemporaryDirectory() as directory:
            coordinator = coordinator_for(value, catalog, skills, runtime, directory)
            task = coordinator.admit_dynamic_plan(OWNER, DynamicPlanner().plan_dynamic(value), value)
            result = coordinator.run_dynamic_step(task["task_id"], OWNER)
        self.assertEqual("BLOCKED", result["status"])
        self.assertEqual("INVALID_RUNTIME_EVIDENCE", result["failure_category"])
        self.assertEqual(1, len(runtime.verifier_calls))

    def test_unknown_side_effect_blocks_without_retry_or_replan(self) -> None:
        value, catalog, skills = planner_input(
            "observe",
            tools=("describe_screen",),
            constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
        )
        runtime = FakeGovernedDynamicRuntime()
        runtime.execution_results.append(
            DynamicExecutionEvidence(
                "UNKNOWN_SIDE_EFFECT",
                "execution.test54.unknown",
                "dispatch_response_unavailable",
                False,
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            coordinator = coordinator_for(value, catalog, skills, runtime, directory)
            task = coordinator.admit_dynamic_plan(OWNER, DynamicPlanner().plan_dynamic(value), value)
            first = coordinator.run_dynamic_step(task["task_id"], OWNER)
            second = coordinator.run_dynamic_step(task["task_id"], OWNER)
        self.assertEqual("UNKNOWN_SIDE_EFFECT", first["failure_category"])
        self.assertFalse(first["replan_requested"])
        self.assertEqual("BLOCKED", second["status"])
        self.assertEqual(1, len(runtime.executor_calls))

    def test_replan_bound_becomes_terminal(self) -> None:
        value, catalog, skills = planner_input(
            "observe",
            tools=("describe_screen",),
            constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
            with_methods=True,
        )
        runtime = FakeGovernedDynamicRuntime()
        runtime.verification_results.extend(
            DynamicVerificationEvidence(False, "verification.test54.failed", "verification_failed", True)
            for _ in range(3)
        )
        with tempfile.TemporaryDirectory() as directory:
            coordinator = coordinator_for(value, catalog, skills, runtime, directory)
            task = coordinator.admit_dynamic_plan(OWNER, DynamicPlanner().plan_dynamic(value), value)
            for version in (2, 3):
                coordinator.run_dynamic_step(task["task_id"], OWNER)
                coordinator.replan_dynamic_task(
                    task["task_id"],
                    OWNER,
                    DynamicPlanner(),
                    value,
                    fresh_observation_ref="observation.test54.%03d" % version,
                    context_version=version,
                )
            coordinator.run_dynamic_step(task["task_id"], OWNER)
            terminal = coordinator.replan_dynamic_task(
                task["task_id"],
                OWNER,
                DynamicPlanner(),
                value,
                fresh_observation_ref="observation.test54.004",
                context_version=4,
            )
        self.assertEqual("FAILED", terminal["status"])
        self.assertEqual("RETRY_LIMIT_REACHED", terminal["failure_category"])
        self.assertEqual(3, len(runtime.executor_calls))


class DynamicPlanRuntimeE2ETests(unittest.TestCase):
    def test_typed_planner_to_coordinator_risk_executor_observation_verifier(self) -> None:
        value, catalog, skills = planner_input(
            "observe",
            tools=("describe_screen",),
            constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
            with_methods=True,
        )
        runtime = FakeGovernedDynamicRuntime()
        with tempfile.TemporaryDirectory() as directory:
            coordinator = coordinator_for(value, catalog, skills, runtime, directory)
            plan = DynamicPlanner().plan_dynamic(value)
            admitted = coordinator.admit_dynamic_plan(OWNER, plan, value)
            completed = coordinator.run_dynamic_step(
                admitted["task_id"],
                OWNER,
                expected_plan_id=plan.plan_id,
                expected_revision=1,
            )
        self.assertEqual("DONE", completed["status"])
        self.assertEqual("allowed", completed["risk_decision"])
        self.assertEqual("PASSED", completed["verification_result"])
        self.assertEqual(1, completed["executor_invocation_count"])
        self.assertEqual(1, len(runtime.observer_calls))


class DynamicPlanRuntimeSecurityTests(unittest.TestCase):
    def test_forged_skill_and_semantic_action_are_blocked(self) -> None:
        value, catalog, skills = planner_input(
            "observe",
            tools=("describe_screen",),
            constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
        )
        plan = DynamicPlanner().plan_dynamic(value)
        variants = (
            replace(plan, steps=(replace(plan.steps[0], skill_id="skill.forged.v1"),)),
            replace(plan, steps=(replace(plan.steps[0], semantic_action="run_shell"),)),
        )
        for forged in variants:
            with self.subTest(step=forged.steps[0]), tempfile.TemporaryDirectory() as directory:
                runtime = FakeGovernedDynamicRuntime()
                coordinator = coordinator_for(value, catalog, skills, runtime, directory)
                result = coordinator.admit_dynamic_plan(OWNER, forged, value)
                self.assertEqual("BLOCKED", result["status"])
                self.assertEqual(0, len(runtime.executor_calls))

    def test_test52_missing_direct_authorization_never_invokes_executor(self) -> None:
        value, catalog, skills = planner_input(
            "search_current",
            tools=("describe_screen", "tap_element", "input_text", "press_key"),
            constraints=(
                PlannerConstraintState("fresh_screen_observation", "SATISFIED"),
                PlannerConstraintState("nonempty_query", "SATISFIED"),
                PlannerConstraintState("single_search_control", "SATISFIED"),
            ),
            authorization_facts=(
                PlannerAuthorizationFact("editable", "TRUE", "DERIVED", True),
                PlannerAuthorizationFact("secure_false", "TRUE", "DERIVED", True),
                PlannerAuthorizationFact("enabled", "TRUE", "DIRECT", True),
                PlannerAuthorizationFact("authorization_grade_visible", "TRUE", "DERIVED", True),
                PlannerAuthorizationFact("actionable", "TRUE", "DERIVED", True),
            ),
        )
        plan = DynamicPlanner().plan_dynamic(value)
        runtime = FakeGovernedDynamicRuntime()
        with tempfile.TemporaryDirectory() as directory:
            coordinator = coordinator_for(value, catalog, skills, runtime, directory)
            result = coordinator.admit_dynamic_plan(OWNER, plan, value)
        self.assertEqual("BLOCKED", result["status"])
        self.assertEqual(0, result["executor_invocation_count"])
        self.assertEqual(0, len(runtime.executor_calls))

    def test_forged_device_pass_metadata_does_not_authorize_input(self) -> None:
        with self.assertRaises(ValueError):
            PlannerAuthorizationFact("editable", "TRUE", "DEVICE_PASS", True)

    def test_verifier_false_cannot_be_forged_into_verified(self) -> None:
        value, catalog, skills = planner_input(
            "observe",
            tools=("describe_screen",),
            constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
        )
        runtime = FakeGovernedDynamicRuntime()
        runtime.verification_results.append(
            DynamicVerificationEvidence(False, "verification.test54.failed", "verification_failed", False)
        )
        with tempfile.TemporaryDirectory() as directory:
            coordinator = coordinator_for(value, catalog, skills, runtime, directory)
            task = coordinator.admit_dynamic_plan(OWNER, DynamicPlanner().plan_dynamic(value), value)
            result = coordinator.run_dynamic_step(task["task_id"], OWNER)
        self.assertEqual("FAILED", result["step_state"])
        self.assertNotEqual("DONE", result["status"])

    def test_failure_evidence_rejects_secret_like_content(self) -> None:
        with self.assertRaises(ValueError):
            DynamicExecutionEvidence("FAILED", "password=secret", "execution_failed", True)

    def test_coordinator_dynamic_path_has_no_mcp_or_tool_call_port(self) -> None:
        source = "\n".join((
            inspect.getsource(TaskCoordinator.admit_dynamic_plan),
            inspect.getsource(TaskCoordinator.run_dynamic_step),
            inspect.getsource(TaskCoordinator.replan_dynamic_task),
        ))
        for forbidden in ("MCPClient", "call_tool", "_execution_port", "PlanExecutor("):
            self.assertNotIn(forbidden, source)
        self.assertLess(source.index(".assess("), source.index(".execute_dynamic_step("))

    def test_dynamic_session_is_owner_isolated_and_restart_invalidated(self) -> None:
        value, catalog, skills = planner_input(
            "observe",
            tools=("describe_screen",),
            constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
        )
        runtime = FakeGovernedDynamicRuntime()
        with tempfile.TemporaryDirectory() as directory:
            coordinator = coordinator_for(value, catalog, skills, runtime, directory)
            task = coordinator.admit_dynamic_plan(OWNER, DynamicPlanner().plan_dynamic(value), value)
            with self.assertRaises(CoordinatorOwnershipError):
                coordinator.inspect_dynamic_task(task["task_id"], "different-owner-token-987654321")
            recovery = coordinator.recover_after_restart(now=100)
            with self.assertRaises(CoordinatorStateError):
                coordinator.inspect_dynamic_task(task["task_id"], OWNER)
        self.assertEqual([], recovery["device_actions_sent"])
        self.assertEqual(0, len(runtime.executor_calls))


if __name__ == "__main__":
    unittest.main(verbosity=2)
