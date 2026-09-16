#!/usr/bin/env python3
"""TEST-55 host gates for governed Dynamic Plan capability binding."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any

from phoneharness_agent import (
    ActionObligationLedger,
    BoundInstalledApp,
    CapabilityBindingPolicyError,
    CapabilityCatalog,
    CapabilityEvidence,
    CapabilityMethodDefinition,
    CapabilityMethodRegistry,
    CompiledDynamicPlanStep,
    CoordinatorStateStore,
    DynamicExecutionEvidence,
    DynamicObservationEvidence,
    DynamicPlanRuntimeCompiler,
    DynamicPlanner,
    DynamicStepStateMachine,
    GovernedCapabilityBindingRuntime,
    InstalledAppLaunchCapabilityArguments,
    InstalledAppLaunchBindingStore,
    MapLinkAdapter,
    MCPCallError,
    MCPClient,
    PlannerAuthorizationFact,
    PlannerConstraintState,
    PlannerInput,
    PublicMapsCapabilityArguments,
    RiskController,
    ScreenObservationCapabilityArguments,
    SkillRegistry,
    TaskCoordinator,
)


OWNER = "owner-token-test55-123456789"
PERMISSIONS = ("mcp.read_screen", "mcp.foreground_interaction")
PLATFORMS = ("macos_host", "ios_mcp")


class UnusedReadOnlyRuntime:
    def prepare_goal(self, _goal: str):
        raise AssertionError("legacy coordinator route is not used")


class FakeGovernedTransport(MCPClient):
    def __init__(self, *, verifier_passes: bool = True, lose_response: bool = False) -> None:
        super().__init__("http://unused.invalid")
        self.verifier_passes = verifier_passes
        self.lose_response = lose_response
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.frontmost = "example.fixture"

    def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.requests.append((method, dict(params)))
        if method == "tools/list":
            return {"tools": [
                {"name": "describe_screen", "inputSchema": {"required": []}},
                {"name": "open_url", "inputSchema": {"required": ["url"]}},
                {"name": "launch_app", "inputSchema": {"required": ["bundle_id"]}},
            ]}
        if method != "tools/call":
            raise AssertionError("unexpected MCP request")
        tool = str(params.get("name") or "")
        arguments = dict(params.get("arguments") or {})
        if tool == "open_url":
            self.frontmost = "com.apple.Maps" if self.verifier_passes else "example.other"
        elif tool == "launch_app":
            self.frontmost = str(arguments.get("bundle_id") or "") if self.verifier_passes else "example.other"
        elif tool != "describe_screen":
            raise AssertionError("unexpected tool")
        if self.lose_response and tool in {"open_url", "launch_app"}:
            raise MCPCallError("response unavailable")
        if tool == "describe_screen":
            return {"structuredContent": {
                "frontmost": {"name": "Fixture", "bundleId": self.frontmost},
                "element_count": 2,
                "source": "AX",
                "elements": [{"text": "Ready", "clickable": False}],
            }}
        return {"structuredContent": {"accepted": True}}


class RejectingExecutionRiskController(RiskController):
    def assess(self, plan: dict[str, Any], authorization: Any = None, **kwargs: Any) -> dict[str, Any]:
        return {
            "status": "blocked",
            "reason": "execution_time_policy_changed",
            "risk_level": "interaction",
        }


def method_definition(capability_id: str, method_id: str) -> CapabilityMethodDefinition:
    if capability_id == "capability.screen.observe.v1":
        method_type, risk, inputs, outputs, verifier = (
            "mcp", "read_only", (), ("semantic_observation",), "observation_nonempty"
        )
    elif capability_id == "capability.maps.open_native_link.v1":
        method_type, risk, inputs, outputs, verifier = (
            "native_capability_link", "interaction", ("public_destination",),
            ("url_dispatched", "maps_observed"), "frontmost_app_is"
        )
    else:
        method_type, risk, inputs, outputs, verifier = (
            "mcp", "interaction", ("runtime_app_binding",),
            ("launch_dispatched", "bound_app_observed"), "frontmost_bound_app"
        )
    return CapabilityMethodDefinition(
        method_id=method_id,
        capability_id=capability_id,
        name=method_id.replace(".", "_"),
        purpose="test55_governed_binding",
        version="1.0.0",
        method_type=method_type,
        source="built_in",
        lifecycle="ACTIVE",
        availability="available",
        required_permissions=("mcp.read_screen",) if risk == "read_only" else ("mcp.foreground_interaction",),
        risk_level=risk,
        input_schema=inputs,
        output_schema=outputs,
        verifier=verifier,
        platform_support=PLATFORMS,
        evidence=CapabilityEvidence(success_count=3, confidence=0.95, last_verified=100),
        verification_status="device_pass",
        latency_class="fast",
    )


def runtime_input(intent: str, *, method_id: str, constraints: tuple[PlannerConstraintState, ...]) -> PlannerInput:
    skills = SkillRegistry()
    catalog = CapabilityCatalog.from_skill_registry(skills)
    matching = next(skill for skill in skills.skills if intent in skill.intent_kinds)
    capability_id = "capability.%s" % matching.skill_id
    methods = CapabilityMethodRegistry(catalog, (method_definition(capability_id, method_id),))
    return PlannerInput.from_runtime(
        request_id="request.test55.%s" % intent,
        goal_class=intent,
        normalized_intent=intent,
        task_context_ref="context.test55.%s" % intent,
        context_version=1,
        capability_catalog=catalog,
        skill_registry=skills,
        method_registry=methods,
        available_tools=tuple(sorted(matching.allowed_tools)),
        available_permissions=PERMISSIONS,
        available_platforms=PLATFORMS,
        constraints=constraints,
    )


def build_runtime(
    planner_input: PlannerInput,
    client: FakeGovernedTransport | None = None,
    *,
    risk_controller: RiskController | None = None,
    method_override: CapabilityMethodDefinition | None = None,
    failed_health: bool = False,
) -> tuple[GovernedCapabilityBindingRuntime, ActionObligationLedger, InstalledAppLaunchBindingStore]:
    directory = tempfile.TemporaryDirectory()
    _TEMP_DIRECTORIES.append(directory)
    ledger = ActionObligationLedger(Path(directory.name))
    bindings = InstalledAppLaunchBindingStore()
    skills = SkillRegistry()
    catalog = CapabilityCatalog.from_skill_registry(skills)
    method_definitions = (method_override,) if method_override is not None else tuple(
        method_definition(item.capability_id, item.method_id) for item in planner_input.methods
    )
    methods = CapabilityMethodRegistry(catalog, method_definitions)
    if failed_health:
        methods.record_health(
            method_definitions[0].method_id,
            platform="ios_mcp",
            compatibility="compatible",
            verification_status="failed",
            passed=False,
            failure_category="verification_failed",
            validated_at=200,
        )
    runtime = GovernedCapabilityBindingRuntime(
        client or FakeGovernedTransport(),
        capability_catalog=catalog,
        skill_registry=skills,
        method_registry=methods,
        action_obligation_ledger=ledger,
        installed_app_launch_binding_store=bindings,
        risk_controller=risk_controller,
        available_permissions=PERMISSIONS,
        available_platforms=PLATFORMS,
    )
    return runtime, ledger, bindings


_TEMP_DIRECTORIES: list[tempfile.TemporaryDirectory[str]] = []


def coordinator(planner_input: PlannerInput, runtime: GovernedCapabilityBindingRuntime) -> tuple[TaskCoordinator, dict[str, Any], CompiledDynamicPlanStep]:
    plan = DynamicPlanner().plan_dynamic(planner_input)
    directory = tempfile.TemporaryDirectory()
    _TEMP_DIRECTORIES.append(directory)
    coordinator = TaskCoordinator(
        CoordinatorStateStore(Path(directory.name)),
        UnusedReadOnlyRuntime(),
        dynamic_runtime=runtime,
        dynamic_compiler=DynamicPlanRuntimeCompiler(
            CapabilityCatalog.from_skill_registry(SkillRegistry()),
            SkillRegistry(),
        ),
    )
    task = coordinator.admit_dynamic_plan(OWNER, plan, planner_input)
    step = coordinator.dynamic_compiled_step(task["task_id"], OWNER, plan.steps[-1].step_id)
    return coordinator, task, step


class GovernedCapabilityBindingUnitTests(unittest.TestCase):
    def tearDown(self) -> None:
        while _TEMP_DIRECTORIES:
            _TEMP_DIRECTORIES.pop().cleanup()

    def test_read_only_observation_reuses_planexecutor_ledger_and_verifier(self) -> None:
        planner_input = runtime_input(
            "observe", method_id="method.observe.test55.v1",
            constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
        )
        runtime, ledger, _ = build_runtime(planner_input)
        owner, task, step = coordinator(planner_input, runtime)
        runtime.bind_dynamic_step(
            step, task_id=task["task_id"], context_ref="context.test55.observe",
            context_version=1, parameters=ScreenObservationCapabilityArguments(),
        )

        result = owner.run_dynamic_step(task["task_id"], OWNER, expected_plan_id=step.plan_id, expected_revision=1)

        self.assertEqual("DONE", result["status"])
        self.assertEqual(1, runtime.plan_executor_invocation_count)
        self.assertEqual("VERIFIED", ledger.records()[0]["state"])
        self.assertEqual("PASSED", result["verification_result"])

    def test_maps_binding_selects_existing_maplink_adapter(self) -> None:
        planner_input = runtime_input(
            "map_link", method_id="method.maps.test55.v1",
            constraints=(PlannerConstraintState("nonempty_public_destination", "SATISFIED"),),
        )
        runtime, ledger, _ = build_runtime(planner_input)
        owner, task, step = coordinator(planner_input, runtime)
        summary = runtime.bind_dynamic_step(
            step, task_id=task["task_id"], context_ref="context.test55.maps",
            context_version=1, parameters=PublicMapsCapabilityArguments(MapLinkAdapter("KLIA")),
        )

        result = owner.run_dynamic_step(task["task_id"], OWNER, expected_revision=1)

        self.assertEqual("adapter.maps_legacy_link.v1", summary["adapter_id"])
        self.assertEqual("DONE", result["status"])
        self.assertEqual("VERIFIED", ledger.records()[0]["state"])

    def test_installed_app_uses_existing_one_time_binding(self) -> None:
        planner_input = runtime_input(
            "launch_installed_app", method_id="method.launch.test55.v1",
            constraints=(PlannerConstraintState("nonempty_query", "SATISFIED"),),
        )
        runtime, ledger, bindings = build_runtime(planner_input)
        owner, task, step = coordinator(planner_input, runtime)
        binding = bindings.bind_unique(
            {"apps": [{"name": "Fixture App", "bundle_id": "example.fixture"}]}, "Fixture App"
        )
        runtime.bind_dynamic_step(
            step, task_id=task["task_id"], context_ref="context.test55.launch",
            context_version=1, parameters=InstalledAppLaunchCapabilityArguments(binding),
        )

        result = owner.run_dynamic_step(task["task_id"], OWNER)

        self.assertEqual("DONE", result["status"])
        self.assertEqual("VERIFIED", ledger.records()[0]["state"])
        self.assertEqual(1, runtime.plan_executor_invocation_count)

    def test_executor_success_but_verifier_failure_requires_replan(self) -> None:
        planner_input = runtime_input(
            "map_link", method_id="method.maps.test55.v1",
            constraints=(PlannerConstraintState("nonempty_public_destination", "SATISFIED"),),
        )
        runtime, _, _ = build_runtime(planner_input, FakeGovernedTransport(verifier_passes=False))
        owner, task, step = coordinator(planner_input, runtime)
        runtime.bind_dynamic_step(
            step, task_id=task["task_id"], context_ref="context.test55.maps",
            context_version=1, parameters=PublicMapsCapabilityArguments(MapLinkAdapter("KLIA")),
        )

        result = owner.run_dynamic_step(task["task_id"], OWNER)

        self.assertEqual("REPLAN_REQUIRED", result["status"])
        self.assertEqual("VERIFICATION_FAILED", result["failure_category"])
        self.assertEqual("FAILED", result["verification_result"])

    def test_missing_binding_fails_before_planexecutor(self) -> None:
        planner_input = runtime_input(
            "observe", method_id="method.observe.test55.v1",
            constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
        )
        runtime, _, _ = build_runtime(planner_input)
        owner, task, _ = coordinator(planner_input, runtime)

        result = owner.run_dynamic_step(task["task_id"], OWNER)

        self.assertEqual("REPLAN_REQUIRED", result["status"])
        self.assertEqual("CAPABILITY_BINDING_FAILED", result["failure_category"])
        self.assertEqual(0, runtime.plan_executor_invocation_count)

    def test_stale_context_binding_fails_closed(self) -> None:
        planner_input = runtime_input(
            "observe", method_id="method.observe.test55.v1",
            constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
        )
        runtime, _, _ = build_runtime(planner_input)
        owner, task, step = coordinator(planner_input, runtime)
        runtime.bind_dynamic_step(
            step, task_id=task["task_id"], context_ref="context.test55.observe",
            context_version=2, parameters=ScreenObservationCapabilityArguments(),
        )

        result = owner.run_dynamic_step(task["task_id"], OWNER)

        self.assertEqual("STALE_EXECUTION_EVIDENCE", result["failure_category"])
        self.assertEqual(0, runtime.plan_executor_invocation_count)

    def test_unknown_and_extra_parameters_are_rejected(self) -> None:
        planner_input = runtime_input(
            "observe", method_id="method.observe.test55.v1",
            constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
        )
        runtime, _, _ = build_runtime(planner_input)
        _, task, step = coordinator(planner_input, runtime)
        for value in ({}, {"tool_name": "launch_app"}, {"command": "delete all"}):
            with self.assertRaises(CapabilityBindingPolicyError):
                runtime.bind_dynamic_step(
                    step, task_id=task["task_id"], context_ref="context.test55.observe",
                    context_version=1, parameters=value,
                )

    def test_adapter_capability_mismatch_is_rejected(self) -> None:
        planner_input = runtime_input(
            "observe", method_id="method.observe.test55.v1",
            constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
        )
        runtime, _, _ = build_runtime(planner_input)
        _, task, step = coordinator(planner_input, runtime)
        with self.assertRaises(CapabilityBindingPolicyError):
            runtime.bind_dynamic_step(
                step, task_id=task["task_id"], context_ref="context.test55.observe",
                context_version=1, parameters=PublicMapsCapabilityArguments(MapLinkAdapter("KLIA")),
            )

    def test_forged_adapter_or_verifier_cannot_be_selected(self) -> None:
        planner_input = runtime_input(
            "map_link", method_id="method.maps.test55.v1",
            constraints=(PlannerConstraintState("nonempty_public_destination", "SATISFIED"),),
        )
        runtime, _, _ = build_runtime(planner_input)
        _, task, step = coordinator(planner_input, runtime)
        with self.assertRaises(CapabilityBindingPolicyError):
            runtime.bind_dynamic_step(
                replace(step, verification_requirement="observation_nonempty"),
                task_id=task["task_id"], context_ref="context.test55.maps", context_version=1,
                parameters=PublicMapsCapabilityArguments(MapLinkAdapter("KLIA")),
                adapter_id="adapter.attacker.v1",
            )

    def test_unknown_capability_and_missing_method_fail_closed(self) -> None:
        planner_input = runtime_input(
            "observe", method_id="method.observe.test55.v1",
            constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
        )
        runtime, _, _ = build_runtime(planner_input)
        _, task, step = coordinator(planner_input, runtime)
        for forged in (replace(step, capability_id="capability.forged.v1"), replace(step, method_id="method.missing.v1")):
            with self.assertRaises(CapabilityBindingPolicyError):
                runtime.bind_dynamic_step(
                    forged, task_id=task["task_id"], context_ref="context.test55.observe",
                    context_version=1, parameters=ScreenObservationCapabilityArguments(),
                )

    def test_cross_task_binding_is_rejected_before_executor(self) -> None:
        planner_input = runtime_input(
            "observe", method_id="method.observe.test55.v1",
            constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
        )
        runtime, _, _ = build_runtime(planner_input)
        owner, task, step = coordinator(planner_input, runtime)
        runtime.bind_dynamic_step(
            step, task_id="dynamic.task.other", context_ref="context.test55.observe",
            context_version=1, parameters=ScreenObservationCapabilityArguments(),
        )

        result = owner.run_dynamic_step(task["task_id"], OWNER)

        self.assertEqual("STALE_EXECUTION_EVIDENCE", result["failure_category"])
        self.assertEqual(0, runtime.plan_executor_invocation_count)

    def test_test52_semantic_input_cannot_bind_through_observation_authority(self) -> None:
        planner_input = runtime_input(
            "observe", method_id="method.observe.test55.v1",
            constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
        )
        runtime, _, _ = build_runtime(planner_input)
        _, task, step = coordinator(planner_input, runtime)
        forged = replace(
            step,
            semantic_action="search_current_screen",
            capability_id="capability.browser.search_current_page.v1",
            skill_id="browser.search_current_page.v1",
            required_tools=("input_text", "press_key", "tap_element"),
            allowed_tools=("input_text", "press_key", "tap_element"),
            verification_requirement="visible_text_contains",
            risk_class="interaction",
        )
        with self.assertRaises(CapabilityBindingPolicyError):
            runtime.bind_dynamic_step(
                forged, task_id=task["task_id"], context_ref="context.test55.search",
                context_version=1, parameters=ScreenObservationCapabilityArguments(),
            )
        self.assertEqual(0, runtime.plan_executor_invocation_count)

    def test_public_summaries_and_ledger_do_not_leak_arguments(self) -> None:
        secret = "Private Destination Fixture"
        planner_input = runtime_input(
            "map_link", method_id="method.maps.test55.v1",
            constraints=(PlannerConstraintState("nonempty_public_destination", "SATISFIED"),),
        )
        runtime, ledger, _ = build_runtime(planner_input)
        owner, task, step = coordinator(planner_input, runtime)
        summary = runtime.bind_dynamic_step(
            step, task_id=task["task_id"], context_ref="context.test55.maps",
            context_version=1, parameters=PublicMapsCapabilityArguments(MapLinkAdapter(secret)),
        )
        result = owner.run_dynamic_step(task["task_id"], OWNER)

        rendered = repr(summary) + repr(result) + repr(ledger.records())
        self.assertNotIn(secret, rendered)
        self.assertNotIn("maps.apple.com", rendered)
        self.assertNotIn("url", rendered.casefold())

    def test_lost_mutation_response_preserves_unknown_side_effect(self) -> None:
        planner_input = runtime_input(
            "map_link", method_id="method.maps.test55.v1",
            constraints=(PlannerConstraintState("nonempty_public_destination", "SATISFIED"),),
        )
        runtime, ledger, _ = build_runtime(planner_input, FakeGovernedTransport(lose_response=True))
        owner, task, step = coordinator(planner_input, runtime)
        runtime.bind_dynamic_step(
            step, task_id=task["task_id"], context_ref="context.test55.maps",
            context_version=1, parameters=PublicMapsCapabilityArguments(MapLinkAdapter("KLIA")),
        )

        result = owner.run_dynamic_step(task["task_id"], OWNER)

        self.assertEqual("BLOCKED", result["status"])
        self.assertEqual("UNKNOWN_SIDE_EFFECT", result["failure_category"])
        self.assertEqual("UNKNOWN_SIDE_EFFECT", ledger.records()[0]["state"])

    def test_host_execution_does_not_mutate_method_health(self) -> None:
        planner_input = runtime_input(
            "observe", method_id="method.observe.test55.v1",
            constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
        )
        runtime, _, _ = build_runtime(planner_input)
        owner, task, step = coordinator(planner_input, runtime)
        runtime.bind_dynamic_step(
            step, task_id=task["task_id"], context_ref="context.test55.observe",
            context_version=1, parameters=ScreenObservationCapabilityArguments(),
        )
        owner.run_dynamic_step(task["task_id"], OWNER)
        self.assertEqual([], runtime.method_health_effects())

    def test_execution_time_risk_change_blocks_before_transport_call(self) -> None:
        planner_input = runtime_input(
            "map_link", method_id="method.maps.test55.v1",
            constraints=(PlannerConstraintState("nonempty_public_destination", "SATISFIED"),),
        )
        client = FakeGovernedTransport()
        runtime, ledger, _ = build_runtime(
            planner_input,
            client,
            risk_controller=RejectingExecutionRiskController(),
        )
        owner, task, step = coordinator(planner_input, runtime)
        runtime.bind_dynamic_step(
            step, task_id=task["task_id"], context_ref="context.test55.maps",
            context_version=1, parameters=PublicMapsCapabilityArguments(MapLinkAdapter("KLIA")),
        )

        result = owner.run_dynamic_step(task["task_id"], OWNER)

        self.assertEqual("BLOCKED", result["status"])
        self.assertEqual("NOT_AUTHORIZED", result["failure_category"])
        self.assertEqual([], [request for request in client.requests if request[0] == "tools/call"])
        self.assertEqual((), ledger.records())

    def test_cross_action_verification_evidence_is_rejected(self) -> None:
        planner_input = runtime_input(
            "observe", method_id="method.observe.test55.v1",
            constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
        )
        runtime, _, _ = build_runtime(planner_input)
        _, task, step = coordinator(planner_input, runtime)
        runtime.bind_dynamic_step(
            step, task_id=task["task_id"], context_ref="context.test55.observe",
            context_version=1, parameters=ScreenObservationCapabilityArguments(),
        )
        execution = runtime.execute_governed_dynamic_step(step)
        observation = runtime.observe_dynamic_step(step)
        forged_execution = DynamicExecutionEvidence("PASSED", "execution.test55.unrelated", None, False)
        forged_observation = DynamicObservationEvidence("AVAILABLE", "observation.test55.unrelated")

        self.assertEqual(
            "stale_execution_evidence",
            runtime.verify_dynamic_step(step, forged_execution, observation).failure_category,
        )
        self.assertEqual(
            "stale_execution_evidence",
            runtime.verify_dynamic_step(step, execution, forged_observation).failure_category,
        )

    def test_expired_target_evidence_is_rejected_before_planexecutor(self) -> None:
        planner_input = runtime_input(
            "launch_installed_app", method_id="method.launch.test55.v1",
            constraints=(PlannerConstraintState("nonempty_query", "SATISFIED"),),
        )
        runtime, _, bindings = build_runtime(planner_input)
        owner, task, step = coordinator(planner_input, runtime)
        current = bindings.bind_unique(
            {"apps": [{"name": "Fixture App", "bundle_id": "example.fixture"}]}, "Fixture App"
        )
        expired = replace(current, expires_at=0)
        runtime.bind_dynamic_step(
            step, task_id=task["task_id"], context_ref="context.test55.launch",
            context_version=1, parameters=InstalledAppLaunchCapabilityArguments(expired),
        )

        result = owner.run_dynamic_step(task["task_id"], OWNER, now=100)

        self.assertEqual("STALE_TARGET_EVIDENCE", result["failure_category"])
        self.assertEqual(0, runtime.plan_executor_invocation_count)

    def test_unverified_dependency_is_rejected_by_binding_preflight(self) -> None:
        planner_input = runtime_input(
            "observe", method_id="method.observe.test55.v1",
            constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
        )
        runtime, _, _ = build_runtime(planner_input)
        _, task, step = coordinator(planner_input, runtime)
        dependent = replace(step, dependencies=("step.test55.dependency",))
        runtime.bind_dynamic_step(
            dependent, task_id=task["task_id"], context_ref="context.test55.observe",
            context_version=1, parameters=ScreenObservationCapabilityArguments(),
        )

        validation = runtime.validate_dynamic_step_binding(
            dependent,
            task_id=task["task_id"],
            context_version=1,
            verified_dependencies=(),
        )

        self.assertFalse(validation.eligible)
        self.assertEqual("dependency_not_verified", validation.failure_category)

    def test_method_platform_mismatch_is_rejected(self) -> None:
        planner_input = runtime_input(
            "observe", method_id="method.observe.test55.v1",
            constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
        )
        original = method_definition("capability.screen.observe.v1", "method.observe.test55.v1")
        incompatible = replace(original, platform_support=("watchos",))
        runtime, _, _ = build_runtime(planner_input, method_override=incompatible)
        _, task, step = coordinator(planner_input, runtime)

        with self.assertRaisesRegex(CapabilityBindingPolicyError, "method_unavailable"):
            runtime.bind_dynamic_step(
                step, task_id=task["task_id"], context_ref="context.test55.observe",
                context_version=1, parameters=ScreenObservationCapabilityArguments(),
            )

    def test_method_verifier_mismatch_is_rejected(self) -> None:
        planner_input = runtime_input(
            "observe", method_id="method.observe.test55.v1",
            constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
        )
        original = method_definition("capability.screen.observe.v1", "method.observe.test55.v1")
        incompatible = replace(original, verifier="visible_text_contains")
        runtime, _, _ = build_runtime(planner_input, method_override=incompatible)
        _, task, step = coordinator(planner_input, runtime)

        with self.assertRaisesRegex(CapabilityBindingPolicyError, "method_unavailable"):
            runtime.bind_dynamic_step(
                step, task_id=task["task_id"], context_ref="context.test55.observe",
                context_version=1, parameters=ScreenObservationCapabilityArguments(),
            )

    def test_failed_method_health_is_rejected_before_binding(self) -> None:
        planner_input = runtime_input(
            "observe", method_id="method.observe.test55.v1",
            constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
        )
        original = method_definition("capability.screen.observe.v1", "method.observe.test55.v1")
        runtime, _, _ = build_runtime(
            planner_input,
            method_override=original,
            failed_health=True,
        )
        _, task, step = coordinator(planner_input, runtime)

        with self.assertRaisesRegex(CapabilityBindingPolicyError, "method_unavailable"):
            runtime.bind_dynamic_step(
                step, task_id=task["task_id"], context_ref="context.test55.observe",
                context_version=1, parameters=ScreenObservationCapabilityArguments(),
            )

    def test_binding_is_one_time_and_cannot_be_replayed(self) -> None:
        planner_input = runtime_input(
            "observe", method_id="method.observe.test55.v1",
            constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
        )
        runtime, _, _ = build_runtime(planner_input)
        owner, task, step = coordinator(planner_input, runtime)
        runtime.bind_dynamic_step(
            step, task_id=task["task_id"], context_ref="context.test55.observe",
            context_version=1, parameters=ScreenObservationCapabilityArguments(),
        )
        owner.run_dynamic_step(task["task_id"], OWNER)

        with self.assertRaises(CapabilityBindingPolicyError):
            runtime.bind_dynamic_step(
                step, task_id=task["task_id"], context_ref="context.test55.observe",
                context_version=1, parameters=ScreenObservationCapabilityArguments(),
            )

    def test_adapter_has_no_authorization_or_verification_authority(self) -> None:
        for forbidden in ("assess", "authorize", "verify", "call_tool", "execute"):
            self.assertNotIn(forbidden, MapLinkAdapter.__dict__)
        self.assertEqual(
            "REPLAN_REQUIRED",
            DynamicStepStateMachine.transition("AWAITING_CONFIRMATION", "REPLAN_REQUIRED"),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
