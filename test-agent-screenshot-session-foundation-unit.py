#!/usr/bin/env python3
"""Focused TEST-44.1 contracts for temporary Screenshot Session Foundation.

All image bytes and OCR/layout fixtures are synthetic and remain only inside
the temporary in-memory session.  This suite has no capture adapter, no MCP
client, no device action, no storage, and no network activity.
"""

from __future__ import annotations

import json
import unittest

from phoneharness_agent import (
    CapabilityCatalog,
    CapabilityEvaluator,
    CapabilityIntelligenceError,
    PermissionDecision,
    SCREENSHOT_SESSION_FOUNDATION_VERSION,
    ScreenshotSessionFoundation,
    ScreenshotSessionPolicyError,
    ScreenshotSessionStateError,
    VisualEvidence,
    VisualSemanticCandidate,
)


FORBIDDEN_KEYS = frozenset(
    {
        "screenshot",
        "image",
        "pixels",
        "ocr",
        "raw_ocr",
        "text",
        "content",
        "coordinate",
        "coordinates",
        "rect",
        "geometry",
        "layout_regions",
        "ui",
        "bundle_id",
        "app",
        "password",
        "token",
        "mcp",
        "raw_mcp_response",
        "tool_arguments",
        "replay_steps",
        "action",
    }
)


def keys_in(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(keys_in(item) for item in value.values())) if value else set()
    if isinstance(value, (tuple, list)):
        return set().union(*(keys_in(item) for item in value)) if value else set()
    return set()


def allowed_permission() -> PermissionDecision:
    return PermissionDecision(
        eligible=True,
        reason_codes=("approved",),
        identity_id="identity.test44",
        ownership_ref="ownership.test44",
        consent_id="consent.test44",
        action="READ",
        effective_expires_at=None,
        policy_version="test-36.0",
    )


def denied_permission() -> PermissionDecision:
    return PermissionDecision(
        eligible=False,
        reason_codes=("default_deny",),
        identity_id="identity.test44",
        ownership_ref="ownership.test44",
        consent_id="consent.test44",
        action="READ",
        effective_expires_at=None,
        policy_version="test-36.0",
    )


def candidate(*, status: str = "READY", confidence: float = 0.92) -> VisualSemanticCandidate:
    reasons = () if status == "READY" else ("low_visual_confidence",)
    domain = "domain_alpha" if status == "READY" else "UNKNOWN_DOMAIN"
    result = VisualSemanticCandidate(
        visual_intelligence_version="test-40.1",
        candidate_id="visual.%s" % ("a" * 32),
        status=status,
        confidence=confidence,
        detected_entity_types=("screen_context", "interaction_affordance"),
        domain=domain,
        source_types=("AX",),
        evidence=(VisualEvidence("AX", confidence, 100, "screen_context", "semantic_graph"),),
        reason_codes=reasons,
        timestamp=100,
        expires_at=160,
    )
    result.validate_public_schema()
    return result


class ScreenshotSessionFoundationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.foundation = ScreenshotSessionFoundation()

    def create(self, *, now: int = 100, ttl_seconds: int = 20) -> dict[str, object]:
        return self.foundation.create(
            ingress="shortcut",
            image_bytes=b"synthetic-private-image-bytes",
            permission=allowed_permission(),
            explicit_user_confirmation=True,
            now=now,
            ttl_seconds=ttl_seconds,
        ).schema()

    def test_capability_uses_existing_catalog_but_is_unavailable_without_future_adapter(self) -> None:
        capability = self.foundation.capability_definition()
        catalog = CapabilityCatalog((capability,))
        contract = catalog.get(capability.capability_id)
        self.assertEqual("DISCOVERED", contract["lifecycle"])
        self.assertEqual(["visual_session_capture"], contract["required_tools"])
        evaluation = CapabilityEvaluator().evaluate(
            catalog,
            available_tools=(),
            available_permissions=(),
            available_platforms=("macos_host",),
        )
        self.assertFalse(evaluation.candidates[0].eligible)
        self.assertEqual(("missing_required_tools", "missing_required_permissions"), evaluation.candidates[0].reason_codes)

    def test_creation_requires_existing_permission_and_explicit_confirmation(self) -> None:
        with self.assertRaises(ScreenshotSessionPolicyError):
            self.foundation.create(
                ingress="shortcut",
                image_bytes=b"synthetic",
                permission=denied_permission(),
                explicit_user_confirmation=True,
                now=100,
            )
        with self.assertRaises(ScreenshotSessionPolicyError):
            self.foundation.create(
                ingress="shortcut",
                image_bytes=b"synthetic",
                permission=allowed_permission(),
                explicit_user_confirmation=False,
                now=100,
            )
        self.assertEqual((), self.foundation.summaries(now=100))

    def test_lifecycle_is_explicit_and_private_material_has_no_public_schema(self) -> None:
        created = self.create()
        self.assertEqual(SCREENSHOT_SESSION_FOUNDATION_VERSION, created["session_version"])
        self.assertEqual("CREATED", created["state"])
        self.assertFalse(FORBIDDEN_KEYS.intersection(keys_in(created)))
        self.assertNotIn("synthetic-private-image-bytes", json.dumps(created))

        active = self.foundation.activate(created["session_id"], now=101).schema()
        analyzed = self.foundation.submit_local_analysis(
            created["session_id"],
            ocr_regions=({"private": "never-public"},),
            layout_regions=({"private_rect": (1, 2, 3, 4)},),
            candidate=candidate(),
            now=102,
        ).schema()
        self.assertEqual("ACTIVE", active["state"])
        self.assertEqual("ANALYZED", analyzed["state"])
        self.assertEqual("AVAILABLE", analyzed["analysis_status"])
        self.assertFalse(FORBIDDEN_KEYS.intersection(keys_in(analyzed)))
        serialized = json.dumps(analyzed, sort_keys=True)
        self.assertNotIn("never-public", serialized)
        self.assertNotIn("private_rect", serialized)

        destroyed = self.foundation.destroy(created["session_id"]).schema()
        self.assertEqual("DESTROYED", destroyed["state"])
        self.assertEqual("CLEARED", destroyed["analysis_status"])
        self.assertEqual("NONE", destroyed["candidate_status"])
        self.assertEqual([], destroyed["evidence"])
        self.assertEqual((), self.foundation.summaries(now=103))

    def test_local_analysis_cannot_run_before_activation_or_after_expiry(self) -> None:
        created = self.create()
        with self.assertRaises(ScreenshotSessionStateError):
            self.foundation.activate(created["session_id"], now=99)
        with self.assertRaises(ScreenshotSessionStateError):
            self.foundation.submit_local_analysis(
                created["session_id"],
                ocr_regions=(),
                layout_regions=(),
                candidate=candidate(),
                now=101,
            )
        self.foundation.activate(created["session_id"], now=101)
        expired = self.foundation.expire(now=121)
        self.assertEqual(1, len(expired))
        self.assertEqual("EXPIRED", expired[0].state)
        self.assertEqual("CLEARED", expired[0].analysis_status)
        with self.assertRaises(ScreenshotSessionStateError):
            self.foundation.propose_intent(created["session_id"], intent_kind="translate", now=122)

    def test_intent_and_translation_preparation_are_advisory_only(self) -> None:
        created = self.create()
        self.foundation.activate(created["session_id"], now=101)
        self.foundation.submit_local_analysis(
            created["session_id"],
            ocr_regions=({"internal": "private"},),
            layout_regions=({"internal": "private"},),
            candidate=candidate(),
            now=102,
        )
        proposal = self.foundation.propose_intent(created["session_id"], intent_kind="translate", now=103)
        overlay = self.foundation.prepare_translation_overlay(created["session_id"], now=104)
        self.assertEqual("READY", proposal["status"])
        self.assertEqual("none", proposal["execution_authority"])
        self.assertEqual("Planner -> Risk Controller -> Executor -> Verifier", proposal["next_gate"])
        self.assertTrue(overlay["layout_available"])
        self.assertEqual("none", overlay["render_authority"])
        self.assertFalse(FORBIDDEN_KEYS.intersection(keys_in(proposal)))
        self.assertFalse(FORBIDDEN_KEYS.intersection(keys_in(overlay)))

    def test_low_confidence_candidate_needs_confirmation_and_never_executes(self) -> None:
        created = self.create()
        self.foundation.activate(created["session_id"], now=101)
        self.foundation.submit_local_analysis(
            created["session_id"],
            ocr_regions=(),
            layout_regions=(),
            candidate=candidate(status="NEEDS_CONFIRMATION", confidence=0.41),
            now=102,
        )
        proposal = self.foundation.propose_intent(created["session_id"], intent_kind="explain", now=103)
        self.assertEqual("NEEDS_CONFIRMATION", proposal["status"])
        self.assertEqual(["needs_confirmation"], proposal["reason_codes"])
        self.assertEqual("none", proposal["execution_authority"])

    def test_private_region_capacity_and_invalid_ingress_are_rejected(self) -> None:
        with self.assertRaises(ScreenshotSessionPolicyError):
            self.foundation.create(
                ingress="unknown_ingress",
                image_bytes=b"synthetic",
                permission=allowed_permission(),
                explicit_user_confirmation=True,
                now=100,
            )
        created = self.create()
        self.foundation.activate(created["session_id"], now=101)
        with self.assertRaises(ScreenshotSessionPolicyError):
            self.foundation.submit_local_analysis(
                created["session_id"],
                ocr_regions=tuple(range(self.foundation.MAX_PRIVATE_REGIONS + 1)),
                layout_regions=(),
                candidate=candidate(),
                now=102,
            )

    def test_foundation_has_no_device_or_runtime_action_interface(self) -> None:
        for forbidden_name in (
            "client",
            "mcp",
            "call_tool",
            "observe",
            "plan",
            "risk",
            "execute",
            "verify",
            "open_url",
            "tap",
            "input",
            "launch",
            "save",
            "persist",
        ):
            self.assertFalse(hasattr(self.foundation, forbidden_name), forbidden_name)
        with self.assertRaises(CapabilityIntelligenceError):
            CapabilityCatalog((self.foundation.capability_definition(), self.foundation.capability_definition()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
