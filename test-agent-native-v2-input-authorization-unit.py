#!/usr/bin/env python3
"""Host-only TEST-52 Native V2 disabled authorization security proof."""

from __future__ import annotations

import json
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import phoneharness_agent as p


NONCE = "11111111-1111-4111-8111-111111111111"


def wire_response(**changes) -> dict:
    value = {
        "schema": "ph.controlled_fixture.native_evidence.response.v2",
        "scope": "CONTROLLED_FIXTURE_ONLY",
        "provider": "NATIVE_UIKIT_SINGLE_PROVIDER",
        "status": "DIAGNOSTIC_ONLY",
        "failure_code": "NONE",
        "request_nonce": NONCE,
        "bundle": "com.charles.phoneharness.test52.c1",
        "peer_pid": 77,
        "peer_version": 3,
        "runtime_cdhash_status": "PASS",
        "runtime_cdhash_provenance": "DIRECT_KERNEL_AUDIT_TOKEN_CDHASH",
        "process_instance_status": "PASS",
        "lifecycle_epoch_status": "PASS",
        "target_slot": "disabled",
        "slot_bound": True,
        "expected_class": "UITextField",
        "expected_class_match": True,
        "native_object_present": True,
        "native_same_target": True,
        "object_generation_consistency": True,
        "evidence_generation_consistency": True,
        "enabled_state": "FALSE",
        "enabled_presence": "PRESENT_FALSE",
        "enabled_provenance": "DIRECT_NATIVE_GETTER",
        "enabled_getter": "TYPED_UITEXTFIELD_ISENABLED",
        "editable_state": "NOT_APPLICABLE",
        "secure_state": "FALSE",
        "secure_presence": "PRESENT_FALSE",
        "focused_state": "FALSE",
        "focused_presence": "PRESENT_FALSE",
        "can_become_first_responder_state": "FALSE",
        "can_become_first_responder_presence": "PRESENT_FALSE",
        "user_interaction_enabled_state": "TRUE",
        "user_interaction_enabled_presence": "PRESENT_TRUE",
        "fixture_text_mutation_state": "TRUE",
        "fixture_text_mutation_provenance": "DIRECT_FIXTURE_CONTRACT",
        "presentation": "PRESENTED_IN_CONTROLLED_FIXTURE",
        "capsule_side_effect_count": 0,
        "authorization_capsule_issued": False,
        "risk_authorization_receipt_count": 0,
        "input_grant_count": 0,
        "executor_dispatch_count": 0,
        "external_input_dispatch_count": 0,
        "text_event_count": 0,
        "test_setup_action_count_delta": 0,
        "device_action_count_delta": 0,
        "device_action_count": 0,
    }
    value.update(changes)
    return value


def validated(response: dict | None = None, **binding_changes) -> p.ValidatedNativeV2AuthorizationEvidence:
    arguments = {
        "request_nonce_match": True,
        "c1_initial_auth_pass": True,
        "c1_post_auth_pass": True,
        "received_at": 100,
        "now": 100,
    }
    arguments.update(binding_changes)
    return p.ValidatedNativeV2AuthorizationEvidence.from_authenticated_transaction(
        response or wire_response(), **arguments,
    )


def evaluate(response: dict | None = None) -> p.InputAuthorizationEvaluation:
    return p.RiskController().evaluate_native_v2_input_authorization(validated(response))


def ax_field(**changes) -> p.SemanticSearchFieldEvidence:
    field = p.SemanticSearchFieldEvidence(
        field_ref="field.host", source="AX", role="text_field", role_source="xc_attribute",
        editable=True, editable_source="xc_attribute", secure=False, secure_source="xc_attribute",
        enabled=True, enabled_source="xc_attribute", visible=True, visible_source="xc_attribute",
        actionable=True, actionable_source="xc_attribute", focused=True, focused_source="xc_attribute",
        same_leaf_identity=True, selector_text="Host fixture selector",
        same_leaf_source="direct_snapshot", snapshot_ref="synthetic.generation",
    )
    return replace(field, **changes)


