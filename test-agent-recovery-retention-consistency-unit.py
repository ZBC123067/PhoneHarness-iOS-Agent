#!/usr/bin/env python3
"""TEST-58 host gates for bounded recovery retention and reconciliation."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "phoneharness_test57_fixtures",
    ROOT / "test-agent-process-durability-recovery-unit.py",
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("unable to load TEST-57 fixtures")
FIXTURES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIXTURES)

from phoneharness_agent import (  # noqa: E402
    ActionObligationRequest,
    CoordinatorStateError,
    CoordinatorStateStore,
    DynamicPlanRecoveryCheckpoint,
    RECOVERY_RETENTION_VERSION,
    ScreenObservationCapabilityArguments,
)


OWNER = FIXTURES.OWNER


def _fixture(root: Path):
    return FIXTURES._fixture(root)


def _verified(root: Path):
    value, plan, runtime, ledger, coordinator = _fixture(root)
    task = coordinator.admit_dynamic_plan(OWNER, plan, value, now=100)
    step = coordinator.dynamic_compiled_step(task["task_id"], OWNER, plan.steps[0].step_id)
    runtime.bind_dynamic_step(
        step,
        task_id=task["task_id"],
        context_ref=value.task_context_ref,
        context_version=value.context_version,
        parameters=ScreenObservationCapabilityArguments(),
    )
    result = coordinator.run_dynamic_step(task["task_id"], OWNER, now=101)
    if result["status"] != "DONE":
        raise AssertionError("verified fixture did not complete")
    return value, plan, runtime, ledger, coordinator, task


def _ledger_state(
    root: Path,
    target_state: str,
    *,
    checkpoint_state: str,
    checkpoint_status: str,
):
    value, plan, runtime, ledger, coordinator = _fixture(root)
    task = coordinator.admit_dynamic_plan(OWNER, plan, value, now=100)
    step = coordinator.dynamic_compiled_step(task["task_id"], OWNER, plan.steps[0].step_id)
    refs = runtime.expected_recovery_references(step)
    record = ledger.create(
        ActionObligationRequest(
            obligation_ref=runtime._evidence_ref("dynamicbinding", step),
            task_id=task["task_id"],
            context_id=value.task_context_ref,
            capability_id=step.capability_id,
            method_id=str(step.method_id),
            risk_level=step.risk_class,
        ),
        timestamp=101,
    )
    if target_state != "CREATED":
        record = ledger.transition(
            record["obligation_id"], "AUTHORIZED", "risk_allowed",
            event_id="event.test58.authorized", timestamp=102,
        )
    if target_state not in {"CREATED", "AUTHORIZED", "FAILED"}:
        record = ledger.transition(
            record["obligation_id"], "DISPATCHED", "dispatch_started",
            event_id="event.test58.dispatched", timestamp=103,
        )
    if target_state in {"OBSERVING", "VERIFIED"}:
        record = ledger.transition(
            record["obligation_id"], "OBSERVING", "dispatch_response_received",
            event_id="event.test58.observing", timestamp=104,
        )
    if target_state == "VERIFIED":
        record = ledger.transition(
            record["obligation_id"], "VERIFIED", "verification_passed",
            event_id="event.test58.verified", timestamp=105,
        )
    elif target_state == "FAILED":
        record = ledger.transition(
            record["obligation_id"], "FAILED", "execution_failed",
            event_id="event.test58.failed", timestamp=103,
        )

    checkpoint = coordinator.store.get_dynamic_checkpoint(task["task_id"])
    checkpoint["status"] = checkpoint_status
    checkpoint["executor_invocation_count"] = 0 if target_state in {"CREATED", "AUTHORIZED"} else 1
    checkpoint["step_records"][0]["state"] = checkpoint_state
    checkpoint["step_records"][0]["ledger_ref"] = refs["ledger_ref"]
    checkpoint["step_records"][0]["ledger_state"] = record["state"]
    checkpoint["step_records"][0]["verification_ref"] = (
        refs["verification_ref"] if checkpoint_state == "VERIFIED" else None
    )
    if checkpoint_status in {"FAILED", "BLOCKED", "REPLAN_REQUIRED"}:
        checkpoint["failure_category"] = "execution_failed"
        checkpoint["failed_step_id"] = step.step_id
        checkpoint["failure_evidence_status"] = "failed"
        checkpoint["failure_recoverable"] = checkpoint_status == "REPLAN_REQUIRED"
    checkpoint["integrity_digest"] = DynamicPlanRecoveryCheckpoint.digest(checkpoint)
    coordinator.store.put_dynamic_checkpoint(checkpoint)
    return value, plan, runtime, ledger, coordinator, task, record


class RecoveryRetentionUnitTests(unittest.TestCase):
    def test_terminal_verified_cleanup_keeps_ledger_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _value, _plan, runtime, ledger, coordinator, task = _verified(root)
            result = coordinator.reconcile_dynamic_recovery_retention(
                task["task_id"], OWNER, now=110, cleanup=True
            )
            with self.assertRaises(CoordinatorStateError):
                coordinator.store.get_dynamic_checkpoint(task["task_id"])
            ledger_state = ledger.records()[0]["state"]

        self.assertEqual(RECOVERY_RETENTION_VERSION, result["recovery_retention_version"])
        self.assertEqual("TERMINAL_VERIFIED", result["classification"])
        self.assertTrue(result["cleanup_performed"])
        self.assertEqual("VERIFIED", ledger_state)
        self.assertEqual([], runtime.method_health_effects())

    def test_terminal_failure_and_cancellation_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            *_prefix, coordinator, task, _record = _ledger_state(
                root, "FAILED", checkpoint_state="FAILED", checkpoint_status="FAILED"
            )
            failed = coordinator.reconcile_dynamic_recovery_retention(
                task["task_id"], OWNER, now=110, cleanup=True
            )
            self.assertEqual("TERMINAL_FAILURE", failed["classification"])
            self.assertTrue(failed["cleanup_performed"])

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _value, _plan, _runtime, _ledger, coordinator = _fixture(root)
            task = coordinator.admit_dynamic_plan(OWNER, _plan, _value, now=100)
            checkpoint = coordinator.store.get_dynamic_checkpoint(task["task_id"])
            checkpoint["status"] = "CANCELLED"
            checkpoint["step_records"][0]["state"] = "CANCELLED"
            checkpoint["integrity_digest"] = DynamicPlanRecoveryCheckpoint.digest(checkpoint)
            coordinator.store.put_dynamic_checkpoint(checkpoint)
            cancelled = coordinator.reconcile_dynamic_recovery_retention(
                task["task_id"], OWNER, now=110, cleanup=True
            )
            self.assertEqual("USER_CANCELLED", cancelled["classification"])
            self.assertTrue(cancelled["cleanup_performed"])

    def test_superseded_revision_cleanup_and_idempotency(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value, plan, _runtime, _ledger, coordinator = _fixture(root)
            task = coordinator.admit_dynamic_plan(OWNER, plan, value, now=100)
            first = coordinator.reconcile_dynamic_recovery_retention(
                task["task_id"], OWNER, current_planning_revision=2, now=110, cleanup=True
            )
            second = coordinator.reconcile_dynamic_recovery_retention(
                task["task_id"], OWNER, current_planning_revision=2, now=111, cleanup=True
            )

        self.assertEqual("SUPERSEDED_REVISION", first["classification"])
        self.assertTrue(first["cleanup_performed"])
        self.assertEqual("ALREADY_CLEANED", second["classification"])
        self.assertFalse(second["cleanup_performed"])

    def test_interrupted_cleanup_preserves_last_valid_payload(self) -> None:
        for operation in ("write", "replace"):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                _value, _plan, _runtime, _ledger, coordinator, task = _verified(root)
                before = coordinator.store.path.read_bytes()
                failing = FIXTURES.FaultInjectingCoordinatorStore(coordinator.store.path, operation)
                coordinator.store = failing
                with self.assertRaises(OSError):
                    coordinator.reconcile_dynamic_recovery_retention(
                        task["task_id"], OWNER, now=110, cleanup=True
                    )
                self.assertEqual(before, coordinator.store.path.read_bytes())

    def test_stale_lease_cleanup_is_safe_but_not_execution_truth(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = CoordinatorStateStore(root / "coordinator.json")
            store.acquire_dynamic_recovery_lease(
                task_id="dynamic.task.test58.stale",
                plan_id="plan.test58.stale",
                planning_revision=1,
                holder_ref="runtime.test58.old",
                now=100,
                lease_seconds=1,
            )
            value, _plan, runtime, _ledger, coordinator = _fixture(root)
            coordinator.store = store
            result = coordinator.reconcile_dynamic_recovery_retention(
                "dynamic.task.test58.stale", OWNER, now=102, cleanup=True
            )

        self.assertEqual("STALE_OWNERSHIP", result["classification"])
        self.assertTrue(result["cleanup_performed"])
        self.assertEqual(0, runtime.plan_executor_invocation_count)

    def test_active_foreign_lease_blocks_terminal_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _value, _plan, runtime, _ledger, coordinator, task = _verified(root)
            checkpoint = coordinator.store.get_dynamic_checkpoint(task["task_id"])
            coordinator.store.acquire_dynamic_recovery_lease(
                task_id=task["task_id"],
                plan_id=checkpoint["plan_id"],
                planning_revision=checkpoint["planning_revision"],
                holder_ref="runtime.test58.foreign",
                now=102,
            )
            before_executor_count = runtime.plan_executor_invocation_count
            result = coordinator.reconcile_dynamic_recovery_retention(
                task["task_id"], OWNER, now=110, cleanup=True
            )

        self.assertEqual("ACTIVE_RECOVERY_OWNERSHIP", result["classification"])
        self.assertFalse(result["cleanup_performed"])
        self.assertEqual(before_executor_count, runtime.plan_executor_invocation_count)


class RecoveryConsistencyIntegrationTests(unittest.TestCase):
    def test_ledger_checkpoint_disagreement_is_retained(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            *prefix, coordinator, task, record = _ledger_state(
                root, "FAILED", checkpoint_state="FAILED", checkpoint_status="FAILED"
            )
            checkpoint = coordinator.store.get_dynamic_checkpoint(task["task_id"])
            runtime = prefix[2]
            step = coordinator.dynamic_compiled_step(task["task_id"], OWNER, checkpoint["step_records"][0]["step_id"])
            expected = runtime.expected_recovery_references(step)
            checkpoint["status"] = "DONE"
            checkpoint["step_records"][0]["state"] = "VERIFIED"
            checkpoint["step_records"][0]["ledger_state"] = "VERIFIED"
            checkpoint["step_records"][0]["verification_ref"] = expected["verification_ref"]
            checkpoint["failure_category"] = None
            checkpoint["failed_step_id"] = None
            checkpoint["failure_evidence_status"] = None
            checkpoint["failure_recoverable"] = False
            checkpoint["integrity_digest"] = DynamicPlanRecoveryCheckpoint.digest(checkpoint)
            coordinator.store.put_dynamic_checkpoint(checkpoint)
            result = coordinator.reconcile_dynamic_recovery_retention(
                task["task_id"], OWNER, now=110, cleanup=True
            )

        self.assertEqual("LEDGER_CHECKPOINT_CONFLICT", result["classification"])
        self.assertFalse(result["cleanup_performed"])
        self.assertEqual("FAILED", record["state"])

    def test_verifier_checkpoint_disagreement_is_retained(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _value, _plan, _runtime, _ledger, coordinator, task = _verified(root)
            checkpoint = coordinator.store.get_dynamic_checkpoint(task["task_id"])
            checkpoint["step_records"][0]["verification_ref"] = "verification.forged.test58"
            checkpoint["integrity_digest"] = DynamicPlanRecoveryCheckpoint.digest(checkpoint)
            coordinator.store.put_dynamic_checkpoint(checkpoint)
            result = coordinator.reconcile_dynamic_recovery_retention(
                task["task_id"], OWNER, now=110, cleanup=True
            )

        self.assertEqual("VERIFIER_CHECKPOINT_CONFLICT", result["classification"])
        self.assertFalse(result["cleanup_performed"])

    def test_orphan_checkpoint_and_orphan_ledger_are_conservative(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value, plan, runtime, ledger, coordinator = _fixture(root)
            task = coordinator.admit_dynamic_plan(OWNER, plan, value, now=100)
            checkpoint = coordinator.store.get_dynamic_checkpoint(task["task_id"])
            checkpoint["status"] = "DONE"
            checkpoint["step_records"][0]["state"] = "VERIFIED"
            checkpoint["step_records"][0]["ledger_ref"] = "obligation.missing.test58"
            checkpoint["step_records"][0]["ledger_state"] = "VERIFIED"
            checkpoint["step_records"][0]["verification_ref"] = "verification.missing.test58"
            checkpoint["integrity_digest"] = DynamicPlanRecoveryCheckpoint.digest(checkpoint)
            coordinator.store.put_dynamic_checkpoint(checkpoint)
            orphan_checkpoint = coordinator.reconcile_dynamic_recovery_retention(
                task["task_id"], OWNER, now=110, cleanup=True
            )

            ledger.create(
                ActionObligationRequest(
                    obligation_ref="dynamicbinding.orphan.test58",
                    task_id="dynamic.task.test58.orphanledger",
                    context_id="context.test58.orphan",
                    capability_id="capability.screen.observe.v1",
                    method_id="method.observe.test56.v1",
                    risk_level="read_only",
                ),
                timestamp=111,
            )
            orphan_ledger = coordinator.reconcile_dynamic_recovery_retention(
                "dynamic.task.test58.orphanledger", OWNER, now=112, cleanup=True
            )

        self.assertEqual("ORPHAN_CHECKPOINT", orphan_checkpoint["classification"])
        self.assertFalse(orphan_checkpoint["cleanup_performed"])
        self.assertEqual("ORPHAN_LEDGER_PRE_DISPATCH", orphan_ledger["classification"])
        self.assertFalse(orphan_ledger["cleanup_performed"])
        self.assertEqual(0, runtime.plan_executor_invocation_count)

    def test_unknown_execution_outcome_and_lease_are_retained(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            *_prefix, coordinator, task, _record = _ledger_state(
                root, "DISPATCHED", checkpoint_state="EXECUTING", checkpoint_status="RUNNING"
            )
            checkpoint = coordinator.store.get_dynamic_checkpoint(task["task_id"])
            lease = coordinator.store.acquire_dynamic_recovery_lease(
                task_id=task["task_id"], plan_id=checkpoint["plan_id"], planning_revision=1,
                holder_ref="runtime.test58.unknown", now=100, lease_seconds=1,
            )
            result = coordinator.reconcile_dynamic_recovery_retention(
                task["task_id"], OWNER, now=110, cleanup=True
            )
            retained = coordinator.store.get_dynamic_checkpoint(task["task_id"])
            retained_lease = coordinator.store.get_dynamic_recovery_lease(task["task_id"])

        self.assertEqual("UNKNOWN_EXECUTION_OUTCOME", result["classification"])
        self.assertFalse(result["cleanup_performed"])
        self.assertEqual(lease["lease_id"], retained_lease["lease_id"])
        self.assertEqual(task["task_id"], retained["task_id"])

    def test_checkpoint_without_lease_cleanup_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _value, _plan, _runtime, _ledger, coordinator, task = _verified(root)
            first = coordinator.reconcile_dynamic_recovery_retention(
                task["task_id"], OWNER, now=110, cleanup=True
            )
            second = coordinator.reconcile_dynamic_recovery_retention(
                task["task_id"], OWNER, now=111, cleanup=True
            )
        self.assertTrue(first["cleanup_performed"])
        self.assertFalse(second["cleanup_performed"])

    def test_test52_blocked_input_survives_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value, plan, _runtime, _ledger, coordinator = _fixture(root)
            task = coordinator.admit_dynamic_plan(OWNER, plan, value, now=100)
            value2, plan2, runtime2, _ledger2, restarted = _fixture(root)
            blocked = restarted.recover_dynamic_plan(
                task["task_id"], OWNER, plan2, value2,
                parameters_by_step={plan2.steps[0].step_id: {"tool": "input_text", "text": "private"}},
                now=110,
            )
            retention = restarted.reconcile_dynamic_recovery_retention(
                task["task_id"], OWNER, now=111, cleanup=True
            )

        self.assertEqual("REPLAN_REQUIRED", blocked["recovery_decision"])
        self.assertEqual("ACTIVE_PLAN", retention["classification"])
        self.assertFalse(retention["cleanup_performed"])
        self.assertEqual(0, runtime2.plan_executor_invocation_count)


class RecoveryRetentionSecurityAndE2ETests(unittest.TestCase):
    def test_task_scoped_reconciliation_does_not_mutate_unrelated_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _value, _plan, runtime, ledger, coordinator = _fixture(root)
            record = ledger.create(
                ActionObligationRequest(
                    obligation_ref="dynamicbinding.unrelated.test58",
                    task_id="dynamic.task.test58.unrelated",
                    context_id="context.test58.unrelated",
                    capability_id="capability.screen.observe.v1",
                    method_id="method.observe.test56.v1",
                    risk_level="read_only",
                ),
                timestamp=100,
            )
            record = ledger.transition(
                record["obligation_id"], "AUTHORIZED", "risk_allowed",
                event_id="event.test58.unrelated.authorized", timestamp=101,
            )
            record = ledger.transition(
                record["obligation_id"], "DISPATCHED", "dispatch_started",
                event_id="event.test58.unrelated.dispatched", timestamp=102,
            )
            result = coordinator.reconcile_dynamic_recovery_retention(
                "dynamic.task.test58.absent", OWNER, now=110, cleanup=True
            )
            after = ledger.get(record["obligation_id"])

        self.assertEqual("ALREADY_CLEANED", result["classification"])
        self.assertEqual("DISPATCHED", after["state"])
        self.assertEqual(0, runtime.plan_executor_invocation_count)

    def test_secret_retention_and_method_health_remain_clean(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _value, _plan, runtime, _ledger, coordinator, task = _verified(root)
            result = coordinator.reconcile_dynamic_recovery_retention(
                task["task_id"], OWNER, now=110, cleanup=True
            )
            durable = "\n".join(
                path.read_text(encoding="utf-8")
                for path in root.rglob("*.json")
            ).casefold()

        self.assertTrue(result["ledger_audit_retained"])
        for forbidden in (
            "password", "otp", "cookie", "screenshot", "raw_ocr", "raw_model_context",
            "private_document", "secure_value",
        ):
            self.assertNotIn(forbidden, durable)
        self.assertEqual([], runtime.method_health_effects())

    def test_process_e2e_reconciles_and_cleans_from_disk_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            created = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--worker", "verified", str(root)],
                check=True, capture_output=True, text=True,
            )
            task_id = json.loads(created.stdout)["task_id"]
            cleaned = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--worker", "cleanup", str(root), task_id],
                check=True, capture_output=True, text=True,
            )
            result = json.loads(cleaned.stdout)

        self.assertEqual("TERMINAL_VERIFIED", result["classification"])
        self.assertTrue(result["cleanup_performed"])
        self.assertEqual(0, result["executor_count"])


def _run_worker(arguments: list[str]) -> None:
    mode = arguments[0]
    root = Path(arguments[1])
    if mode == "verified":
        *_prefix, task = _verified(root)
        print(json.dumps({"task_id": task["task_id"]}), flush=True)
        return
    if mode == "cleanup":
        value, _plan, runtime, _ledger, coordinator = _fixture(root)
        result = coordinator.reconcile_dynamic_recovery_retention(
            arguments[2], OWNER, now=200, cleanup=True
        )
        result["executor_count"] = runtime.plan_executor_invocation_count
        print(json.dumps(result), flush=True)
        return
    raise RuntimeError("unknown TEST-58 worker mode")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        _run_worker(sys.argv[2:])
    else:
        unittest.main(verbosity=2)
