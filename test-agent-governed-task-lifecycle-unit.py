#!/usr/bin/env python3
"""TEST-59 host gates for governed terminal acknowledgement and cleanup."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load fixture %s" % filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


T54 = _load("phoneharness_test54_fixtures", "test-agent-dynamic-plan-runtime-integration-unit.py")
T57 = _load("phoneharness_test57_fixtures", "test-agent-process-durability-recovery-unit.py")

from phoneharness_agent import (  # noqa: E402
    ActionObligationLedger,
    ActionObligationRequest,
    CapabilityCatalog,
    CapabilityEvidence,
    CapabilityMethodDefinition,
    CapabilityMethodRegistry,
    CoordinatorStateStore,
    DynamicExecutionEvidence,
    DynamicObservationEvidence,
    DynamicPlanRecoveryCheckpoint,
    DynamicPlanRuntimeCompiler,
    DynamicPlanner,
    DynamicVerificationEvidence,
    GovernedCapabilityBindingRuntime,
    PlannerConstraintState,
    PlannerInput,
    RiskController,
    SkillRegistry,
    TASK_LIFECYCLE_VERSION,
    TaskCoordinator,
)


OWNER = "owner-token-test59-123456789"
PERMISSIONS = ("mcp.read_screen", "mcp.foreground_interaction")
PLATFORMS = ("macos_host", "ios_mcp")


class UnusedRuntime:
    def prepare_goal(self, _goal: str):
        raise AssertionError("legacy route is not used")


class LifecycleRuntime:
    def __init__(self, ledger: ActionObligationLedger) -> None:
        self.ledger = ledger
        self.records: dict[tuple[str, int, str], dict[str, str | bool | None]] = {}
        self.verification_results: list[tuple[bool, bool]] = []
        self.unknown_next = False
        self.executor_calls = 0

    @staticmethod
    def _key(step):
        return (step.plan_id, step.planning_revision, step.step_id)

    def execute_dynamic_step(self, step):
        self.executor_calls += 1
        refs = GovernedCapabilityBindingRuntime.expected_recovery_references(step)
        record = self.ledger.create(
            ActionObligationRequest(
                obligation_ref=GovernedCapabilityBindingRuntime._evidence_ref("dynamicbinding", step),
                task_id=self.task_id,
                context_id=self.context_id,
                capability_id=step.capability_id,
                method_id=str(step.method_id),
                risk_level=step.risk_class,
            ),
            timestamp=1000 + self.executor_calls * 10,
        )
        record = self.ledger.transition(
            record["obligation_id"], "AUTHORIZED", "risk_allowed",
            event_id="event.test59.authorized.%d" % self.executor_calls,
            timestamp=1001 + self.executor_calls * 10,
        )
        record = self.ledger.transition(
            record["obligation_id"], "DISPATCHED", "dispatch_started",
            event_id="event.test59.dispatched.%d" % self.executor_calls,
            timestamp=1002 + self.executor_calls * 10,
        )
        self.records[self._key(step)] = {
            "ledger_ref": refs["ledger_ref"],
            "ledger_state": record["state"],
            "verification_ref": None,
        }
        if self.unknown_next:
            self.unknown_next = False
            return DynamicExecutionEvidence(
                "UNKNOWN_SIDE_EFFECT", "execution.test59.unknown", "dispatch_response_unavailable", False
            )
        return DynamicExecutionEvidence("PASSED", "execution.test59.%d" % self.executor_calls, None, False)

    def observe_dynamic_step(self, step):
        current = self.records[self._key(step)]
        record = self.ledger.transition(
            str(current["ledger_ref"]), "OBSERVING", "dispatch_response_received",
            event_id="event.test59.observing.%d" % self.executor_calls,
            timestamp=1003 + self.executor_calls * 10,
        )
        current["ledger_state"] = record["state"]
        return DynamicObservationEvidence("AVAILABLE", "observation.test59.%d" % self.executor_calls)

    def verify_dynamic_step(self, step, _execution, _observation):
        passed, recoverable = self.verification_results.pop(0) if self.verification_results else (True, False)
        current = self.records[self._key(step)]
        state = "VERIFIED" if passed else "FAILED"
        record = self.ledger.transition(
            str(current["ledger_ref"]), state,
            "verification_passed" if passed else "verification_failed",
            event_id="event.test59.verification.%d" % self.executor_calls,
            timestamp=1004 + self.executor_calls * 10,
        )
        current["ledger_state"] = record["state"]
        current["verification_ref"] = (
            GovernedCapabilityBindingRuntime.expected_recovery_references(step)["verification_ref"]
            if passed else None
        )
        return DynamicVerificationEvidence(
            passed,
            GovernedCapabilityBindingRuntime.expected_recovery_references(step)["verification_ref"],
            None if passed else "verification_failed",
            recoverable,
        )

    def dynamic_recovery_evidence(self, step):
        return dict(self.records.get(self._key(step), {
            "ledger_ref": None, "ledger_state": "NOT_CREATED", "verification_ref": None,
        }))

    def dynamic_recovery_ledger_records(self, task_id: str):
        return tuple(record for record in self.ledger.records() if record["task_id"] == task_id)

    @staticmethod
    def expected_recovery_references(step):
        return GovernedCapabilityBindingRuntime.expected_recovery_references(step)

    def method_health_effects(self):
        return []


def _method(capability_id: str, index: int) -> CapabilityMethodDefinition:
    return CapabilityMethodDefinition(
        method_id="method.test59.%d.%s" % (index, capability_id.split(".")[-2]),
        capability_id=capability_id,
        name="test59_method_%d" % index,
        purpose="test59_lifecycle",
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
        evidence=CapabilityEvidence(success_count=3, confidence=0.95 - index * 0.05, last_verified=100),
        verification_status="device_pass",
    )


def _fixture(root: Path, *, multi_step: bool = False):
    skills = SkillRegistry()
    catalog = CapabilityCatalog.from_skill_registry(skills)
    intent = "verify_visible" if multi_step else "observe"
    capability_ids = (
        ("capability.screen.observe.v1", "capability.screen.verify_visible_text.v1")
        if multi_step else ("capability.screen.observe.v1",)
    )
    methods = CapabilityMethodRegistry(
        catalog,
        tuple(_method(capability_id, index) for capability_id in capability_ids for index in range(1, 4)),
    )
    constraints = [PlannerConstraintState("fresh_screen_observation", "SATISFIED")]
    if multi_step:
        constraints.append(PlannerConstraintState("nonempty_query", "SATISFIED"))
    value = PlannerInput.from_runtime(
        request_id="request.test59.lifecycle",
        goal_class=intent,
        normalized_intent=intent,
        task_context_ref="context.test59.lifecycle",
        context_version=1,
        capability_catalog=catalog,
        skill_registry=skills,
        method_registry=methods,
        available_tools=("describe_screen",),
        available_permissions=PERMISSIONS,
        available_platforms=PLATFORMS,
        constraints=tuple(constraints),
    )
    plan = DynamicPlanner().plan_dynamic(value)
    ledger = ActionObligationLedger(root / "ledger")
    runtime = LifecycleRuntime(ledger)
    runtime.context_id = value.task_context_ref
    coordinator = TaskCoordinator(
        CoordinatorStateStore(root / "coordinator.json"),
        UnusedRuntime(),
        dynamic_runtime=runtime,
        dynamic_compiler=DynamicPlanRuntimeCompiler(catalog, skills),
        dynamic_risk_controller=RiskController(),
    )
    task = coordinator.admit_dynamic_plan(OWNER, plan, value, now=100)
    runtime.task_id = task["task_id"]
    return value, plan, runtime, ledger, coordinator, task


class GovernedTaskLifecycleUnitTests(unittest.TestCase):
    def test_successful_multistep_requires_ack_before_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            value, plan, runtime, _ledger, coordinator, task = _fixture(Path(directory), multi_step=True)
            coordinator.run_dynamic_step(task["task_id"], OWNER, now=101)
            coordinator.run_dynamic_step(task["task_id"], OWNER, now=102)
            candidate = coordinator.evaluate_dynamic_task_terminal(
                task["task_id"], OWNER, expected_revision=1, now=103
            )
            premature = coordinator.cleanup_acknowledged_dynamic_task(
                task["task_id"], OWNER, expected_revision=1, now=104
            )
            acknowledged = coordinator.acknowledge_dynamic_task_terminal(
                task["task_id"], OWNER, expected_revision=1,
                acknowledgement_id="ack.test59.success", now=105,
            )
            closed = coordinator.cleanup_acknowledged_dynamic_task(
                task["task_id"], OWNER, expected_revision=1, now=106
            )

        self.assertEqual("ACKNOWLEDGEMENT_PENDING", candidate["lifecycle_state"])
        self.assertEqual("TERMINAL_SUCCESS", candidate["terminal_classification"])
        self.assertEqual("RETENTION_NOT_ELIGIBLE", premature["failure_category"])
        self.assertEqual("RETENTION_ELIGIBLE", acknowledged["lifecycle_state"])
        self.assertEqual("CLOSED", closed["lifecycle_state"])
        self.assertTrue(closed["cleanup_performed"])
        self.assertEqual(2, runtime.executor_calls)

    def test_verifier_incomplete_and_unknown_are_not_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _value, _plan, runtime, _ledger, coordinator, task = _fixture(Path(directory))
            runtime.verification_results.append((False, True))
            coordinator.run_dynamic_step(task["task_id"], OWNER, now=101)
            incomplete = coordinator.evaluate_dynamic_task_terminal(
                task["task_id"], OWNER, expected_revision=1, now=102
            )
        self.assertEqual("ACTIVE", incomplete["lifecycle_state"])
        self.assertFalse(incomplete["retention_eligible"])

        with tempfile.TemporaryDirectory() as directory:
            _value, _plan, runtime, _ledger, coordinator, task = _fixture(Path(directory))
            runtime.unknown_next = True
            coordinator.run_dynamic_step(task["task_id"], OWNER, now=101)
            unknown = coordinator.evaluate_dynamic_task_terminal(
                task["task_id"], OWNER, expected_revision=1, now=102
            )
        self.assertEqual("UNKNOWN_EXECUTION_OUTCOME", unknown["failure_category"])
        self.assertFalse(unknown["retention_eligible"])

    def test_user_cancelled_flow_is_distinct_from_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _value, _plan, runtime, _ledger, coordinator, task = _fixture(Path(directory))
            cancelled = coordinator.cancel_dynamic_task(task["task_id"], OWNER, expected_revision=1, now=101)
            candidate = coordinator.evaluate_dynamic_task_terminal(
                task["task_id"], OWNER, expected_revision=1, now=102
            )
        self.assertEqual("CANCELLED", cancelled["status"])
        self.assertEqual("USER_CANCELLED", candidate["terminal_classification"])
        self.assertEqual(0, runtime.executor_calls)

    def test_duplicate_acknowledgement_is_idempotent_and_stale_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _value, _plan, _runtime, _ledger, coordinator, task = _fixture(Path(directory))
            coordinator.run_dynamic_step(task["task_id"], OWNER, now=101)
            coordinator.evaluate_dynamic_task_terminal(task["task_id"], OWNER, expected_revision=1, now=102)
            first = coordinator.acknowledge_dynamic_task_terminal(
                task["task_id"], OWNER, expected_revision=1,
                acknowledgement_id="ack.test59.same", now=103,
            )
            duplicate = coordinator.acknowledge_dynamic_task_terminal(
                task["task_id"], OWNER, expected_revision=1,
                acknowledgement_id="ack.test59.same", now=104,
            )
            stale = coordinator.acknowledge_dynamic_task_terminal(
                task["task_id"], OWNER, expected_revision=2,
                acknowledgement_id="ack.test59.stale", now=105,
            )
        self.assertEqual(first["acknowledgement_digest"], duplicate["acknowledgement_digest"])
        self.assertEqual("STALE_PLAN_REVISION", stale["failure_category"])

    def test_conflicting_acknowledgement_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _value, _plan, _runtime, _ledger, coordinator, task = _fixture(Path(directory))
            coordinator.run_dynamic_step(task["task_id"], OWNER, now=101)
            coordinator.evaluate_dynamic_task_terminal(task["task_id"], OWNER, expected_revision=1, now=102)
            first = coordinator.acknowledge_dynamic_task_terminal(
                task["task_id"], OWNER, expected_revision=1,
                acknowledgement_id="ack.test59.original", now=103,
            )
            conflict = coordinator.acknowledge_dynamic_task_terminal(
                task["task_id"], OWNER, expected_revision=1,
                acknowledgement_id="ack.test59.conflicting", now=104,
            )
        self.assertEqual("ACKNOWLEDGEMENT_CONFLICT", conflict["failure_category"])
        self.assertEqual(
            first["acknowledgement_digest"], conflict.get("acknowledgement_digest")
        )


class GovernedTaskLifecycleIntegrationTests(unittest.TestCase):
    def test_retry_limit_becomes_terminal_failure_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value, _plan, runtime, _ledger, coordinator, task = _fixture(root)
            runtime.verification_results.extend([(False, True)] * 3)
            for version in (2, 3):
                coordinator.run_dynamic_step(task["task_id"], OWNER, now=100 + version)
                coordinator.replan_dynamic_task(
                    task["task_id"], OWNER, DynamicPlanner(), value,
                    fresh_observation_ref="observation.test59.%d" % version,
                    context_version=version,
                )
            coordinator.run_dynamic_step(task["task_id"], OWNER, now=104)
            coordinator.replan_dynamic_task(
                task["task_id"], OWNER, DynamicPlanner(), value,
                fresh_observation_ref="observation.test59.4", context_version=4,
            )
            terminal = coordinator.evaluate_dynamic_task_terminal(
                task["task_id"], OWNER, expected_revision=3, now=105
            )
        self.assertEqual("TERMINAL_FAILURE", terminal["terminal_classification"])
        self.assertEqual("ACKNOWLEDGEMENT_PENDING", terminal["lifecycle_state"])

    def test_active_replan_revision_prevents_old_revision_closure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            value, _plan, runtime, _ledger, coordinator, task = _fixture(Path(directory))
            runtime.verification_results.append((False, True))
            coordinator.run_dynamic_step(task["task_id"], OWNER, now=101)
            replanned = coordinator.replan_dynamic_task(
                task["task_id"], OWNER, DynamicPlanner(), value,
                fresh_observation_ref="observation.test59.replan", context_version=2,
            )
            old = coordinator.evaluate_dynamic_task_terminal(
                task["task_id"], OWNER, expected_revision=1, now=102
            )
            current = coordinator.inspect_dynamic_task_lifecycle(task["task_id"], OWNER)
        self.assertEqual(2, replanned["planning_revision"])
        self.assertEqual("STALE_PLAN_REVISION", old["failure_category"])
        self.assertEqual("ACTIVE", current["lifecycle_state"])
        self.assertEqual(2, current["planning_revision"])

    def test_cleanup_io_failure_does_not_reopen_terminal_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _value, _plan, _runtime, _ledger, coordinator, task = _fixture(root)
            coordinator.run_dynamic_step(task["task_id"], OWNER, now=101)
            coordinator.evaluate_dynamic_task_terminal(task["task_id"], OWNER, expected_revision=1, now=102)
            coordinator.acknowledge_dynamic_task_terminal(
                task["task_id"], OWNER, expected_revision=1,
                acknowledgement_id="ack.test59.cleanup.failure", now=103,
            )
            coordinator.store = T57.FaultInjectingCoordinatorStore(coordinator.store.path, "replace")
            failed = coordinator.cleanup_acknowledged_dynamic_task(
                task["task_id"], OWNER, expected_revision=1, now=104
            )
            state = coordinator.inspect_dynamic_task_lifecycle(task["task_id"], OWNER)
        self.assertEqual("CLEANUP_FAILED", failed["failure_category"])
        self.assertEqual("RETENTION_ELIGIBLE", state["lifecycle_state"])
        self.assertEqual("TERMINAL_SUCCESS", state["terminal_classification"])

    def test_ledger_verifier_mismatch_blocks_terminal_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _value, _plan, _runtime, _ledger, coordinator, task = _fixture(root)
            coordinator.run_dynamic_step(task["task_id"], OWNER, now=101)
            checkpoint = coordinator.store.get_dynamic_checkpoint(task["task_id"])
            checkpoint["step_records"][0]["verification_ref"] = "verification.forged.test59"
            checkpoint["integrity_digest"] = DynamicPlanRecoveryCheckpoint.digest(checkpoint)
            coordinator.store.put_dynamic_checkpoint(checkpoint)
            blocked = coordinator.evaluate_dynamic_task_terminal(
                task["task_id"], OWNER, expected_revision=1, now=102
            )
        self.assertEqual("VERIFIER_CHECKPOINT_CONFLICT", blocked["failure_category"])
        self.assertEqual("ACTIVE", blocked["lifecycle_state"])


class GovernedTaskLifecycleSecurityTests(unittest.TestCase):
    def test_direct_retention_cleanup_cannot_bypass_acknowledgement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _value, _plan, _runtime, _ledger, coordinator, task = _fixture(Path(directory))
            coordinator.run_dynamic_step(task["task_id"], OWNER, now=101)
            coordinator.inspect_dynamic_task_lifecycle(task["task_id"], OWNER)
            bypass = coordinator.reconcile_dynamic_recovery_retention(
                task["task_id"], OWNER, current_planning_revision=1, now=102, cleanup=True
            )
            checkpoint = coordinator.store.get_dynamic_checkpoint(task["task_id"])
        self.assertEqual("ACKNOWLEDGEMENT_REQUIRED", bypass["classification"])
        self.assertFalse(bypass["cleanup_eligible"])
        self.assertFalse(bypass["cleanup_performed"])
        self.assertEqual(task["task_id"], checkpoint["task_id"])

    def test_cancellation_preserves_unknown_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _value, _plan, runtime, _ledger, coordinator, task = _fixture(Path(directory))
            runtime.unknown_next = True
            coordinator.run_dynamic_step(task["task_id"], OWNER, now=101)
            coordinator.cancel_dynamic_task(task["task_id"], OWNER, expected_revision=1, now=102)
            lifecycle = coordinator.evaluate_dynamic_task_terminal(
                task["task_id"], OWNER, expected_revision=1, now=103
            )
        self.assertEqual("UNKNOWN_EXECUTION_OUTCOME", lifecycle["failure_category"])
        self.assertEqual("ACTIVE", lifecycle["lifecycle_state"])
        self.assertFalse(lifecycle["retention_eligible"])

    def test_test52_blocked_input_cannot_become_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value, plan, runtime, _ledger, coordinator = T57._fixture(root)
            task = coordinator.admit_dynamic_plan(T57.OWNER, plan, value, now=100)
            value2, plan2, runtime2, _ledger2, restarted = T57._fixture(root)
            blocked = restarted.recover_dynamic_plan(
                task["task_id"], T57.OWNER, plan2, value2,
                parameters_by_step={plan2.steps[0].step_id: {"tool": "input_text", "text": "private"}},
                now=101,
            )
            lifecycle = restarted.evaluate_dynamic_task_terminal(
                task["task_id"], T57.OWNER, expected_revision=1, now=102
            )
        self.assertEqual("REPLAN_REQUIRED", blocked["recovery_decision"])
        self.assertNotEqual("TERMINAL_SUCCESS", lifecycle["terminal_classification"])
        self.assertEqual(0, runtime2.plan_executor_invocation_count)
        self.assertEqual([], runtime2.method_health_effects())

    def test_lifecycle_persistence_contains_only_safe_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _value, _plan, runtime, _ledger, coordinator, task = _fixture(root)
            coordinator.run_dynamic_step(task["task_id"], OWNER, now=101)
            coordinator.evaluate_dynamic_task_terminal(task["task_id"], OWNER, expected_revision=1, now=102)
            coordinator.acknowledge_dynamic_task_terminal(
                task["task_id"], OWNER, expected_revision=1,
                acknowledgement_id="ack.test59.privacy", now=103,
            )
            raw = coordinator.store.path.read_text(encoding="utf-8").casefold()
        self.assertIn(TASK_LIFECYCLE_VERSION, raw)
        for forbidden in (
            "password", "otp", "token", "cookie", "screenshot", "raw_ocr",
            "private_document", "model_prompt", "ack.test59.privacy",
        ):
            self.assertNotIn(forbidden, raw)
        self.assertEqual([], runtime.method_health_effects())


if __name__ == "__main__":
    unittest.main(verbosity=2)
