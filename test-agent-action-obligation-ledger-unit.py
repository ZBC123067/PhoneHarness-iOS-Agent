#!/usr/bin/env python3
"""TEST-45 unit and negative gates for the Action Obligation Ledger.

All tests use a local fake transport and temporary Mac storage. They do not
contact an iPhone, call a live MCP endpoint, or perform a device action.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from phoneharness_agent import (
    ActionObligationLedger,
    ActionObligationPolicyError,
    ActionObligationRequest,
    ActionObligationTransitionError,
    DynamicPlanner,
    MCPCallError,
    MCPClient,
    PlanExecutor,
    Snapshot,
)


class FakeMCPClient(MCPClient):
    def __init__(self, *, fail_dispatch: bool = False) -> None:
        super().__init__("http://unused.invalid")
        self.fail_dispatch = fail_dispatch
        self.requests: list[str] = []

    def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method != "tools/call":
            raise AssertionError("expected a structured MCP tool request")
        tool = params.get("name")
        if not isinstance(tool, str):
            raise AssertionError("tool name is required")
        self.requests.append(tool)
        if self.fail_dispatch:
            raise MCPCallError("simulated transport response loss")
        return {
            "structuredContent": {
                "frontmost": {"name": "Test", "bundleId": "example.test"},
                "element_count": 1,
                "source": "AX",
                "elements": [{"text": "Ready", "clickable": False}],
            }
        }


def snapshot() -> Snapshot:
    return Snapshot(
        frontmost_name="Test",
        frontmost_bundle_id="example.test",
        element_count=1,
        source="AX",
        elements=({"text": "Ready", "clickable": False},),
    )


def ready_plan() -> dict[str, Any]:
    return DynamicPlanner().plan("描述当前屏幕", {"describe_screen"}, snapshot())


def request(ref: str = "action.ledger.alpha") -> ActionObligationRequest:
    return ActionObligationRequest(
        obligation_ref=ref,
        task_id="task.ledger",
        context_id="context.ledger",
        capability_id="capability.screen_observation.v1",
        method_id="method.mcp_describe_screen.v1",
        risk_level="read_only",
    )


class ActionObligationLedgerTests(unittest.TestCase):
    def test_state_machine_reaches_verified_with_only_redacted_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = ActionObligationLedger(directory)
            created = ledger.create(request(), timestamp=100)
            authorized = ledger.transition(
                created["obligation_id"], "AUTHORIZED", "risk_allowed", event_id="event.ledger.authorized", timestamp=101
            )
            dispatched = ledger.transition(
                authorized["obligation_id"], "DISPATCHED", "dispatch_started", event_id="event.ledger.dispatched", timestamp=102
            )
            observing = ledger.transition(
                dispatched["obligation_id"], "OBSERVING", "response_received", event_id="event.ledger.observing", timestamp=103
            )
            verified = ledger.transition(
                observing["obligation_id"], "VERIFIED", "verification_passed", event_id="event.ledger.verified", timestamp=104
            )
            self.assertEqual("VERIFIED", verified["state"])
            self.assertEqual(5, verified["revision"])
            self.assertEqual(5, verified["event_count"])
            self.assertFalse(verified["automatic_retry_allowed"])
            self.assertEqual("none", verified["content_access"])
            self.assertEqual("none", verified["replay_authority"])
            self.assertEqual(
                {
                    "action_obligation_ledger_version", "obligation_id", "task_id", "context_id", "capability_id",
                    "method_id", "risk_level", "state", "revision", "created_at", "updated_at", "event_count",
                    "automatic_retry_allowed", "content_access", "replay_authority",
                },
                set(verified),
            )

    def test_duplicate_obligation_reference_creates_no_second_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = ActionObligationLedger(directory)
            first = ledger.create(request(), timestamp=100)
            duplicate = ledger.create(request(), timestamp=105)
            records = ledger.records()
        self.assertEqual(first["obligation_id"], duplicate["obligation_id"])
        self.assertEqual(first["revision"], duplicate["revision"])
        self.assertEqual(1, len(records))

    def test_full_ledger_rotates_terminal_records_and_keeps_idempotency(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = ActionObligationLedger(directory)
            oldest_id = None
            for index in range(ActionObligationLedger.MAX_OBLIGATIONS):
                created = ledger.create(
                    request("action.ledger.rotation.%03d" % index), timestamp=100 + index
                )
                ledger.transition(
                    created["obligation_id"],
                    "FAILED",
                    "dispatch_failed",
                    event_id="event.ledger.rotation.%03d" % index,
                    timestamp=100 + index,
                )
                if index == 0:
                    oldest_id = created["obligation_id"]
            fresh = ledger.create(request("action.ledger.rotation.new"), timestamp=999)
            by_id = {record["obligation_id"]: record for record in ledger.records()}
            self.assertIn(fresh["obligation_id"], by_id)
            self.assertEqual("CREATED", by_id[fresh["obligation_id"]]["state"])
            rotated = by_id[oldest_id]
            self.assertEqual("FAILED", rotated["state"])
            self.assertEqual(1, rotated["event_count"])
            archive_payload = json.loads(
                (Path(directory) / "action-obligations-archive-v1.json").read_text(encoding="utf-8")
            )
            archived = archive_payload["payload"]["records"]
            self.assertIn(oldest_id, archived)
            self.assertGreaterEqual(len(archived[oldest_id]["events"]), 2)
            duplicate = ledger.create(request("action.ledger.rotation.000"), timestamp=1000)
            self.assertEqual(oldest_id, duplicate["obligation_id"])
            self.assertEqual("FAILED", duplicate["state"])

    def test_saturated_unfinished_obligations_stay_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = ActionObligationLedger(directory)
            for index in range(ActionObligationLedger.MAX_OBLIGATIONS):
                ledger.create(request("action.ledger.unfinished.%03d" % index), timestamp=100 + index)
            with self.assertRaises(ActionObligationPolicyError):
                ledger.create(request("action.ledger.unfinished.new"), timestamp=999)

    def test_negative_invalid_transitions_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = ActionObligationLedger(directory)
            created = ledger.create(request(), timestamp=100)
            with self.assertRaises(ActionObligationTransitionError):
                ledger.transition(
                    created["obligation_id"], "VERIFIED", "forbidden_skip", event_id="event.ledger.invalid", timestamp=101
                )
            with self.assertRaises(ActionObligationPolicyError):
                ledger.transition(
                    created["obligation_id"], "NOT_A_STATE", "invalid_state", event_id="event.ledger.badstate", timestamp=101
                )
            authorized = ledger.transition(
                created["obligation_id"], "AUTHORIZED", "risk_allowed", event_id="event.ledger.authorized", timestamp=101
            )
            with self.assertRaises(ActionObligationPolicyError):
                ledger.transition(
                    authorized["obligation_id"],
                    "DISPATCHED",
                    "dispatch_started",
                    event_id="event.ledger.time_regression",
                    timestamp=100,
                )

    def test_risk_rejection_marks_failed_before_any_mcp_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = FakeMCPClient()
            plan = ready_plan()
            plan["skill_selection"] = {"status": "blocked"}
            result = PlanExecutor(client, action_obligation_ledger=ActionObligationLedger(directory)).execute(
                plan,
                action_obligation=request(),
            )
            self.assertEqual("blocked", result["status"])
            self.assertEqual("FAILED", result["action_obligation"]["state"])
            self.assertEqual([], client.requests)

    def test_dispatch_response_loss_becomes_unknown_without_automatic_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = FakeMCPClient(fail_dispatch=True)
            ledger = ActionObligationLedger(directory)
            result = PlanExecutor(client, action_obligation_ledger=ledger).execute(
                ready_plan(),
                action_obligation=request(),
            )
            self.assertEqual("unknown_side_effect", result["status"])
            self.assertEqual("UNKNOWN_SIDE_EFFECT", result["action_obligation"]["state"])
            self.assertFalse(result["retry_repair_handoff"]["automatic_retry_allowed"])
            self.assertEqual("fresh_observation_and_verification", result["retry_repair_handoff"]["required_next_step"])
            self.assertEqual(["describe_screen"], client.requests)
            with self.assertRaises(ActionObligationTransitionError):
                ledger.transition(
                    result["action_obligation"]["obligation_id"],
                    "DISPATCHED",
                    "forbidden_replay",
                    event_id="event.ledger.forbidden_replay",
                    timestamp=101,
                )

            repeated = PlanExecutor(client, action_obligation_ledger=ledger).execute(
                ready_plan(),
                action_obligation=request(),
            )
            self.assertEqual("blocked", repeated["status"])
            self.assertEqual("UNKNOWN_SIDE_EFFECT", repeated["action_obligation"]["state"])
            self.assertEqual(["describe_screen"], client.requests)

    def test_executor_integrates_risk_dispatch_observation_and_verifier(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = FakeMCPClient()
            result = PlanExecutor(client, action_obligation_ledger=ActionObligationLedger(directory)).execute(
                ready_plan(),
                action_obligation=request(),
            )
            self.assertEqual("passed", result["status"])
            self.assertEqual("allowed", result["risk_assessment"]["status"])
            self.assertEqual("VERIFIED", result["action_obligation"]["state"])
            self.assertEqual(["describe_screen", "describe_screen"], client.requests)

    def test_interrupted_dispatch_is_reconciled_to_unknown_without_replay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = ActionObligationLedger(directory)
            created = ledger.create(request(), timestamp=100)
            authorized = ledger.transition(
                created["obligation_id"], "AUTHORIZED", "risk_allowed", event_id="event.ledger.auth", timestamp=101
            )
            dispatched = ledger.transition(
                authorized["obligation_id"], "DISPATCHED", "dispatch_started", event_id="event.ledger.dispatch", timestamp=102
            )
            recovered = ActionObligationLedger(directory).recover_interrupted(
                event_id="event.ledger.reconcile", timestamp=103
            )
            self.assertEqual((dispatched["obligation_id"],), tuple(record["obligation_id"] for record in recovered))
            self.assertEqual("UNKNOWN_SIDE_EFFECT", recovered[0]["state"])
            self.assertFalse(recovered[0]["automatic_retry_allowed"])
            with self.assertRaises(ActionObligationTransitionError):
                ledger.transition(
                    dispatched["obligation_id"],
                    "OBSERVING",
                    "retry_requested",
                    event_id="event.ledger.invalid_recovery",
                    timestamp=104,
                )
            resumed = ledger.transition(
                dispatched["obligation_id"],
                "OBSERVING",
                "fresh_observation_started",
                event_id="event.ledger.fresh_observation",
                timestamp=105,
            )
            self.assertEqual("OBSERVING", resumed["state"])

    def test_storage_contains_no_action_payload_or_private_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = ActionObligationLedger(directory)
            ledger.create(request("action.ledger.privacy"), timestamp=100)
            stored = json.loads((Path(directory) / "action-obligations-v1.json").read_text(encoding="utf-8"))
            encoded = json.dumps(stored, sort_keys=True)
            for forbidden in ("goal", "arguments", "screenshot", "ocr", "selector", "response", "password", "hello123"):
                self.assertNotIn(forbidden, encoded.casefold())
            record = next(iter(stored["payload"]["records"].values()))
            self.assertNotIn("obligation_ref", record)
            self.assertNotIn("events", ledger.records()[0])

    def test_content_like_metadata_is_rejected_before_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = ActionObligationLedger(directory)
            unsafe = ActionObligationRequest(
                obligation_ref="action.unsafe",
                task_id="task.unsafe",
                context_id=None,
                capability_id="capability.maps?destination=private",
                method_id="method.safe.v1",
                risk_level="interaction",
            )
            with self.assertRaises(ActionObligationPolicyError):
                ledger.create(unsafe, timestamp=100)
            self.assertFalse((Path(directory) / "action-obligations-v1.json").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
