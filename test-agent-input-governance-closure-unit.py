#!/usr/bin/env python3
"""Host-only closure gates; synthetic provider evidence and temporary stores."""

import importlib.util
import json
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import phoneharness_agent as p

spec = importlib.util.spec_from_file_location(
    "input_governance_fixture", Path(__file__).with_name("test-agent-input-orchestrator-governance-unit.py")
)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class EvidenceClient(fixture.FakeMCPClient):
    def __init__(self):
        super().__init__()
        self.value = ""
        self.version = 0
        self.leaf = "field.primary"
        self.page = "page.current"
        self.direct = True
        self.focused = True
        self.value_source = "xc_attribute"
        self.deliver = True
        self.after_dispatch = None
        self.frozen_version = False
        self.field_overrides = {}

    def _rpc(self, method, params):
        result = super()._rpc(method, params)
        if self.deliver and params["name"] == "exp_keycode_tap":
            usage = params["arguments"]["usage"]
            self.value += chr(ord("a") + usage - 4)
        if self.after_dispatch:
            self.after_dispatch()
        return result

    def observe_semantic_search_page(self, *, task_id, context_id, expected_query=None):
        if not self.frozen_version:
            self.version += 1
        field = p.SemanticSearchFieldEvidence(
            self.leaf, "AX", "text_field", "xc_attribute",
            True if self.direct else None, "xc_attribute" if self.direct else "unavailable",
            False, "xc_attribute", True, "xc_attribute", True, "xc_attribute",
            True, "xc_attribute", self.focused, "xc_attribute", True, "Field",
            self.value == expected_query, self.value_source,
            same_leaf_source="direct_snapshot", snapshot_ref=f"synthetic.{self.version}",
        )
        field = replace(field, **self.field_overrides)
        return p.SemanticSearchPageObservation(
            "AX", int(time.time()), self.version, self.page, task_id, context_id, (field,),
            freshness_source="direct_snapshot", device_generation=f"synthetic.{self.version}",
            device_generation_source="direct_snapshot",
        )


class ClosureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.engine = p.ActiveContextEngine(Path(self.tmp.name) / "context")
        self.owner = "synthetic-context-owner"
        record = self.engine.create(
            self.owner, task_ref="task.input.governed", workspace_ref="workspace.test",
            goal_ref="goal.test", intent_category="text_entry", domain_code="test",
        )
        self.context_id = record["context_id"]
        self.engine.activate(self.context_id, self.owner)
        self.risk = p.RiskController()
        self.client = EvidenceClient()
        self.ledger = p.ActionObligationLedger(Path(self.tmp.name) / "ledger")
        self.store = p.InputTextActionBindingStore()
        self.runtime = p.GovernedInputTextRuntime(
            self.client, capability_method_registry=fixture.registry(),
            action_obligation_ledger=self.ledger, risk_controller=self.risk, binding_store=self.store,
        )

    def issue(self, text="abc", **kwargs):
        return self.risk.authorize_input_target(
            text, client=self.client, context_engine=self.engine,
            context_id=self.context_id, owner_token=self.owner, keyboard="apple_qwerty", **kwargs,
        )

    def assert_blocked(self, target, text="abc", **kwargs):
        result = self.runtime.execute(text, target=target, **kwargs)
        self.assertEqual("blocked", result["status"])
        self.assertFalse(result["dispatched"])
        self.assertEqual(0, result["device_action_count"])
        self.assertEqual(0, self.runtime.plan_executor_invocation_count)
        self.assertEqual([], self.client.calls)

    def test_forged_authorization(self):
        self.assert_blocked(fixture.target())

    def test_copied_receipt_is_not_an_issued_handle(self):
        self.assert_blocked(replace(self.issue()))

    def test_unknown_authorization_ref(self):
        self.assert_blocked(replace(self.issue(), authorization_ref="unknown"))

    def test_stale_context_version(self):
        target = self.issue()
        self.engine.pause(self.context_id, self.owner)
        self.engine.resume(self.context_id, self.owner)
        self.assert_blocked(target)

    def test_target_authorization_mismatch(self):
        self.assert_blocked(replace(self.issue(), field_ref="field.other"))

    def test_changed_query_does_not_inherit_authorization(self):
        self.assert_blocked(self.issue(), text="def")

    def test_other_risk_instance_cannot_use_receipt(self):
        target = self.issue()
        self.runtime._risk = p.RiskController()
        self.assert_blocked(target)

    def test_test52_evidence_missing_at_issue(self):
        self.client.direct = False
        with self.assertRaises(p.InputTextActionBindingError):
            self.issue()
        self.assertEqual(0, self.runtime.plan_executor_invocation_count)

    def test_test52_evidence_missing_before_execution(self):
        target = self.issue()
        self.client.direct = False
        self.assert_blocked(target)

    def test_page_changed_before_execution(self):
        target = self.issue()
        self.client.page = "page.other"
        self.assert_blocked(target)

    def test_leaf_changed_before_execution(self):
        target = self.issue()
        self.client.leaf = "field.other"
        self.assert_blocked(target)

    def test_method_cannot_substitute_page_text_verifier(self):
        target = self.issue()
        original = self.runtime._methods.get
        with patch.object(self.runtime._methods, "get", side_effect=lambda method_id: {
            **original(method_id), "verifier": "visible_text_contains",
        }):
            self.assert_blocked(target)

    def test_missing_leaf_identity_rejects_receipt(self):
        self.client.leaf = ""
        with self.assertRaises(p.InputTextActionBindingError):
            self.issue()
        self.assertEqual([], self.client.calls)

    def test_malformed_observation_time_fails_closed(self):
        original = self.client.observe_semantic_search_page
        with patch.object(self.client, "observe_semantic_search_page", side_effect=lambda **kwargs: replace(
            original(**kwargs), observed_at="invalid",
        )):
            with self.assertRaises(p.InputTextActionBindingError):
                self.issue()
        self.assertEqual([], self.client.calls)

    def test_unrelated_page_text_cannot_verify_input(self):
        self.client.deliver = False
        self.client.delivered_text = "unrelated abc"
        result = self.runtime.execute("abc", target=self.issue())
        self.assertTrue(result["dispatched"])
        self.assertNotEqual("completed", result["status"])
        self.assertNotIn("VERIFIED", [a["ledger_state"] for a in result["attempts"]])
        self.assertEqual(1, len(self.client.calls))

    def test_nonempty_page_cannot_verify_intermediate_action(self):
        self.client.deliver = False
        result = self.runtime.execute("abc", target=self.issue())
        self.assertEqual(1, len(self.client.calls))
        self.assertNotEqual("VERIFIED", result["attempts"][0]["ledger_state"])

    def test_placeholder_match_cannot_verify(self):
        self.client.after_dispatch = lambda: setattr(self.client, "value_source", "placeholder")
        result = self.runtime.execute("abc", target=self.issue())
        self.assertNotEqual("VERIFIED", result["attempts"][0]["ledger_state"])

    def test_other_leaf_match_cannot_verify(self):
        self.client.after_dispatch = lambda: setattr(self.client, "leaf", "field.other")
        result = self.runtime.execute("abc", target=self.issue())
        self.assertNotEqual("VERIFIED", result["attempts"][0]["ledger_state"])

    def test_stale_snapshot_cannot_verify(self):
        self.client.after_dispatch = lambda: setattr(self.client, "frozen_version", True)
        result = self.runtime.execute("abc", target=self.issue())
        self.assertNotEqual("VERIFIED", result["attempts"][0]["ledger_state"])

    def test_risk_denied_at_executor_does_not_count_dispatch(self):
        original = self.risk.assess
        def deny(plan, authorization=None, *, consume_authorization=False, now=None):
            if consume_authorization:
                return {"status": "blocked", "reason": "revoked"}
            return original(plan, authorization, consume_authorization=False, now=now)
        self.risk.assess = deny
        result = self.runtime.execute("abc", target=self.issue())
        self.assertFalse(result["dispatched"])
        self.assertEqual(0, result["device_action_count"])
        self.assertEqual([], self.client.calls)

    def test_valid_same_leaf_prefixes_use_existing_ledger(self):
        result = self.runtime.execute("abc", target=self.issue())
        self.assertEqual("completed", result["status"])
        self.assertEqual(3, len(self.client.calls))
        self.assertEqual(3, result["device_action_count"])
        self.assertTrue(all(a["ledger_state"] == "VERIFIED" for a in result["attempts"]))

    def test_sensitive_cannot_be_downgraded(self):
        self.assert_blocked(self.issue(sensitive=True), sensitive=False)

    def test_finished_authorization_cannot_replay(self):
        target = self.issue()
        self.runtime.execute("abc", target=target)
        result = self.runtime.execute("abc", target=target)
        self.assertEqual("blocked", result["status"])
        self.assertEqual(3, len(self.client.calls))

    def test_payloads_discarded_and_ledger_redacted(self):
        text = "syntheticcanary"
        result = self.runtime.execute(text, target=self.issue(text, sensitive=True), sensitive=True)
        self.assertNotIn(text, json.dumps(result))
        self.assertEqual({}, self.store._bindings)
        for path in (Path(self.tmp.name) / "ledger").rglob("*.json"):
            self.assertNotIn(text, path.read_text())

    def test_expired_authorization(self):
        target = self.issue()
        with patch.object(p.time, "time", return_value=time.time() + 61):
            self.assert_blocked(target)

    def test_forged_context_version_in_handle(self):
        target = self.issue()
        self.assert_blocked(replace(target, context_version=target.context_version + 1))

    def test_wrong_context_owner_cannot_issue(self):
        self.owner = "wrong-synthetic-owner"
        with self.assertRaises(p.InputTextActionBindingError):
            self.issue()
        self.assertEqual([], self.client.calls)

    def test_nonempty_field_is_not_cleared_or_appended(self):
        self.client.value = "existing"
        with self.assertRaises(p.InputTextActionBindingError):
            self.issue()
        self.assertEqual([], self.client.calls)

    def test_inferred_missing_or_cross_leaf_state_cannot_authorize(self):
        for overrides in (
            {"editable_source": "inferred"}, {"secure": None}, {"secure": True},
            {"visible_source": "inferred"}, {"same_leaf_identity": False},
            {"focused": False}, {"focused_source": "inferred"}, {"enabled": False},
            {"source": "OCR"}, {"value_match_source": "placeholder"},
        ):
            with self.subTest(overrides=overrides):
                self.client.field_overrides = overrides
                with self.assertRaises(p.InputTextActionBindingError):
                    self.issue()
                self.assertEqual([], self.client.calls)

    def test_candidate_methods_cannot_execute_even_with_issued_authorization(self):
        self.runtime._methods = p.CapabilityMethodRegistry(
            p.CapabilityCatalog((p.INPUT_TEXT_CAPABILITY_DEFINITION,)), p.INPUT_TEXT_METHOD_DEFINITIONS,
        )
        self.assert_blocked(self.issue())
        self.assertTrue(all(item.lifecycle == "CANDIDATE" for item in p.INPUT_TEXT_METHOD_DEFINITIONS))

    def test_unknown_action_parameters_are_rejected(self):
        target = self.issue()
        self.risk.begin_input_target(target, "abc", False, self.client, self.store)
        for args in ({"page": 7, "usage": 4, "text": "extra"}, {"page": 7, "usage": True},
                     {"page": 7, "usage": 5}, {"page": 7}):
            with self.subTest(args=args), self.assertRaises(p.InputTextActionBindingError):
                self.store.create(target=target, tool="exp_keycode_tap", step_id="step.input",
                                  arguments=args, expected_text="abc", expected_before="", expected_after="a",
                                  require_delivery=True)
        self.assertEqual([], self.client.calls)

    def test_binding_requires_matching_risk_receipt_and_verifier_contract(self):
        target = self.issue()
        self.risk.begin_input_target(target, "abc", False, self.client, self.store)
        binding_id = self.store.create(
            target=target, tool="exp_keycode_tap", step_id="step.input", arguments={"page": 7, "usage": 4},
            expected_text="abc", expected_before="", expected_after="a", require_delivery=True,
        )
        plan = self.runtime._plan_for("exp_keycode_tap", "step.input", binding_id, target.task_id, target.context_id)
        plan["verification"]["input_authorization_ref"] = target.authorization_ref
        receipt = self.risk._input_grant(target)["receipt"]
        self.assertEqual("blocked", self.risk.assess(plan)["status"])
        self.assertEqual("blocked", self.risk.assess(plan, replace(receipt))["status"])
        plan["verification"]["kind"] = "observation_nonempty"
        self.assertEqual("blocked", self.risk.assess(plan, receipt)["status"])
        self.assertEqual([], self.client.calls)

    def test_lost_dispatch_response_counts_attempt_without_verification(self):
        def lose_response():
            raise p.MCPCallError("synthetic response loss")
        self.client.after_dispatch = lose_response
        result = self.runtime.execute("abc", target=self.issue())
        self.assertTrue(result["dispatched"])
        self.assertEqual(1, result["device_action_count"])
        self.assertEqual("UNKNOWN_SIDE_EFFECT", result["attempts"][0]["ledger_state"])
        self.assertEqual(1, len(self.client.calls))

    def test_changed_context_between_characters_stops_remaining_actions(self):
        self.client.after_dispatch = lambda: self.engine.pause(self.context_id, self.owner)
        result = self.runtime.execute("abc", target=self.issue())
        self.assertEqual(1, len(self.client.calls))
        self.assertNotEqual("VERIFIED", result["attempts"][0]["ledger_state"])
        self.assertEqual({}, self.store._bindings)


if __name__ == "__main__":
    unittest.main()
