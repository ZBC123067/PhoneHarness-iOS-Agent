#!/usr/bin/env python3
"""Static boundary tests for TEST-18 Task Coordinator.

These tests use a local runtime facade. They never connect to the iPhone and
never instantiate an MCP client inside the Coordinator.
"""

from __future__ import annotations

import json
import stat
import tempfile
import threading
import unittest
from pathlib import Path

from phoneharness_agent import (
    CoordinatorOwnershipError,
    CoordinatorStateError,
    CoordinatorStateStore,
    PreparedReadOnlyGoal,
    ReadOnlyTaskRuntime,
    TaskCoordinator,
)


OWNER = "coordinator-unit-owner-0001"
OTHER_OWNER = "coordinator-unit-owner-9999"


class FakeReadOnlyRuntime:
    """A test double with no MCP client and explicit outcome accounting."""

    def __init__(self, outcomes: list[dict[str, str]] | None = None) -> None:
        self.prepared_goals: list[str] = []
        self.executed_subgoals: list[str] = []
        self.mcp_call_count = 0
        self.outcomes = list(outcomes or [])

    def prepare_goal(self, goal: str) -> PreparedReadOnlyGoal:
        self.prepared_goals.append(goal)
        if goal == "risk-rejected":
            return PreparedReadOnlyGoal("risk_blocked", error_code="risk_rejected")
        if goal == "unsupported":
            return PreparedReadOnlyGoal("blocked", error_code="goal_not_supported")
        return PreparedReadOnlyGoal(
            "ready",
            ("in-memory-observation-1", "in-memory-observation-2"),
            ("observe", "observe"),
        )

    def execute_subgoal(self, goal: str) -> dict[str, str]:
        self.executed_subgoals.append(goal)
        if self.outcomes:
            return self.outcomes.pop(0)
        return {"status": "passed"}


class BlockingReadOnlyRuntime(FakeReadOnlyRuntime):
    """Force a concurrent scheduler attempt while one read-only child is active."""

    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()
        self._count_lock = threading.Lock()
        self.execution_count = 0

    def execute_subgoal(self, goal: str) -> dict[str, str]:
        with self._count_lock:
            self.execution_count += 1
        self.executed_subgoals.append(goal)
        self.started.set()
        if not self.release.wait(timeout=3):
            raise AssertionError("test release was not provided")
        return {"status": "passed"}


class TaskCoordinatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "private" / "coordinator-v1.json"
        self.store = CoordinatorStateStore(self.path)
        self.runtime = FakeReadOnlyRuntime()
        self.coordinator = TaskCoordinator(self.store, self.runtime)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_create_is_private_and_persists_no_goal_or_ui_data(self) -> None:
        task = self.coordinator.create(OWNER, "raw sensitive goal 0.5 0.8 screenshot", now=100)
        raw = self.path.read_text(encoding="utf-8")
        persisted = json.loads(raw)

        self.assertEqual("created", task["status"])
        self.assertEqual(0o700, stat.S_IMODE(self.path.parent.stat().st_mode))
        self.assertEqual(0o600, stat.S_IMODE(self.path.stat().st_mode))
        self.assertEqual(["schema_version", "task_coordinator_version", "tasks"], sorted(persisted))
        for prohibited in (
            "raw sensitive",
            "in-memory-observation",
            "0.5",
            "screenshot",
            "coordinates",
            "response",
            "arguments",
            "steps",
        ):
            self.assertNotIn(prohibited, raw)

    def test_create_run_pause_resume_and_complete_replans_at_each_subgoal(self) -> None:
        task = self.coordinator.create(OWNER, "two read-only checks", now=100)
        first = self.coordinator.run_next(task["task_id"], OWNER, now=101)
        paused = self.coordinator.pause(task["task_id"], OWNER, now=102)
        skipped = self.coordinator.run_next(task["task_id"], OWNER, now=103)
        executed_while_paused = list(self.runtime.executed_subgoals)
        resumed = self.coordinator.resume(task["task_id"], OWNER, now=104)
        second = self.coordinator.run_next(task["task_id"], OWNER, now=105)

        self.assertEqual("running", first["status"])
        self.assertEqual(["in-memory-observation-1"], executed_while_paused)
        self.assertEqual("paused", paused["status"])
        self.assertEqual("not_run", skipped["status"])
        self.assertEqual(1, len(executed_while_paused))
        self.assertEqual("running", resumed["status"])
        self.assertEqual("completed", second["status"])
        self.assertEqual(
            ["in-memory-observation-1", "in-memory-observation-2"],
            self.runtime.executed_subgoals,
        )

    def test_cancel_stops_future_scheduling_and_requires_owner(self) -> None:
        task = self.coordinator.create(OWNER, "two read-only checks", now=100)
        with self.assertRaises(CoordinatorOwnershipError):
            self.coordinator.cancel(task["task_id"], OTHER_OWNER, now=101)

        cancelled = self.coordinator.cancel(task["task_id"], OWNER, now=102)
        skipped = self.coordinator.run_next(task["task_id"], OWNER, now=103)

        self.assertEqual("cancelled", cancelled["status"])
        self.assertEqual("not_run", skipped["status"])
        self.assertEqual([], self.runtime.executed_subgoals)
        with self.assertRaises(CoordinatorStateError):
            self.coordinator.resume(task["task_id"], OWNER, now=104)

    def test_created_can_pause_resume_and_cancel_without_running_a_child(self) -> None:
        task = self.coordinator.create(OWNER, "two read-only checks", now=100)
        paused = self.coordinator.pause(task["task_id"], OWNER, now=101)
        resumed = self.coordinator.resume(task["task_id"], OWNER, now=102)
        cancelled = self.coordinator.cancel(task["task_id"], OWNER, now=103)

        self.assertEqual("paused", paused["status"])
        self.assertEqual("running", resumed["status"])
        self.assertEqual("cancelled", cancelled["status"])
        self.assertEqual([], self.runtime.executed_subgoals)

    def test_risk_reject_is_blocked_before_any_runtime_or_mcp_call(self) -> None:
        task = self.coordinator.create(OWNER, "risk-rejected", now=100)
        skipped = self.coordinator.run_next(task["task_id"], OWNER, now=101)
        cancelled = self.coordinator.cancel(task["task_id"], OWNER, now=102)

        self.assertEqual("blocked", task["status"])
        self.assertEqual("risk_rejected", task["last_error_code"])
        self.assertEqual("not_run", skipped["status"])
        self.assertEqual([], self.runtime.executed_subgoals)
        self.assertEqual(0, self.runtime.mcp_call_count)
        self.assertEqual("cancelled", cancelled["status"])

    def test_interrupted_recovery_requires_owner_resubmission_and_fresh_runtime_call(self) -> None:
        task = self.coordinator.create(OWNER, "two read-only checks", now=100)
        first = self.coordinator.run_next(task["task_id"], OWNER, now=101)
        self.assertEqual("running", first["status"])
        paused = self.coordinator.pause(task["task_id"], OWNER, now=102)
        self.assertEqual("paused", paused["status"])

        restarted_runtime = FakeReadOnlyRuntime()
        restarted = TaskCoordinator(CoordinatorStateStore(self.path), restarted_runtime)
        recovery = restarted.recover_after_restart(now=103)
        interrupted = restarted.inspect(task["task_id"], OWNER)
        no_session = restarted.run_next(task["task_id"], OWNER, now=104)
        executed_before_resume = list(restarted_runtime.executed_subgoals)
        resumed = restarted.resume(task["task_id"], OWNER, "two read-only checks", now=105)
        second = restarted.run_next(task["task_id"], OWNER, now=106)

        self.assertEqual([task["task_id"]], recovery["interrupted_task_ids"])
        self.assertEqual([], recovery["device_actions_sent"])
        self.assertEqual("interrupted", interrupted["status"])
        self.assertTrue(interrupted["recovery_required"])
        self.assertEqual("not_run", no_session["status"])
        self.assertEqual([], executed_before_resume)
        self.assertEqual("running", resumed["status"])
        self.assertEqual("completed", second["status"])
        self.assertEqual(["in-memory-observation-2"], restarted_runtime.executed_subgoals)

    def test_verifier_or_execution_failure_is_failed_not_blocked(self) -> None:
        runtime = FakeReadOnlyRuntime([{"status": "failed", "error_code": "verification_failed"}])
        coordinator = TaskCoordinator(CoordinatorStateStore(Path(self.temporary.name) / "failure.json"), runtime)
        task = coordinator.create(OWNER, "two read-only checks", now=100)
        result = coordinator.run_next(task["task_id"], OWNER, now=101)

        self.assertEqual("failed", result["status"])
        self.assertEqual("verification_failed", result["task"]["last_error_code"])
        self.assertEqual(["in-memory-observation-1"], runtime.executed_subgoals)

    def test_runtime_accepts_only_read_only_goal_intents_without_contacting_mcp(self) -> None:
        runtime = ReadOnlyTaskRuntime(None)  # prepare_goal is deliberately local.
        observe = runtime.prepare_goal("描述当前屏幕")
        verify = runtime.prepare_goal("验证当前屏幕包含 设置")
        interaction = runtime.prepare_goal("在当前页面搜索 设置")

        self.assertEqual("ready", observe.status)
        self.assertEqual(("observe",), observe.intent_kinds)
        self.assertEqual("ready", verify.status)
        self.assertEqual(("verify_visible",), verify.intent_kinds)
        self.assertEqual("blocked", interaction.status)
        self.assertEqual("read_only_scope_rejected", interaction.error_code)

    def test_permission_broad_coordinator_state_file_is_rejected(self) -> None:
        task = self.coordinator.create(OWNER, "two read-only checks", now=100)
        self.assertTrue(task["task_id"])
        self.path.chmod(0o644)
        with self.assertRaises(OSError):
            self.coordinator.inspect(task["task_id"], OWNER)

    def test_concurrent_legacy_schedule_claim_prevents_duplicate_runtime_execution(self) -> None:
        runtime = BlockingReadOnlyRuntime()
        coordinator = TaskCoordinator(CoordinatorStateStore(Path(self.temporary.name) / "concurrent.json"), runtime)
        task = coordinator.create(OWNER, "two read-only checks", now=100)
        first_result: list[dict[str, object]] = []

        worker = threading.Thread(
            target=lambda: first_result.append(coordinator.run_next(task["task_id"], OWNER, now=101)),
        )
        worker.start()
        self.assertTrue(runtime.started.wait(timeout=3))
        duplicate = coordinator.run_next(task["task_id"], OWNER, now=102)
        with self.assertRaises(CoordinatorStateError):
            coordinator.cancel(task["task_id"], OWNER, now=102)
        runtime.release.set()
        worker.join(timeout=3)

        self.assertFalse(worker.is_alive())
        self.assertEqual(1, runtime.execution_count)
        self.assertEqual("not_run", duplicate["status"])
        self.assertEqual("task_operation_in_progress", duplicate["reason"])
        self.assertEqual("running", first_result[0]["status"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
