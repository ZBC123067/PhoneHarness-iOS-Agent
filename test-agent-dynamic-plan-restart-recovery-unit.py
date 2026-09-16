#!/usr/bin/env python3
"""TEST-56 host gates for restart-safe Dynamic Plan recovery."""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any

from phoneharness_agent import (
    ActionObligationLedger,
    ActionObligationRequest,
    CapabilityCatalog,
    CapabilityEvidence,
    CapabilityMethodDefinition,
    CapabilityMethodRegistry,
    CoordinatorStateStore,
    DYNAMIC_PLAN_RECOVERY_VERSION,
    DynamicPlanRecoveryPolicyError,
    DynamicPlanRuntimeCompiler,
    DynamicPlanner,
    GovernedCapabilityBindingRuntime,
    MCPCallError,
    MCPClient,
    PlannerConstraintState,
    PlannerInput,
    RiskController,
    ScreenObservationCapabilityArguments,
    SkillRegistry,
    TaskCoordinator,
)


OWNER = "owner-token-test56-123456789"
PERMISSIONS = ("mcp.read_screen", "mcp.foreground_interaction")
PLATFORMS = ("macos_host", "ios_mcp")


class UnusedReadOnlyRuntime:
    def prepare_goal(self, _goal: str):
        raise AssertionError("legacy coordinator route is not used")


class RejectingRecoveryRiskController(RiskController):
    def assess(self, plan: dict[str, Any], authorization: Any = None, **kwargs: Any) -> dict[str, Any]:
        return {"status": "blocked", "reason": "recovery_policy_changed", "risk_level": "read_only"}


class FakeRecoveryTransport(MCPClient):
    def __init__(self, *, lose_response: bool = False, empty_observation: bool = False) -> None:
        super().__init__("http://unused.invalid")
        self.lose_response = lose_response
        self.empty_observation = empty_observation
        self.requests: list[str] = []

    def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "tools/list":
            return {"tools": [{"name": "describe_screen", "inputSchema": {"required": []}}]}
        if method != "tools/call":
            raise AssertionError("unexpected transport method")
        tool = str(params.get("name") or "")
        self.requests.append(tool)
        if self.lose_response:
            raise MCPCallError("simulated response loss")
        return {"structuredContent": {
            "frontmost": {"name": "Fixture", "bundleId": "example.fixture"},
            "element_count": 0 if self.empty_observation else 1,
            "source": "AX",
            "elements": [] if self.empty_observation else [{"text": "Ready", "clickable": False}],
        }}


def method_definition() -> CapabilityMethodDefinition:
    return CapabilityMethodDefinition(
        method_id="method.observe.test56.v1",
        capability_id="capability.screen.observe.v1",
        name="observe_test56",
        purpose="test56_restart_recovery",
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
        evidence=CapabilityEvidence(success_count=3, confidence=0.95, last_verified=100),
        verification_status="device_pass",
        latency_class="fast",
    )


def planner_fixture(*, revision: int = 1) -> tuple[PlannerInput, Any, CapabilityCatalog, SkillRegistry]:
    skills = SkillRegistry()
    catalog = CapabilityCatalog.from_skill_registry(skills)
    methods = CapabilityMethodRegistry(catalog, (method_definition(),))
    value = PlannerInput.from_runtime(
        request_id="request.test56.observe",
        goal_class="observe",
        normalized_intent="observe",
        task_context_ref="context.test56.observe",
        context_version=revision,
        capability_catalog=catalog,
        skill_registry=skills,
        method_registry=methods,
        available_tools=("describe_screen",),
        available_permissions=PERMISSIONS,
        available_platforms=PLATFORMS,
        constraints=(PlannerConstraintState("fresh_screen_observation", "SATISFIED"),),
    )
    if revision != 1:
        value = replace(value, planning_revision=revision, replan_count=revision - 1)
    return value, DynamicPlanner().plan_dynamic(value), catalog, skills


