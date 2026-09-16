#!/usr/bin/env python3
"""Static privacy and persistence tests for TEST-14 AgentMemoryStore."""

from __future__ import annotations

import multiprocessing
import stat
import tempfile
import unittest
from pathlib import Path

from phoneharness_agent import AgentMemoryStore


def plan_for(bundle_id: str = "com.example.app", status: str = "ready") -> dict[str, object]:
    return {
        "goal": "在当前页面搜索 private-query-should-not-persist",
        "intent": "search_current",
        "status": status,
        "observation": {
            "frontmost": {"name": "Example App", "bundle_id": bundle_id},
            "element_count": 7,
            "source": "accessibility",
            "elements": [{"text": "private-ui-text"}],
        },
        "selected_tools": ["tap_element", "input_text", "press_key", "input_text"],
        "steps": [{"arguments": {"text": "private-query-should-not-persist"}}],
    }


def record_plan_in_child(path: str, status: str) -> None:
    """Exercise the JSONL store from a separate host process."""

    AgentMemoryStore(path, capacity=32).record_plan(plan_for(status=status))


class AgentMemoryStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "memory.jsonl"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_record_is_sanitized_and_private(self) -> None:
        store = AgentMemoryStore(self.path)
        entry = store.record_plan(plan_for())
        raw = self.path.read_text(encoding="utf-8")
        self.assertEqual(entry["record_id"], store.recent(limit=1)[0]["record_id"])
        self.assertEqual(["tap_element", "input_text", "press_key"], entry["selected_tools"])
        self.assertNotIn("private-query-should-not-persist", raw)
        self.assertNotIn("private-ui-text", raw)
        self.assertNotIn('"goal"', raw)
        self.assertEqual(0o600, stat.S_IMODE(self.path.stat().st_mode))

    def test_recent_can_filter_by_foreground_bundle(self) -> None:
        store = AgentMemoryStore(self.path)
        first = store.record_plan(plan_for("com.example.one"))
        second = store.record_plan(plan_for("com.example.two"))
        self.assertEqual(second["record_id"], store.recent(limit=1)[0]["record_id"])
        filtered = store.recent(limit=5, bundle_id="com.example.one")
        self.assertEqual([first["record_id"]], [record["record_id"] for record in filtered])

    def test_capacity_keeps_newest_records(self) -> None:
        store = AgentMemoryStore(self.path, capacity=2)
        first = store.record_plan(plan_for(status="one"))
        second = store.record_plan(plan_for(status="two"))
        third = store.record_plan(plan_for(status="three"))
        records = store.recent(limit=5)
        self.assertEqual([third["record_id"], second["record_id"]], [record["record_id"] for record in records])
        self.assertNotIn(first["record_id"], [record["record_id"] for record in records])

    def test_corrupt_line_is_ignored_without_losing_new_record(self) -> None:
        self.path.write_text("not json\n", encoding="utf-8")
        self.path.chmod(0o600)
        store = AgentMemoryStore(self.path)
        entry = store.record_plan(plan_for())
        records = store.recent(limit=5)
        self.assertEqual([entry["record_id"]], [record["record_id"] for record in records])

    def test_read_rejects_a_permission_broad_memory_file(self) -> None:
        self.path.write_text("", encoding="utf-8")
        self.path.chmod(0o644)
        with self.assertRaises(OSError):
            AgentMemoryStore(self.path).recent(limit=1)
        with self.assertRaises(OSError):
            AgentMemoryStore(self.path).records()

    def test_cross_process_writers_preserve_every_sanitized_record(self) -> None:
        context = multiprocessing.get_context("spawn")
        processes = [
            context.Process(target=record_plan_in_child, args=(str(self.path), "child-%d" % index))
            for index in range(6)
        ]
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=10)
            self.assertEqual(0, process.exitcode)

        records = AgentMemoryStore(self.path, capacity=32).records()
        outcomes = {record.get("outcome") for record in records if record.get("record_type") == "plan"}
        self.assertEqual({"child-%d" % index for index in range(6)}, outcomes)
        self.assertEqual(0o600, stat.S_IMODE(self.path.with_name(".%s.lock" % self.path.name).stat().st_mode))


if __name__ == "__main__":
    unittest.main(verbosity=2)
