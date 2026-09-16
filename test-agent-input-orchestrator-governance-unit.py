#!/usr/bin/env python3
"""Host-only governance integration for Batch 1E P5.

No test contacts a live MCP endpoint or an iPhone. The fake transport is only
reachable through PlanExecutor's private execution seam.
"""

from __future__ import annotations

import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path

from phoneharness_agent import (
    ActionObligationLedger,
    ActiveContextEngine,
    CapabilityCatalog,
    CapabilityEvidence,
    CapabilityMethodRegistry,
    INPUT_TEXT_CAPABILITY_DEFINITION,
    INPUT_TEXT_METHOD_DEFINITIONS,
    GovernedInputTextRuntime,
    InputTextTargetAuthorization,
    InputTextActionBindingError,
    MCPClient,
    RiskController,
    Snapshot,
    SemanticSearchFieldEvidence,
    SemanticSearchPageObservation,
)


class FakeMCPClient(MCPClient):
    def __init__(self, *, delivered_text: str = "") -> None:
        super().__init__("http://unused.invalid")
        self.delivered_text = delivered_text
        self.calls: list[str] = []
        self.field_value = ""
        self.observation_version = 0

    def _rpc(self, method, params):
        if method != "tools/call":
            raise AssertionError("unexpected RPC method")
        self.calls.append(str(params.get("name")))
        if params.get("name") == "exp_keycode_tap" and self.delivered_text:
            self.field_value += chr(ord("a") + params["arguments"]["usage"] - 4)
        return {"structuredContent": {"accepted": True, "dispatched": True, "delivery": "unverified"}}

    def describe(self, *, include_ocr=False):
        elements = ({"text": self.delivered_text},) if self.delivered_text else ({"text": "Ready"},)
        return Snapshot("Test", "example.test", len(elements), "AX", elements)

    def observe_semantic_search_page(self, *, task_id, context_id, expected_query=None):
        self.observation_version += 1
        field = SemanticSearchFieldEvidence(
            "field.primary", "AX", "text_field", "xc_attribute",
            True, "xc_attribute", False, "xc_attribute", True, "xc_attribute",
            True, "xc_attribute", True, "xc_attribute", True, "xc_attribute", True, "Field",
            self.field_value == expected_query, "xc_attribute",
            same_leaf_source="direct_snapshot", snapshot_ref=f"synthetic.{self.observation_version}",
        )
        return SemanticSearchPageObservation(
            "AX", int(time.time()), self.observation_version, "page.current", task_id, context_id, (field,),
            freshness_source="direct_snapshot", device_generation=field.snapshot_ref,
            device_generation_source="direct_snapshot",
        )


class DenyRisk(RiskController):
    def assess(self, plan, authorization=None, *, consume_authorization=False, now=None):
        return {"status": "blocked", "reason": "test_risk_denied"}


def registry() -> CapabilityMethodRegistry:
    catalog = CapabilityCatalog((INPUT_TEXT_CAPABILITY_DEFINITION,))
    # Host-only integration seam. These declarations are intentionally not
    # promoted in production; the fixture only proves the governed wiring.
    methods = tuple(
        replace(
            method,
            lifecycle="ACTIVE",
            verification_status="device_pass",
            evidence=CapabilityEvidence(success_count=1, confidence=1.0, last_verified=1),
        )
        for method in INPUT_TEXT_METHOD_DEFINITIONS
    )
    return CapabilityMethodRegistry(catalog, methods)


def target(*, keyboard="apple_qwerty", clear=False, point=(50.0, 60.0)) -> InputTextTargetAuthorization:
    return InputTextTargetAuthorization(
        task_id="task.input.governed",
        context_id="context.input.governed",
        context_version=1,
        authorization_ref="direct.input.authorization",
        keyboard=keyboard,
        clear_available=clear,
        paste_point=point,
    )


def issued_target(runtime, directory, text, *, sensitive=False, clear=False):
    engine = ActiveContextEngine(Path(directory) / "context")
    owner = "synthetic-host-context-owner"
    context = engine.create(owner, task_ref="task.input.governed", workspace_ref="workspace.test",
                            goal_ref="goal.test", intent_category="text_entry", domain_code="test")
    engine.activate(context["context_id"], owner)
    return runtime._risk.authorize_input_target(
        text, client=runtime._client, context_engine=engine, context_id=context["context_id"],
        owner_token=owner, keyboard="apple_qwerty", sensitive=sensitive, clear_available=clear,
    )


