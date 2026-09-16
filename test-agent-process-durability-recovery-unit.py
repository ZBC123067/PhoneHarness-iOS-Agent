#!/usr/bin/env python3
"""TEST-57 host gates for process durability and recovery ownership."""

from __future__ import annotations

import importlib.util
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "phoneharness_test56_fixtures",
    ROOT / "test-agent-dynamic-plan-restart-recovery-unit.py",
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("unable to load TEST-56 fixtures")
FIXTURES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIXTURES)

from phoneharness_agent import (  # noqa: E402
    ActionObligationRequest,
    CoordinatorStateError,
    CoordinatorStateStore,
    DynamicPlanRecoveryCheckpoint,
    DynamicRecoveryOwnershipPolicyError,
    PROCESS_DURABILITY_VERSION,
    ScreenObservationCapabilityArguments,
)


OWNER = FIXTURES.OWNER


class FaultInjectingCoordinatorStore(CoordinatorStateStore):
    def __init__(self, path: Path, operation: str) -> None:
        super().__init__(path)
        self.operation = operation

    def _before_persistence_operation(self, operation: str) -> None:
        if operation == self.operation:
            raise OSError("injected %s failure" % operation)


def _fixture(root: Path, *, risk_controller: Any = None):
    value, plan, catalog, skills = FIXTURES.planner_fixture()
    governed, ledger = FIXTURES.runtime(catalog, skills, root)
    coordinator = FIXTURES.coordinator(
        root, value, catalog, skills, governed, risk_controller=risk_controller
    )
    return value, plan, governed, ledger, coordinator


def _subprocess_command(*parts: str) -> list[str]:
    return [sys.executable, str(Path(__file__).resolve()), "--worker", *parts]


def _read_worker_json(process: subprocess.Popen[str]) -> dict[str, Any]:
    line = process.stdout.readline() if process.stdout is not None else ""
    if not line:
        stderr = process.stderr.read() if process.stderr is not None else ""
        raise AssertionError("worker produced no result: %s" % stderr)
    return json.loads(line)


