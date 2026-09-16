#!/usr/bin/env python3
"""Static boundary tests for TEST-25 Semantic Planner -> Executor.

These tests never contact an iPhone. They cover the new opaque binding seam
and prove that TEST-25 still delegates every device action to the existing
Risk Controller, PlanExecutor, and Verifier boundaries.
"""

from __future__ import annotations

import json
import unittest

from phoneharness_agent import (
    BoundSemanticControl,
    DynamicPlanner,
    MCPCallError,
    PlanExecutor,
    PlannerSemanticContext,
    RiskController,
    SemanticActionBindingStore,
    SemanticExecutionRuntime,
    SemanticObservation,
    Snapshot,
)


TOOLS = {"describe_screen", "tap_element", "input_text", "type_text", "press_key"}
RAW_SEARCH_LABEL = "Search or enter URL"


def semantic_context(*, confidence: float = 0.9) -> PlannerSemanticContext:
    return PlannerSemanticContext.from_semantic_observation(
        SemanticObservation(
            source="AX",
            timestamp=100,
            confidence=confidence,
            page_type="search",
            intents=(
                {"intent": "search", "count": 1, "actionable": True},
                {"intent": "text_entry", "count": 1, "actionable": True},
            ),
            actionable=True,
        )
    )


def raw_snapshot(*, verified: bool = False) -> Snapshot:
    elements: tuple[dict[str, object], ...]
    if verified:
        elements = ({"text": "PhoneHarness results", "clickable": False},)
    else:
        elements = (
            {
                "text": RAW_SEARCH_LABEL,
                "clickable": True,
                "rect": {"x": 91, "y": 42, "width": 320, "height": 44},
            },
        )
    return Snapshot(
        frontmost_name="Private Browser",
        frontmost_bundle_id="private.browser.example",
        element_count=len(elements),
        source="accessibility",
        elements=elements,
    )


class OrderedRiskController(RiskController):
    def __init__(self) -> None:
        super().__init__()
        self.assessed = False

    def assess(self, *args: object, **kwargs: object) -> dict[str, object]:
        self.assessed = True
        return super().assess(*args, **kwargs)  # type: ignore[arg-type]


class RecordingClient:
    def __init__(self, *, verifier_passes: bool = True, risk_controller: OrderedRiskController | None = None) -> None:
        self.verifier_passes = verifier_passes
        self.risk_controller = risk_controller
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.describe_calls: list[bool] = []

    def list_tools(self) -> set[str]:
        return set(TOOLS)

    def observe_planner_context(self) -> PlannerSemanticContext:
        return semantic_context()

    def describe(self, include_ocr: bool = False) -> Snapshot:
        self.describe_calls.append(include_ocr)
        if len(self.describe_calls) == 1:
            return raw_snapshot()
        return raw_snapshot(verified=self.verifier_passes)

    def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        if self.risk_controller is not None:
            assert self.risk_controller.assessed, "Risk Controller must run before the first MCP action"
        self.calls.append((name, dict(arguments)))
        return {"ok": True}


class NeverCallClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        self.calls.append((name, dict(arguments)))
        raise AssertionError("a rejected or expired binding must not reach MCP")

    def describe(self, include_ocr: bool = False) -> Snapshot:
        del include_ocr
        raise AssertionError("verification must not start when the binding cannot resolve")


