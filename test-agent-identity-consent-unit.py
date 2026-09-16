#!/usr/bin/env python3
"""Static contract tests for TEST-36 Personal Identity and Consent Foundation.

These tests use synthetic identifiers and temporary local files only. They do
not contact an iPhone, a cloud model, MCP, a planner, or any execution layer.
"""

from __future__ import annotations

import json
import stat
import tempfile
import unittest
from pathlib import Path

from phoneharness_agent import (
    IdentityConsentFoundation,
    IdentityConsentPolicyError,
    PermissionRequest,
)


FORBIDDEN_KEYS = frozenset(
    {
        "goal",
        "screenshot",
        "coordinate",
        "coordinates",
        "rect",
        "ui",
        "ocr",
        "input",
        "clipboard",
        "raw_mcp_response",
        "raw_response",
        "password",
        "private_message",
        "claims",
    }
)


def keys_in(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(keys_in(item) for item in value.values())) if value else set()
    if isinstance(value, (tuple, list)):
        return set().union(*(keys_in(item) for item in value)) if value else set()
    return set()


class IdentityConsentFoundationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name) / "identity-consent"
        self.foundation = IdentityConsentFoundation(self.root)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _create_personal_identity(self, *, identity_id: str = "person.owner", timestamp: int = 100) -> None:
        self.foundation.create_identity(
            identity_id=identity_id,
            identity_kind="PERSONAL",
            claims={"preferred_language": "zh-Hans", "locale": "ms-MY"},
            confirmed_by_user=True,
            created_at=timestamp,
        )

    def _create_read_policy(self) -> PermissionRequest:
        self._create_personal_identity()
        self.foundation.classify_ownership(
            ownership_ref="personal.knowledge",
            ownership_class="PERSONAL",
            controlling_identity_id="person.owner",
            confirmed_by_user=True,
            classified_at=101,
        )
        self.foundation.set_workspace_permissions(
            workspace_ref="personal.workspace",
            permission_actions=("READ", "ANSWER"),
            confirmed_by_user=True,
            recorded_at=102,
        )
        self.foundation.grant_consent(
            consent_id="personal.reference",
            identity_id="person.owner",
            ownership_ref="personal.knowledge",
            purpose_code="knowledge.answer",
            audience_scope="owner_only",
            permission_actions=("READ", "ANSWER"),
            consent_uses=("REFERENCE_ONLY",),
            retention_category="until_revoked",
            confirmed_by_user=True,
            created_at=103,
        )
        return PermissionRequest(
            identity_id="person.owner",
            ownership_ref="personal.knowledge",
            ownership_class="PERSONAL",
            workspace_ref="personal.workspace",
            purpose_code="knowledge.answer",
            audience_scope="owner_only",
            action="READ",
            consent_use="REFERENCE_ONLY",
            risk_policy_allows=True,
        )

    def test_identity_creation_is_confirmed_scoped_and_private(self) -> None:
        with self.assertRaises(IdentityConsentPolicyError):
            self.foundation.create_identity(
                identity_id="person.owner",
                identity_kind="PERSONAL",
                claims={"preferred_language": "zh-Hans"},
                confirmed_by_user=False,
                created_at=100,
            )
        self._create_personal_identity()
        metadata = self.foundation.identity_metadata("person.owner")
        self.assertIsNotNone(metadata)
        self.assertEqual("PERSONAL", metadata.identity_kind)
        self.assertEqual(("locale", "preferred_language"), metadata.claim_keys)
        serialised = json.dumps([metadata.summary(), self.foundation.audit_events(), self.foundation.advisory_context()])
        self.assertNotIn("zh-Hans", serialised)
        self.assertNotIn("ms-MY", serialised)
        self.assertFalse(FORBIDDEN_KEYS.intersection(keys_in(json.loads(serialised))))

    def test_temporary_identity_requires_explicit_expiry(self) -> None:
        with self.assertRaises(IdentityConsentPolicyError):
            self.foundation.create_identity(
                identity_id="role.temp",
                identity_kind="TEMPORARY_ROLE",
                claims={"role_code": "delegate", "purpose_code": "knowledge.answer"},
                confirmed_by_user=True,
                created_at=100,
            )
        temporary = self.foundation.create_identity(
            identity_id="role.temp",
            identity_kind="TEMPORARY_ROLE",
            claims={"role_code": "delegate", "purpose_code": "knowledge.answer"},
            confirmed_by_user=True,
            created_at=100,
            expires_at=200,
        )
        self.assertEqual("TEMPORARY_ROLE", temporary.identity_kind)
        self.assertEqual(200, temporary.expires_at)

    def test_ownership_classification_enforces_identity_scope(self) -> None:
        self._create_personal_identity()
        with self.assertRaises(IdentityConsentPolicyError):
            self.foundation.classify_ownership(
                ownership_ref="company.knowledge",
                ownership_class="COMPANY",
                controlling_identity_id="person.owner",
                confirmed_by_user=True,
                classified_at=101,
            )
        ownership = self.foundation.classify_ownership(
            ownership_ref="personal.knowledge",
            ownership_class="PERSONAL",
            controlling_identity_id="person.owner",
            confirmed_by_user=True,
            classified_at=101,
        )
        self.assertEqual("PERSONAL", ownership.ownership_class)

    def test_consent_modes_allow_only_their_declared_actions(self) -> None:
        request = self._create_read_policy()
        allowed = self.foundation.resolve_permission(request, evaluated_at=104)
        self.assertTrue(allowed.eligible)
        self.assertEqual(("approved",), allowed.reason_codes)
        denied = self.foundation.resolve_permission(
            PermissionRequest(
                **{**request.__dict__, "action": "CREATE_RULE", "consent_use": "REFERENCE_ONLY"}
            ),
            evaluated_at=104,
        )
        self.assertFalse(denied.eligible)
        self.assertIn("workspace_permission_denied", denied.reason_codes)
        self.assertIn("consent_action_denied", denied.reason_codes)

    def test_multiple_consent_uses_allow_their_union_not_their_intersection(self) -> None:
        self._create_personal_identity()
        self.foundation.classify_ownership(
            ownership_ref="personal.rules",
            ownership_class="PERSONAL",
            controlling_identity_id="person.owner",
            confirmed_by_user=True,
            classified_at=101,
        )
        consent = self.foundation.grant_consent(
            consent_id="personal.learn",
            identity_id="person.owner",
            ownership_ref="personal.rules",
            purpose_code="knowledge.learn",
            audience_scope="owner_only",
            permission_actions=("CREATE_RULE", "TRAIN_MEMORY"),
            consent_uses=("LEARN", "TRAIN_MEMORY"),
            retention_category="bounded",
            confirmed_by_user=True,
            created_at=102,
        )
        self.assertEqual(("CREATE_RULE", "TRAIN_MEMORY"), consent.permission_actions)

    def test_resolution_intersects_workspace_ownership_consent_purpose_and_risk(self) -> None:
        request = self._create_read_policy()
        approved = self.foundation.resolve_permission(request, evaluated_at=104)
        self.assertTrue(approved.eligible)
        self.assertEqual("personal.reference", approved.consent_id)
        risk_denied = self.foundation.resolve_permission(
            PermissionRequest(**{**request.__dict__, "risk_policy_allows": False}),
            evaluated_at=104,
        )
        self.assertFalse(risk_denied.eligible)
        self.assertIn("risk_policy_denied", risk_denied.reason_codes)
        missing_workspace = self.foundation.resolve_permission(
            PermissionRequest(**{**request.__dict__, "workspace_ref": "other.workspace"}),
            evaluated_at=104,
        )
        self.assertFalse(missing_workspace.eligible)
        self.assertIn("workspace_permission_missing", missing_workspace.reason_codes)

    def test_revocation_versions_consent_and_removes_future_eligibility(self) -> None:
        request = self._create_read_policy()
        revoked = self.foundation.revoke_consent(
            consent_id="personal.reference",
            reason_code="owner.revoked",
            confirmed_by_user=True,
            revoked_at=105,
        )
        self.assertEqual(2, revoked.version)
        self.assertEqual(103, revoked.created_at)
        self.assertEqual(105, revoked.updated_at)
        self.assertEqual(105, revoked.revoked_at)
        rejected = self.foundation.resolve_permission(request, evaluated_at=106)
        self.assertFalse(rejected.eligible)
        self.assertIn("consent_revoked", rejected.reason_codes)
        events = self.foundation.audit_events()
        self.assertTrue(any(event["event_type"] == "revocation" for event in events))

    def test_company_data_cannot_be_shared_externally_without_explicit_external_consent(self) -> None:
        self.foundation.create_identity(
            identity_id="org.owner",
            identity_kind="ORGANIZATION",
            claims={"organization_relation": "employee", "organization_policy_ref": "policy.internal"},
            confirmed_by_user=True,
            created_at=100,
        )
        self.foundation.classify_ownership(
            ownership_ref="company.knowledge",
            ownership_class="COMPANY",
            controlling_identity_id="org.owner",
            confirmed_by_user=True,
            classified_at=101,
        )
        self.foundation.set_workspace_permissions(
            workspace_ref="company.workspace",
            permission_actions=("SHARE",),
            confirmed_by_user=True,
            recorded_at=102,
        )
        self.foundation.grant_consent(
            consent_id="company.internal",
            identity_id="org.owner",
            ownership_ref="company.knowledge",
            purpose_code="knowledge.share",
            audience_scope="organization_internal",
            permission_actions=("SHARE",),
            consent_uses=("TEMPORARY_USE",),
            retention_category="bounded",
            confirmed_by_user=True,
            created_at=103,
            expires_at=200,
        )
        result = self.foundation.resolve_permission(
            PermissionRequest(
                identity_id="org.owner",
                ownership_ref="company.knowledge",
                ownership_class="COMPANY",
                workspace_ref="company.workspace",
                purpose_code="knowledge.share",
                audience_scope="external_authorized",
                action="SHARE",
                consent_use="TEMPORARY_USE",
                risk_policy_allows=True,
            ),
            evaluated_at=104,
        )
        self.assertFalse(result.eligible)
        self.assertIn("consent_not_found", result.reason_codes)

    def test_customer_ownership_isolated_by_opaque_reference(self) -> None:
        self.foundation.create_identity(
            identity_id="work.owner",
            identity_kind="PROFESSIONAL",
            claims={"professional_role": "operator", "work_language": "en", "communication_style": "concise"},
            confirmed_by_user=True,
            created_at=100,
        )
        self.foundation.classify_ownership(
            ownership_ref="customer.acme",
            ownership_class="CUSTOMER",
            controlling_identity_id="work.owner",
            confirmed_by_user=True,
            classified_at=101,
        )
        self.foundation.set_workspace_permissions(
            workspace_ref="customer.workspace",
            permission_actions=("READ",),
            confirmed_by_user=True,
            recorded_at=102,
        )
        self.foundation.grant_consent(
            consent_id="customer.acme.read",
            identity_id="work.owner",
            ownership_ref="customer.acme",
            purpose_code="knowledge.answer",
            audience_scope="customer_specific",
            permission_actions=("READ",),
            consent_uses=("REFERENCE_ONLY",),
            retention_category="until_revoked",
            confirmed_by_user=True,
            created_at=103,
        )
        other_customer = self.foundation.resolve_permission(
            PermissionRequest(
                identity_id="work.owner",
                ownership_ref="customer.beta",
                ownership_class="CUSTOMER",
                workspace_ref="customer.workspace",
                purpose_code="knowledge.answer",
                audience_scope="customer_specific",
                action="READ",
                consent_use="REFERENCE_ONLY",
                risk_policy_allows=True,
            ),
            evaluated_at=104,
        )
        self.assertFalse(other_customer.eligible)
        self.assertIn("ownership_not_found", other_customer.reason_codes)
        self.assertIn("consent_not_found", other_customer.reason_codes)

    def test_same_version_conflict_default_denies(self) -> None:
        request = self._create_read_policy()
        path = self.foundation._stream_path("consents")
        record = self.foundation._require_current("consents", "consent_id", "personal.reference")
        conflict = dict(record)
        conflict["record_id"] = "conflicting-consent-record"
        conflict["retention_category"] = "bounded"
        with path.open("a", encoding="utf-8") as destination:
            destination.write(json.dumps(conflict, sort_keys=True) + "\n")
        result = self.foundation.resolve_permission(request, evaluated_at=104)
        self.assertFalse(result.eligible)
        self.assertIn("consent_conflict", result.reason_codes)

    def test_audit_integrity_and_private_file_permissions(self) -> None:
        self._create_read_policy()
        audit = self.foundation.audit_events()
        self.assertGreaterEqual(len(audit), 4)
        self.assertEqual(0o700, stat.S_IMODE(self.root.stat().st_mode))
        for path in self.root.iterdir():
            self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode), path.name)
        path = self.foundation._stream_path("audit")
        with path.open("a", encoding="utf-8") as destination:
            destination.write(json.dumps({"schema_version": "8.0", "identity_consent_version": "test-36.0", "record_type": "consent_audit_event", "recorded_at": 110}) + "\n")
        with self.assertRaises(IdentityConsentPolicyError):
            self.foundation.audit_events()

    def test_foundation_has_no_execution_or_content_query_interface(self) -> None:
        context = self.foundation.advisory_context()
        self.assertEqual("local_policy_foundation", context["mode"])
        self.assertEqual("none", context["decision_effect"])
        self.assertEqual("none", context["execution_authority"])
        self.assertFalse(FORBIDDEN_KEYS.intersection(keys_in(context)))
        for forbidden_name in ("client", "plan", "execute", "call_tool", "observe", "query_knowledge", "screenshot"):
            self.assertFalse(hasattr(self.foundation, forbidden_name), forbidden_name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
