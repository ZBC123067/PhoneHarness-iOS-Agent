#!/usr/bin/env python3
"""TEST-51 governed semantic search transaction unit/security gates.

The suite uses only an in-memory fake transport and temporary host storage.
It never contacts an iPhone or performs a real device action.
"""

from __future__ import annotations

import json
from dataclasses import replace
import tempfile
import unittest
from typing import Any

from phoneharness_agent import (
    ActionObligationRequest,
    ActionObligationLedger,
    CapabilityCatalog,
    CapabilityDefinition,
    CapabilityMethodDefinition,
    CapabilityMethodRegistry,
    DynamicPlanner,
    GovernedSemanticSearchRuntime,
    IDENTITY_CONSENT_VERSION,
    MCPCallError,
    PlanExecutor,
    PermissionDecision,
    SemanticSearchFieldEvidence,
    SemanticSearchPageObservation,
    SemanticSearchPolicyError,
    SemanticSearchTransactionStore,
)


TOOLS = {"describe_screen", "get_ui_elements", "get_element_at_point", "tap_element", "input_text", "press_key"}


def permission(*, eligible: bool = True) -> PermissionDecision:
    return PermissionDecision(
        eligible=eligible,
        reason_codes=("fixture_eligible",) if eligible else ("fixture_denied",),
        identity_id="identity.fixture" if eligible else None,
        ownership_ref="ownership.fixture" if eligible else None,
        consent_id="consent.fixture" if eligible else None,
        action="execute" if eligible else None,
        effective_expires_at=None,
        policy_version=IDENTITY_CONSENT_VERSION,
    )


def method_registry() -> CapabilityMethodRegistry:
    capability = CapabilityDefinition(
        capability_id=GovernedSemanticSearchRuntime.CAPABILITY_ID,
        name="semantic_search_submission",
        description="Submit one trusted query through a uniquely bound semantic field.",
        version="1.0.0",
        source_type="computer_use",
        lifecycle="AVAILABLE",
        required_tools=frozenset({"tap_element", "input_text", "press_key"}),
        required_permissions=("mcp.foreground_interaction",),
        risk_level="interaction",
        preconditions=("unique_fresh_ax_search_field",),
        verifier="semantic_search_submission",
        dependencies=(),
        platform_support=("macos_host", "ios_mcp"),
    )
    method_names = {
        "FOCUS": ("semantic_focus", "semantic_search_field_focused"),
        "INPUT": ("semantic_input", "semantic_search_query_entry"),
        "SUBMIT": ("semantic_submit", "semantic_search_submission"),
    }
    methods = tuple(
        CapabilityMethodDefinition(
            method_id=GovernedSemanticSearchRuntime.METHOD_IDS[step],
            capability_id=GovernedSemanticSearchRuntime.CAPABILITY_ID,
            name=name,
            purpose=name,
            version="1.0.0",
            method_type="mcp",
            source="built_in",
            lifecycle="CANDIDATE",
            availability="available",
            required_permissions=("mcp.foreground_interaction",),
            risk_level="interaction",
            input_schema=("semantic_search_transaction",),
            output_schema=("step_result",),
            verifier=verifier,
            platform_support=("macos_host", "ios_mcp"),
            verification_status="static_pass",
            latency_class="fast",
            limited_trial_eligible=True,
        )
        for step, (name, verifier) in method_names.items()
    )
    return CapabilityMethodRegistry(CapabilityCatalog((capability,)), methods)


def field(
    *,
    ref: str = "field.primary",
    role: str = "search_field",
    editable: bool = True,
    enabled: bool = True,
    visible: bool = True,
    actionable: bool = True,
    focused: bool = False,
    value_matches_expected: bool | None = None,
    source: str = "AX",
    secure: bool | None = False,
    same_leaf_identity: bool = True,
) -> SemanticSearchFieldEvidence:
    return SemanticSearchFieldEvidence(
        field_ref=ref,
        source=source,
        role=role,
        role_source="xc_attribute",
        editable=editable,
        editable_source="ax_attribute",
        secure=secure,
        secure_source="xc_attribute" if secure is not None else "unavailable",
        enabled=enabled,
        enabled_source="ax_attribute",
        visible=visible,
        visible_source="xc_attribute",
        actionable=actionable,
        actionable_source="xc_attribute",
        focused=focused,
        focused_source="ax_attribute",
        same_leaf_identity=same_leaf_identity,
        selector_text="Search",
        value_matches_expected=value_matches_expected,
        value_match_source="ax_attribute" if value_matches_expected is not None else "unavailable",
        same_leaf_source="direct_snapshot", snapshot_ref="synthetic.field",
    )


