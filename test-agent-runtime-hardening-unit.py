#!/usr/bin/env python3
"""TEST-40.0 static gates for execution, storage, and redacted tracing.

These tests use only local fake transports and temporary Mac storage. They do
not contact an iPhone, call a live MCP endpoint, or perform device actions.
"""

from __future__ import annotations

import tempfile
import unittest
import multiprocessing
from pathlib import Path
from typing import Any

from phoneharness_agent import (
    DynamicPlanner,
    MCPClient,
    MCPExecutionBoundaryError,
    PlanExecutor,
    PrivateRecordWriter,
    RedactedAgentTrace,
    RedactedAgentTraceError,
    Snapshot,
)


class FakeMCPClient(MCPClient):
    def __init__(self) -> None:
        super().__init__("http://unused.invalid")
        self.requests: list[tuple[str, dict[str, Any]]] = []

    def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.requests.append((method, dict(params)))
        self.assert_tool_call(method, params)
        return {
            "structuredContent": {
                "frontmost": {"name": "Test", "bundleId": "example.test"},
                "element_count": 1,
                "source": "AX",
                "elements": [{"text": "Ready", "clickable": False}],
            }
        }

    @staticmethod
    def assert_tool_call(method: str, params: dict[str, Any]) -> None:
        if method != "tools/call" or not isinstance(params.get("name"), str):
            raise AssertionError("expected a structured MCP tool request")


def snapshot() -> Snapshot:
    return Snapshot(
        frontmost_name="Test",
        frontmost_bundle_id="example.test",
        element_count=1,
        source="AX",
        elements=({"text": "Ready", "clickable": False},),
    )


def counter_initial() -> dict[str, Any]:
    return {"count": 0}


def counter_validate(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"count"} or not isinstance(value["count"], int):
        raise ValueError("invalid payload")
    return {"count": value["count"]}


def increment_private_counter(directory: str, event_id: str) -> None:
    writer = PrivateRecordWriter(directory, "shared.json")
    writer.mutate(
        event_id=event_id,
        initial_payload=counter_initial,
        validate_payload=counter_validate,
        mutation=lambda value: (value.update({"count": value["count"] + 1}) or "state.%s.v1" % event_id),
    )


class RuntimeHardeningTests(unittest.TestCase):
    def test_public_mcp_surface_rejects_action_before_transport(self) -> None:
        client = FakeMCPClient()
        with self.assertRaises(MCPExecutionBoundaryError):
            client.call_tool("tap_element", {"selector": "private"})
        self.assertEqual([], client.requests)

    def test_executor_owned_port_retains_risk_and_verifier_path(self) -> None:
        client = FakeMCPClient()
        plan = DynamicPlanner().plan("描述当前屏幕", {"describe_screen"}, snapshot())
        result = PlanExecutor(client).execute(plan)
        self.assertEqual("passed", result["status"])
        self.assertEqual("allowed", result["risk_assessment"]["status"])
        self.assertEqual(["describe_screen", "describe_screen"], [entry[1]["name"] for entry in client.requests])
        self.assertEqual(2, len(client.requests))

    def test_read_only_mcp_surface_remains_available_for_observation(self) -> None:
        client = FakeMCPClient()
        response = client.call_tool("describe_screen", {"include_screenshot": False})
        self.assertEqual("example.test", response["frontmost"]["bundleId"])
        self.assertEqual(1, len(client.requests))

    def test_private_writer_recovers_last_valid_generation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            writer = PrivateRecordWriter(directory, "state.json")

            def initial() -> dict[str, Any]:
                return {"value": 0}

            def validate(value: Any) -> dict[str, Any]:
                if not isinstance(value, dict) or set(value) != {"value"} or not isinstance(value["value"], int):
                    raise ValueError("invalid payload")
                return {"value": value["value"]}

            writer.mutate(
                event_id="event.alpha",
                initial_payload=initial,
                validate_payload=validate,
                mutation=lambda value: (value.update({"value": 1}) or "state.alpha.v1"),
            )
            writer.mutate(
                event_id="event.beta",
                initial_payload=initial,
                validate_payload=validate,
                mutation=lambda value: (value.update({"value": 2}) or "state.beta.v2"),
            )
            self.assertTrue(writer.recovery_path.exists())
            writer.path.write_text("{", encoding="utf-8")
            self.assertEqual({"value": 1}, writer.read(initial, validate))

    def test_private_writer_idempotency_prevents_duplicate_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            writer = PrivateRecordWriter(directory, "state.json")

            def initial() -> dict[str, Any]:
                return {"count": 0}

            def validate(value: Any) -> dict[str, Any]:
                if not isinstance(value, dict) or set(value) != {"count"} or not isinstance(value["count"], int):
                    raise ValueError("invalid payload")
                return {"count": value["count"]}

            mutation = lambda value: (value.update({"count": value["count"] + 1}) or "state.once.v1")
            first, _result, created = writer.mutate(
                event_id="event.once", initial_payload=initial, validate_payload=validate, mutation=mutation
            )
            second, _result, created_again = writer.mutate(
                event_id="event.once", initial_payload=initial, validate_payload=validate, mutation=mutation
            )
            self.assertTrue(created)
            self.assertFalse(created_again)
            self.assertEqual({"count": 1}, first)
            self.assertEqual(first, second)

    def test_private_writer_serializes_independent_processes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context = multiprocessing.get_context("fork")
            first = context.Process(target=increment_private_counter, args=(directory, "event.processone"))
            second = context.Process(target=increment_private_counter, args=(directory, "event.processtwo"))
            first.start()
            second.start()
            first.join(10)
            second.join(10)
            self.assertEqual(0, first.exitcode)
            self.assertEqual(0, second.exitcode)
            writer = PrivateRecordWriter(directory, "shared.json")
            self.assertEqual({"count": 2}, writer.read(counter_initial, counter_validate))

    def test_trace_is_persisted_but_has_no_content_or_execution_authority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            trace = RedactedAgentTrace(directory)
            record = trace.append(
                event_id="event.trace.alpha",
                task_id="task.alpha",
                context_id="context.alpha",
                module="executor",
                event="execution_started",
                result="allowed",
                reason_code="risk_allowed",
                timestamp=100,
            )
            allowed = {
                "trace_id", "task_id", "context_id", "module", "event", "result", "reason_code", "timestamp",
                "trace_version", "content_access", "execution_authority", "write_result_ref",
            }
            self.assertEqual(allowed, set(record))
            self.assertEqual("none", record["content_access"])
            self.assertEqual("none", record["execution_authority"])
            self.assertEqual(1, len(trace.records()))

    def test_trace_rejects_content_like_codes_and_unknown_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            trace = RedactedAgentTrace(Path(directory))
            with self.assertRaises(RedactedAgentTraceError):
                trace.append(
                    event_id="event.trace.bad",
                    task_id="task.alpha",
                    context_id=None,
                    module="private message",
                    event="execution_started",
                    result="allowed",
                    reason_code="risk_allowed",
                    timestamp=100,
                )
            with self.assertRaises(TypeError):
                trace.append(  # type: ignore[call-arg]
                    event_id="event.trace.extra",
                    task_id="task.alpha",
                    context_id=None,
                    module="executor",
                    event="execution_started",
                    result="allowed",
                    reason_code="risk_allowed",
                    timestamp=100,
                    raw_goal="private content",
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
