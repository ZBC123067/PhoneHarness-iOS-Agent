#!/usr/bin/env python3
"""TEST-42.1 static gates for the Apple Maps native capability bridge.

All tests use an in-process MCP transport.  They do not contact an iPhone,
open a URL, or perform a device action.
"""

from __future__ import annotations

import unittest
from typing import Any

from phoneharness_agent import (
    IDENTITY_CONSENT_VERSION,
    MCPClient,
    MCPExecutionBoundaryError,
    MapLinkAdapter,
    NativeCapabilityBridge,
    PermissionDecision,
)


class FakeMapsMCPClient(MCPClient):
    """A deterministic Maps observation after one executor-owned dispatch."""

    def __init__(self) -> None:
        super().__init__("http://unused.invalid")
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.dispatched = False

    def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.requests.append((method, dict(params)))
        if method == "tools/list":
            return {
                "tools": [
                    {"name": "open_url", "inputSchema": {"required": ["url"]}},
                    {"name": "describe_screen", "inputSchema": {"required": []}},
                ]
            }
        if method != "tools/call":
            raise AssertionError("unexpected MCP method")
        if params["name"] == "open_url":
            self.dispatched = True
            return {"structuredContent": {"accepted": True}}
        if params["name"] == "describe_screen":
            return {
                "structuredContent": {
                    "frontmost": {
                        "name": "Maps" if self.dispatched else "Other",
                        "bundleId": "com.apple.Maps" if self.dispatched else "example.other",
                    },
                    "element_count": 1,
                    "source": "AX",
                    "elements": [{"text": "Maps", "clickable": False}],
                }
            }
        raise AssertionError("unexpected MCP tool")


def eligible_permission() -> PermissionDecision:
    """A pre-resolved TEST-36 fixture, not a source of executor authority."""

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


class NativeCapabilityBridgeTests(unittest.TestCase):
    def test_map_adapter_builds_legacy_link_and_redacts_its_summary(self) -> None:
        adapter = MapLinkAdapter("Kuching Waterfront")
        self.assertEqual("http://maps.apple.com/?q=Kuching+Waterfront", adapter.map_url())
        self.assertEqual(
            {
                "destination_present": True,
                "destination_length_bucket": "medium",
                "destination_class": "public_destination",
            },
            adapter.input_summary(),
        )
        self.assertNotIn("Kuching", str(adapter.input_summary()))

    def test_map_adapter_rejects_url_or_control_injection(self) -> None:
        for invalid in ("https://example.invalid", "Maps?query=x", "place\nother"):
            with self.assertRaises(ValueError):
                MapLinkAdapter(invalid)

    def test_bridge_runs_only_through_executor_then_maps_verifier(self) -> None:
        client = FakeMapsMCPClient()
        result = NativeCapabilityBridge(client).execute_maps_link(
            "Kuching Waterfront",
            permission_decision=eligible_permission(),
            trial_approval_id="approval.maps_trial.v1",
        )
        self.assertEqual("verified", result["status"])
        self.assertEqual("maps_observed", result["execution_evidence"]["execution_status"])
        self.assertEqual("maps_observed", result["execution_evidence"]["verification_result"])
        self.assertTrue(result["execution_evidence"]["url_dispatched"])
        self.assertEqual("link_query_dispatched", result["execution_evidence"]["destination_handoff_status"])
        self.assertTrue(result["verification"]["app_observed"])
        self.assertFalse(result["navigation_completed"])
        self.assertNotIn("Kuching", str(result))
        tool_calls = [params["name"] for method, params in client.requests if method == "tools/call"]
        self.assertEqual(["open_url", "describe_screen"], tool_calls)

    def test_denied_permission_blocks_before_mcp_discovery_or_dispatch(self) -> None:
        client = FakeMapsMCPClient()
        denied = PermissionDecision(
            False,
            ("permission_denied",),
            "identity.fixture",
            "ownership.fixture",
            "consent.fixture",
            "execute",
            None,
            IDENTITY_CONSENT_VERSION,
        )
        result = NativeCapabilityBridge(client).execute_maps_link(
            "Kuching Waterfront",
            permission_decision=denied,
            trial_approval_id="approval.maps_trial.v1",
        )
        self.assertEqual("blocked", result["status"])
        self.assertEqual("blocked", result["execution_evidence"]["execution_status"])
        self.assertEqual([], client.requests)

    def test_public_mcp_surface_still_rejects_map_dispatch(self) -> None:
        client = FakeMapsMCPClient()
        with self.assertRaises(MCPExecutionBoundaryError):
            client.call_tool("open_url", {"url": "http://maps.apple.com/?q=Kuching"})
        self.assertEqual([], client.requests)

    def test_safe_verification_never_claims_navigation_completion(self) -> None:
        verification = NativeCapabilityBridge._safe_verification(
            {"kind": "frontmost_app_is", "passed": False, "error_code": "maps_not_observed"}
        )
        self.assertEqual("maps_not_observed", verification["verification_result"])
        self.assertFalse(verification["passed"])
        self.assertFalse(verification["app_observed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