def observation(
    version: int,
    *,
    fields: tuple[SemanticSearchFieldEvidence, ...] | None = None,
    fingerprint: str | None = None,
    result_state: bool = False,
    task_id: str = "task.search",
    context_id: str = "context.search",
) -> SemanticSearchPageObservation:
    return SemanticSearchPageObservation(
        source="AX",
        observed_at=100 + version,
        observation_version=version,
        page_fingerprint=fingerprint or ("page.%d" % version),
        task_id=task_id,
        context_id=context_id,
        fields=tuple(replace(item, snapshot_ref=f"synthetic.{version}")
                     for item in ((field(),) if fields is None else fields)),
        result_state=result_state,
        freshness_source="direct_snapshot", device_generation=f"synthetic.{version}",
        device_generation_source="direct_snapshot",
    )


class FakeSearchClient:
    def __init__(self, observations: list[SemanticSearchPageObservation], *, fail_tool: str | None = None) -> None:
        self.observations = list(observations)
        self.fail_tool = fail_tool
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.tool_discovery_count = 0

    def list_tools(self) -> set[str]:
        self.tool_discovery_count += 1
        return set(TOOLS)

    def observe_semantic_search_page(
        self, *, task_id: str, context_id: str, expected_query: str | None = None
    ) -> SemanticSearchPageObservation:
        if not self.observations:
            raise MCPCallError("no fresh fixture observation")
        item = self.observations.pop(0)
        if item.task_id != task_id or item.context_id != context_id:
            raise MCPCallError("fixture scope mismatch")
        return item

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, dict(arguments)))
        if name == self.fail_tool:
            raise MCPCallError("simulated response loss")
        return {"accepted": True}