def runtime(catalog: CapabilityCatalog, skills: SkillRegistry, root: Path, *, lose_response: bool = False,
            empty_observation: bool = False,
            method: CapabilityMethodDefinition | None = None) -> tuple[GovernedCapabilityBindingRuntime, ActionObligationLedger]:
    ledger = ActionObligationLedger(root / "ledger")
    methods = CapabilityMethodRegistry(catalog, (method or method_definition(),))
    return GovernedCapabilityBindingRuntime(
        FakeRecoveryTransport(lose_response=lose_response, empty_observation=empty_observation),
        capability_catalog=catalog,
        skill_registry=skills,
        method_registry=methods,
        action_obligation_ledger=ledger,
        risk_controller=RiskController(),
        available_permissions=PERMISSIONS,
        available_platforms=PLATFORMS,
    ), ledger


def coordinator(root: Path, value: PlannerInput, catalog: CapabilityCatalog, skills: SkillRegistry,
                governed: GovernedCapabilityBindingRuntime,
                risk_controller: RiskController | None = None) -> TaskCoordinator:
    return TaskCoordinator(
        CoordinatorStateStore(root / "coordinator.json"),
        UnusedReadOnlyRuntime(),
        dynamic_runtime=governed,
        dynamic_compiler=DynamicPlanRuntimeCompiler(catalog, skills),
        dynamic_risk_controller=risk_controller,
    )


