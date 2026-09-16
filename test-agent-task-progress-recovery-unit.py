#!/usr/bin/env python3
"""TEST-46 Task Progress and Recovery contract tests.

These are metadata-only host tests.  They create no MCP client, contact no
device, retain no raw goal, UI, screenshot, OCR, or action replay data.
"""

from __future__ import annotations

import inspect
import json
import tempfile
import unittest
from pathlib import Path

from phoneharness_agent import (
    ActiveContextEngine,
    ActiveContextStateError,
    CoordinatorStateError,
    CoordinatorStateStore,
    PreparedReadOnlyGoal,
    TaskCoordinator,
    TaskProgressMonitor,
    TaskProgressPolicyError,
)


OWNER = "task-progress-owner-0001"


class FakeReadOnlyRuntime:
    """Local runtime double that proves TEST-46 never dispatches an action."""

    def __init__(self) -> None:
        self.prepare_calls: list[str] = []
        self.execution_calls: list[str] = []
        self.mcp_call_count = 0

    def prepare_goal(self, goal: str) -> PreparedReadOnlyGoal:
        self.prepare_calls.append(goal)
        return PreparedReadOnlyGoal("ready", ("fresh-read-only-subgoal",), ("observe",))

    def execute_subgoal(self, goal: str) -> dict[str, str]:
        self.execution_calls.append(goal)
        return {"status": "passed"}


class TaskProgressMonitorTests(unittest.TestCase):
    def initial(self) -> dict[str, object]:
        return TaskProgressMonitor.initial_storage(100)

    def test_progressing_signal_keeps_only_digest_metadata(self) -> None:
        result = TaskProgressMonitor.assess(
            self.initial(),
            phase="OBSERVATION",
            progress_ref="progress.observe.001",
            state_ref="state.screen.001",
            evidence_status="PRESENT",
            timestamp=101,
        )

        public = TaskProgressMonitor.public(result)
        self.assertEqual("PROGRESSING", public["state"])
        self.assertFalse(public["recovery_required"])
        self.assertEqual("none", public["execution_authority"])
        self.assertNotIn("progress.observe.001", json.dumps(result, sort_keys=True))

    def test_missing_evidence_requires_recovery_without_retry(self) -> None:
        result = TaskProgressMonitor.assess(
            self.initial(),
            phase="VERIFICATION",
            progress_ref="progress.verify.001",
            evidence_status="MISSING",
            timestamp=101,
        )

        contract = TaskProgressMonitor.recovery_contract(result)
        self.assertEqual("STALL_SUSPECTED", result["state"])
        self.assertEqual("MISSING_EVIDENCE", contract["failure_category"])
        self.assertFalse(contract["automatic_retry_allowed"])
        self.assertEqual("none", contract["execution_authority"])
        self.assertEqual(["reobserve", "context_update", "replan", "risk_reassess"], contract["required_steps"])

    def test_repeated_state_is_detected(self) -> None:
        first = TaskProgressMonitor.assess(
            self.initial(),
            phase="OBSERVATION",
            progress_ref="progress.observe.001",
            state_ref="state.screen.001",
            evidence_status="PRESENT",
            timestamp=101,
        )
        result = TaskProgressMonitor.assess(
            first,
            phase="OBSERVATION",
            progress_ref="progress.observe.002",
            state_ref="state.screen.001",
            evidence_status="PRESENT",
            timestamp=102,
        )

        self.assertEqual("REPEATED_STATE", result["failure_category"])
        self.assertTrue(TaskProgressMonitor.requires_recovery(result))

    def test_repeated_action_is_detected(self) -> None:
        first = TaskProgressMonitor.assess(
            self.initial(),
            phase="EXECUTION",
            progress_ref="progress.execute.001",
            action_ref="action.native.001",
            evidence_status="PRESENT",
            timestamp=101,
        )
        result = TaskProgressMonitor.assess(
            first,
            phase="EXECUTION",
            progress_ref="progress.execute.002",
            action_ref="action.native.001",
            evidence_status="PRESENT",
            timestamp=102,
        )

        self.assertEqual("REPEATED_ACTION", result["failure_category"])
        self.assertTrue(TaskProgressMonitor.requires_recovery(result))

    def test_no_progress_is_detected(self) -> None:
        first = TaskProgressMonitor.assess(
            self.initial(),
            phase="PLANNING",
            progress_ref="progress.plan.001",
            evidence_status="PRESENT",
            timestamp=101,
        )
        result = TaskProgressMonitor.assess(
            first,
            phase="PLANNING",
            progress_ref="progress.plan.001",
            evidence_status="PRESENT",
            timestamp=102,
        )

        self.assertEqual("NO_PROGRESS", result["failure_category"])
        self.assertEqual("STALL_SUSPECTED", result["state"])

    def test_negative_recovery_cannot_be_cleared_by_another_signal(self) -> None:
        stalled = TaskProgressMonitor.assess(
            self.initial(),
            phase="VERIFICATION",
            progress_ref="progress.verify.001",
            evidence_status="MISSING",
            timestamp=101,
        )
        with self.assertRaises(TaskProgressPolicyError):
            TaskProgressMonitor.assess(
                stalled,
                phase="OBSERVATION",
                progress_ref="progress.observe.002",
                evidence_status="PRESENT",
                timestamp=102,
            )
        with self.assertRaises(TaskProgressPolicyError):
            TaskProgressMonitor.assess(
                self.initial(),
                phase="OBSERVATION",
                progress_ref="raw private user instruction",
                timestamp=101,
            )


class TaskProgressRecoveryIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.runtime = FakeReadOnlyRuntime()
        self.coordinator = TaskCoordinator(CoordinatorStateStore(self.root / "coordinator.json"), self.runtime)
        self.contexts = ActiveContextEngine(self.root / "contexts")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_stall_stops_scheduling_then_requires_a_fresh_goal_before_runtime_reentry(self) -> None:
        task = self.coordinator.create(OWNER, "observe this screen", now=100)
        task_id = str(task["task_id"])
        self.coordinator.record_progress(
            task_id,
            OWNER,
            phase="OBSERVATION",
            progress_ref="progress.observe.001",
            state_ref="state.screen.001",
            evidence_status="PRESENT",
            now=101,
        )
        stalled = self.coordinator.record_progress(
            task_id,
            OWNER,
            phase="OBSERVATION",
            progress_ref="progress.observe.002",
            state_ref="state.screen.001",
            evidence_status="PRESENT",
            now=102,
        )
        skipped = self.coordinator.run_next(task_id, OWNER, now=103)

        self.assertEqual("interrupted", stalled["status"])
        self.assertEqual("REPEATED_STATE", stalled["recovery_contract"]["failure_category"])
        self.assertFalse(stalled["recovery_contract"]["automatic_retry_allowed"])
        self.assertEqual("not_run", skipped["status"])
        self.assertEqual([], self.runtime.execution_calls)
        with self.assertRaises(CoordinatorStateError):
            self.coordinator.resume(task_id, OWNER, now=104)

        resumed = self.coordinator.resume(task_id, OWNER, "observe this screen", now=105)
        completed = self.coordinator.run_next(task_id, OWNER, now=106)
        self.assertEqual("running", resumed["status"])
        self.assertEqual("completed", completed["status"])
        self.assertEqual(["fresh-read-only-subgoal"], self.runtime.execution_calls)
        self.assertFalse(completed["task"]["recovery_required"])

    def test_context_recovery_invalidates_action_metadata_and_forbids_completion(self) -> None:
        context = self.contexts.create(
            OWNER,
            task_ref="task.progress.recovery.01",
            workspace_ref="workspace.agent.runtime",
            goal_ref="goal.handle.01",
            intent_category="observe_screen",
            domain_code="agent",
            now=100,
        )
        context_id = str(context["context_id"])
        self.contexts.activate(context_id, OWNER, now=101)
        self.contexts.set_plan_reference(
            context_id,
            OWNER,
            plan_ref="plan.runtime.001",
            plan_status="PLANNED",
            step_count=1,
            pending_action_state="AWAITING_CONFIRMATION",
            now=102,
        )
        recovery = self.contexts.require_recovery(context_id, OWNER, "REPEATED_ACTION", now=103)

        self.assertEqual("PAUSED", recovery["state"])
        self.assertTrue(recovery["recovery_required"])
        self.assertEqual("REPEATED_ACTION", recovery["recovery_failure_category"])
        self.assertFalse(recovery["plan_reference_present"])
        self.assertEqual("INVALIDATED", recovery["pending_action_state"])
        self.assertEqual(
            ["reobserve", "context_update", "replan", "reauthorize", "risk_reassess"],
            recovery["recovery_requirements"],
        )
        with self.assertRaises(ActiveContextStateError):
            self.contexts.complete(context_id, OWNER, now=104)

    def test_restart_marks_active_context_for_fresh_processing_without_device_access(self) -> None:
        context = self.contexts.create(
            OWNER,
            task_ref="task.progress.restart.01",
            workspace_ref="workspace.agent.runtime",
            goal_ref="goal.handle.02",
            intent_category="observe_screen",
            domain_code="agent",
            now=100,
        )
        context_id = str(context["context_id"])
        self.contexts.activate(context_id, OWNER, now=101)
        restarted = ActiveContextEngine(self.root / "contexts")
        result = restarted.recover_after_restart(now=102)
        recovered = restarted.inspect(context_id, OWNER, now=103)

        self.assertEqual([context_id], result["paused_context_ids"])
        self.assertEqual([], result["device_actions_sent"])
        self.assertEqual("PAUSED", recovered["state"])
        self.assertTrue(recovered["recovery_required"])
        self.assertEqual("INTERRUPTED", recovered["recovery_failure_category"])

    def test_storage_and_source_boundaries_are_non_replayable(self) -> None:
        task = self.coordinator.create(OWNER, "raw goal must never persist", now=100)
        self.coordinator.record_progress(
            str(task["task_id"]),
            OWNER,
            phase="OBSERVATION",
            progress_ref="progress.observe.001",
            evidence_status="PRESENT",
            now=101,
        )
        raw = (self.root / "coordinator.json").read_text(encoding="utf-8")
        for forbidden in ("raw goal", "progress.observe.001", "screenshot", "coordinate", "replay"):
            self.assertNotIn(forbidden, raw)

        source = inspect.getsource(TaskProgressMonitor)
        self.assertNotIn("MCPClient(", source)
        self.assertNotIn("call_tool(", source)
        self.assertNotIn("execute_subgoal(", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