def _admit_worker(root: Path, mode: str = "admit_wait") -> tuple[subprocess.Popen[str], dict[str, Any]]:
    process = subprocess.Popen(
        _subprocess_command(mode, str(root)),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return process, _read_worker_json(process)


def _recover_worker(root: Path, task_id: str, *, now: int = 200, barrier: Path | None = None) -> dict[str, Any]:
    command = _subprocess_command("recover_run", str(root), task_id, str(now))
    if barrier is not None:
        command.append(str(barrier))
    completed = subprocess.run(command, capture_output=True, text=True, check=True, timeout=20)
    return json.loads(completed.stdout.strip())


def _terminate(process: subprocess.Popen[str], sig: int | None) -> int:
    if sig is None:
        process.terminate()
    else:
        os.kill(process.pid, sig)
    return_code = process.wait(timeout=10)
    _close_process_pipes(process)
    return return_code


def _close_process_pipes(process: subprocess.Popen[str]) -> None:
    if process.stdout is not None:
        process.stdout.close()
    if process.stderr is not None:
        process.stderr.close()


class ProcessDurabilityE2ETests(unittest.TestCase):
    def _restart_case(self, termination: str) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            process, admitted = _admit_worker(root, "admit_exit" if termination == "normal" else "admit_wait")
            if termination == "normal":
                return_code = process.wait(timeout=10)
                _close_process_pipes(process)
                self.assertEqual(0, return_code)
            elif termination == "sigterm":
                self.assertEqual(-signal.SIGTERM, _terminate(process, signal.SIGTERM))
            else:
                self.assertEqual(-signal.SIGKILL, _terminate(process, signal.SIGKILL))
            return _recover_worker(root, admitted["task_id"])

    def test_clean_process_restart_loads_disk_only(self) -> None:
        result = self._restart_case("normal")
        self.assertEqual("RESUME_READY", result["recovery_decision"])
        self.assertEqual("DONE", result["run_status"])
        self.assertEqual(1, result["executor_count"])

    def test_sigkill_before_checkpoint_write_recovers_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            process = subprocess.Popen(
                _subprocess_command("before_checkpoint_wait", str(root)),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            announced = _read_worker_json(process)
            self.assertEqual(-signal.SIGKILL, _terminate(process, signal.SIGKILL))
            result = _recover_worker(root, announced["task_id"])

        self.assertEqual("CHECKPOINT_INVALID", result["recovery_decision"])
        self.assertEqual(0, result["executor_count"])

    def test_sigterm_process_restart_loads_disk_only(self) -> None:
        result = self._restart_case("sigterm")
        self.assertEqual("RESUME_READY", result["recovery_decision"])
        self.assertEqual("DONE", result["run_status"])

    def test_sigkill_process_restart_loads_disk_only(self) -> None:
        result = self._restart_case("sigkill")
        self.assertEqual("RESUME_READY", result["recovery_decision"])
        self.assertEqual("DONE", result["run_status"])

    def test_simultaneous_recovery_has_exactly_one_owner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            process, admitted = _admit_worker(root)
            process.send_signal(signal.SIGUSR1)
            self.assertEqual(0, process.wait(timeout=10))
            _close_process_pipes(process)
            barrier = root / "start.barrier"
            workers = [
                subprocess.Popen(
                    _subprocess_command("recover_run", str(root), admitted["task_id"], "200", str(barrier)),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for _ in range(2)
            ]
            time.sleep(0.1)
            barrier.touch()
            results = [_read_worker_json(worker) for worker in workers]
            for worker in workers:
                self.assertEqual(0, worker.wait(timeout=10))
                _close_process_pipes(worker)

        decisions = sorted(item["recovery_decision"] for item in results)
        self.assertEqual(["RECOVERY_OWNERSHIP_CONFLICT", "RESUME_READY"], decisions)
        loser = next(item for item in results if item["recovery_decision"] == "RECOVERY_OWNERSHIP_CONFLICT")
        self.assertEqual(0, loser["executor_count"])


class RecoveryOwnershipIntegrationTests(unittest.TestCase):
    def test_stale_owner_transfers_and_old_owner_is_fenced_before_executor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value, plan, first_runtime, _ledger, first = _fixture(root)
            task = first.admit_dynamic_plan(OWNER, plan, value, now=100)
            first_recovery = first.recover_dynamic_plan(task["task_id"], OWNER, plan, value, now=110)

            value2, plan2, second_runtime, _ledger2, second = _fixture(root)
            second_recovery = second.recover_dynamic_plan(task["task_id"], OWNER, plan2, value2, now=141)
            old_result = first.run_dynamic_step(task["task_id"], OWNER, now=142)
            new_result = second.run_dynamic_step(task["task_id"], OWNER, now=142)

        self.assertEqual("RESUME_READY", first_recovery["recovery_decision"])
        self.assertEqual("RESUME_READY", second_recovery["recovery_decision"])
        self.assertEqual("RECOVERY_OWNERSHIP_LOST", old_result["failure_category"])
        self.assertEqual(0, first_runtime.plan_executor_invocation_count)
        self.assertEqual("DONE", new_result["status"])
        self.assertEqual(1, second_runtime.plan_executor_invocation_count)

    def test_lease_uses_fencing_not_pid_and_rejects_forgery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CoordinatorStateStore(Path(directory) / "coordinator.json")
            lease = store.acquire_dynamic_recovery_lease(
                task_id="dynamic.task.test57",
                plan_id="plan.test57",
                planning_revision=1,
                holder_ref="runtime.test57.one",
                now=100,
            )
            raw = store.path.read_text(encoding="utf-8")
            self.assertNotIn(str(os.getpid()), raw)
            self.assertTrue(store.validate_dynamic_recovery_lease(lease, holder_ref="runtime.test57.one", now=101))
            forged = dict(lease)
            forged["fencing_token"] += 1
            self.assertFalse(store.validate_dynamic_recovery_lease(forged, holder_ref="runtime.test57.one", now=101))

    def test_unknown_dispatched_and_observing_outcomes_never_replay(self) -> None:
        for ledger_state, step_state in (("DISPATCHED", "EXECUTING"), ("OBSERVING", "AWAITING_VERIFICATION")):
            with self.subTest(ledger_state=ledger_state), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                process = subprocess.Popen(
                    _subprocess_command("phase_wait", str(root), ledger_state, step_state),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                admitted = _read_worker_json(process)
                self.assertEqual(-signal.SIGKILL, _terminate(process, signal.SIGKILL))
                result = _recover_worker(root, admitted["task_id"])
                self.assertEqual("EXECUTION_OUTCOME_UNKNOWN", result["recovery_decision"])
                self.assertEqual(0, result["executor_count"])

    def test_durable_verified_ledger_prevents_duplicate_after_checkpoint_lag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            process = subprocess.Popen(
                _subprocess_command("phase_wait", str(root), "VERIFIED_AFTER_CHECKPOINT", "AWAITING_VERIFICATION"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            admitted = _read_worker_json(process)
            self.assertEqual(-signal.SIGKILL, _terminate(process, signal.SIGKILL))
            result = _recover_worker(root, admitted["task_id"])

        self.assertEqual("ALREADY_VERIFIED", result["recovery_decision"])
        self.assertEqual(0, result["executor_count"])

    def test_checkpoint_alone_never_proves_execution_truth(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value, plan, governed, _ledger, owner = _fixture(root)
            task = owner.admit_dynamic_plan(OWNER, plan, value, now=100)
            checkpoint = owner.store.get_dynamic_checkpoint(task["task_id"])
            checkpoint["status"] = "DONE"
            checkpoint["step_records"][0]["state"] = "VERIFIED"
            checkpoint["step_records"][0]["ledger_ref"] = "obligation.forged.test57"
            checkpoint["step_records"][0]["ledger_state"] = "VERIFIED"
            checkpoint["step_records"][0]["verification_ref"] = "verification.forged.test57"
            checkpoint["integrity_digest"] = DynamicPlanRecoveryCheckpoint.digest(checkpoint)
            owner.store.put_dynamic_checkpoint(checkpoint)

            value2, plan2, restarted_runtime, _ledger2, restarted = _fixture(root)
            result = restarted.recover_dynamic_plan(task["task_id"], OWNER, plan2, value2, now=110)

        self.assertEqual("CHECKPOINT_INVALID", result["recovery_decision"])
        self.assertEqual(0, restarted_runtime.plan_executor_invocation_count)

    def test_stale_confirmation_requires_current_confirmation_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value, plan, governed, _ledger, first = _fixture(root)
            task = first.admit_dynamic_plan(OWNER, plan, value, now=100)
            checkpoint = first.store.get_dynamic_checkpoint(task["task_id"])
            checkpoint["status"] = "WAITING_CONFIRMATION"
            checkpoint["confirmation_state"] = "REQUIRED"
            checkpoint["step_records"][0]["state"] = "AWAITING_CONFIRMATION"
            checkpoint["integrity_digest"] = DynamicPlanRecoveryCheckpoint.digest(checkpoint)
            first.store.put_dynamic_checkpoint(checkpoint)

            value2, plan2, runtime2, _ledger2, restarted = _fixture(root)
            result = restarted.recover_dynamic_plan(task["task_id"], OWNER, plan2, value2, now=110)

        self.assertEqual("CONFIRMATION_REQUIRED", result["recovery_decision"])
        self.assertEqual(0, runtime2.plan_executor_invocation_count)
        self.assertFalse(result["automatic_retry_allowed"])


class PersistenceFaultAndSecurityTests(unittest.TestCase):
    def test_write_and_rename_faults_preserve_last_valid_payload(self) -> None:
        for operation in ("write", "replace"):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "coordinator.json"
                baseline = CoordinatorStateStore(path)
                lease = baseline.acquire_dynamic_recovery_lease(
                    task_id="dynamic.task.test57",
                    plan_id="plan.test57",
                    planning_revision=1,
                    holder_ref="runtime.test57.initial",
                    now=100,
                )
                before = path.read_bytes()
                failing = FaultInjectingCoordinatorStore(path, operation)
                with self.assertRaises(OSError):
                    failing.acquire_dynamic_recovery_lease(
                        task_id="dynamic.task.test57",
                        plan_id="plan.test57",
                        planning_revision=1,
                        holder_ref="runtime.test57.next",
                        now=lease["expires_at"] + 1,
                    )
                self.assertEqual(before, path.read_bytes())
                self.assertFalse(list(path.parent.glob(".*.tmp")))

    def test_missing_corrupt_truncated_integrity_and_schema_fail_closed(self) -> None:
        variants = (
            b"{",
            json.dumps({"schema_version": "999", "tasks": []}).encode(),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value, plan, governed, _ledger, recovery = _fixture(root)
            missing = recovery.recover_dynamic_plan("dynamic.task.missing", OWNER, plan, value, now=100)
            self.assertEqual("CHECKPOINT_INVALID", missing["recovery_decision"])
            for payload in variants:
                recovery.store.path.write_bytes(payload)
                result = recovery.recover_dynamic_plan("dynamic.task.missing", OWNER, plan, value, now=101)
                self.assertEqual("CHECKPOINT_INVALID", result["recovery_decision"])

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value, plan, governed, _ledger, owner = _fixture(root)
            task = owner.admit_dynamic_plan(OWNER, plan, value, now=100)
            payload = json.loads(owner.store.path.read_text(encoding="utf-8"))
            payload["dynamic_plan_checkpoints"][task["task_id"]]["context_version"] += 1
            owner.store.path.write_text(json.dumps(payload), encoding="utf-8")
            value2, plan2, runtime2, _ledger2, restarted = _fixture(root)
            result = restarted.recover_dynamic_plan(task["task_id"], OWNER, plan2, value2, now=110)
            self.assertEqual("CHECKPOINT_INVALID", result["recovery_decision"])
            self.assertEqual(0, runtime2.plan_executor_invocation_count)

    def test_stale_plan_confirmation_and_risk_remain_non_authoritative(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value, plan, governed, _ledger, first = _fixture(root)
            task = first.admit_dynamic_plan(OWNER, plan, value, now=100)

            newer_value = replace(value, planning_revision=2, context_version=2, replan_count=1)
            newer_plan = FIXTURES.DynamicPlanner().plan_dynamic(newer_value)
            value2, plan2, runtime2, _ledger2, rejecting = _fixture(
                root, risk_controller=FIXTURES.RejectingRecoveryRiskController()
            )
            stale = rejecting.recover_dynamic_plan(task["task_id"], OWNER, newer_plan, newer_value, now=110)
            blocked = rejecting.recover_dynamic_plan(task["task_id"], OWNER, plan2, value2, now=111)

        self.assertEqual("STALE_PLAN_REVISION", stale["recovery_decision"])
        self.assertEqual("RECOVERY_BLOCKED", blocked["recovery_decision"])
        self.assertEqual(0, runtime2.plan_executor_invocation_count)

    def test_test52_and_secret_storage_remain_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value, plan, governed, _ledger, first = _fixture(root)
            task = first.admit_dynamic_plan(OWNER, plan, value, now=100)
            value2, plan2, runtime2, _ledger2, restarted = _fixture(root)
            result = restarted.recover_dynamic_plan(
                task["task_id"], OWNER, plan2, value2,
                parameters_by_step={plan2.steps[0].step_id: {"tool": "input_text", "text": "secret"}},
                now=110,
            )
            raw = restarted.store.path.read_text(encoding="utf-8").casefold()

        self.assertEqual("REPLAN_REQUIRED", result["recovery_decision"])
        self.assertEqual(0, runtime2.plan_executor_invocation_count)
        for forbidden in ("secret", "password", "otp", "cookie", "raw_ocr", "screenshot", "tool_args"):
            self.assertNotIn(forbidden, raw)
        self.assertEqual([], runtime2.method_health_effects())


def _worker_fixture(root: Path):
    return _fixture(root)


def _worker_admit_wait(root: Path) -> None:
    value, plan, _runtime, _ledger, coordinator = _worker_fixture(root)
    task = coordinator.admit_dynamic_plan(OWNER, plan, value, now=100)
    print(json.dumps({"task_id": task["task_id"], "version": PROCESS_DURABILITY_VERSION}), flush=True)
    signal.signal(signal.SIGUSR1, lambda _signum, _frame: sys.exit(0))
    while True:
        time.sleep(1)


def _worker_admit_exit(root: Path) -> None:
    value, plan, _runtime, _ledger, coordinator = _worker_fixture(root)
    task = coordinator.admit_dynamic_plan(OWNER, plan, value, now=100)
    print(json.dumps({"task_id": task["task_id"], "version": PROCESS_DURABILITY_VERSION}), flush=True)


def _worker_before_checkpoint_wait(_root: Path) -> None:
    print(json.dumps({"task_id": "dynamic.task.test57.before.checkpoint"}), flush=True)
    while True:
        time.sleep(1)


def _worker_phase_wait(root: Path, ledger_state: str, step_state: str) -> None:
    value, plan, governed, ledger, coordinator = _worker_fixture(root)
    task = coordinator.admit_dynamic_plan(OWNER, plan, value, now=100)
    step = coordinator.dynamic_compiled_step(task["task_id"], OWNER, plan.steps[0].step_id)
    obligation_ref = governed._evidence_ref("dynamicbinding", step)
    record = ledger.create(
        ActionObligationRequest(
            obligation_ref=obligation_ref,
            task_id=task["task_id"],
            context_id=value.task_context_ref,
            capability_id=step.capability_id,
            method_id=str(step.method_id),
            risk_level=step.risk_class,
        ),
        timestamp=101,
    )
    record = ledger.transition(
        record["obligation_id"], "AUTHORIZED", "risk_allowed",
        event_id="event.test57.worker.authorized", timestamp=102,
    )
    record = ledger.transition(
        record["obligation_id"], "DISPATCHED", "dispatch_started",
        event_id="event.test57.worker.dispatched", timestamp=103,
    )
    if ledger_state in {"OBSERVING", "VERIFIED_AFTER_CHECKPOINT"}:
        record = ledger.transition(
            record["obligation_id"], "OBSERVING", "dispatch_response_received",
            event_id="event.test57.worker.observing", timestamp=104,
        )
    checkpoint = coordinator.store.get_dynamic_checkpoint(task["task_id"])
    checkpoint["status"] = "RUNNING"
    checkpoint["executor_invocation_count"] = 1
    checkpoint["step_records"][0]["state"] = step_state
    checkpoint["step_records"][0]["ledger_ref"] = record["obligation_id"]
    checkpoint["step_records"][0]["ledger_state"] = record["state"]
    checkpoint["integrity_digest"] = DynamicPlanRecoveryCheckpoint.digest(checkpoint)
    coordinator.store.put_dynamic_checkpoint(checkpoint)
    if ledger_state == "VERIFIED_AFTER_CHECKPOINT":
        ledger.transition(
            record["obligation_id"], "VERIFIED", "verification_passed",
            event_id="event.test57.worker.verified", timestamp=105,
        )
    print(json.dumps({"task_id": task["task_id"]}), flush=True)
    while True:
        time.sleep(1)


def _worker_recover_run(root: Path, task_id: str, now: int, barrier: Path | None) -> None:
    if barrier is not None:
        deadline = time.time() + 10
        while not barrier.exists():
            if time.time() >= deadline:
                raise RuntimeError("recovery barrier timed out")
            time.sleep(0.01)
    value, plan, governed, _ledger, coordinator = _worker_fixture(root)
    recovered = coordinator.recover_dynamic_plan(task_id, OWNER, plan, value, now=now)
    run_status = "NOT_RUN"
    if recovered["recovery_decision"] == "RESUME_READY":
        run_status = coordinator.run_dynamic_step(task_id, OWNER, now=now + 1)["status"]
    print(json.dumps({
        "recovery_decision": recovered["recovery_decision"],
        "failure_category": recovered.get("failure_category"),
        "run_status": run_status,
        "executor_count": governed.plan_executor_invocation_count,
    }), flush=True)


def _run_worker(arguments: list[str]) -> None:
    mode = arguments[0]
    if mode == "admit_wait":
        _worker_admit_wait(Path(arguments[1]))
    elif mode == "admit_exit":
        _worker_admit_exit(Path(arguments[1]))
    elif mode == "before_checkpoint_wait":
        _worker_before_checkpoint_wait(Path(arguments[1]))
    elif mode == "phase_wait":
        _worker_phase_wait(Path(arguments[1]), arguments[2], arguments[3])
    elif mode == "recover_run":
        barrier = Path(arguments[4]) if len(arguments) > 4 else None
        _worker_recover_run(Path(arguments[1]), arguments[2], int(arguments[3]), barrier)
    else:
        raise RuntimeError("unknown TEST-57 worker mode")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        _run_worker(sys.argv[2:])
    else:
        unittest.main(verbosity=2)
