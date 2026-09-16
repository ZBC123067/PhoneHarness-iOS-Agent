#!/usr/bin/env python3
"""TEST-49 local contracts for the governed installed-app launch bridge.

The transport is wholly in-process. These tests never contact a device,
enumerate a real application inventory, or launch an application.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from phoneharness_agent import (
    ActionObligationLedger,
    BoundInstalledAppLaunchBridge,
    IDENTITY_CONSENT_VERSION,
    MCPCallError,
    MCPClient,
    MCPExecutionBoundaryError,
    PermissionDecision,
)


class FakeInstalledAppMCPClient(MCPClient):
    """Return a private fixture inventory without emitting identifiers in results."""

    def __init__(self, apps: list[dict[str, str]], *, observe_launch: bool = True, lose_response: bool = False) -> None:
        super().__init__("http://unused.invalid")
        self._apps = apps
        self._observe_launch = observe_launch
        self._lose_response = lose_response
        self._launched_bundle: str | None = None
        self.requests: list[tuple[str, dict[str, Any]]] = []

    def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.requests.append((method, dict(params)))
        if method == "tools/list":
            return {
                "tools": [
                    {"name": "list_apps", "inputSchema": {"required": []}},
                    {"name": "launch_app", "inputSchema": {"required": ["bundle_id"]}},
                    {"name": "describe_screen", "inputSchema": {"required": []}},
                ]
            }
        if method != "tools/call":
            raise AssertionError("unexpected MCP method")
        tool = params.get("name")
        if tool == "list_apps":
            return {"structuredContent": {"apps": self._apps}}
        if tool == "launch_app":
            self._launched_bundle = str((params.get("arguments") or {}).get("bundle_id") or "")
            if self._lose_response:
                raise MCPCallError("response unavailable")
            return {"structuredContent": {"accepted": True}}
        if tool == "describe_screen":
            frontmost = self._launched_bundle if self._observe_launch else "example.other"
            return {
                "structuredContent": {
                    "frontmost": {"name": "Fixture", "bundleId": frontmost},
                    "element_count": 1,
                    "source": "AX",
                    "elements": [{"text": "Ready", "clickable": False}],
                }
            }
        raise AssertionError("unexpected MCP tool")


def eligible_permission() -> PermissionDecision:
    return PermissionDecision(
        True,
        ("fixture_eligible",),
        "identity.fixture",
        "ownership.fixture",
        "consent.fixture",
        "execute",
        None,
        IDENTITY_CONSENT_VERSION,
    )


def denied_permission() -> PermissionDecision:
    return PermissionDecision(
        False,
        ("fixture_denied",),
        "identity.fixture",
        "ownership.fixture",
        "consent.fixture",
        "execute",
        None,
        IDENTITY_CONSENT_VERSION,
    )


def tool_calls(client: FakeInstalledAppMCPClient) -> list[str]:
    return [str(params.get("name")) for method, params in client.requests if method == "tools/call"]


class BoundInstalledAppLaunchTests(unittest.TestCase):
    def _run(
        self,
        client: FakeInstalledAppMCPClient,
        requested_app: str = "Fixture App",
        permission: PermissionDecision | None = None,
    ) -> tuple[dict[str, Any], ActionObligationLedger]:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        ledger = ActionObligationLedger(Path(directory.name))
        result = BoundInstalledAppLaunchBridge(client, action_obligation_ledger=ledger).execute(
            requested_app,
            permission_decision=permission or eligible_permission(),
            trial_approval_id="approval.bound_launch.v1",
        )
        return result, ledger

    def test_unique_match_launches_only_through_existing_executor_and_verifier(self) -> None:
        client = FakeInstalledAppMCPClient([{"name": "Fixture App", "bundle_id": "example.fixture"}])
        result, ledger = self._run(client)

        self.assertEqual("verified", result["status"])
        self.assertEqual("bound_app_observed", result["execution_evidence"]["verification_result"])
        self.assertTrue(result["execution_evidence"]["launch_dispatched"])
        self.assertEqual(["list_apps", "launch_app", "describe_screen"], tool_calls(client))
        self.assertEqual("VERIFIED", result["action_obligation"]["state"])
        self.assertEqual(result["action_obligation"], ledger.get(result["action_obligation"]["obligation_id"]))

    def test_permission_rejection_performs_zero_mcp_calls(self) -> None:
        client = FakeInstalledAppMCPClient([{"name": "Fixture App", "bundle_id": "example.fixture"}])
        result, _ = self._run(client, permission=denied_permission())

        self.assertEqual("blocked", result["status"])
        self.assertEqual("permission_denied", result["retry_repair_handoff"]["reason"])
        self.assertEqual([], client.requests)

    def test_malformed_target_does_not_read_private_inventory(self) -> None:
        client = FakeInstalledAppMCPClient([{"name": "Fixture App", "bundle_id": "example.fixture"}])
        result, _ = self._run(client, requested_app="Fixture\nApp")

        self.assertEqual("blocked", result["status"])
        self.assertEqual("unique_target_unavailable", result["retry_repair_handoff"]["reason"])
        self.assertEqual([], client.requests)

    def test_ambiguous_match_never_dispatches_an_action(self) -> None:
        client = FakeInstalledAppMCPClient(
            [
                {"name": "Fixture App", "bundle_id": "example.fixture.one"},
                {"name": "Fixture App", "bundle_id": "example.fixture.two"},
            ]
        )
        result, _ = self._run(client)

        self.assertEqual("blocked", result["status"])
        self.assertEqual("unique_target_unavailable", result["retry_repair_handoff"]["reason"])
        self.assertEqual(["list_apps"], tool_calls(client))
        self.assertNotIn("launch_app", tool_calls(client))

    def test_unverified_result_requires_fresh_observation_and_replan_without_retry(self) -> None:
        client = FakeInstalledAppMCPClient(
            [{"name": "Fixture App", "bundle_id": "example.fixture"}], observe_launch=False
        )
        result, _ = self._run(client)

        self.assertEqual("dispatched_unverified", result["status"])
        self.assertEqual("bound_app_not_observed", result["verification"]["verification_result"])
        self.assertEqual("fresh_observation_and_replan_required", result["retry_repair_handoff"]["reason"])
        self.assertEqual(1, tool_calls(client).count("launch_app"))

    def test_lost_dispatch_response_is_unknown_side_effect_without_retry(self) -> None:
        client = FakeInstalledAppMCPClient(
            [{"name": "Fixture App", "bundle_id": "example.fixture"}], lose_response=True
        )
        result, _ = self._run(client)

        self.assertEqual("unknown_side_effect", result["status"])
        self.assertEqual("fresh_observation_and_replan_required", result["retry_repair_handoff"]["reason"])
        self.assertEqual(1, tool_calls(client).count("launch_app"))
        self.assertEqual("UNKNOWN_SIDE_EFFECT", result["action_obligation"]["state"])

    def test_public_result_never_contains_request_or_private_application_identity(self) -> None:
        secret_name = "Private Fixture App"
        secret_bundle = "com.example.privatefixture"
        client = FakeInstalledAppMCPClient([{"name": secret_name, "bundle_id": secret_bundle}])
        result, _ = self._run(client, requested_app=secret_name)

        rendered = repr(result)
        self.assertNotIn(secret_name, rendered)
        self.assertNotIn(secret_bundle, rendered)
        self.assertEqual("none", result["execution_evidence"]["app_identity_access"])
        self.assertEqual("none", result["execution_evidence"]["replay_authority"])

    def test_public_mcp_surface_cannot_launch_application(self) -> None:
        client = FakeInstalledAppMCPClient([{"name": "Fixture App", "bundle_id": "example.fixture"}])
        with self.assertRaises(MCPExecutionBoundaryError):
            client.call_tool("launch_app", {"bundle_id": "example.fixture"})
        self.assertEqual([], client.requests)


if __name__ == "__main__":
    unittest.main(verbosity=2)