class SemanticExecutionTests(unittest.TestCase):
    def build_plan(self, *, now: int | None = None) -> tuple[dict[str, object], SemanticActionBindingStore]:
        store = SemanticActionBindingStore(ttl_seconds=60)
        context = semantic_context()
        binding = store.bind_search_control(raw_snapshot(), context, now=now)
        plan = DynamicPlanner().plan_search_from_semantic_context(
            "搜索 PhoneHarness",
            TOOLS,
            context,
            binding,
            now=now,
        )
        return plan, store

    def test_bound_control_schema_excludes_raw_selector_and_geometry(self) -> None:
        store = SemanticActionBindingStore()
        binding = store.bind_search_control(raw_snapshot(), semantic_context(), now=100)
        schema = binding.schema()
        self.assertEqual(
            {"binding_version", "binding_id", "semantic_role", "source", "candidate_count", "expires_at"},
            set(schema),
        )
        serialized = json.dumps(schema, ensure_ascii=False)
        self.assertNotIn(RAW_SEARCH_LABEL, serialized)
        self.assertNotIn("rect", serialized)
        self.assertNotIn("Private Browser", serialized)

    def test_planner_receives_only_context_and_opaque_binding(self) -> None:
        plan, _store = self.build_plan()
        self.assertEqual("ready", plan["status"])
        self.assertNotIn("observation", plan)
        self.assertEqual(["tap_element", "input_text", "press_key"], [step["tool"] for step in plan["steps"]])
        self.assertEqual({"semantic_binding_id"}, set(plan["steps"][0]["arguments"]))
        serialized = json.dumps(plan, ensure_ascii=False)
        self.assertNotIn(RAW_SEARCH_LABEL, serialized)
        self.assertNotIn("private.browser.example", serialized)
        self.assertNotIn("rect", serialized)

    def test_planner_rejects_expired_or_non_semantic_binding(self) -> None:
        plan, store = self.build_plan(now=100)
        binding_schema = plan["semantic_binding"]
        expired = BoundSemanticControl(
            binding_version=str(binding_schema["binding_version"]),
            binding_id=str(binding_schema["binding_id"]),
            semantic_role=str(binding_schema["semantic_role"]),
            source=str(binding_schema["source"]),
            candidate_count=int(binding_schema["candidate_count"]),
            expires_at=100,
        )
        blocked = DynamicPlanner().plan_search_from_semantic_context(
            "搜索 PhoneHarness", TOOLS, semantic_context(), expired, now=100
        )
        self.assertEqual("blocked", blocked["status"])
        self.assertEqual([], blocked["steps"])
        self.assertIsInstance(store, SemanticActionBindingStore)

    def test_risk_controller_runs_before_bound_mcp_action_and_verifier_passes(self) -> None:
        plan, store = self.build_plan()
        controller = OrderedRiskController()
        client = RecordingClient(verifier_passes=True, risk_controller=controller)
        execution = PlanExecutor(client, controller, store).execute(plan)
        self.assertEqual("passed", execution["status"])
        self.assertEqual("allowed", execution["risk_assessment"]["status"])
        self.assertTrue(execution["verification"]["passed"])
        self.assertEqual(["tap_element", "input_text", "press_key"], [name for name, _ in client.calls])
        self.assertEqual(RAW_SEARCH_LABEL, client.calls[0][1]["text"])
        self.assertEqual([True, True], client.describe_calls)

    def test_expired_binding_fails_closed_before_mcp_and_enters_repair_handoff(self) -> None:
        store = SemanticActionBindingStore(ttl_seconds=1)
        context = semantic_context()
        binding = store.bind_search_control(raw_snapshot(), context, now=100)
        plan = DynamicPlanner().plan_search_from_semantic_context(
            "搜索 PhoneHarness", TOOLS, context, binding, now=100
        )
        client = NeverCallClient()
        execution = PlanExecutor(client, semantic_binding_store=store).execute(plan)
        self.assertEqual("failed", execution["status"])
        self.assertEqual("semantic_binding_unavailable", execution["retry_repair_handoff"]["reason"])
        self.assertEqual([], client.calls)

    def test_verification_failure_returns_existing_repair_handoff_without_replay(self) -> None:
        plan, store = self.build_plan()
        plan["verification"] = {"kind": "visible_text_contains", "text": "PhoneHarness", "timeout_seconds": 0}
        client = RecordingClient(verifier_passes=False)
        execution = PlanExecutor(client, semantic_binding_store=store).execute(plan)
        self.assertEqual("failed", execution["status"])
        self.assertEqual("verification_failed", execution["retry_repair_handoff"]["reason"])
        self.assertEqual(["tap_element", "input_text", "press_key"], [name for name, _ in client.calls])

    def test_runtime_only_reads_before_existing_executor_owns_actions(self) -> None:
        client = RecordingClient(verifier_passes=True)
        result = SemanticExecutionRuntime(client).execute_search("搜索 PhoneHarness")
        self.assertEqual("passed", result["status"])
        self.assertEqual("passed", result["execution"]["status"])
        self.assertNotIn("observation", result["plan"])
        self.assertEqual(["tap_element", "input_text", "press_key"], [name for name, _ in client.calls])
        self.assertEqual([False, True], client.describe_calls)

    def test_runtime_precondition_failure_is_blocked_without_interaction(self) -> None:
        class NoSearchRuntimeClient(RecordingClient):
            def describe(self, include_ocr: bool = False) -> Snapshot:
                self.describe_calls.append(include_ocr)
                return Snapshot("", "", 1, "accessibility", ({"text": "Home", "clickable": True},))

        client = NoSearchRuntimeClient()
        result = SemanticExecutionRuntime(client).execute_search("搜索 PhoneHarness")
        self.assertEqual("blocked", result["status"])
        self.assertEqual("semantic_precondition_blocked", result["retry_repair_handoff"]["reason"])
        self.assertEqual([], client.calls)

    def test_runtime_translates_mcp_preflight_failure_to_safe_handoff(self) -> None:
        class OfflineClient(RecordingClient):
            def list_tools(self) -> set[str]:
                raise MCPCallError("offline")

        result = SemanticExecutionRuntime(OfflineClient()).execute_search("搜索 PhoneHarness")
        self.assertEqual("blocked", result["status"])
        self.assertEqual("semantic_precondition_blocked", result["retry_repair_handoff"]["reason"])
        self.assertEqual("MCPCallError", result["retry_repair_handoff"]["error_type"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