def legacy_eligible(field: p.SemanticSearchFieldEvidence) -> bool:
    return (
        field.source == "AX" and field.has_same_leaf_identity()
        and field.role in {"search_field", "editable_text_field", "text_field"}
        and field.role_source in field.ROLE_SOURCES and field.editable is True
        and field.editable_source in field.DIRECT_SOURCES and field.secure is False
        and field.secure_source in field.DIRECT_SOURCES and field.enabled is True
        and field.enabled_source in field.DIRECT_SOURCES and field.visible is True
        and field.visible_source in field.DIRECT_SOURCES and field.actionable is True
        and field.actionable_source in field.DIRECT_SOURCES and bool(field.selector_text.strip())
    )


class NativeV2InputAuthorizationTests(unittest.TestCase):
    def test_01_disabled_direct_false_denies_with_enabled_false(self):
        result = evaluate()
        self.assertEqual("DENY", result.decision)
        self.assertIn("ENABLED_FALSE", result.failed_predicates)

    def test_02_false_presence_is_exact(self):
        value = validated()
        self.assertEqual("FALSE", value._facts["enabled_state"])

    def test_03_unavailable_is_not_collapsed_to_false(self):
        with self.assertRaises(p.NativeV2InputEvidenceAdapterError):
            validated(wire_response(enabled_state="UNAVAILABLE", enabled_presence="UNAVAILABLE",
                                    enabled_provenance="UNAVAILABLE", enabled_getter="UNAVAILABLE"))

    def test_04_invalid_enabled_provenance_is_rejected(self):
        with self.assertRaises(p.NativeV2InputEvidenceAdapterError):
            validated(wire_response(enabled_provenance="INFERRED_FROM_SLOT"))

    def test_05_slot_name_cannot_infer_missing_enabled(self):
        response = wire_response(); del response["enabled_state"]
        with self.assertRaises(p.NativeV2InputEvidenceAdapterError):
            validated(response)

    def test_06_wrong_class_rejected(self):
        with self.assertRaises(p.NativeV2InputEvidenceAdapterError):
            validated(wire_response(expected_class="UITextView"))

    def test_07_same_target_false_rejected(self):
        with self.assertRaises(p.NativeV2InputEvidenceAdapterError):
            validated(wire_response(native_same_target=False))

    def test_08_object_generation_mismatch_rejected(self):
        with self.assertRaises(p.NativeV2InputEvidenceAdapterError):
            validated(wire_response(object_generation_consistency=False))

    def test_09_evidence_generation_mismatch_rejected(self):
        with self.assertRaises(p.NativeV2InputEvidenceAdapterError):
            validated(wire_response(evidence_generation_consistency=False))

    def test_10_runtime_identity_invalid_rejected(self):
        with self.assertRaises(p.NativeV2InputEvidenceAdapterError):
            validated(wire_response(runtime_cdhash_status="FAIL_CLOSED"))

    def test_11_stale_lifecycle_or_request_rejected(self):
        with self.assertRaises(p.NativeV2InputEvidenceAdapterError):
            validated(wire_response(lifecycle_epoch_status="FAIL_CLOSED"))
        with self.assertRaises(p.NativeV2InputEvidenceAdapterError):
            validated(received_at=1, now=100)
        with self.assertRaises(p.NativeV2InputEvidenceAdapterError):
            validated(request_nonce_match=False)

    def test_12_c1_binding_is_required(self):
        with self.assertRaises(p.NativeV2InputEvidenceAdapterError):
            validated(c1_initial_auth_pass=False)
        with self.assertRaises(p.NativeV2InputEvidenceAdapterError):
            validated(c1_post_auth_pass=False)

    def test_13_wrong_provider_rejected(self):
        with self.assertRaises(p.NativeV2InputEvidenceAdapterError):
            validated(wire_response(provider="OTHER"))

    def test_14_wrong_scope_rejected(self):
        with self.assertRaises(p.NativeV2InputEvidenceAdapterError):
            validated(wire_response(scope="PRODUCTION"))

    def test_15_raw_host_forgery_cannot_qualify(self):
        with self.assertRaises(p.NativeV2InputEvidenceAdapterError):
            p.NativeV2InputAuthorizationEvidenceAdapter.adapt({"enabled_state": "FALSE"})
        with self.assertRaises(p.NativeV2InputEvidenceAdapterError):
            p.ValidatedNativeV2AuthorizationEvidence(object(), {}, fresh_request_binding=True)

    def test_16_exact_response_shape_rejects_extra_and_missing(self):
        extra = wire_response(pointer="0x1")
        with self.assertRaises(p.NativeV2InputEvidenceAdapterError):
            validated(extra)
        missing = wire_response(); del missing["enabled_getter"]
        with self.assertRaises(p.NativeV2InputEvidenceAdapterError):
            validated(missing)

    def test_17_canonical_enabled_false_result(self):
        result = evaluate()
        self.assertIn("ENABLED_FALSE", result.failed_predicates)
        self.assertNotIn("ENABLED_PROVENANCE_INVALID", result.failed_predicates)

    def test_18_trusted_enabled_true_differential_omits_enabled_false(self):
        normalized = p.NativeV2InputAuthorizationEvidenceAdapter.adapt(validated())
        positive = replace(normalized, enabled_state="TRUE")
        result = p.InputAuthorizationPredicateEvaluator.evaluate(positive)
        self.assertNotIn("ENABLED_FALSE", result.failed_predicates)
        self.assertNotIn("ENABLED_PROVENANCE_INVALID", result.failed_predicates)

    def test_19_controlled_v2_is_never_grantable(self):
        result = evaluate()
        self.assertFalse(result.grantable)
        self.assertIn("PROVIDER_SCOPE_NOT_GRANTABLE", result.failed_predicates)

    def test_20_no_receipt_or_input_grant(self):
        risk = p.RiskController(); before = dict(risk._input_grants)
        with patch.object(p, "RiskAuthorization", side_effect=AssertionError("receipt reached")):
            risk.evaluate_native_v2_input_authorization(validated())
        self.assertEqual(before, risk._input_grants)

    def test_21_no_executor_capsule_or_external_dispatch(self):
        with (
            patch.object(p.PlanExecutor, "__init__", side_effect=AssertionError("executor reached")),
            patch.object(p.MCPClient, "call_tool", side_effect=AssertionError("MCP dispatch reached")),
            patch.object(p._ExecutorMCPPort, "call_tool", side_effect=AssertionError("executor MCP reached")),
        ):
            result = p.RiskController().evaluate_native_v2_input_authorization(validated())
        self.assertEqual("DENY", result.decision)

    def test_22_fixture_mutation_contract_does_not_override_enabled_false(self):
        result = evaluate(wire_response(fixture_text_mutation_state="TRUE"))
        self.assertIn("ENABLED_FALSE", result.failed_predicates)

    def test_23_ax_authorization_behavior_has_zero_drift(self):
        variants = (
            {}, {"enabled": False}, {"enabled": None}, {"enabled_source": "inferred"},
            {"editable": False}, {"secure": True}, {"visible": False},
            {"actionable": False}, {"focused": False}, {"same_leaf_identity": False},
        )
        for changes in variants:
            with self.subTest(changes=changes):
                field = ax_field(**changes)
                self.assertEqual(legacy_eligible(field), field.eligible())

    def test_24_privacy_safe_evaluation_summary(self):
        summary = evaluate().safe_summary()
        self.assertEqual({"decision", "failed_predicates", "provider", "scope", "grantable"}, set(summary))
        wire = json.dumps(summary).lower()
        for forbidden in ("request_nonce", "coordinate", "selector", "label", "pointer", "address", "value"):
            self.assertNotIn(forbidden, wire)

    def test_25_no_production_grant_even_with_synthetic_enabled_true(self):
        normalized = replace(p.NativeV2InputAuthorizationEvidenceAdapter.adapt(validated()), enabled_state="TRUE")
        result = p.InputAuthorizationPredicateEvaluator.evaluate(normalized)
        self.assertEqual("DENY", result.decision)
        self.assertIn("PROVIDER_SCOPE_NOT_GRANTABLE", result.failed_predicates)

    def test_26_host_route_is_disabled_only(self):
        source = Path(p.__file__).read_text()
        start = source.index("class ValidatedNativeV2AuthorizationEvidence")
        end = source.index("@dataclass(frozen=True)\nclass SemanticSearchFieldEvidence", start)
        block = source[start:end]
        self.assertIn('"target_slot": "disabled"', block)
        self.assertNotIn('"target_slot": "A"', block)


if __name__ == "__main__":
    unittest.main(verbosity=2)
