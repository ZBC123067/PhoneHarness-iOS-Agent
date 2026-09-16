#!/usr/bin/env python3
"""Static lifecycle tests for TEST-17 Long Running Task.

These tests use a fake read-only client. They never contact the iPhone or run
an MCP action other than the shape of `describe_screen` represented locally.
"""

from __future__ import annotations

import json
import stat
import tempfile
import unittest
from pathlib import Path

from phoneharness_agent import (
    LongRunningTaskController,
    MCPCallError,
    Snapshot,
    TaskOwnershipError,
    TaskStateError,
    TaskStateStore,
)


OWNER = "unit-test-owner-token-0001"
OTHER_OWNER = "unit-test-owner-token-9999"


class ReadOnlyClient:
    def __init__(self, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    def describe(self, include_ocr: bool = False) -> Snapshot:
        self.calls += 1
        if self.fail:
            raise MCPCallError("synthetic observation failure")
        return Snapshot(
            frontmost_name="Sensitive App Name",
            frontmost_bundle_id="example.test.app",
            element_count=7,
            source="accessibility",
            elements=({"text": "sensitive screen text"},),
        )


class LongRunningTaskTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "private" / "tasks-v1.json"
        self.store = TaskStateStore(self.path)
        self.controller = LongRunningTaskController(self.store)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_create_is_private_and_redacts_raw_goal_or_tool_data(self) -> None:
        task = self.controller.create(OWNER, max_observations=2, now=100)
        raw = self.path.read_text(encoding="utf-8")
        persisted = json.loads(raw)

        self.assertEqual("waiting", task["status"])
        self.assertTrue(task["owner_bound"])
        self.assertEqual(0o700, stat.S_IMODE(self.path.parent.stat().st_mode))
        self.assertEqual(0o600, stat.S_IMODE(self.path.stat().st_mode))
        for prohibited in ("goal", "query", "arguments", "steps", "screenshot", "response", "sensitive"):
            self.assertNotIn(prohibited, raw)
        self.assertEqual(["schema_version", "task_runtime_version", "tasks"], sorted(persisted))

    def test_tick_is_bounded_and_uses_only_read_only_observation(self) -> None:
        task = self.controller.create(OWNER, max_observations=2, now=100)
        client = ReadOnlyClient()

        first = self.controller.tick(task["task_id"], OWNER, client, now=101)
        second = self.controller.tick(task["task_id"], OWNER, client, now=102)

        self.assertEqual(2, client.calls)
        self.assertEqual("waiting", first["status"])
        self.assertTrue(first["checkpointed"])
        self.assertEqual("example.test.app", first["observation"]["frontmost_bundle_id"])
        self.assertEqual("completed", second["status"])
        self.assertEqual(2, second["task"]["completed_observations"])
        self.assertEqual([], second["device_actions_sent"])

    def test_pause_and_resume_require_owner_and_stop_tick_before_device_call(self) -> None:
        task = self.controller.create(OWNER, now=100)
        with self.assertRaises(TaskOwnershipError):
            self.controller.pause(task["task_id"], OTHER_OWNER, now=101)

        paused = self.controller.pause(task["task_id"], OWNER, now=101)
        client = ReadOnlyClient()
        skipped = self.controller.tick(task["task_id"], OWNER, client, now=102)
        resumed = self.controller.resume(task["task_id"], OWNER, now=103)

        self.assertEqual("paused", paused["status"])
        self.assertEqual("not_run", skipped["status"])
        self.assertEqual(0, client.calls)
        self.assertEqual("waiting", resumed["status"])

    def test_cancel_is_terminal_and_cannot_resume_or_tick(self) -> None:
        task = self.controller.create(OWNER, now=100)
        cancelled = self.controller.cancel(task["task_id"], OWNER, now=101)
        with self.assertRaises(TaskStateError):
            self.controller.resume(task["task_id"], OWNER, now=102)

        client = ReadOnlyClient()
        skipped = self.controller.tick(task["task_id"], OWNER, client, now=103)
        self.assertEqual("cancelled", cancelled["status"])
        self.assertEqual("not_run", skipped["status"])
        self.assertEqual(0, client.calls)

    def test_restart_recovery_requires_an_explicit_owner_resume(self) -> None:
        task = self.controller.create(OWNER, now=100)
        restarted = LongRunningTaskController(TaskStateStore(self.path))
        recovery = restarted.recover_after_restart(now=101)
        interrupted = restarted.inspect(task["task_id"], OWNER)

        self.assertEqual([task["task_id"]], recovery["interrupted_task_ids"])
        self.assertEqual([], recovery["device_actions_sent"])
        self.assertEqual("interrupted", interrupted["status"])
        self.assertTrue(interrupted["recovery_required"])
        client = ReadOnlyClient()
        self.assertEqual("not_run", restarted.tick(task["task_id"], OWNER, client, now=102)["status"])
        self.assertEqual(0, client.calls)
        self.assertEqual("waiting", restarted.resume(task["task_id"], OWNER, now=103)["status"])

    def test_failed_observation_never_retries_or_persists_raw_error(self) -> None:
        task = self.controller.create(OWNER, now=100)
        client = ReadOnlyClient(fail=True)
        failed = self.controller.tick(task["task_id"], OWNER, client, now=101)
        raw = self.path.read_text(encoding="utf-8")

        self.assertEqual(1, client.calls)
        self.assertEqual("failed", failed["status"])
        self.assertEqual("mcp_observation_failed", failed["error_code"])
        self.assertNotIn("synthetic observation failure", raw)

    def test_permission_broad_state_file_is_rejected(self) -> None:
        task = self.controller.create(OWNER, now=100)
        self.assertTrue(task["task_id"])
        self.path.chmod(0o644)
        with self.assertRaises(OSError):
            self.controller.inspect(task["task_id"], OWNER)


if __name__ == "__main__":
    unittest.main(verbosity=2)
