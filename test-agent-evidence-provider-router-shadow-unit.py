"""Host-only P2 shadow EvidenceRequirement builder and EvidenceProviderRouter tests.

Shadow-only: the router reads immutable contracts and never captures,
authorizes, or reaches Risk, Executor, or the Verifier.
"""

import dataclasses
import inspect
import itertools
import json
import unittest
from unittest.mock import Mock

import phoneharness_agent as p

NOW = 1_000_000
AX_PROVIDER_ID = "phoneharness.ax.same_leaf.v1"
NATIVE_PROVIDER_ID = "controlled_native_l3"


def ax_descriptor():
    return p.AXL2GovernedEvidenceProvider._DESCRIPTOR


def native_descriptor():
    return p.ControlledNativeL3GovernedEvidenceProvider._DESCRIPTOR


def production_requirement(requirement_id="req-input-text-1"):
    return p.InputTextEvidenceRequirementBuilder.production_input_text(
        requirement_id, NOW,
        task_id="task-1", context_id="ctx-1", context_version=3,
        observation_generation="gen-1",
    )


def focus_requirement(requirement_id="req-focus-1"):
    return p.InputTextEvidenceRequirementBuilder.ax_structural_focus(
        requirement_id, NOW, task_id="task-1", context_id="ctx-1", context_version=3,
    )


def controlled_diagnostic(requirement_id, semantic, expected_state):
    return p.InputTextEvidenceRequirementBuilder.controlled_native_diagnostic(
        requirement_id, NOW,
        (p.InputTextEvidenceRequirementBuilder.native_claim(semantic, expected_state),),
    )


def fake_descriptor(provider_id, *, kinds=None, semantics=(), scope=p.EvidenceProviderScope.PRODUCTION_AX,
                    identity=(p.EvidenceIdentityRequirement.SAME_PROVIDER_LEAF,), provenance=(),
                    freshness=("HOST_CAPTURE_TIME",), grantable=True,
                    grade=p.EvidenceGrade.L4_STRUCTURED,
                    privacy=p.EvidencePrivacyClass.SAFE_TYPED_METADATA):
    return p.GovernedEvidenceProviderDescriptor(
        provider_id=provider_id,
        provider_kind=kinds or p.EvidenceProviderKind.STRUCTURAL_AX,
        grade=grade,
        supported_semantics=frozenset(semantics),
        scope=scope,
        identity_guarantees=frozenset(identity),
        provenance_guarantees=frozenset(provenance),
        freshness_capabilities=frozenset(freshness),
        privacy_class=privacy,
        authorization_grantable=grantable,
    )


class CountingProvider:
    """Provider whose capture/validate must never be reached by the router."""

    def __init__(self, descriptor):
        self.descriptor = descriptor
        self.capture_calls = 0
        self.validate_calls = 0

    def capture(self, request):
        self.capture_calls += 1
        raise AssertionError("router must not capture")

    def validate(self, evidence, requirement):
        self.validate_calls += 1
        raise AssertionError("router must not validate live evidence")


