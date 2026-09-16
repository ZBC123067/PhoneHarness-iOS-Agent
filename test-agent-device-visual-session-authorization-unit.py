#!/usr/bin/env python3
"""Focused P2 contracts for device-issued temporary visual authorization.

This suite uses synthetic grants only.  It never captures a screen, performs
OCR, calls a real MCP endpoint, or emits visual/private content.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import unittest

from phoneharness_agent import (
    DeviceVisualSessionGrant,
    LocalVisualAnalysisError,
    MCPClient,
    MCPExecutionBoundaryError,
    MCPVisualRecognitionPort,
    PermissionDecision,
    ScreenshotSessionFoundation,
    ScreenshotSessionPolicyError,
    ScreenshotSessionStateError,
    VisualSessionAuthorizationPort,
)


def permission() -> PermissionDecision:
    return PermissionDecision(
        eligible=True,
        reason_codes=("p2_test",),
        identity_id="identity.visual-test",
        ownership_ref="ownership.visual-test",
        consent_id="consent.visual-test",
        action="READ",
        effective_expires_at=None,
        policy_version="test-36.0",
    )


def grant_payload(*, session_id: str = "visualsession." + "a" * 32, expiration_time: int = 220) -> dict[str, object]:
    return {
        "session_id": session_id,
        "created_time": 100,
        "expiration_time": expiration_time,
        "permission_scope": "visual_observation",
        "one_time_access": True,
        "status": "ACTIVE",
    }


class DeviceVisualSessionAuthorizationTests(unittest.TestCase):
    def test_device_grant_uses_exact_safe_schema(self) -> None:
        grant = DeviceVisualSessionGrant.from_payload(grant_payload())
        self.assertEqual(grant.summary(), grant_payload())

        for key, value in (("owner_id", "visualowner.hidden"), ("pixels", "forbidden"), ("scope", "override")):
            payload = grant_payload()
            payload[key] = value
            with self.assertRaises(LocalVisualAnalysisError):
                DeviceVisualSessionGrant.from_payload(payload)

    def test_device_grant_rejects_expired_or_weakened_authorization(self) -> None:
        for changed in (
            {"expiration_time": 100},
            {"expiration_time": 221},
            {"permission_scope": "other"},
            {"one_time_access": False},
            {"status": "USED"},
        ):
            payload = grant_payload()
            payload.update(changed)
            with self.assertRaises(LocalVisualAnalysisError):
                DeviceVisualSessionGrant.from_payload(payload)

        foundation = ScreenshotSessionFoundation()
        expired = DeviceVisualSessionGrant.from_payload(grant_payload(expiration_time=200))
        with self.assertRaises(ScreenshotSessionPolicyError):
            foundation.create(
                ingress="shortcut",
                image_bytes=b"synthetic-boundary-marker",
                permission=permission(),
                explicit_user_confirmation=True,
                now=201,
                device_grant=expired,
            )

    def test_device_grant_binds_exactly_one_host_session(self) -> None:
        foundation = ScreenshotSessionFoundation()
        grant = DeviceVisualSessionGrant.from_payload(grant_payload())
        summary = foundation.create(
            ingress="shortcut",
            image_bytes=b"synthetic-boundary-marker",
            permission=permission(),
            explicit_user_confirmation=True,
            now=110,
            device_grant=grant,
        )
        self.assertEqual(summary.session_id, grant.session_id)
        self.assertLessEqual(summary.expires_at, grant.expiration_time)
        with self.assertRaises(ScreenshotSessionPolicyError):
            foundation.create(
                ingress="shortcut",
                image_bytes=b"synthetic-boundary-marker-two",
                permission=permission(),
                explicit_user_confirmation=True,
                now=111,
                device_grant=grant,
            )

    def test_local_analysis_claim_is_single_consumer_and_cleanup_releases_it(self) -> None:
        foundation = ScreenshotSessionFoundation()
        summary = foundation.create(
            ingress="shortcut",
            image_bytes=b"synthetic-local-marker",
            permission=permission(),
            explicit_user_confirmation=True,
            now=100,
        )
        foundation.activate(summary.session_id, now=100)

        def claim() -> str:
            try:
                foundation.claim_local_analysis(summary.session_id, now=100)
                return "claimed"
            except ScreenshotSessionStateError:
                return "rejected"

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = tuple(pool.map(lambda _: claim(), range(2)))
        self.assertEqual(results.count("claimed"), 1)
        self.assertEqual(results.count("rejected"), 1)
        foundation.destroy(summary.session_id)
        with self.assertRaises(ScreenshotSessionStateError):
            foundation.claim_local_analysis(summary.session_id, now=101)

    def test_private_bridge_issues_grant_but_generic_client_cannot_call_it(self) -> None:
        client = MCPClient("http://127.0.0.1:1/mcp")
        with self.assertRaises(MCPExecutionBoundaryError):
            client.call_tool("create_visual_session", {})
        with self.assertRaises(MCPExecutionBoundaryError):
            client.call_tool("analyze_visual_session", {"session_id": "visualsession." + "b" * 32})

        client._call_tool_payload = lambda name, arguments: grant_payload()  # type: ignore[method-assign]
        adapter = MCPVisualRecognitionPort(client)
        self.assertIsInstance(adapter, VisualSessionAuthorizationPort)
        self.assertEqual(adapter.issue_temporary_visual_session_grant().session_id, grant_payload()["session_id"])

    def test_device_source_uses_memory_registry_secure_random_and_one_time_consume(self) -> None:
        source = Path(__file__).with_name("MCPServer.m").read_text(encoding="utf-8")
        self.assertIn("SecRandomCopyBytes", source)
        self.assertIn("_temporaryVisualSessions", source)
        self.assertIn("MCP_VISUAL_SESSION_TTL_SECONDS 120", source)
        self.assertIn("[_temporaryVisualSessions removeObjectForKey:sessionId]", source)
        self.assertIn("create_visual_session", source)
        self.assertIn("analyze_visual_session", source)

        implementation_start = source.index("@implementation MCPServer")
        session_start = source.index("- (void)purgeExpiredVisualSessionsAtTime:", implementation_start)
        session_end = source.index("- (NSDictionary *)executeDescribeScreen:", session_start)
        session_source = source[session_start:session_end]
        self.assertNotIn("writeToFile", session_source)
        self.assertNotIn("NSUserDefaults", session_source)
        grant_start = source.index("- (NSDictionary *)executeCreateVisualSession:", implementation_start)
        grant_end = source.index("- (NSDictionary *)executeAnalyzeVisualSession:", grant_start)
        grant_source = source[grant_start:grant_end]
        public_result_source = grant_source[grant_source.index("return [self mcpSuccess:reqId structuredContent:@{") :]
        self.assertNotIn('@"owner_id"', public_result_source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