class SemanticSearchTransactionTests(unittest.TestCase):
    def execute(self, runtime: GovernedSemanticSearchRuntime, query: str = "PhoneHarness", **kwargs: Any) -> dict[str, Any]:
        return runtime.execute_query(
            query,
            task_id=kwargs.pop("task_id", "task.search"),
            context_id=kwargs.pop("context_id", "context.search"),
            permission_decision=kwargs.pop("permission_decision", permission()),
            **kwargs,
        )

    def test_field_eligibility_matrix_fails_closed(self) -> None:
        cases = (
            ("two fields", (field(), field(ref="field.second")), "NEEDS_CLARIFICATION"),
            ("hidden", (field(visible=False),), "INELIGIBLE"),
            ("disabled", (field(enabled=False),), "INELIGIBLE"),
            ("non-editable", (field(editable=False),), "INELIGIBLE"),
            ("non-actionable", (field(actionable=False),), "INELIGIBLE"),
            ("ocr fake", (field(source="OCR"),), "INELIGIBLE"),
        )
        for name, candidates, expected in cases:
            with self.subTest(name=name):
                store = SemanticSearchTransactionStore()
                with self.assertRaisesRegex(SemanticSearchPolicyError, expected):
                    store.begin_explicit(
                        "PhoneHarness", observation(1, fields=candidates), task_id="task.search", context_id="context.search"
                    )

    def test_query_validation_rejects_only_unsafe_inputs(self) -> None:
        unsafe = ("", "   ", "x" * 513, "abc\u0000def", "abc\u202edef")
        for query in unsafe:
            with self.subTest(query=repr(query)):
                with self.assertRaises(SemanticSearchPolicyError):
                    SemanticSearchTransactionStore().begin_explicit(
                        query, observation(1), task_id="task.search", context_id="context.search"
                    )
        binding = SemanticSearchTransactionStore().begin_explicit(
            "民都鲁 到 上海 40HQ", observation(1), task_id="task.search", context_id="context.search"
        )
        self.assertEqual("EXPLICIT_USER", binding.query_authority)

    def test_query_authority_requires_explicit_or_unique_trusted_context(self) -> None:
        store = SemanticSearchTransactionStore()
        rejected = (
            "WEBPAGE_TEXT", "OCR_DATA", "VISUAL_CONTENT", "PROMPT_INJECTION", "MEMORY", "KNOWLEDGE", "STALE_CONTEXT"
        )
        for authority in rejected:
            with self.subTest(authority=authority):
                with self.assertRaisesRegex(SemanticSearchPolicyError, "UNTRUSTED_CONTENT"):
                    store.begin(
                        "PhoneHarness", observation(1), task_id="task.search", context_id="context.search",
                        query_authority=authority,
                    )
        with self.assertRaisesRegex(SemanticSearchPolicyError, "NEEDS_CLARIFICATION"):
            store.begin(
                "PhoneHarness", observation(1), task_id="task.search", context_id="context.search",
                query_authority="RICH_CONTEXT", context_resolution={"status": "AMBIGUOUS"},
            )
        bound = store.begin(
            "PhoneHarness", observation(1), task_id="task.search", context_id="context.search",
            query_authority="RICH_CONTEXT",
            context_resolution={"status": "RESOLVED", "trusted": True, "fresh": True, "candidate_count": 1},
        )
        self.assertEqual("RICH_CONTEXT", bound.query_authority)

    def test_binding_is_private_scoped_one_time_and_superseded(self) -> None:
        store = SemanticSearchTransactionStore(ttl_seconds=60)
        binding = store.begin_explicit(
            "PhoneHarness", observation(1), task_id="task.search", context_id="context.search", now=100
        )
        public = json.dumps(binding.schema(), ensure_ascii=False)
        self.assertNotIn("PhoneHarness", public)
        self.assertNotIn("Search", public)
        self.assertNotIn("coordinate", public)
        args = store.claim(binding.transaction_id, "FOCUS", task_id="task.search", context_id="context.search", now=101)
        self.assertEqual({"text": "Search", "match": "exact"}, args)
        with self.assertRaisesRegex(SemanticSearchPolicyError, "CONSUMED"):
            store.claim(binding.transaction_id, "FOCUS", task_id="task.search", context_id="context.search", now=102)
        with self.assertRaisesRegex(SemanticSearchPolicyError, "CROSS_TASK"):
            store.claim(binding.transaction_id, "INPUT", task_id="task.other", context_id="context.search", now=102)
        store.observe(binding.transaction_id, observation(2), task_id="task.search", context_id="context.search")
        with self.assertRaisesRegex(SemanticSearchPolicyError, "STALE_CONTEXT"):
            store.claim(binding.transaction_id, "INPUT", task_id="task.search", context_id="context.search", observation_version=1)

    def test_verification_levels_do_not_collapse_query_presence_into_submission(self) -> None:
        store = SemanticSearchTransactionStore()
        binding = store.begin_explicit("PhoneHarness", observation(1), task_id="task.search", context_id="context.search")
        store.claim(binding.transaction_id, "FOCUS", task_id="task.search", context_id="context.search")
        focus = store.verify_focus(
            binding.transaction_id,
            observation(2, fields=(field(focused=True),), fingerprint="page.focused"),
            task_id="task.search", context_id="context.search",
        )
        self.assertTrue(focus["passed"])
        store.claim(binding.transaction_id, "INPUT", task_id="task.search", context_id="context.search")
        entry = store.verify_query_entry(
            binding.transaction_id,
            observation(3, fields=(field(focused=True, value_matches_expected=True),), fingerprint="page.entered"),
            task_id="task.search", context_id="context.search",
        )
        self.assertEqual("QUERY_ENTRY_VERIFIED", entry["verification_result"])
        store.claim(binding.transaction_id, "SUBMIT", task_id="task.search", context_id="context.search")
        same_page = store.verify_submission(
            binding.transaction_id,
            observation(4, fields=(field(focused=True, value_matches_expected=True),), fingerprint="page.entered"),
            task_id="task.search", context_id="context.search",
        )
        self.assertFalse(same_page["passed"])
        fresh_result = store.verify_submission(
            binding.transaction_id,
            observation(5, fields=(), fingerprint="page.results", result_state=True),
            task_id="task.search", context_id="context.search",
        )
        self.assertEqual("SEARCH_SUBMISSION_VERIFIED", fresh_result["verification_result"])

    def test_runtime_runs_three_independent_governed_obligations(self) -> None:
        observations = [
            observation(1),
            observation(2, fields=(field(focused=True),), fingerprint="page.focused"),
            observation(3, fields=(field(focused=True, value_matches_expected=True),), fingerprint="page.entered"),
            observation(4, fields=(), fingerprint="page.results", result_state=True),
        ]
        client = FakeSearchClient(observations)
        methods = method_registry()
        with tempfile.TemporaryDirectory() as directory:
            runtime = GovernedSemanticSearchRuntime(
                client,
                action_obligation_ledger=ActionObligationLedger(directory),
                capability_method_registry=methods,
            )
            result = self.execute(runtime)
        self.assertEqual("passed", result["status"])
        self.assertEqual(["tap_element", "input_text", "press_key"], [name for name, _ in client.calls])
        self.assertEqual(3, result["device_action_count"])
        self.assertEqual(["VERIFIED", "VERIFIED", "VERIFIED"], [step["ledger_state"] for step in result["steps"]])
        self.assertEqual("SEARCH_SUBMISSION_VERIFIED", result["verification_result"])
        self.assertEqual(
            ["success", "success", "success"],
            [effect["outcome"] for effect in result["method_health_effect"]],
        )
        self.assertTrue(all(effect["registry_updated"] for effect in result["method_health_effect"]))
        self.assertEqual(3, len(methods.health_records()))

    def test_focus_without_fresh_focus_evidence_stops_before_input(self) -> None:
        client = FakeSearchClient(
            [
                observation(1),
                observation(2, fields=(field(focused=False),), fingerprint="page.not-focused"),
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            runtime = GovernedSemanticSearchRuntime(
                client,
                action_obligation_ledger=ActionObligationLedger(directory),
            )
            result = self.execute(runtime)
        self.assertEqual("failed", result["status"])
        self.assertEqual(["tap_element"], [name for name, _ in client.calls])
        self.assertEqual(1, result["device_action_count"])
        self.assertEqual(["FAILED"], [step["ledger_state"] for step in result["steps"]])
        self.assertEqual(["failure"], [effect["outcome"] for effect in result["method_health_effect"]])

    def test_executor_rejects_cross_task_transaction_before_dispatch(self) -> None:
        store = SemanticSearchTransactionStore()
        binding = store.begin_explicit(
            "PhoneHarness",
            observation(1),
            task_id="task.search",
            context_id="context.search",
        )
        plan = DynamicPlanner().plan_governed_search_step(binding, "FOCUS", set(TOOLS))
        client = FakeSearchClient([])
        with tempfile.TemporaryDirectory() as directory:
            ledger = ActionObligationLedger(directory)
            result = PlanExecutor(
                client,
                semantic_search_transaction_store=store,
                action_obligation_ledger=ledger,
            ).execute(
                plan,
                action_obligation=ActionObligationRequest(
                    obligation_ref="semanticsearch.cross-task",
                    task_id="task.other",
                    context_id="context.search",
                    capability_id=GovernedSemanticSearchRuntime.CAPABILITY_ID,
                    method_id=GovernedSemanticSearchRuntime.METHOD_IDS["FOCUS"],
                    risk_level="interaction",
                ),
            )
        self.assertEqual("failed", result["status"])
        self.assertEqual([], client.calls)
        self.assertEqual("FAILED", result["action_obligation"]["state"])
        self.assertEqual("semantic_binding_unavailable", result["retry_repair_handoff"]["reason"])

    def test_pre_action_rejections_have_zero_actions_and_no_health_effect(self) -> None:
        cases = (
            ("ambiguous", observation(1, fields=(field(), field(ref="field.second")))),
            ("stale", observation(1, task_id="task.other")),
        )
        for name, first in cases:
            with self.subTest(name=name):
                client = FakeSearchClient([first])
                with tempfile.TemporaryDirectory() as directory:
                    runtime = GovernedSemanticSearchRuntime(
                        client, action_obligation_ledger=ActionObligationLedger(directory)
                    )
                    result = self.execute(runtime)
                self.assertEqual(0, result["device_action_count"])
                self.assertEqual([], client.calls)
                self.assertEqual([], result["method_health_effect"])

    def test_input_success_submit_response_loss_is_unknown_and_not_replayed(self) -> None:
        client = FakeSearchClient(
            [
                observation(1),
                observation(2, fields=(field(focused=True),)),
                observation(3, fields=(field(focused=True, value_matches_expected=True),), fingerprint="page.entered"),
            ],
            fail_tool="press_key",
        )
        with tempfile.TemporaryDirectory() as directory:
            runtime = GovernedSemanticSearchRuntime(client, action_obligation_ledger=ActionObligationLedger(directory))
            result = self.execute(runtime)
            recovered = runtime.continue_task(task_id="task.search", context_id="context.search")
        self.assertEqual("unknown_side_effect", result["status"])
        self.assertEqual("UNKNOWN_SIDE_EFFECT", result["steps"][-1]["ledger_state"])
        self.assertFalse(result["automatic_retry_allowed"])
        self.assertEqual("needs_fresh_observation", recovered["status"])
        self.assertEqual(["tap_element", "input_text", "press_key"], [name for name, _ in client.calls])

    def test_recovery_skips_already_verified_entry_or_submission(self) -> None:
        entry_client = FakeSearchClient(
            [
                observation(1),
                observation(2, fields=(field(focused=True),)),
                observation(3, fields=(field(focused=True, value_matches_expected=True),), fingerprint="page.entered"),
                observation(4, fields=(field(focused=True, value_matches_expected=True),), fingerprint="page.entered"),
            ],
            fail_tool="press_key",
        )
        with tempfile.TemporaryDirectory() as directory:
            runtime = GovernedSemanticSearchRuntime(entry_client, action_obligation_ledger=ActionObligationLedger(directory))
            self.execute(runtime)
            recovery = runtime.continue_task(task_id="task.search", context_id="context.search")
        self.assertNotIn("input_text", recovery.get("actions_to_repeat", []))
        self.assertNotIn("press_key", recovery.get("actions_to_repeat", []))

    def test_permission_default_deny_and_explicit_rejection_are_pre_action(self) -> None:
        for decision in (None, permission(eligible=False)):
            with self.subTest(decision=decision):
                client = FakeSearchClient([observation(1)])
                with tempfile.TemporaryDirectory() as directory:
                    runtime = GovernedSemanticSearchRuntime(
                        client, action_obligation_ledger=ActionObligationLedger(directory)
                    )
                    result = runtime.execute_query(
                        "PhoneHarness",
                        task_id="task.search",
                        context_id="context.search",
                        permission_decision=decision,
                    )
                self.assertEqual("blocked", result["status"])
                self.assertEqual("PERMISSION_DENIED", result["reason_code"])
                self.assertEqual(0, result["device_action_count"])
                self.assertEqual(0, client.tool_discovery_count)
                self.assertEqual([], client.calls)
                self.assertEqual([], result["method_health_effect"])

    def test_risk_rejection_creates_failed_obligation_without_dispatch(self) -> None:
        class RejectingRiskController:
            def assess(self, plan: dict[str, Any], authorization: Any = None, **kwargs: Any) -> dict[str, Any]:
                return {"status": "blocked", "reason": "fixture_risk_denied"}

        client = FakeSearchClient([observation(1)])
        with tempfile.TemporaryDirectory() as directory:
            runtime = GovernedSemanticSearchRuntime(
                client,
                risk_controller=RejectingRiskController(),
                action_obligation_ledger=ActionObligationLedger(directory),
            )
            result = self.execute(runtime)
        self.assertEqual("blocked", result["status"])
        self.assertEqual(0, result["device_action_count"])
        self.assertEqual([], client.calls)
        self.assertEqual([], result["method_health_effect"])
        self.assertEqual("FAILED", result["steps"][0]["ledger_state"])

    def test_expired_and_cross_task_claims_fail_closed(self) -> None:
        store = SemanticSearchTransactionStore(ttl_seconds=2)
        bound = store.begin_explicit(
            "PhoneHarness", observation(1), task_id="task.search", context_id="context.search", now=100
        )
        with self.assertRaisesRegex(SemanticSearchPolicyError, "STALE_CONTEXT"):
            store.claim(
                bound.transaction_id,
                "FOCUS",
                task_id="task.search",
                context_id="context.search",
                now=102,
            )

        fresh = store.begin_explicit(
            "PhoneHarness", observation(2), task_id="task.search", context_id="context.search", now=200
        )
        with self.assertRaisesRegex(SemanticSearchPolicyError, "CROSS_TASK"):
            store.claim(
                fresh.transaction_id,
                "FOCUS",
                task_id="task.other",
                context_id="context.search",
                now=201,
            )

    def test_rich_context_query_uses_same_governed_runtime(self) -> None:
        client = FakeSearchClient(
            [
                observation(1),
                observation(2, fields=(field(focused=True),)),
                observation(3, fields=(field(focused=True, value_matches_expected=True),), fingerprint="page.entered"),
                observation(4, fields=(), fingerprint="page.results", result_state=True),
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            runtime = GovernedSemanticSearchRuntime(client, action_obligation_ledger=ActionObligationLedger(directory))
            result = self.execute(
                runtime,
                query_authority="RICH_CONTEXT",
                context_resolution={"status": "RESOLVED", "trusted": True, "fresh": True, "candidate_count": 1},
            )
        self.assertEqual("passed", result["status"])
        self.assertEqual("SEARCH_SUBMISSION_VERIFIED", result["verification_result"])

    def test_ambiguous_rich_context_and_prompt_injection_never_dispatch(self) -> None:
        cases = (
            (
                "RICH_CONTEXT",
                {"status": "AMBIGUOUS", "trusted": True, "fresh": True, "candidate_count": 2},
                "NEEDS_CLARIFICATION",
            ),
            ("PROMPT_INJECTION", None, "UNTRUSTED_CONTENT"),
            ("WEBPAGE_TEXT", None, "UNTRUSTED_CONTENT"),
        )
        for authority, resolution, expected in cases:
            with self.subTest(authority=authority):
                client = FakeSearchClient([observation(1)])
                with tempfile.TemporaryDirectory() as directory:
                    runtime = GovernedSemanticSearchRuntime(
                        client, action_obligation_ledger=ActionObligationLedger(directory)
                    )
                    result = self.execute(
                        runtime,
                        query_authority=authority,
                        context_resolution=resolution,
                    )
                self.assertEqual("blocked", result["status"])
                self.assertEqual(expected, result["reason_code"])
                self.assertEqual(0, result["device_action_count"])
                self.assertEqual([], client.calls)

    def test_submit_definitive_verification_failure_does_not_reinput(self) -> None:
        client = FakeSearchClient(
            [
                observation(1),
                observation(2, fields=(field(focused=True),)),
                observation(3, fields=(field(focused=True, value_matches_expected=True),), fingerprint="page.entered"),
                observation(4, fields=(field(focused=True, value_matches_expected=True),), fingerprint="page.entered"),
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            runtime = GovernedSemanticSearchRuntime(client, action_obligation_ledger=ActionObligationLedger(directory))
            result = self.execute(runtime)
        self.assertEqual("failed", result["status"])
        self.assertEqual("VERIFIED", result["steps"][1]["ledger_state"])
        self.assertEqual("FAILED", result["steps"][2]["ledger_state"])
        self.assertEqual(3, result["device_action_count"])
        self.assertEqual(1, [name for name, _ in client.calls].count("input_text"))
        self.assertEqual(1, [name for name, _ in client.calls].count("press_key"))

    def test_malformed_surrogate_is_rejected_without_persistence(self) -> None:
        with self.assertRaisesRegex(SemanticSearchPolicyError, "MALFORMED_QUERY"):
            SemanticSearchTransactionStore().begin_explicit(
                "Phone\ud800Harness",
                observation(1),
                task_id="task.search",
                context_id="context.search",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