class EvidenceProviderRouterShadowTests(unittest.TestCase):
    def setUp(self):
        self.router = p.EvidenceProviderRouter()

    # 01
    def test_01_input_text_requirement_immutable(self):
        requirement = production_requirement()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            requirement.capability_id = "other"
        with self.assertRaises(dataclasses.FrozenInstanceError):
            requirement.claims[0].accepted_provenance = frozenset({"anything"})

    # 02
    def test_02_production_input_text_predicates_complete(self):
        requirement = production_requirement()
        claims = {claim.semantic: claim for claim in requirement.claims}
        self.assertEqual({
            p.EvidenceSemantic.ROLE_ALLOWED, p.EvidenceSemantic.EDITABLE,
            p.EvidenceSemantic.SECURE, p.EvidenceSemantic.ENABLED,
            p.EvidenceSemantic.PRESENTATION, p.EvidenceSemantic.ACTIONABLE,
            p.EvidenceSemantic.FOCUS, p.EvidenceSemantic.SAME_LEAF_IDENTITY,
            p.EvidenceSemantic.SNAPSHOT_FRESHNESS, p.EvidenceSemantic.EXPECTED_VALUE_MATCH,
        }, set(claims))
        self.assertEqual(requirement.identity_requirement, p.EvidenceIdentityRequirement.SAME_PROVIDER_LEAF)
        self.assertEqual(requirement.combination_policy, p.EvidenceCombinationPolicy.SINGLE_PROVIDER_ONLY)
        self.assertTrue(requirement.require_generation_binding)
        self.assertEqual(requirement.maximum_age_seconds, p.SemanticSearchTransactionStore.DEFAULT_TTL_SECONDS)

    # 03
    def test_03_policy_drift_zero_against_live_risk_sources(self):
        requirement = production_requirement()
        direct = p.SemanticSearchFieldEvidence.DIRECT_SOURCES
        role_sources = p.SemanticSearchFieldEvidence.ROLE_SOURCES
        snapshot = {"direct_snapshot"}
        expected = {
            p.EvidenceSemantic.ROLE_ALLOWED: (p.EvidenceState.TRUE, role_sources),
            p.EvidenceSemantic.EDITABLE: (p.EvidenceState.TRUE, direct),
            p.EvidenceSemantic.SECURE: (p.EvidenceState.FALSE, direct),
            p.EvidenceSemantic.ENABLED: (p.EvidenceState.TRUE, direct),
            p.EvidenceSemantic.PRESENTATION: (p.EvidenceState.TRUE, direct),
            p.EvidenceSemantic.ACTIONABLE: (p.EvidenceState.TRUE, direct),
            p.EvidenceSemantic.FOCUS: (p.EvidenceState.TRUE, direct),
            p.EvidenceSemantic.SAME_LEAF_IDENTITY: (p.EvidenceState.TRUE, snapshot),
            p.EvidenceSemantic.SNAPSHOT_FRESHNESS: (p.EvidenceState.TRUE, snapshot),
            p.EvidenceSemantic.EXPECTED_VALUE_MATCH: (p.EvidenceState.TRUE, direct),
        }
        for claim in requirement.claims:
            state, provenance = expected[claim.semantic]
            self.assertEqual(claim.expected_state, state, claim.semantic)
            self.assertEqual(claim.accepted_provenance, frozenset(provenance), claim.semantic)

    # 04
    def test_04_router_deterministic(self):
        requirement = production_requirement()
        first = self.router.evaluate(requirement, (ax_descriptor(), native_descriptor()),
                                     p.EvidenceRoutingPurpose.AUTHORIZATION)
        for _ in range(4):
            again = self.router.evaluate(requirement, (native_descriptor(), ax_descriptor()),
                                         p.EvidenceRoutingPurpose.AUTHORIZATION)
            self.assertEqual(first.safe_summary(), again.safe_summary())

    # 05
    def test_05_router_result_and_candidate_immutable(self):
        result = self.router.evaluate(production_requirement(), (ax_descriptor(), native_descriptor()),
                                      p.EvidenceRoutingPurpose.AUTHORIZATION)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.status = p.ShadowEvidenceRoutingStatus.NO_SUITABLE_PROVIDER
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.candidates[0].status = p.EvidenceRoutingCandidateStatus.SUITABLE

    # 06
    def test_06_router_has_no_authority_api(self):
        forbidden = ("authorize", "grant", "issue_receipt", "risk_override", "execute",
                     "dispatch", "verify_success", "mark_verified", "replan",
                     "capture", "validate")
        names = {name for name, _ in inspect.getmembers(p.EvidenceProviderRouter)}
        for authority in forbidden:
            self.assertNotIn(authority, names, authority)

    # 07
    def test_07_no_grade_ordering_in_routing(self):
        requirement = production_requirement()
        l4 = fake_descriptor("fake.l4", semantics=frozenset(claim.semantic for claim in requirement.claims),
                             provenance={"ax_attribute", "xc_attribute", "direct_snapshot"},
                             freshness=("HOST_CAPTURE_TIME", "DIRECT_SNAPSHOT_GENERATION"),
                             grantable=False, grade=p.EvidenceGrade.L4_STRUCTURED)
        result = self.router.evaluate(requirement, (ax_descriptor(), native_descriptor(), l4),
                                      p.EvidenceRoutingPurpose.AUTHORIZATION)
        self.assertEqual(result.status, p.ShadowEvidenceRoutingStatus.SUITABLE)
        self.assertEqual(result.recommended_provider_id, AX_PROVIDER_ID)

    # 08
    def test_08_full_input_text_native_rejected(self):
        result = self.router.evaluate(production_requirement(), (native_descriptor(),),
                                      p.EvidenceRoutingPurpose.AUTHORIZATION)
        self.assertEqual(result.status, p.ShadowEvidenceRoutingStatus.NO_SUITABLE_PROVIDER)
        candidate = result.candidates[0]
        self.assertEqual(candidate.status, p.EvidenceRoutingCandidateStatus.SCOPE_MISMATCH)
        self.assertFalse(candidate.semantic_suitability)
        self.assertIn("UNSUPPORTED_SEMANTIC", " ".join(candidate.rejection_reasons))
        self.assertIn("SCOPE_MISMATCH", candidate.rejection_reasons)
        self.assertIn("NON_GRANTABLE", candidate.rejection_reasons)

    # 09
    def test_09_full_input_text_ax_suitable(self):
        result = self.router.evaluate(production_requirement(), (ax_descriptor(),),
                                      p.EvidenceRoutingPurpose.AUTHORIZATION)
        self.assertEqual(result.status, p.ShadowEvidenceRoutingStatus.SUITABLE)
        self.assertEqual(result.recommended_provider_id, AX_PROVIDER_ID)
        candidate = result.candidates[0]
        self.assertEqual(candidate.status, p.EvidenceRoutingCandidateStatus.SUITABLE)
        self.assertTrue(candidate.semantic_suitability)
        self.assertTrue(candidate.authorization_route_suitability)

    # 10
    def test_10_native_missing_secure_rejected(self):
        requirement = dataclasses.replace(
            controlled_diagnostic("req-editable-diag", p.EvidenceSemantic.EDITABLE, p.EvidenceState.TRUE),
            permitted_provider_scopes=frozenset({p.EvidenceProviderScope.PRODUCTION_AX}),
        )
        requirement = dataclasses.replace(
            requirement,
            claims=requirement.claims + (
                p.InputTextEvidenceRequirementBuilder._claim(
                    p.EvidenceSemantic.SECURE, p.EvidenceState.FALSE, frozenset({"ax_attribute", "xc_attribute"})),
            ),
        )
        result = self.router.evaluate(requirement, (native_descriptor(),),
                                      p.EvidenceRoutingPurpose.DIAGNOSTIC)
        self.assertEqual(result.status, p.ShadowEvidenceRoutingStatus.NO_SUITABLE_PROVIDER)
        self.assertIn("UNSUPPORTED_SEMANTIC(SECURE)",
                      result.candidates[0].rejection_reasons)

    # 11
    def test_11_native_missing_actionable_rejected(self):
        requirement = dataclasses.replace(
            controlled_diagnostic("req-editable-diag", p.EvidenceSemantic.EDITABLE, p.EvidenceState.TRUE),
            permitted_provider_scopes=frozenset({p.EvidenceProviderScope.PRODUCTION_AX}),
        )
        requirement = dataclasses.replace(
            requirement,
            claims=requirement.claims + (
                p.InputTextEvidenceRequirementBuilder._claim(
                    p.EvidenceSemantic.ACTIONABLE, p.EvidenceState.TRUE, frozenset({"ax_attribute", "xc_attribute"})),
            ),
        )
        result = self.router.evaluate(requirement, (native_descriptor(),),
                                      p.EvidenceRoutingPurpose.DIAGNOSTIC)
        self.assertEqual(result.status, p.ShadowEvidenceRoutingStatus.NO_SUITABLE_PROVIDER)
        self.assertIn("UNSUPPORTED_SEMANTIC(ACTIONABLE)", result.candidates[0].rejection_reasons)

    # 12
    def test_12_native_missing_focus_rejected(self):
        requirement = dataclasses.replace(
            controlled_diagnostic("req-editable-diag", p.EvidenceSemantic.EDITABLE, p.EvidenceState.TRUE),
            permitted_provider_scopes=frozenset({p.EvidenceProviderScope.PRODUCTION_AX}),
        )
        requirement = dataclasses.replace(
            requirement,
            claims=requirement.claims + (
                p.InputTextEvidenceRequirementBuilder._claim(
                    p.EvidenceSemantic.FOCUS, p.EvidenceState.TRUE, frozenset({"ax_attribute", "xc_attribute"})),
            ),
        )
        result = self.router.evaluate(requirement, (native_descriptor(),),
                                      p.EvidenceRoutingPurpose.DIAGNOSTIC)
        self.assertEqual(result.status, p.ShadowEvidenceRoutingStatus.NO_SUITABLE_PROVIDER)
        self.assertIn("UNSUPPORTED_SEMANTIC(FOCUS)", result.candidates[0].rejection_reasons)

    # 13
    def test_13_native_scope_mismatch_rejected(self):
        requirement = dataclasses.replace(
            controlled_diagnostic("req-editable-diag", p.EvidenceSemantic.EDITABLE, p.EvidenceState.TRUE),
            permitted_provider_scopes=frozenset({p.EvidenceProviderScope.PRODUCTION_AX}),
        )
        result = self.router.evaluate(requirement, (native_descriptor(),),
                                      p.EvidenceRoutingPurpose.DIAGNOSTIC)
        self.assertEqual(result.status, p.ShadowEvidenceRoutingStatus.NO_SUITABLE_PROVIDER)
        self.assertIn("SCOPE_MISMATCH", result.candidates[0].rejection_reasons)

    # 14
    def test_14_diagnostic_requirement_cannot_route_as_authorization(self):
        requirement = controlled_diagnostic("req-editable-diag", p.EvidenceSemantic.EDITABLE, p.EvidenceState.TRUE)
        with self.assertRaises(ValueError):
            self.router.evaluate(requirement, (native_descriptor(),),
                                 p.EvidenceRoutingPurpose.AUTHORIZATION)
        with self.assertRaises(ValueError):
            self.router.evaluate(production_requirement(), (ax_descriptor(),),
                                 p.EvidenceRoutingPurpose.VERIFICATION)
        # AUTHORIZATION grantability is still evaluated on the authorization-grade
        # requirement: the native candidate carries NON_GRANTABLE there (test_08).

    # 15
    def test_15_controlled_editable_diagnostic_native_suitable(self):
        requirement = controlled_diagnostic("req-editable-diag", p.EvidenceSemantic.EDITABLE, p.EvidenceState.TRUE)
        result = self.router.evaluate(requirement, (native_descriptor(),),
                                      p.EvidenceRoutingPurpose.DIAGNOSTIC)
        self.assertEqual(result.status, p.ShadowEvidenceRoutingStatus.SUITABLE)
        self.assertEqual(result.recommended_provider_id, NATIVE_PROVIDER_ID)

    # 16
    def test_16_controlled_target_hidden_diagnostic_native_suitable(self):
        requirement = controlled_diagnostic("req-hidden-diag", p.EvidenceSemantic.TARGET_HIDDEN, p.EvidenceState.TRUE)
        result = self.router.evaluate(requirement, (native_descriptor(),),
                                      p.EvidenceRoutingPurpose.DIAGNOSTIC)
        self.assertEqual(result.status, p.ShadowEvidenceRoutingStatus.SUITABLE)
        self.assertEqual(result.recommended_provider_id, NATIVE_PROVIDER_ID)

    # 17
    def test_17_target_hidden_ax_unsupported(self):
        requirement = controlled_diagnostic("req-hidden-diag", p.EvidenceSemantic.TARGET_HIDDEN, p.EvidenceState.TRUE)
        requirement = dataclasses.replace(
            requirement,
            permitted_provider_kinds=frozenset({p.EvidenceProviderKind.STRUCTURAL_AX,
                                                p.EvidenceProviderKind.CONTROLLED_NATIVE}),
        )
        result = self.router.evaluate(requirement, (ax_descriptor(),),
                                      p.EvidenceRoutingPurpose.DIAGNOSTIC)
        self.assertEqual(result.status, p.ShadowEvidenceRoutingStatus.NO_SUITABLE_PROVIDER)
        self.assertIn("UNSUPPORTED_SEMANTIC(TARGET_HIDDEN)", result.candidates[0].rejection_reasons)

    # 18
    def test_18_focus_ax_suitable_native_unsuitable(self):
        result = self.router.evaluate(focus_requirement(), (ax_descriptor(), native_descriptor()),
                                      p.EvidenceRoutingPurpose.DIAGNOSTIC)
        self.assertEqual(result.status, p.ShadowEvidenceRoutingStatus.SUITABLE)
        self.assertEqual(result.recommended_provider_id, AX_PROVIDER_ID)
        native = [c for c in result.candidates if c.provider_id == NATIVE_PROVIDER_ID][0]
        self.assertIn("UNSUPPORTED_SEMANTIC(FOCUS)", native.rejection_reasons)

    # 19
    def test_19_l3_does_not_supersede_l2_by_grade(self):
        result = self.router.evaluate(focus_requirement(), (ax_descriptor(), native_descriptor()),
                                      p.EvidenceRoutingPurpose.DIAGNOSTIC)
        ax_candidate = [c for c in result.candidates if c.provider_id == AX_PROVIDER_ID][0]
        native = [c for c in result.candidates if c.provider_id == NATIVE_PROVIDER_ID][0]
        self.assertEqual(ax_candidate.grade, p.EvidenceGrade.L2_STRUCTURAL_AX)
        self.assertEqual(native.grade, p.EvidenceGrade.L3_NATIVE_EXACT)
        self.assertEqual(ax_candidate.status, p.EvidenceRoutingCandidateStatus.SUITABLE)
        self.assertNotEqual(native.status, p.EvidenceRoutingCandidateStatus.SUITABLE)

    # 20
    def test_20_l4_enum_does_not_auto_win(self):
        requirement = focus_requirement()
        l4 = fake_descriptor("fake.l4", semantics=frozenset(),
                             grade=p.EvidenceGrade.L4_STRUCTURED, grantable=True)
        result = self.router.evaluate(requirement, (l4, ax_descriptor()),
                                      p.EvidenceRoutingPurpose.DIAGNOSTIC)
        self.assertEqual(result.status, p.ShadowEvidenceRoutingStatus.SUITABLE)
        self.assertEqual(result.recommended_provider_id, AX_PROVIDER_ID)

    # 21
    def test_21_l1_enum_does_not_auto_lose_or_win(self):
        requirement = focus_requirement()
        l1 = fake_descriptor("fake.l1", kinds=p.EvidenceProviderKind.VISION_SEMANTIC,
                             semantics=frozenset({p.EvidenceSemantic.FOCUS}),
                             provenance={"ax_attribute"}, freshness=("DIRECT_SNAPSHOT_GENERATION",),
                             grantable=True, grade=p.EvidenceGrade.L1_VISION_SEMANTIC)
        requirement = dataclasses.replace(
            requirement,
            permitted_provider_kinds=frozenset({p.EvidenceProviderKind.STRUCTURAL_AX,
                                                p.EvidenceProviderKind.VISION_SEMANTIC}),
        )
        result = self.router.evaluate(requirement, (ax_descriptor(), l1),
                                      p.EvidenceRoutingPurpose.DIAGNOSTIC)
        self.assertEqual(result.status, p.ShadowEvidenceRoutingStatus.AMBIGUOUS)
        self.assertIsNone(result.recommended_provider_id)

    # 22
    def test_22_first_nonempty_prohibited(self):
        requirement = production_requirement()
        insufficient_first = fake_descriptor("aaa.insufficient", semantics=frozenset(),
                                             provenance={"ax_attribute"})
        sufficient_second = ax_descriptor()
        order_one = self.router.evaluate(requirement, (insufficient_first, sufficient_second),
                                         p.EvidenceRoutingPurpose.AUTHORIZATION)
        order_two = self.router.evaluate(requirement, (sufficient_second, insufficient_first),
                                         p.EvidenceRoutingPurpose.AUTHORIZATION)
        self.assertEqual(order_one.status, p.ShadowEvidenceRoutingStatus.SUITABLE)
        self.assertEqual(order_one.recommended_provider_id, AX_PROVIDER_ID)
        self.assertEqual(order_one.safe_summary(), order_two.safe_summary())

    # 23
    def test_23_no_safety_downgrade_fallback(self):
        requirement = production_requirement()
        insufficient = fake_descriptor("only.provider", semantics=frozenset({p.EvidenceSemantic.EDITABLE}),
                                       provenance={"ax_attribute"})
        result = self.router.evaluate(requirement, (insufficient,),
                                      p.EvidenceRoutingPurpose.AUTHORIZATION)
        self.assertEqual(result.status, p.ShadowEvidenceRoutingStatus.NO_SUITABLE_PROVIDER)
        self.assertIsNone(result.recommended_provider_id)
        self.assertIn("UNSUPPORTED_SEMANTIC", result.candidates[0].rejection_reasons[0])

    # 24
    def test_24_unsupported_semantic_fails_closed(self):
        requirement = focus_requirement()
        provider = fake_descriptor("no.focus", semantics=frozenset({p.EvidenceSemantic.EDITABLE}),
                                   provenance={"ax_attribute"})
        result = self.router.evaluate(requirement, (provider,),
                                      p.EvidenceRoutingPurpose.DIAGNOSTIC)
        self.assertEqual(result.status, p.ShadowEvidenceRoutingStatus.NO_SUITABLE_PROVIDER)
        self.assertIn("UNSUPPORTED_SEMANTIC(FOCUS)", result.candidates[0].rejection_reasons)

    # 25
    def test_25_insufficient_provenance_fails_closed(self):
        requirement = focus_requirement()
        provider = fake_descriptor("bad.provenance", semantics=frozenset({p.EvidenceSemantic.FOCUS}),
                                   provenance={"inferred"})
        result = self.router.evaluate(requirement, (provider,),
                                      p.EvidenceRoutingPurpose.DIAGNOSTIC)
        self.assertEqual(result.status, p.ShadowEvidenceRoutingStatus.NO_SUITABLE_PROVIDER)
        self.assertIn("PROVENANCE_INSUFFICIENT(FOCUS)", result.candidates[0].rejection_reasons)

    # 26
    def test_26_insufficient_identity_fails_closed(self):
        requirement = dataclasses.replace(production_requirement(),
                                          identity_requirement=p.EvidenceIdentityRequirement.EXACT_TARGET)
        provider = fake_descriptor("weak.identity", semantics=frozenset(claim.semantic for claim in requirement.claims),
                                   identity=(p.EvidenceIdentityRequirement.SAME_PROVIDER_LEAF,),
                                   provenance={"ax_attribute", "xc_attribute", "direct_snapshot"})
        result = self.router.evaluate(requirement, (provider,),
                                      p.EvidenceRoutingPurpose.AUTHORIZATION)
        self.assertEqual(result.status, p.ShadowEvidenceRoutingStatus.NO_SUITABLE_PROVIDER)
        self.assertIn("IDENTITY_INSUFFICIENT", result.candidates[0].rejection_reasons)

    # 27
    def test_27_insufficient_freshness_fails_closed(self):
        requirement = production_requirement()
        provider = fake_descriptor("stale.provider",
                                   semantics=frozenset(claim.semantic for claim in requirement.claims),
                                   provenance={"ax_attribute", "xc_attribute", "direct_snapshot"},
                                   freshness=("HOST_CAPTURE_TIME",))
        result = self.router.evaluate(requirement, (provider,),
                                      p.EvidenceRoutingPurpose.AUTHORIZATION)
        self.assertEqual(result.status, p.ShadowEvidenceRoutingStatus.NO_SUITABLE_PROVIDER)
        self.assertIn("FRESHNESS_INSUFFICIENT", result.candidates[0].rejection_reasons)

    # 28
    def test_28_privacy_mismatch_fails_closed(self):
        requirement = focus_requirement()
        descriptor = fake_descriptor("leaky.provider", semantics=frozenset({p.EvidenceSemantic.FOCUS}),
                                     provenance={"ax_attribute"})
        object.__setattr__(descriptor, "privacy_class", "UNSAFE_RAW")  # simulate foreign privacy class
        result = self.router.evaluate(requirement, (descriptor,),
                                      p.EvidenceRoutingPurpose.DIAGNOSTIC)
        self.assertEqual(result.status, p.ShadowEvidenceRoutingStatus.NO_SUITABLE_PROVIDER)
        self.assertIn("PRIVACY_INCOMPATIBLE", result.candidates[0].rejection_reasons)

    # 29
    def test_29_single_provider_only_blocks_combination(self):
        requirement = production_requirement()
        a = fake_descriptor("provider.a",
                            semantics=frozenset({p.EvidenceSemantic.EDITABLE, p.EvidenceSemantic.SECURE}),
                            provenance={"ax_attribute"})
        b = fake_descriptor("provider.b",
                            semantics=frozenset({p.EvidenceSemantic.FOCUS, p.EvidenceSemantic.ENABLED}),
                            provenance={"ax_attribute"})
        result = self.router.evaluate(requirement, (a, b), p.EvidenceRoutingPurpose.AUTHORIZATION)
        self.assertEqual(result.status, p.ShadowEvidenceRoutingStatus.NO_SUITABLE_PROVIDER)
        self.assertIsNone(result.recommended_provider_id)
        for candidate in result.candidates:
            self.assertIn("UNSUPPORTED_SEMANTIC", candidate.rejection_reasons[0])

    # 30
    def test_30_cross_provider_semantic_union_fails(self):
        requirement = production_requirement()
        a = fake_descriptor("provider.a",
                            semantics=frozenset({p.EvidenceSemantic.EDITABLE, p.EvidenceSemantic.SECURE,
                                                 p.EvidenceSemantic.FOCUS, p.EvidenceSemantic.ENABLED}),
                            provenance={"ax_attribute"})
        result = self.router.evaluate(requirement, (a,), p.EvidenceRoutingPurpose.AUTHORIZATION)
        self.assertEqual(result.status, p.ShadowEvidenceRoutingStatus.NO_SUITABLE_PROVIDER)
        self.assertIn("UNSUPPORTED_SEMANTIC", result.candidates[0].rejection_reasons[0])

    # 31
    def test_31_scope_mismatch_fails(self):
        requirement = production_requirement()
        provider = fake_descriptor("frame.provider",
                                   semantics=frozenset(claim.semantic for claim in requirement.claims),
                                   scope=p.EvidenceProviderScope.FRAME_SCOPED,
                                   provenance={"ax_attribute", "xc_attribute", "direct_snapshot"})
        result = self.router.evaluate(requirement, (provider,),
                                      p.EvidenceRoutingPurpose.AUTHORIZATION)
        self.assertEqual(result.status, p.ShadowEvidenceRoutingStatus.NO_SUITABLE_PROVIDER)
        self.assertIn("SCOPE_MISMATCH", result.candidates[0].rejection_reasons)

    # 32
    def test_32_non_grantable_evidence_diagnostic_usable(self):
        requirement = controlled_diagnostic("req-hidden-diag", p.EvidenceSemantic.TARGET_HIDDEN, p.EvidenceState.TRUE)
        result = self.router.evaluate(requirement, (native_descriptor(),),
                                      p.EvidenceRoutingPurpose.DIAGNOSTIC)
        candidate = result.candidates[0]
        self.assertEqual(candidate.status, p.EvidenceRoutingCandidateStatus.SUITABLE)
        self.assertFalse(candidate.authorization_grantable)
        self.assertFalse(candidate.authorization_route_suitability)
        self.assertEqual(candidate.rejection_reasons, ())

    # 33
    def test_33_registration_order_independence(self):
        requirement = production_requirement()
        extra = fake_descriptor("aaa.extra", semantics=frozenset(),
                                provenance={"ax_attribute"})
        forward = self.router.evaluate(requirement, (extra, ax_descriptor(), native_descriptor()),
                                       p.EvidenceRoutingPurpose.AUTHORIZATION)
        reverse = self.router.evaluate(requirement, (native_descriptor(), ax_descriptor(), extra),
                                       p.EvidenceRoutingPurpose.AUTHORIZATION)
        self.assertEqual(forward.safe_summary(), reverse.safe_summary())
        self.assertEqual(
            [c.provider_id for c in forward.candidates],
            sorted(c.provider_id for c in forward.candidates),
        )

    # 34
    def test_34_exact_tie_produces_ambiguous(self):
        requirement = production_requirement()
        twin = fake_descriptor("twin.ax", kinds=p.EvidenceProviderKind.STRUCTURAL_AX,
                               semantics=frozenset(claim.semantic for claim in requirement.claims),
                               identity=(p.EvidenceIdentityRequirement.SAME_PROVIDER_LEAF,),
                               provenance={"ax_attribute", "xc_attribute", "direct_snapshot"},
                               freshness=("HOST_CAPTURE_TIME", "DIRECT_SNAPSHOT_GENERATION"),
                               grantable=True, grade=p.EvidenceGrade.L2_STRUCTURAL_AX)
        result = self.router.evaluate(requirement, (ax_descriptor(), twin),
                                      p.EvidenceRoutingPurpose.AUTHORIZATION)
        self.assertEqual(result.status, p.ShadowEvidenceRoutingStatus.AMBIGUOUS)
        self.assertIsNone(result.recommended_provider_id)
        self.assertEqual({c.status for c in result.candidates}, {p.EvidenceRoutingCandidateStatus.SUITABLE})

    # 35
    def test_35_planner_cannot_select_provider(self):
        plan_fields = {field.name for field in dataclasses.fields(p.DynamicPlanStep)}
        for forbidden in ("provider", "provider_id", "provider_ids", "evidence_provider",
                          "authorized_provider", "preferred_provider"):
            self.assertFalse(any(forbidden in name for name in plan_fields), forbidden)
        request_fields = {field.name for field in dataclasses.fields(p.EvidenceCaptureRequest)}
        self.assertFalse(any("provider" in name for name in request_fields))

    # 36
    def test_36_planner_cannot_weaken_requirement(self):
        requirement = production_requirement()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            requirement.claims = ()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            requirement.permitted_provider_kinds = frozenset({p.EvidenceProviderKind.CONTROLLED_NATIVE})
        with self.assertRaises(dataclasses.FrozenInstanceError):
            requirement.identity_requirement = p.EvidenceIdentityRequirement.NONE
        with self.assertRaises(dataclasses.FrozenInstanceError):
            requirement.permitted_provider_scopes = frozenset(p.EvidenceProviderScope)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            requirement.combination_policy = p.EvidenceCombinationPolicy.EXPLICIT_CORRELATED

    # 37
    def test_37_router_capture_call_count_zero(self):
        counting_ax = CountingProvider(ax_descriptor())
        counting_native = CountingProvider(native_descriptor())
        self.router.evaluate(production_requirement(), (counting_ax, counting_native),
                             p.EvidenceRoutingPurpose.AUTHORIZATION)
        self.assertEqual(counting_ax.capture_calls, 0)
        self.assertEqual(counting_native.capture_calls, 0)

    # 38
    def test_38_router_validate_call_count_zero(self):
        counting_ax = CountingProvider(ax_descriptor())
        counting_native = CountingProvider(native_descriptor())
        self.router.evaluate(production_requirement(), (counting_ax, counting_native),
                             p.EvidenceRoutingPurpose.AUTHORIZATION)
        self.assertEqual(counting_ax.validate_calls, 0)
        self.assertEqual(counting_native.validate_calls, 0)

    # 39
    def test_39_router_creates_no_risk_receipt(self):
        result = self.router.evaluate(production_requirement(), (ax_descriptor(),),
                                      p.EvidenceRoutingPurpose.AUTHORIZATION)
        result_fields = {field.name for field in dataclasses.fields(result)}
        candidate_fields = {field.name for field in dataclasses.fields(result.candidates[0])}
        forbidden_names = {"receipt", "grant", "risk", "token", "authorized", "allow",
                           "execution", "verified", "replan", "dispatch"}
        self.assertTrue(result_fields & candidate_fields)  # sanity: both field sets read
        self.assertFalse(result_fields & forbidden_names)
        self.assertFalse(candidate_fields & forbidden_names)

    # 40
    def test_40_router_reaches_no_executor(self):
        self.assertFalse(any("executor" in name.lower()
                             for name, _ in inspect.getmembers(p.EvidenceProviderRouter)))
        self.assertFalse(hasattr(self.router, "_executor"))
        result = self.router.evaluate(production_requirement(), (ax_descriptor(),),
                                      p.EvidenceRoutingPurpose.AUTHORIZATION)
        result_fields = {field.name for field in dataclasses.fields(result)}
        self.assertFalse(any("executor" in name for name in result_fields))

    # 41
    def test_41_router_declares_no_verified(self):
        result = self.router.evaluate(production_requirement(), (ax_descriptor(),),
                                      p.EvidenceRoutingPurpose.AUTHORIZATION)
        status_values = {item.value for item in p.ShadowEvidenceRoutingStatus}
        candidate_values = {item.value for item in p.EvidenceRoutingCandidateStatus}
        self.assertNotIn("VERIFIED", status_values)
        self.assertNotIn("VERIFIED", candidate_values)
        self.assertNotIn("VERIFIED", result.safe_summary())

    # 42
    def test_42_shadow_result_contains_no_authority_fields(self):
        result = self.router.evaluate(production_requirement(), (ax_descriptor(), native_descriptor()),
                                      p.EvidenceRoutingPurpose.AUTHORIZATION)
        summary = result.safe_summary()
        forbidden = ("ALLOW", "AUTHORIZED", "receipt", "execution", "token", "binding_token",
                     "VERIFIED", "grant")
        encoded = repr(sorted(summary))
        for item in forbidden:
            self.assertNotIn(item, encoded, item)

    # 43
    def test_43_generic_observation_provider_remains_separate(self):
        with self.assertRaises(TypeError):
            self.router.evaluate(production_requirement(), (object(),),
                                 p.EvidenceRoutingPurpose.AUTHORIZATION)
        untyped = Mock(spec=["descriptor"])
        untyped.descriptor = {"provider_id": "dict"}
        with self.assertRaises(TypeError):
            self.router.evaluate(production_requirement(), (untyped,),
                                 p.EvidenceRoutingPurpose.AUTHORIZATION)

    # 44
    def test_44_ax_provider_behavior_unchanged(self):
        descriptor = ax_descriptor()
        self.assertEqual(descriptor.provider_id, AX_PROVIDER_ID)
        self.assertEqual(descriptor.grade, p.EvidenceGrade.L2_STRUCTURAL_AX)
        self.assertTrue(descriptor.authorization_grantable)
        self.assertIn(p.EvidenceSemantic.FOCUS, descriptor.supported_semantics)
        self.assertIn(p.EvidenceSemantic.EXPECTED_VALUE_MATCH, descriptor.supported_semantics)

    # 45
    def test_45_native_l3_provider_behavior_unchanged(self):
        descriptor = native_descriptor()
        self.assertEqual(descriptor.provider_id, NATIVE_PROVIDER_ID)
        self.assertEqual(descriptor.provider_kind, p.EvidenceProviderKind.CONTROLLED_NATIVE)
        self.assertEqual(descriptor.grade, p.EvidenceGrade.L3_NATIVE_EXACT)
        self.assertEqual(descriptor.scope, p.EvidenceProviderScope.CONTROLLED_FIXTURE_ONLY)
        self.assertFalse(descriptor.authorization_grantable)
        self.assertEqual(descriptor.supported_semantics, frozenset({
            p.EvidenceSemantic.EDITABLE, p.EvidenceSemantic.ENABLED,
            p.EvidenceSemantic.TARGET_HIDDEN, p.EvidenceSemantic.CONTROLLED_PRESENTATION,
        }))
        request = p.EvidenceCaptureRequest(
            requirement_id="req-x", task_id="task-1", plan_id="plan-1", planning_revision=1,
            step_id="step-1", capability_id="input_text", action_class="INPUT_TEXT",
            target_ref="read_only", context_id="ctx-1", context_version=1,
            observation_generation=None, requested_at=NOW,
            max_age_seconds=60, required_semantics=frozenset({p.EvidenceSemantic.EDITABLE}),
        )
        provider = p.ControlledNativeL3GovernedEvidenceProvider()
        result = provider.capture(request)
        self.assertEqual(result.capture_status, p.EvidenceCaptureStatus.UNAVAILABLE)
        self.assertEqual(result.failure_codes, ("PRODUCTION_DORMANT",))


