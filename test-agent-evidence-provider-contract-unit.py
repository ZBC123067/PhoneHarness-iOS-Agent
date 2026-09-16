#!/usr/bin/env python3
"""Host-only P0 governed evidence-provider contract and AX shadow tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, replace
import inspect
import json
import unittest
from unittest.mock import patch

import phoneharness_agent as p


def ax_field(**changes) -> p.SemanticSearchFieldEvidence:
    value = p.SemanticSearchFieldEvidence(
        field_ref="field.synthetic",
        source="AX",
        role="text_field",
        role_source="ax_attribute",
        editable=True,
        editable_source="ax_attribute",
        secure=False,
        secure_source="ax_attribute",
        enabled=True,
        enabled_source="ax_attribute",
        visible=True,
        visible_source="ax_attribute",
        actionable=True,
        actionable_source="ax_attribute",
        focused=True,
        focused_source="ax_attribute",
        same_leaf_identity=True,
        selector_text="Field",
        value_matches_expected=True,
        value_match_source="ax_attribute",
        same_leaf_source="direct_snapshot",
        snapshot_ref="snapshot.1",
    )
    return replace(value, **changes)


def ax_page(field: p.SemanticSearchFieldEvidence | None = None, **changes) -> p.SemanticSearchPageObservation:
    value = p.SemanticSearchPageObservation(
        source="AX",
        observed_at=100,
        observation_version=3,
        page_fingerprint="page.synthetic",
        task_id="task.synthetic",
        context_id="context.synthetic",
        fields=(field or ax_field(),),
        freshness_source="direct_snapshot",
        device_generation="snapshot.1",
        device_generation_source="direct_snapshot",
    )
    return replace(value, **changes)


def capture_request(**changes) -> p.EvidenceCaptureRequest:
    value = p.EvidenceCaptureRequest(
        requirement_id="requirement.input",
        task_id="task.synthetic",
        plan_id="plan.synthetic",
        planning_revision=2,
        step_id="step.input",
        capability_id="INPUT_TEXT",
        action_class="INPUT_TEXT",
        target_ref="field.synthetic",
        context_id="context.synthetic",
        context_version=7,
        observation_generation="snapshot.1",
        requested_at=100,
        max_age_seconds=30,
        required_semantics=frozenset({
            p.EvidenceSemantic.ROLE_ALLOWED,
            p.EvidenceSemantic.EDITABLE,
            p.EvidenceSemantic.SECURE,
            p.EvidenceSemantic.ENABLED,
            p.EvidenceSemantic.PRESENTATION,
            p.EvidenceSemantic.ACTIONABLE,
            p.EvidenceSemantic.FOCUS,
            p.EvidenceSemantic.SAME_LEAF_IDENTITY,
            p.EvidenceSemantic.SNAPSHOT_FRESHNESS,
        }),
    )
    return replace(value, **changes)


def requirement(*, claims=None, **changes) -> p.EvidenceRequirement:
    selected = claims or (
        p.EvidenceClaimRequirement(
            p.EvidenceSemantic.EDITABLE,
            p.EvidenceState.TRUE,
            frozenset({"ax_attribute", "xc_attribute"}),
        ),
        p.EvidenceClaimRequirement(
            p.EvidenceSemantic.SECURE,
            p.EvidenceState.FALSE,
            frozenset({"ax_attribute", "xc_attribute"}),
        ),
    )
    value = p.EvidenceRequirement(
        requirement_id="requirement.input",
        capability_id="INPUT_TEXT",
        action_class="INPUT_TEXT",
        claims=selected,
        identity_requirement=p.EvidenceIdentityRequirement.SAME_PROVIDER_LEAF,
        maximum_age_seconds=30,
        evaluation_time=100,
        required_task_id="task.synthetic",
        required_context_id="context.synthetic",
        required_observation_generation="snapshot.1",
        permitted_provider_ids=frozenset({"phoneharness.ax.same_leaf.v1"}),
        permitted_provider_kinds=frozenset({p.EvidenceProviderKind.STRUCTURAL_AX}),
        combination_policy=p.EvidenceCombinationPolicy.SINGLE_PROVIDER_ONLY,
        privacy_class=p.EvidencePrivacyClass.SAFE_TYPED_METADATA,
        confirmation_requirement=p.EvidenceConfirmationRequirement.NOT_REQUIRED,
        verifier_contract="input_text_action_observed",
    )
    return replace(value, **changes)


def provider(field=None, **page_changes) -> p.AXL2GovernedEvidenceProvider:
    return p.AXL2GovernedEvidenceProvider(ax_page(field, **page_changes))


class EvidenceProviderContractTests(unittest.TestCase):
    def test_01_exact_four_non_numeric_grades(self):
        self.assertEqual(
            {"L4_STRUCTURED", "L3_NATIVE_EXACT", "L2_STRUCTURAL_AX", "L1_VISION_SEMANTIC"},
            {grade.name for grade in p.EvidenceGrade},
        )

    def test_02_grade_is_not_a_total_authorization_order(self):
        with self.assertRaises(TypeError):
            _ = p.EvidenceGrade.L4_STRUCTURED >= p.EvidenceGrade.L3_NATIVE_EXACT

    def test_03_requirement_is_immutable(self):
        value = requirement()
        with self.assertRaises(FrozenInstanceError):
            value.maximum_age_seconds = 999

    def test_04_descriptor_is_deeply_immutable(self):
        value = provider().descriptor
        with self.assertRaises(FrozenInstanceError):
            value.authorization_grantable = False
        self.assertIsInstance(value.supported_semantics, frozenset)

    def test_05_capture_and_result_are_immutable(self):
        request = capture_request()
        result = provider().capture(request)
        with self.assertRaises(FrozenInstanceError):
            request.context_version = 1
        with self.assertRaises(FrozenInstanceError):
            result.capture_status = p.EvidenceCaptureStatus.INVALID

    def test_06_provider_exposes_only_evidence_contract(self):
        value = provider()
        self.assertIsInstance(value, p.GovernedEvidenceProvider)
        self.assertTrue(callable(value.capture))
        self.assertTrue(callable(value.validate))

    def test_07_provider_has_no_authorization_api(self):
        for name in ("authorize", "grant", "issue_receipt", "risk_override"):
            self.assertFalse(hasattr(p.GovernedEvidenceProvider, name))
            self.assertFalse(hasattr(provider(), name))

    def test_08_provider_has_no_execution_api(self):
        for name in ("execute", "dispatch", "replan"):
            self.assertFalse(hasattr(p.GovernedEvidenceProvider, name))
            self.assertFalse(hasattr(provider(), name))

    def test_09_provider_has_no_semantic_success_api(self):
        for name in ("verify", "verify_success", "mark_verified"):
            self.assertFalse(hasattr(p.GovernedEvidenceProvider, name))
            self.assertFalse(hasattr(provider(), name))

    def test_10_non_grantable_is_independent_of_high_grade(self):
        descriptor = p.GovernedEvidenceProviderDescriptor(
            provider_id="controlled.native.synthetic",
            provider_kind=p.EvidenceProviderKind.NATIVE_EXACT,
            grade=p.EvidenceGrade.L3_NATIVE_EXACT,
            supported_semantics=frozenset({p.EvidenceSemantic.EDITABLE}),
            scope=p.EvidenceProviderScope.CONTROLLED_FIXTURE_ONLY,
            identity_guarantees=frozenset({p.EvidenceIdentityRequirement.EXACT_TARGET}),
            provenance_guarantees=frozenset({"DIRECT_NATIVE_GETTER"}),
            freshness_capabilities=frozenset({"REQUEST_BOUND_GENERATION"}),
            privacy_class=p.EvidencePrivacyClass.SAFE_TYPED_METADATA,
            authorization_grantable=False,
        )
        self.assertEqual(p.EvidenceGrade.L3_NATIVE_EXACT, descriptor.grade)
        self.assertFalse(descriptor.authorization_grantable)

    def test_11_planner_and_capture_request_have_no_provider_override(self):
        self.assertNotIn("provider_id", {item.name for item in fields(p.DynamicPlanStep)})
        self.assertNotIn("provider_id", {item.name for item in fields(p.EvidenceCaptureRequest)})
        self.assertNotIn("authorization_override", {item.name for item in fields(p.EvidenceCaptureRequest)})

    def test_12_ax_descriptor_semantic_coverage_is_exact(self):
        self.assertEqual(
            {
                p.EvidenceSemantic.ROLE_ALLOWED, p.EvidenceSemantic.EDITABLE,
                p.EvidenceSemantic.SECURE, p.EvidenceSemantic.ENABLED,
                p.EvidenceSemantic.PRESENTATION, p.EvidenceSemantic.ACTIONABLE,
                p.EvidenceSemantic.FOCUS, p.EvidenceSemantic.SAME_LEAF_IDENTITY,
                p.EvidenceSemantic.SNAPSHOT_FRESHNESS,
                p.EvidenceSemantic.EXPECTED_VALUE_MATCH,
            },
            set(provider().descriptor.supported_semantics),
        )
        self.assertNotIn("TARGET_HIDDEN", {item.name for item in provider().descriptor.supported_semantics})

    def assert_fact(self, result, semantic, state, provenance, direct):
        matches = [fact for fact in result.facts if fact.semantic is semantic]
        self.assertEqual(1, len(matches))
        self.assertEqual((state, provenance, direct), (matches[0].state, matches[0].provenance, matches[0].direct))

    def test_13_ax_adapter_preserves_editable(self):
        result = provider().capture(capture_request())
        self.assert_fact(result, p.EvidenceSemantic.EDITABLE, p.EvidenceState.TRUE, "ax_attribute", True)

    def test_14_ax_adapter_preserves_secure(self):
        result = provider().capture(capture_request())
        self.assert_fact(result, p.EvidenceSemantic.SECURE, p.EvidenceState.FALSE, "ax_attribute", True)

    def test_15_ax_adapter_preserves_enabled(self):
        result = provider().capture(capture_request())
        self.assert_fact(result, p.EvidenceSemantic.ENABLED, p.EvidenceState.TRUE, "ax_attribute", True)

    def test_16_ax_adapter_preserves_presentation(self):
        result = provider().capture(capture_request())
        self.assert_fact(result, p.EvidenceSemantic.PRESENTATION, p.EvidenceState.TRUE, "ax_attribute", True)

    def test_17_ax_adapter_preserves_actionable(self):
        result = provider().capture(capture_request())
        self.assert_fact(result, p.EvidenceSemantic.ACTIONABLE, p.EvidenceState.TRUE, "ax_attribute", True)

    def test_18_ax_adapter_preserves_focus(self):
        result = provider().capture(capture_request())
        self.assert_fact(result, p.EvidenceSemantic.FOCUS, p.EvidenceState.TRUE, "ax_attribute", True)

    def test_19_ax_adapter_preserves_same_leaf_identity(self):
        result = provider().capture(capture_request())
        self.assert_fact(result, p.EvidenceSemantic.SAME_LEAF_IDENTITY, p.EvidenceState.TRUE, "direct_snapshot", True)

    def test_20_ax_adapter_preserves_freshness(self):
        result = provider().capture(capture_request())
        self.assert_fact(result, p.EvidenceSemantic.SNAPSHOT_FRESHNESS, p.EvidenceState.TRUE, "direct_snapshot", True)

    def test_21_stale_ax_evidence_does_not_validate(self):
        result = provider().capture(capture_request(requested_at=200))
        checked = provider().validate(result, requirement(evaluation_time=200))
        self.assertEqual(p.EvidenceValidationStatus.INVALID, checked.status)
        self.assertIn("EVIDENCE_STALE", checked.failure_codes)

    def test_22_cross_leaf_evidence_does_not_validate(self):
        field = ax_field(same_leaf_identity=False, same_leaf_source="unavailable", snapshot_ref=None)
        value = provider(field)
        checked = value.validate(value.capture(capture_request()), requirement())
        self.assertEqual(p.EvidenceValidationStatus.INVALID, checked.status)
        self.assertIn("IDENTITY_REQUIREMENT_UNSATISFIED", checked.failure_codes)

    def test_23_missing_editable_is_not_inferred(self):
        result = provider(ax_field(editable=None, editable_source="unavailable")).capture(capture_request())
        self.assert_fact(result, p.EvidenceSemantic.EDITABLE, p.EvidenceState.UNAVAILABLE, "unavailable", False)

    def test_24_missing_secure_is_not_inferred_false(self):
        result = provider(ax_field(secure=None, secure_source="unavailable")).capture(capture_request())
        self.assert_fact(result, p.EvidenceSemantic.SECURE, p.EvidenceState.UNAVAILABLE, "unavailable", False)

    def test_25_geometry_does_not_synthesize_presentation(self):
        result = provider(ax_field(visible=None, visible_source="unavailable")).capture(capture_request())
        self.assert_fact(result, p.EvidenceSemantic.PRESENTATION, p.EvidenceState.UNAVAILABLE, "unavailable", False)

    def test_26_enabled_does_not_synthesize_actionable(self):
        result = provider(ax_field(enabled=True, actionable=None, actionable_source="unavailable")).capture(capture_request())
        self.assert_fact(result, p.EvidenceSemantic.ACTIONABLE, p.EvidenceState.UNAVAILABLE, "unavailable", False)

    def test_27_non_grantable_high_grade_evidence_can_validate_diagnostics(self):
        descriptor = replace(
            provider().descriptor,
            provider_id="controlled.native.synthetic",
            provider_kind=p.EvidenceProviderKind.NATIVE_EXACT,
            grade=p.EvidenceGrade.L3_NATIVE_EXACT,
            scope=p.EvidenceProviderScope.CONTROLLED_FIXTURE_ONLY,
            authorization_grantable=False,
        )
        self.assertFalse(descriptor.authorization_grantable)
        self.assertNotEqual(p.EvidenceGrade.L2_STRUCTURAL_AX, descriptor.grade)

    def test_28_l1_l4_grades_do_not_create_providers(self):
        self.assertFalse(hasattr(p, "L4StructuredEvidenceProvider"))
        self.assertFalse(hasattr(p, "L1VisionEvidenceProvider"))

    def test_29_generic_observation_provider_remains_distinct(self):
        self.assertFalse(isinstance(p.AXObservationProvider(), p.GovernedEvidenceProvider))

    def test_30_old_and_shadow_normalization_are_equal(self):
        field = ax_field()
        old = p.AXInputAuthorizationEvidenceAdapter.adapt(field)
        new = provider(field).capture(capture_request())
        self.assertEqual(old, new.evidence)

    def test_31_required_context_version_fails_when_ax_cannot_prove_it(self):
        value = provider()
        checked = value.validate(
            value.capture(capture_request()),
            requirement(required_context_version=7),
        )
        self.assertIn("CONTEXT_VERSION_UNAVAILABLE", checked.failure_codes)

    def test_32_wrong_generation_is_rejected(self):
        value = provider()
        checked = value.validate(
            value.capture(capture_request()),
            requirement(required_observation_generation="snapshot.other"),
        )
        self.assertIn("OBSERVATION_GENERATION_MISMATCH", checked.failure_codes)

    def test_33_mixed_snapshot_is_rejected(self):
        field = ax_field(snapshot_ref="snapshot.other")
        value = provider(field)
        checked = value.validate(value.capture(capture_request()), requirement())
        self.assertIn("IDENTITY_REQUIREMENT_UNSATISFIED", checked.failure_codes)
        self.assertIn("OBSERVATION_GENERATION_UNAVAILABLE", checked.failure_codes)

    def test_34_validation_result_has_no_authority_or_success_fields(self):
        names = {item.name for item in fields(p.EvidenceValidationResult)}
        self.assertFalse(names & {"allow", "deny", "authorization", "verified", "semantic_success"})

    def test_35_privacy_safe_result_summary_excludes_payload_and_raw_values(self):
        summary = provider().capture(capture_request()).safe_summary()
        wire = json.dumps(summary).lower()
        for forbidden in ("selector_text", "field.synthetic", "token", "nonce", "coordinate", "raw_text",
                          "raw_value", "field_value"):
            self.assertNotIn(forbidden, wire)

    def test_36_provider_capture_does_not_reach_authority_or_execution(self):
        value = provider()
        with (
            patch.object(p.RiskController, "assess", side_effect=AssertionError("risk reached")),
            patch.object(p.PlanExecutor, "execute", side_effect=AssertionError("executor reached")),
            patch.object(p.MCPClient, "call_tool", side_effect=AssertionError("MCP reached")),
        ):
            result = value.capture(capture_request())
        self.assertEqual(p.EvidenceCaptureStatus.CAPTURED, result.capture_status)

    def test_37_requirement_collections_cannot_be_mutated(self):
        value = requirement()
        with self.assertRaises(AttributeError):
            value.permitted_provider_ids.add("other")
        with self.assertRaises(FrozenInstanceError):
            value.claims[0].expected_state = p.EvidenceState.FALSE

    def test_38_provider_claim_does_not_manufacture_missing_evidence(self):
        value = provider(ax_field(editable=None, editable_source="unavailable"))
        checked = value.validate(value.capture(capture_request()), requirement())
        self.assertEqual(p.EvidenceValidationStatus.INVALID, checked.status)
        self.assertIn("EDITABLE_STATE_MISMATCH", checked.failure_codes)

    def test_39_derived_secure_false_does_not_validate(self):
        value = provider(ax_field(secure=False, secure_source="inferred"))
        checked = value.validate(value.capture(capture_request()), requirement())
        self.assertIn("SECURE_PROVENANCE_UNACCEPTED", checked.failure_codes)

    def test_40_request_does_not_fabricate_plan_binding_in_ax_result(self):
        result = provider().capture(capture_request())
        self.assertIsNone(result.plan_id)
        self.assertIsNone(result.planning_revision)
        self.assertIsNone(result.step_id)

    def test_41_ax_normalization_equivalence_covers_security_variants(self):
        variants = (
            {},
            {"role": "unknown", "role_source": "unavailable"},
            {"editable": None, "editable_source": "unavailable"},
            {"editable": False},
            {"secure": None, "secure_source": "unavailable"},
            {"secure": True},
            {"enabled": None, "enabled_source": "unavailable"},
            {"enabled": False},
            {"visible": None, "visible_source": "unavailable"},
            {"visible": False},
            {"actionable": None, "actionable_source": "unavailable"},
            {"actionable": False},
            {"focused": None, "focused_source": "unavailable"},
            {"focused": False},
            {"same_leaf_identity": False, "same_leaf_source": "unavailable", "snapshot_ref": None},
        )
        for changes in variants:
            with self.subTest(changes=changes):
                field = ax_field(**changes)
                result = provider(field).capture(
                    capture_request(observation_generation=None)
                    if not field.has_same_leaf_identity()
                    else capture_request()
                )
                self.assertEqual(p.AXInputAuthorizationEvidenceAdapter.adapt(field), result.evidence)

    def test_42_new_contracts_are_dormant_in_authority_and_execution(self):
        for runtime_type in (p.RiskController, p.PlanExecutor, p.ObservationVerifier):
            source = inspect.getsource(runtime_type)
            self.assertNotIn("GovernedEvidenceProvider", source)
            self.assertNotIn("AXL2GovernedEvidenceProvider", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