class DynamicPlanRecoveryUnitTests(unittest.TestCase):
    def test_admission_persists_safe_versioned_checkpoint_in_existing_store(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value, plan, catalog, skills = planner_fixture()
            governed, _ = runtime(catalog, skills, root)
            owner = coordinator(root, value, catalog, skills, governed)
            task = owner.admit_dynamic_plan(OWNER, plan, value, now=100)
            checkpoint = owner.store.get_dynamic_checkpoint(task["task_id"])
            raw = (root / "coordinator.json").read_text(encoding="utf-8")

        self.assertEqual(DYNAMIC_PLAN_RECOVERY_VERSION, checkpoint["recovery_version"])
        self.assertEqual("READY", checkpoint["status"])
        self.assertEqual(1, checkpoint["planning_revision"])
        self.assertNotIn("parameters", raw)
        for secret in ("password", "token", "otp", "screenshot", "raw_ocr", "adapter_class"):
            self.assertNotIn(secret, raw.casefold())

    def test_restart_before_execution_rebinds_read_only_and_resumes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value, plan, catalog, skills = planner_fixture()
            first_runtime, _ = runtime(catalog, skills, root)
            first = coordinator(root, value, catalog, skills, first_runtime)
            task = first.admit_dynamic_plan(OWNER, plan, value, now=100)
            del first, first_runtime

            second_runtime, _ = runtime(catalog, skills, root)
            second = coordinator(root, value, catalog, skills, second_runtime)
            recovered = second.recover_dynamic_plan(
                task["task_id"], OWNER, plan, value, now=110
            )
            self.assertEqual(0, second_runtime.plan_executor_invocation_count)
            completed = second.run_dynamic_step(task["task_id"], OWNER, now=111)

        self.assertEqual("RESUME_READY", recovered["recovery_decision"])
        self.assertEqual("DONE", completed["status"])
        self.assertEqual(1, second_runtime.plan_executor_invocation_count)

    def test_restart_after_verified_step_does_not_duplicate_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value, plan, catalog, skills = planner_fixture()
            first_runtime, _ = runtime(catalog, skills, root)
            first = coordinator(root, value, catalog, skills, first_runtime)
            task = first.admit_dynamic_plan(OWNER, plan, value, now=100)
            step = first.dynamic_compiled_step(task["task_id"], OWNER, plan.steps[0].step_id)
            first_runtime.bind_dynamic_step(
                step, task_id=task["task_id"], context_ref=value.task_context_ref,
                context_version=value.context_version, parameters=ScreenObservationCapabilityArguments(),
            )
            self.assertEqual("DONE", first.run_dynamic_step(task["task_id"], OWNER, now=101)["status"])

            second_runtime, _ = runtime(catalog, skills, root)
            second = coordinator(root, value, catalog, skills, second_runtime)
            recovered = second.recover_dynamic_plan(task["task_id"], OWNER, plan, value, now=110)
            after = second.run_dynamic_step(task["task_id"], OWNER, now=111)

        self.assertEqual("ALREADY_VERIFIED", recovered["recovery_decision"])
        self.assertEqual("DONE", after["status"])
        self.assertEqual(0, second_runtime.plan_executor_invocation_count)

    def test_unknown_execution_outcome_never_blindly_retries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value, plan, catalog, skills = planner_fixture()
            first_runtime, _ = runtime(catalog, skills, root, lose_response=True)
            first = coordinator(root, value, catalog, skills, first_runtime)
            task = first.admit_dynamic_plan(OWNER, plan, value, now=100)
            step = first.dynamic_compiled_step(task["task_id"], OWNER, plan.steps[0].step_id)
            first_runtime.bind_dynamic_step(
                step, task_id=task["task_id"], context_ref=value.task_context_ref,
                context_version=value.context_version, parameters=ScreenObservationCapabilityArguments(),
            )
            self.assertEqual("UNKNOWN_SIDE_EFFECT", first.run_dynamic_step(task["task_id"], OWNER, now=101)["failure_category"])

            second_runtime, ledger = runtime(catalog, skills, root)
            second = coordinator(root, value, catalog, skills, second_runtime)
            recovered = second.recover_dynamic_plan(task["task_id"], OWNER, plan, value, now=110)
            ledger_states = [record["state"] for record in ledger.records()]

        self.assertEqual("EXECUTION_OUTCOME_UNKNOWN", recovered["recovery_decision"])
        self.assertEqual(0, second_runtime.plan_executor_invocation_count)
        self.assertIn("UNKNOWN_SIDE_EFFECT", ledger_states)

    def test_stale_plan_revision_and_changed_method_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value, plan, catalog, skills = planner_fixture()
            first_runtime, _ = runtime(catalog, skills, root)
            first = coordinator(root, value, catalog, skills, first_runtime)
            task = first.admit_dynamic_plan(OWNER, plan, value, now=100)

            changed_method = replace(method_definition(), availability="unavailable")
            second_runtime, _ = runtime(catalog, skills, root, method=changed_method)
            second = coordinator(root, value, catalog, skills, second_runtime)
            unavailable = second.recover_dynamic_plan(task["task_id"], OWNER, plan, value, now=110)

            newer_value, newer_plan, _, _ = planner_fixture(revision=2)
            stale = second.recover_dynamic_plan(task["task_id"], OWNER, newer_plan, newer_value, now=111)

        self.assertEqual("REPLAN_REQUIRED", unavailable["recovery_decision"])
        self.assertEqual("METHOD_UNAVAILABLE", unavailable["failure_category"])
        self.assertEqual("STALE_PLAN_REVISION", stale["recovery_decision"])
        self.assertEqual(0, second_runtime.plan_executor_invocation_count)

    def test_confirmation_is_not_restored_as_authority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value, plan, catalog, skills = planner_fixture()
            governed, _ = runtime(catalog, skills, root)
            first = coordinator(root, value, catalog, skills, governed)
            task = first.admit_dynamic_plan(OWNER, plan, value, now=100)
            checkpoint = first.store.get_dynamic_checkpoint(task["task_id"])
            checkpoint["confirmation_state"] = "PREVIOUSLY_ALLOWED"
            with self.assertRaises(DynamicPlanRecoveryPolicyError):
                first.store.put_dynamic_checkpoint(checkpoint)

    def test_waiting_confirmation_checkpoint_requires_fresh_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value, plan, catalog, skills = planner_fixture()
            governed, _ = runtime(catalog, skills, root)
            first = coordinator(root, value, catalog, skills, governed)
            task = first.admit_dynamic_plan(OWNER, plan, value, now=100)
            checkpoint = first.store.get_dynamic_checkpoint(task["task_id"])
            checkpoint["status"] = "WAITING_CONFIRMATION"
            checkpoint["confirmation_state"] = "REQUIRED"
            checkpoint["step_records"][0]["state"] = "AWAITING_CONFIRMATION"
            checkpoint["integrity_digest"] = first.dynamic_checkpoint_digest(checkpoint)
            first.store.put_dynamic_checkpoint(checkpoint)

            second_runtime, _ = runtime(catalog, skills, root)
            second = coordinator(root, value, catalog, skills, second_runtime)
            recovered = second.recover_dynamic_plan(task["task_id"], OWNER, plan, value, now=110)

        self.assertEqual("CONFIRMATION_REQUIRED", recovered["recovery_decision"])
        self.assertEqual(0, second_runtime.plan_executor_invocation_count)
        self.assertFalse(recovered["automatic_retry_allowed"])

    def test_confirmed_execution_failure_recovers_to_replan_not_replay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value, plan, catalog, skills = planner_fixture()
            first_runtime, _ = runtime(catalog, skills, root, empty_observation=True)
            first = coordinator(root, value, catalog, skills, first_runtime)
            task = first.admit_dynamic_plan(OWNER, plan, value, now=100)
            step = first.dynamic_compiled_step(task["task_id"], OWNER, plan.steps[0].step_id)
            first_runtime.bind_dynamic_step(
                step, task_id=task["task_id"], context_ref=value.task_context_ref,
                context_version=value.context_version, parameters=ScreenObservationCapabilityArguments(),
            )
            failed = first.run_dynamic_step(task["task_id"], OWNER, now=101)
            self.assertEqual("REPLAN_REQUIRED", failed["status"])

            second_runtime, _ = runtime(catalog, skills, root)
            second = coordinator(root, value, catalog, skills, second_runtime)
            recovered = second.recover_dynamic_plan(task["task_id"], OWNER, plan, value, now=110)

        self.assertEqual("REPLAN_REQUIRED", recovered["recovery_decision"])
        self.assertEqual(0, second_runtime.plan_executor_invocation_count)

    def test_recovery_rejects_unknown_parameter_scope_before_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value, plan, catalog, skills = planner_fixture()
            first_runtime, _ = runtime(catalog, skills, root)
            first = coordinator(root, value, catalog, skills, first_runtime)
            task = first.admit_dynamic_plan(OWNER, plan, value, now=100)
            second_runtime, _ = runtime(catalog, skills, root)
            second = coordinator(root, value, catalog, skills, second_runtime)
            result = second.recover_dynamic_plan(
                task["task_id"], OWNER, plan, value,
                parameters_by_step={"step.attacker": {"command": "run"}}, now=110,
            )

        self.assertEqual("CHECKPOINT_INVALID", result["recovery_decision"])
        self.assertEqual(0, second_runtime.plan_executor_invocation_count)

    def test_recovery_risk_policy_change_blocks_before_binding_or_executor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value, plan, catalog, skills = planner_fixture()
            first_runtime, _ = runtime(catalog, skills, root)
            first = coordinator(root, value, catalog, skills, first_runtime)
            task = first.admit_dynamic_plan(OWNER, plan, value, now=100)

            second_runtime, _ = runtime(catalog, skills, root)
            second = coordinator(
                root, value, catalog, skills, second_runtime, RejectingRecoveryRiskController()
            )
            result = second.recover_dynamic_plan(task["task_id"], OWNER, plan, value, now=110)

        self.assertEqual("RECOVERY_BLOCKED", result["recovery_decision"])
        self.assertEqual("NOT_AUTHORIZED", result["failure_category"])
        self.assertEqual(0, second_runtime.plan_executor_invocation_count)
        self.assertEqual([], second_runtime.method_health_effects())


class DynamicPlanRecoveryNegativeSecurityTests(unittest.TestCase):
    def test_checkpoint_tampering_and_unknown_schema_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value, plan, catalog, skills = planner_fixture()
            governed, _ = runtime(catalog, skills, root)
            first = coordinator(root, value, catalog, skills, governed)
            task = first.admit_dynamic_plan(OWNER, plan, value, now=100)
            path = root / "coordinator.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["dynamic_plan_checkpoints"][task["task_id"]]["planning_revision"] = 99
            path.write_text(json.dumps(payload), encoding="utf-8")

            restarted_runtime, _ = runtime(catalog, skills, root)
            restarted = coordinator(root, value, catalog, skills, restarted_runtime)
            result = restarted.recover_dynamic_plan(task["task_id"], OWNER, plan, value, now=110)
            self.assertEqual("CHECKPOINT_INVALID", result["recovery_decision"])
            self.assertEqual(0, restarted_runtime.plan_executor_invocation_count)

            payload["dynamic_plan_checkpoints"][task["task_id"]]["schema_version"] = "999.0"
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = restarted.recover_dynamic_plan(task["task_id"], OWNER, plan, value, now=111)
            self.assertEqual("CHECKPOINT_INVALID", result["recovery_decision"])

    def test_adapter_or_command_injection_cannot_enter_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CoordinatorStateStore(Path(directory) / "coordinator.json")
            for field in ("adapter_class", "command", "tool_args", "password", "token"):
                with self.assertRaises(DynamicPlanRecoveryPolicyError):
                    store.put_dynamic_checkpoint({field: "attacker.value"})

    def test_forged_verified_state_without_ledger_verifier_correlation_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value, plan, catalog, skills = planner_fixture()
            governed, _ = runtime(catalog, skills, root)
            first = coordinator(root, value, catalog, skills, governed)
            task = first.admit_dynamic_plan(OWNER, plan, value, now=100)
            checkpoint = first.store.get_dynamic_checkpoint(task["task_id"])
            checkpoint["step_records"][0]["state"] = "VERIFIED"
            checkpoint["status"] = "DONE"
            checkpoint["integrity_digest"] = first.dynamic_checkpoint_digest(checkpoint)
            with self.assertRaises(DynamicPlanRecoveryPolicyError):
                first.store.put_dynamic_checkpoint(checkpoint)

    def test_test52_authorization_cannot_be_laundered_through_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value, plan, catalog, skills = planner_fixture()
            governed, _ = runtime(catalog, skills, root)
            first = coordinator(root, value, catalog, skills, governed)
            task = first.admit_dynamic_plan(OWNER, plan, value, now=100)
            checkpoint = first.store.get_dynamic_checkpoint(task["task_id"])
            step = checkpoint["step_records"][0]
            step["capability_id"] = "capability.browser.search_current_page.v1"
            step["required_tools"] = ["input_text", "press_key", "tap_element"]
            checkpoint["integrity_digest"] = first.dynamic_checkpoint_digest(checkpoint)
            with self.assertRaises(DynamicPlanRecoveryPolicyError):
                first.store.put_dynamic_checkpoint(checkpoint)

    def test_cross_plan_ledger_reference_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value, plan, catalog, skills = planner_fixture()
            governed, _ = runtime(catalog, skills, root)
            first = coordinator(root, value, catalog, skills, governed)
            task = first.admit_dynamic_plan(OWNER, plan, value, now=100)
            checkpoint = first.store.get_dynamic_checkpoint(task["task_id"])
            checkpoint["step_records"][0]["ledger_ref"] = "obligation.crossplan.forged"
            checkpoint["integrity_digest"] = first.dynamic_checkpoint_digest(checkpoint)
            first.store.put_dynamic_checkpoint(checkpoint)

            restarted_runtime, _ = runtime(catalog, skills, root)
            restarted = coordinator(root, value, catalog, skills, restarted_runtime)
            result = restarted.recover_dynamic_plan(task["task_id"], OWNER, plan, value, now=110)

        self.assertEqual("CHECKPOINT_INVALID", result["recovery_decision"])
        self.assertEqual(0, restarted_runtime.plan_executor_invocation_count)

    def test_retry_overflow_and_missing_dependency_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value, plan, catalog, skills = planner_fixture()
            governed, _ = runtime(catalog, skills, root)
            first = coordinator(root, value, catalog, skills, governed)
            task = first.admit_dynamic_plan(OWNER, plan, value, now=100)
            base = first.store.get_dynamic_checkpoint(task["task_id"])

            overflow = json.loads(json.dumps(base))
            overflow["replan_count"] = 3
            overflow["integrity_digest"] = first.dynamic_checkpoint_digest(overflow)
            with self.assertRaises(DynamicPlanRecoveryPolicyError):
                first.store.put_dynamic_checkpoint(overflow)

            missing = json.loads(json.dumps(base))
            missing["step_records"][0]["dependencies"] = ["step.missing"]
            missing["integrity_digest"] = first.dynamic_checkpoint_digest(missing)
            with self.assertRaises(DynamicPlanRecoveryPolicyError):
                first.store.put_dynamic_checkpoint(missing)

    def test_runtime_epoch_changes_but_adapter_object_is_never_serialized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value, plan, catalog, skills = planner_fixture()
            first_runtime, _ = runtime(catalog, skills, root)
            first = coordinator(root, value, catalog, skills, first_runtime)
            task = first.admit_dynamic_plan(OWNER, plan, value, now=100)
            before = first.store.get_dynamic_checkpoint(task["task_id"])

            second_runtime, _ = runtime(catalog, skills, root)
            second = coordinator(root, value, catalog, skills, second_runtime)
            second.recover_dynamic_plan(task["task_id"], OWNER, plan, value, now=110)
            after = second.store.get_dynamic_checkpoint(task["task_id"])
            raw = (root / "coordinator.json").read_text(encoding="utf-8")

        self.assertNotEqual(before["runtime_epoch"], after["runtime_epoch"])
        self.assertNotIn("MapLinkAdapter", raw)
        self.assertNotIn("_BoundDynamicCapability", raw)

    def test_dispatched_checkpoint_is_reconciled_to_unknown_without_replay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value, plan, catalog, skills = planner_fixture()
            first_runtime, ledger = runtime(catalog, skills, root)
            first = coordinator(root, value, catalog, skills, first_runtime)
            task = first.admit_dynamic_plan(OWNER, plan, value, now=100)
            step = first.dynamic_compiled_step(task["task_id"], OWNER, plan.steps[0].step_id)
            refs = first_runtime.expected_recovery_references(step)
            created = ledger.create(
                ActionObligationRequest(
                    obligation_ref=first_runtime._evidence_ref("dynamicbinding", step),
                    task_id=task["task_id"],
                    context_id=value.task_context_ref,
                    capability_id=step.capability_id,
                    method_id=str(step.method_id),
                    risk_level=step.risk_class,
                ),
                timestamp=101,
            )
            authorized = ledger.transition(
                created["obligation_id"], "AUTHORIZED", "risk_allowed",
                event_id="event.test56.dispatched.auth", timestamp=102,
            )
            ledger.transition(
                authorized["obligation_id"], "DISPATCHED", "dispatch_started",
                event_id="event.test56.dispatched.send", timestamp=103,
            )
            checkpoint = first.store.get_dynamic_checkpoint(task["task_id"])
            checkpoint["status"] = "RUNNING"
            checkpoint["executor_invocation_count"] = 1
            checkpoint["step_records"][0]["state"] = "EXECUTING"
            checkpoint["step_records"][0]["ledger_ref"] = refs["ledger_ref"]
            checkpoint["step_records"][0]["ledger_state"] = "DISPATCHED"
            checkpoint["integrity_digest"] = first.dynamic_checkpoint_digest(checkpoint)
            first.store.put_dynamic_checkpoint(checkpoint)

            second_runtime, second_ledger = runtime(catalog, skills, root)
            second = coordinator(root, value, catalog, skills, second_runtime)
            result = second.recover_dynamic_plan(task["task_id"], OWNER, plan, value, now=110)
            states = [record["state"] for record in second_ledger.records()]

        self.assertEqual("EXECUTION_OUTCOME_UNKNOWN", result["recovery_decision"])
        self.assertIn("UNKNOWN_SIDE_EFFECT", states)
        self.assertEqual(0, second_runtime.plan_executor_invocation_count)


if __name__ == "__main__":
    unittest.main(verbosity=2)