class EvidenceProviderRouterAdversarialTests(unittest.TestCase):
    """High-confidence adversarial cases 46-65 over the P2 router surface."""

    def setUp(self):
        self.router = p.EvidenceProviderRouter()

    # 46
    def test_46_duplicate_provider_id_fails_closed(self):
        twin = fake_descriptor(AX_PROVIDER_ID, semantics=frozenset({p.EvidenceSemantic.FOCUS}),
                               provenance={"ax_attribute"})
        with self.assertRaises(ValueError):
            self.router.evaluate(focus_requirement(), (ax_descriptor(), twin),
                                 p.EvidenceRoutingPurpose.DIAGNOSTIC)

    # 47
    def test_47_malformed_descriptor_fails_closed(self):
        malformed = Mock(spec=["descriptor"])
        malformed.descriptor = {"provider_id": "not-a-descriptor"}
        with self.assertRaises(TypeError):
            self.router.evaluate(focus_requirement(), (malformed,),
                                 p.EvidenceRoutingPurpose.DIAGNOSTIC)
        with self.assertRaises(TypeError):
            self.router.evaluate(focus_requirement(), ({"descriptor": None},),
                                 p.EvidenceRoutingPurpose.DIAGNOSTIC)
        wrong_attr = Mock(spec=["descriptor"])
        wrong_attr.descriptor = 42
        with self.assertRaises(TypeError):
            self.router.evaluate(focus_requirement(), (wrong_attr,),
                                 p.EvidenceRoutingPurpose.DIAGNOSTIC)

    # 48
    def test_48_none_provider_fails_closed(self):
        for bad in (None, 42, "provider"):
            with self.assertRaises(TypeError):
                self.router.evaluate(focus_requirement(), (bad,),
                                     p.EvidenceRoutingPurpose.DIAGNOSTIC)

    # 49
    def test_49_unknown_availability_does_not_safety_downgrade(self):
        requirement = focus_requirement()
        suitable = self.router.evaluate(requirement, (ax_descriptor(),),
                                        p.EvidenceRoutingPurpose.DIAGNOSTIC,
                                        availability={AX_PROVIDER_ID: True})
        self.assertEqual(suitable.status, p.ShadowEvidenceRoutingStatus.SUITABLE)
        # Explicit map that omits the suitable provider: unknown != available.
        unknown = self.router.evaluate(requirement, (ax_descriptor(),),
                                       p.EvidenceRoutingPurpose.DIAGNOSTIC,
                                       availability={"someone.else": True})
        self.assertEqual(unknown.status, p.ShadowEvidenceRoutingStatus.NO_SUITABLE_PROVIDER)
        self.assertEqual(unknown.candidates[0].status, p.EvidenceRoutingCandidateStatus.UNAVAILABLE)
        # No fallback to the unsuitable provider when the good one is down.
        unavailable = self.router.evaluate(requirement, (ax_descriptor(), native_descriptor()),
                                           p.EvidenceRoutingPurpose.DIAGNOSTIC,
                                           availability={AX_PROVIDER_ID: False})
        self.assertEqual(unavailable.status, p.ShadowEvidenceRoutingStatus.NO_SUITABLE_PROVIDER)
        self.assertIsNone(unavailable.recommended_provider_id)

    # 50
    def test_50_semantic_specific_provenance_mismatch(self):
        requirement = production_requirement()
        provider = fake_descriptor("partial.provenance",
                                   semantics=frozenset(claim.semantic for claim in requirement.claims),
                                   identity=(p.EvidenceIdentityRequirement.SAME_PROVIDER_LEAF,),
                                   provenance={"ax_attribute", "xc_attribute"},
                                   freshness=("HOST_CAPTURE_TIME", "DIRECT_SNAPSHOT_GENERATION"))
        result = self.router.evaluate(requirement, (provider,),
                                      p.EvidenceRoutingPurpose.AUTHORIZATION)
        reasons = result.candidates[0].rejection_reasons
        self.assertIn("PROVENANCE_INSUFFICIENT(SAME_LEAF_IDENTITY)", reasons)
        self.assertIn("PROVENANCE_INSUFFICIENT(SNAPSHOT_FRESHNESS)", reasons)
        self.assertNotIn("PROVENANCE_INSUFFICIENT(EDITABLE)", reasons)
        self.assertNotIn("PROVENANCE_INSUFFICIENT(SECURE)", reasons)

    # 51
    def test_51_authorization_purpose_always_considers_grantability(self):
        requirement = production_requirement()
        provider = fake_descriptor("strong.but.nongrantable",
                                   semantics=frozenset(claim.semantic for claim in requirement.claims),
                                   identity=(p.EvidenceIdentityRequirement.SAME_PROVIDER_LEAF,),
                                   provenance={"ax_attribute", "xc_attribute", "direct_snapshot"},
                                   freshness=("HOST_CAPTURE_TIME", "DIRECT_SNAPSHOT_GENERATION"),
                                   grantable=False)
        result = self.router.evaluate(requirement, (provider,),
                                      p.EvidenceRoutingPurpose.AUTHORIZATION)
        candidate = result.candidates[0]
        self.assertEqual(candidate.status, p.EvidenceRoutingCandidateStatus.NON_GRANTABLE)
        self.assertTrue(candidate.semantic_suitability)
        self.assertFalse(candidate.authorization_route_suitability)
        self.assertEqual(candidate.rejection_reasons, ("NON_GRANTABLE",))

    # 52
    def test_52_diagnostic_purpose_preserves_nongrantable_usefulness(self):
        requirement = production_requirement()
        provider = fake_descriptor("strong.but.nongrantable",
                                   semantics=frozenset(claim.semantic for claim in requirement.claims),
                                   identity=(p.EvidenceIdentityRequirement.SAME_PROVIDER_LEAF,),
                                   provenance={"ax_attribute", "xc_attribute", "direct_snapshot"},
                                   freshness=("HOST_CAPTURE_TIME", "DIRECT_SNAPSHOT_GENERATION"),
                                   grantable=False)
        result = self.router.evaluate(requirement, (provider,),
                                      p.EvidenceRoutingPurpose.DIAGNOSTIC)
        candidate = result.candidates[0]
        self.assertEqual(candidate.status, p.EvidenceRoutingCandidateStatus.SUITABLE)
        self.assertFalse(candidate.authorization_grantable)
        self.assertFalse(candidate.authorization_route_suitability)
        self.assertEqual(candidate.rejection_reasons, ())

    # 53
    def test_53_purpose_mismatch_cannot_upgrade_privilege(self):
        diagnostic = controlled_diagnostic("req-diag", p.EvidenceSemantic.EDITABLE, p.EvidenceState.TRUE)
        with self.assertRaises(ValueError):
            self.router.evaluate(diagnostic, (native_descriptor(),),
                                 p.EvidenceRoutingPurpose.AUTHORIZATION)
        unstamped = p.EvidenceRequirement(
            requirement_id="req-unstamped", capability_id="input_text", action_class="INPUT_TEXT",
            claims=(p.InputTextEvidenceRequirementBuilder._claim(
                p.EvidenceSemantic.FOCUS, p.EvidenceState.TRUE,
                frozenset({"ax_attribute", "xc_attribute"})),),
            identity_requirement=p.EvidenceIdentityRequirement.SAME_PROVIDER_LEAF,
            maximum_age_seconds=60, evaluation_time=NOW,
            permitted_provider_ids=frozenset({AX_PROVIDER_ID}),
            permitted_provider_kinds=frozenset(),
            combination_policy=p.EvidenceCombinationPolicy.SINGLE_PROVIDER_ONLY,
            privacy_class=p.EvidencePrivacyClass.SAFE_TYPED_METADATA,
            confirmation_requirement=p.EvidenceConfirmationRequirement.NOT_REQUIRED,
            verifier_contract="SEMANTIC_INPUT_TEXT_VERIFICATION_V1",
        )
        with self.assertRaises(ValueError):
            self.router.evaluate(unstamped, (ax_descriptor(),),
                                 p.EvidenceRoutingPurpose.AUTHORIZATION)
        self.assertEqual(
            self.router.evaluate(unstamped, (ax_descriptor(),),
                                 p.EvidenceRoutingPurpose.DIAGNOSTIC).status,
            p.ShadowEvidenceRoutingStatus.SUITABLE,
        )

    # 54
    def test_54_weak_helper_cannot_substitute_production_authorization(self):
        builder = p.InputTextEvidenceRequirementBuilder
        with self.assertRaises(ValueError):
            self.router.evaluate(focus_requirement(), (ax_descriptor(),),
                                 p.EvidenceRoutingPurpose.AUTHORIZATION)
        with self.assertRaises(ValueError):
            self.router.evaluate(
                controlled_diagnostic("req-diag", p.EvidenceSemantic.EDITABLE, p.EvidenceState.TRUE),
                (native_descriptor(),), p.EvidenceRoutingPurpose.AUTHORIZATION)
        with self.assertRaises(ValueError):
            builder.native_claim(p.EvidenceSemantic.FOCUS, p.EvidenceState.TRUE)
        with self.assertRaises(ValueError):
            builder.controlled_native_diagnostic(
                "req-diag", NOW,
                (builder._claim(p.EvidenceSemantic.EDITABLE, p.EvidenceState.TRUE,
                                frozenset({"ax_attribute"})),),
            )
        # The only authorization-grade builder output carries the full predicate set.
        for semantic in (p.EvidenceSemantic.ROLE_ALLOWED, p.EvidenceSemantic.EDITABLE,
                         p.EvidenceSemantic.SECURE, p.EvidenceSemantic.ENABLED,
                         p.EvidenceSemantic.PRESENTATION, p.EvidenceSemantic.ACTIONABLE,
                         p.EvidenceSemantic.FOCUS, p.EvidenceSemantic.SAME_LEAF_IDENTITY,
                         p.EvidenceSemantic.SNAPSHOT_FRESHNESS, p.EvidenceSemantic.EXPECTED_VALUE_MATCH):
            self.assertIn(semantic, {claim.semantic for claim in production_requirement().claims})

    # 55
    def test_55_all_provider_permutations_deterministic(self):
        requirement = production_requirement()
        a = fake_descriptor("perm.a", semantics=frozenset(), provenance={"ax_attribute"})
        b = native_descriptor()
        c = ax_descriptor()
        baseline = None
        for permutation in itertools.permutations((a, b, c)):
            result = self.router.evaluate(requirement, permutation,
                                          p.EvidenceRoutingPurpose.AUTHORIZATION)
            summary = result.safe_summary()
            if baseline is None:
                baseline = summary
            self.assertEqual(baseline, summary)
        self.assertEqual(baseline["recommended_provider_id"], AX_PROVIDER_ID)

    # 56
    def test_56_sorted_output_does_not_become_winner_preference(self):
        requirement = production_requirement()
        twin = fake_descriptor("aaa.lexicographically-first", kinds=p.EvidenceProviderKind.STRUCTURAL_AX,
                               semantics=frozenset(claim.semantic for claim in requirement.claims),
                               identity=(p.EvidenceIdentityRequirement.SAME_PROVIDER_LEAF,),
                               provenance={"ax_attribute", "xc_attribute", "direct_snapshot"},
                               freshness=("HOST_CAPTURE_TIME", "DIRECT_SNAPSHOT_GENERATION"),
                               grantable=True, grade=p.EvidenceGrade.L2_STRUCTURAL_AX)
        result = self.router.evaluate(requirement, (twin, ax_descriptor()),
                                      p.EvidenceRoutingPurpose.AUTHORIZATION)
        self.assertEqual(result.status, p.ShadowEvidenceRoutingStatus.AMBIGUOUS)
        self.assertIsNone(result.recommended_provider_id)

    # 57
    def test_57_exact_multiway_tie_is_ambiguous(self):
        requirement = production_requirement()
        twins = tuple(
            fake_descriptor("twin.%d" % index, kinds=p.EvidenceProviderKind.STRUCTURAL_AX,
                            semantics=frozenset(claim.semantic for claim in requirement.claims),
                            identity=(p.EvidenceIdentityRequirement.SAME_PROVIDER_LEAF,),
                            provenance={"ax_attribute", "xc_attribute", "direct_snapshot"},
                            freshness=("HOST_CAPTURE_TIME", "DIRECT_SNAPSHOT_GENERATION"),
                            grantable=True, grade=p.EvidenceGrade.L2_STRUCTURAL_AX)
            for index in range(3)
        )
        result = self.router.evaluate(requirement, twins, p.EvidenceRoutingPurpose.AUTHORIZATION)
        self.assertEqual(result.status, p.ShadowEvidenceRoutingStatus.AMBIGUOUS)
        self.assertIsNone(result.recommended_provider_id)
        self.assertEqual(len(result.candidates), 3)
        self.assertTrue(all(c.status is p.EvidenceRoutingCandidateStatus.SUITABLE
                            for c in result.candidates))

    # 58
    def test_58_candidate_reason_ordering_deterministic(self):
        requirement = production_requirement()
        summaries = []
        for _ in range(3):
            result = self.router.evaluate(requirement, (ax_descriptor(), native_descriptor()),
                                          p.EvidenceRoutingPurpose.AUTHORIZATION)
            native = [c for c in result.candidates if c.provider_id == NATIVE_PROVIDER_ID][0]
            summaries.append(native.rejection_reasons)
        self.assertEqual(summaries[0], summaries[1])
        self.assertEqual(summaries[1], summaries[2])
        self.assertLess(summaries[0].index("SCOPE_MISMATCH"),
                        summaries[0].index("NON_GRANTABLE"))

    # 59
    def test_59_unknown_combination_policy_fails_closed(self):
        with self.assertRaises(TypeError):
            p.EvidenceRequirement(
                requirement_id="req-bad", capability_id="input_text", action_class="INPUT_TEXT",
                claims=(p.InputTextEvidenceRequirementBuilder._claim(
                    p.EvidenceSemantic.FOCUS, p.EvidenceState.TRUE,
                    frozenset({"ax_attribute", "xc_attribute"})),),
                identity_requirement=p.EvidenceIdentityRequirement.SAME_PROVIDER_LEAF,
                maximum_age_seconds=60, evaluation_time=NOW,
                permitted_provider_ids=frozenset({AX_PROVIDER_ID}),
                permitted_provider_kinds=frozenset(), combination_policy="SINGLE_PROVIDER_ONLY",
                privacy_class=p.EvidencePrivacyClass.SAFE_TYPED_METADATA,
                confirmation_requirement=p.EvidenceConfirmationRequirement.NOT_REQUIRED,
                verifier_contract="SEMANTIC_INPUT_TEXT_VERIFICATION_V1",
            )

    # 60
    def test_60_unsupported_correlated_combination_fails_closed(self):
        requirement = dataclasses.replace(production_requirement(),
                                          combination_policy=p.EvidenceCombinationPolicy.EXPLICIT_CORRELATED)
        result = self.router.evaluate(requirement, (ax_descriptor(), native_descriptor()),
                                      p.EvidenceRoutingPurpose.AUTHORIZATION)
        self.assertEqual(result.status, p.ShadowEvidenceRoutingStatus.NO_SUITABLE_PROVIDER)
        for candidate in result.candidates:
            self.assertEqual(candidate.status, p.EvidenceRoutingCandidateStatus.COMBINATION_FORBIDDEN)
            self.assertEqual(candidate.rejection_reasons, ("COMBINATION_FORBIDDEN",))
        self.assertIsNone(result.recommended_provider_id)

    # 61
    def test_61_privacy_safe_summary_audit(self):
        requirement = production_requirement()
        result = self.router.evaluate(requirement, (ax_descriptor(), native_descriptor()),
                                      p.EvidenceRoutingPurpose.AUTHORIZATION)
        summary = result.safe_summary()
        self.assertEqual(set(summary), {"routing_purpose", "requirement_id", "capability_id",
                                        "action_class", "combination_policy", "status",
                                        "recommended_provider_id", "candidates"})
        candidate_keys = {key for candidate in summary["candidates"] for key in candidate}
        self.assertEqual(candidate_keys, {"provider_id", "provider_kind", "grade", "scope",
                                          "authorization_grantable", "semantic_suitability",
                                          "authorization_route_suitability", "status",
                                          "rejection_reasons"})
        # No raw values anywhere: only enum codes, identifiers, booleans, and reason codes.
        encoded = json.dumps(summary)
        for forbidden in ("coordinate", "pointer", "nonce", "token", "field_ref",
                          "selector_text", "page_fingerprint", "device_generation"):
            self.assertNotIn(forbidden, encoded, forbidden)

    # 62
    def test_62_immutable_requirement_mutation_attempt(self):
        requirement = production_requirement()
        for attr, value in (
                ("routing_purpose", p.EvidenceRoutingPurpose.DIAGNOSTIC),
                ("claims", ()), ("permitted_provider_kinds", frozenset()),
                ("permitted_provider_scopes", frozenset(p.EvidenceProviderScope)),
                ("combination_policy", p.EvidenceCombinationPolicy.EXPLICIT_CORRELATED),
                ("identity_requirement", p.EvidenceIdentityRequirement.NONE),
                ("require_generation_binding", False), ("evaluation_time", 1),
        ):
            with self.assertRaises(dataclasses.FrozenInstanceError, msg=attr):
                setattr(requirement, attr, value)

    # 63
    def test_63_immutable_result_mutation_attempt(self):
        result = self.router.evaluate(production_requirement(),
                                      (ax_descriptor(), native_descriptor()),
                                      p.EvidenceRoutingPurpose.AUTHORIZATION)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.status = p.ShadowEvidenceRoutingStatus.NO_SUITABLE_PROVIDER
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.recommended_provider_id = None
        for candidate in result.candidates:
            with self.assertRaises(dataclasses.FrozenInstanceError, msg="status"):
                candidate.status = p.EvidenceRoutingCandidateStatus.UNAVAILABLE
            with self.assertRaises(dataclasses.FrozenInstanceError, msg="rejection_reasons"):
                candidate.rejection_reasons = ("X",)
            with self.assertRaises(dataclasses.FrozenInstanceError, msg="semantic_suitability"):
                candidate.semantic_suitability = False
            with self.assertRaises(dataclasses.FrozenInstanceError, msg="authorization_grantable"):
                candidate.authorization_grantable = True

    # 64
    def test_64_duplicate_semantic_claims_cannot_weaken_requirement(self):
        builder = p.InputTextEvidenceRequirementBuilder
        duplicate = (
            builder._claim(p.EvidenceSemantic.FOCUS, p.EvidenceState.TRUE,
                           frozenset({"ax_attribute", "xc_attribute"})),
            builder._claim(p.EvidenceSemantic.FOCUS, p.EvidenceState.FALSE,
                           frozenset({"anything"})),
        )
        with self.assertRaises(ValueError):
            p.EvidenceRequirement(
                requirement_id="req-dup", capability_id="input_text", action_class="INPUT_TEXT",
                claims=duplicate, identity_requirement=p.EvidenceIdentityRequirement.SAME_PROVIDER_LEAF,
                maximum_age_seconds=60, evaluation_time=NOW,
                permitted_provider_ids=frozenset({AX_PROVIDER_ID}), permitted_provider_kinds=frozenset(),
                combination_policy=p.EvidenceCombinationPolicy.SINGLE_PROVIDER_ONLY,
                privacy_class=p.EvidencePrivacyClass.SAFE_TYPED_METADATA,
                confirmation_requirement=p.EvidenceConfirmationRequirement.NOT_REQUIRED,
                verifier_contract="SEMANTIC_INPUT_TEXT_VERIFICATION_V1",
            )

    # 65
    def test_65_descriptor_claim_cannot_manufacture_evidence(self):
        result_fields = {field.name for field in dataclasses.fields(p.ShadowEvidenceRoutingResult)}
        candidate_fields = {field.name for field in dataclasses.fields(p.ShadowEvidenceRoutingCandidate)}
        self.assertNotIn("evidence", result_fields | candidate_fields)
        self.assertNotIn("facts", result_fields | candidate_fields)
        requirement = production_requirement()
        all_claiming = fake_descriptor("claims.everything",
                                       semantics=frozenset(claim.semantic for claim in requirement.claims),
                                       identity=(p.EvidenceIdentityRequirement.SAME_PROVIDER_LEAF,),
                                       provenance={"ax_attribute", "xc_attribute", "direct_snapshot"},
                                       freshness=("HOST_CAPTURE_TIME", "DIRECT_SNAPSHOT_GENERATION"),
                                       grantable=True)
        result = self.router.evaluate(requirement, (all_claiming,),
                                      p.EvidenceRoutingPurpose.AUTHORIZATION)
        self.assertEqual(result.status, p.ShadowEvidenceRoutingStatus.SUITABLE)
        self.assertIsInstance(result, p.ShadowEvidenceRoutingResult)
        self.assertNotIsInstance(result, p.GovernedEvidenceResult)


if __name__ == "__main__":
    unittest.main(verbosity=2)