class GovernedInputRuntimeTests(unittest.TestCase):
    def test_s1_uses_plan_executor_and_per_action_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = FakeMCPClient(delivered_text="a")
            runtime = GovernedInputTextRuntime(
                client,
                capability_method_registry=registry(),
                action_obligation_ledger=ActionObligationLedger(directory),
            )
            result = runtime.execute("a", target=issued_target(runtime, directory, "a"))
        self.assertEqual("completed", result["status"])
        self.assertEqual("s1_keycode", result["strategy"])
        self.assertEqual(["exp_keycode_tap"], client.calls)
        self.assertEqual(1, runtime.plan_executor_invocation_count)
        self.assertEqual("VERIFIED", result["attempts"][0]["ledger_state"])

    def test_clear_without_same_leaf_control_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = FakeMCPClient(delivered_text="a")
            runtime = GovernedInputTextRuntime(
                client,
                capability_method_registry=registry(),
                action_obligation_ledger=ActionObligationLedger(directory),
            )
            with self.assertRaises(InputTextActionBindingError):
                issued_target(runtime, directory, "a", clear=True)
        self.assertEqual(0, runtime.plan_executor_invocation_count)
        self.assertEqual([], client.calls)

    def test_s4_is_risk_blocked_before_any_external_action(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = FakeMCPClient(delivered_text="你好")
            runtime = GovernedInputTextRuntime(
                client,
                capability_method_registry=registry(),
                action_obligation_ledger=ActionObligationLedger(directory),
            )
            result = runtime.execute("你好", target=issued_target(runtime, directory, "你好"))
            plan = runtime._plan_for("set_clipboard", "preflight", "unused", "unused", "unused")
            self.assertEqual("forbidden_low_level_tool", runtime._risk.assess(plan)["reason"])
        self.assertEqual("blocked", result["status"])
        self.assertEqual([], client.calls)
        self.assertEqual(0, runtime.plan_executor_invocation_count)
        self.assertEqual(0, result["device_action_count"])

    def test_risk_denial_produces_zero_external_actions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = FakeMCPClient(delivered_text="a")
            runtime = GovernedInputTextRuntime(
                client,
                capability_method_registry=registry(),
                action_obligation_ledger=ActionObligationLedger(directory),
                risk_controller=DenyRisk(),
            )
            result = runtime.execute("a", target=issued_target(runtime, directory, "a"))
        self.assertEqual("blocked", result["status"])
        self.assertEqual([], client.calls)
        self.assertEqual(0, runtime.plan_executor_invocation_count)

    def test_missing_direct_target_authorization_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = FakeMCPClient(delivered_text="a")
            runtime = GovernedInputTextRuntime(
                client,
                capability_method_registry=registry(),
                action_obligation_ledger=ActionObligationLedger(directory),
            )
            result = runtime.execute("a", target=None)
        self.assertEqual("DIRECT_INPUT_AUTHORIZATION_REQUIRED", result["reason_code"])
        self.assertEqual([], client.calls)
        self.assertEqual(0, runtime.plan_executor_invocation_count)

    def test_dispatch_does_not_claim_delivery_or_semantic_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = FakeMCPClient(delivered_text="a")
            runtime = GovernedInputTextRuntime(
                client,
                capability_method_registry=registry(),
                action_obligation_ledger=ActionObligationLedger(directory),
            )
            result = runtime.execute("a", target=issued_target(runtime, directory, "a"))
        self.assertTrue(result["dispatched"])
        self.assertEqual("unverified", result["delivery"])
        self.assertEqual("VERIFIER_REQUIRED", result["semantic_success"])
        self.assertNotIn("verified", result)

    def test_sensitive_never_enters_clipboard_route(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = FakeMCPClient(delivered_text="a")
            runtime = GovernedInputTextRuntime(
                client,
                capability_method_registry=registry(),
                action_obligation_ledger=ActionObligationLedger(directory),
            )
            result = runtime.execute("a", target=issued_target(runtime, directory, "a", sensitive=True), sensitive=True)
        self.assertEqual("s1_keycode", result["strategy"])
        self.assertNotIn("set_clipboard", client.calls)


if __name__ == "__main__":
    unittest.main()
