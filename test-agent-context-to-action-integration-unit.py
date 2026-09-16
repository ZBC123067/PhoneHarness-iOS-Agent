#!/usr/bin/env python3
"""Focused contracts for governed rich-context to installed-app launch.

These tests are host-only.  They exercise the new integration boundary without
contacting a real device.  The separate focused device gate is the only source
of a Context-to-Action DEVICE_PASS claim.
"""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

from phoneharness_agent import (
    ActionObligationLedger,
    BoundInstalledAppLaunchBridge,
    ContextItem,
    ContextReferenceResolver,
    IDENTITY_CONSENT_VERSION,
    MCPCallError,
    MCPClient,
    PermissionDecision,
    ReferenceResolutionRequest,
)


TASK_SCOPE = "task.contextaction.001"
WORKSPACE_SCOPE = "workspace.contextaction.001"


class FakeContextToActionMCPClient(MCPClient):
    """Private fixture transport; public outcomes must not expose app identity."""

    def __init__(self, apps: list[dict[str, str]], *, observe_launch: bool = True) -> None:
        super().__init__("http://unused.invalid")
        self._apps = apps
        self._observe_launch = observe_launch
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
            return {"structuredContent": {"accepted": True}}
        if tool == "describe_screen":
            bundle_id = self._launched_bundle if self._observe_launch else "example.other"
            return {
                "structuredContent": {
                    "frontmost": {"name": "Fixture", "bundleId": bundle_id},
                    "element_count": 1,
                    "source": "AX",
                    "elements": [{"text": "Ready", "clickable": False}],
                }
            }
        raise AssertionError("unexpected MCP tool")


def permission(eligible: bool = True) -> PermissionDecision:
    return PermissionDecision(
        eligible,
        ("fixture_eligible",) if eligible else ("fixture_denied",),
        "identity.fixture",
        "ownership.fixture",
        "consent.fixture",
        "execute",
        None,
        IDENTITY_CONSENT_VERSION,
    )


def tool_calls(client: FakeContextToActionMCPClient) -> list[str]:
    return [str(params.get("name")) for method, params in client.requests if method == "tools/call"]


class ContextToActionIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.client = FakeContextToActionMCPClient(
            [{"name": "Fixture App", "bundle_id": "example.fixture"}]
        )
        self.bridge = BoundInstalledAppLaunchBridge(
            self.client,
            action_obligation_ledger=ActionObligationLedger(Path(self.directory.name)),
        )
        self.resolver = ContextReferenceResolver()

    def current_app_context(self, *, now: int | None = None) -> ContextItem:
        return self.bridge.establish_context_application(
            "Fixture App",
            task_scope=TASK_SCOPE,
            workspace_scope=WORKSPACE_SCOPE,
            now=now,
        )

    def recent_application_resolution(self, item: ContextItem, *, now: int | None = None, risk_level: str = "LOW") -> dict[str, Any]:
        return self.resolver.resolve(
            ReferenceResolutionRequest(
                reference_kind="RECENT_APPLICATION",
                task_scope=TASK_SCOPE,
                workspace_scope=WORKSPACE_SCOPE,
                risk_level=risk_level,
            ),
            [item],
            now=now,
        )

    def test_unique_context_reference_reuses_test49_governed_launch_chain(self) -> None:
        item = self.current_app_context()
        resolution = self.recent_application_resolution(item)
        result = self.bridge.execute_resolved_context_application(
            resolution,
            task_scope=TASK_SCOPE,
            workspace_scope=WORKSPACE_SCOPE,
            permission_decision=permission(),
            trial_approval_id="approval.context_to_action.v1",
        )

        self.assertEqual("RESOLVED", resolution["status"])
        self.assertEqual("application", resolution["resolved_type"])
        self.assertEqual("verified", result["status"])
        self.assertEqual("VERIFIED", result["action_obligation"]["state"])
        self.assertEqual("bound_app_observed", result["verification"]["verification_result"])
        self.assertEqual(["list_apps", "launch_app", "describe_screen"], tool_calls(self.client))
        rendered = repr((item, resolution, result))
        self.assertNotIn("Fixture App", rendered)
        self.assertNotIn("example.fixture", rendered)

    def test_ambiguous_context_never_reaches_planner_or_executor(self) -> None:
        first = self.current_app_context()
        current_time = int(time.time())
        second = ContextItem(
            item_id="context.item.second",
            context_type="app",
            semantic_kind="APPLICATION",
            semantic_ref="app.context.second",
            source="ACTIVE_CONTEXT",
            authority="CONTEXT_BOUND",
            observed_at=current_time,
            expires_at=current_time + 30,
            confidence=1000,
            verification_status="VERIFIED",
            permission_scope=("REFERENCE", "PLAN"),
            task_scope=TASK_SCOPE,
            workspace_scope=WORKSPACE_SCOPE,
        )
        resolution = self.resolver.resolve(
            ReferenceResolutionRequest(
                reference_kind="RECENT_APPLICATION",
                task_scope=TASK_SCOPE,
                workspace_scope=WORKSPACE_SCOPE,
            ),
            [first, second],
            now=current_time,
        )
        result = self.bridge.execute_resolved_context_application(
            resolution,
            task_scope=TASK_SCOPE,
            workspace_scope=WORKSPACE_SCOPE,
            permission_decision=permission(),
            trial_approval_id="approval.context_to_action.v1",
        )

        self.assertEqual("AMBIGUOUS", resolution["status"])
        self.assertEqual("blocked", result["status"])
        self.assertEqual("context_reference_not_resolved", result["retry_repair_handoff"]["reason"])
        self.assertEqual(["list_apps"], tool_calls(self.client))

    def test_stale_context_requires_fresh_observation_not_replay(self) -> None:
        item = self.current_app_context(now=1_000)
        resolution = self.recent_application_resolution(item, now=1_030)
        result = self.bridge.execute_resolved_context_application(
            resolution,
            task_scope=TASK_SCOPE,
            workspace_scope=WORKSPACE_SCOPE,
            permission_decision=permission(),
            trial_approval_id="approval.context_to_action.v1",
        )

        self.assertEqual("STALE", resolution["status"])
        self.assertEqual("blocked", result["status"])
        self.assertEqual("context_reference_not_resolved", result["retry_repair_handoff"]["reason"])
        self.assertNotIn("launch_app", tool_calls(self.client))

    def test_cross_task_context_is_rejected_without_launch(self) -> None:
        item = self.current_app_context()
        resolution = self.resolver.resolve(
            ReferenceResolutionRequest(
                reference_kind="RECENT_APPLICATION",
                task_scope="task.contextaction.other",
                workspace_scope=WORKSPACE_SCOPE,
            ),
            [item],
            now=1_001,
        )
        result = self.bridge.execute_resolved_context_application(
            resolution,
            task_scope="task.contextaction.other",
            workspace_scope=WORKSPACE_SCOPE,
            permission_decision=permission(),
            trial_approval_id="approval.context_to_action.v1",
        )

        self.assertEqual("NEEDS_CLARIFICATION", resolution["status"])
        self.assertEqual("blocked", result["status"])
        self.assertNotIn("launch_app", tool_calls(self.client))

    def test_untrusted_visual_and_high_risk_pronoun_never_gain_launch_authority(self) -> None:
        current_time = int(time.time())
        visual = ContextItem(
            item_id="context.item.visual",
            context_type="visual",
            semantic_kind="APPLICATION",
            semantic_ref="app.context.visual",
            source="VISUAL",
            authority="UNTRUSTED",
            observed_at=current_time,
            expires_at=current_time + 30,
            confidence=990,
            verification_status="UNVERIFIED",
            permission_scope=("REFERENCE",),
            task_scope=TASK_SCOPE,
            workspace_scope=WORKSPACE_SCOPE,
            trusted=False,
        )
        visual_resolution = self.recent_application_resolution(visual)
        high_risk_resolution = self.recent_application_resolution(self.current_app_context(), risk_level="HIGH")

        self.assertEqual("NEEDS_CLARIFICATION", visual_resolution["status"])
        self.assertIn("untrusted_context_excluded", visual_resolution["reason_codes"])
        self.assertEqual("NEEDS_CLARIFICATION", high_risk_resolution["status"])
        self.assertIn("high_consequence_identity_not_verified", high_risk_resolution["reason_codes"])
        self.assertNotIn("launch_app", tool_calls(self.client))

    def test_permission_rejection_keeps_resolved_context_non_executable(self) -> None:
        item = self.current_app_context()
        resolution = self.recent_application_resolution(item)
        result = self.bridge.execute_resolved_context_application(
            resolution,
            task_scope=TASK_SCOPE,
            workspace_scope=WORKSPACE_SCOPE,
            permission_decision=permission(False),
            trial_approval_id="approval.context_to_action.v1",
        )

        self.assertEqual("blocked", result["status"])
        self.assertEqual("permission_denied", result["retry_repair_handoff"]["reason"])
        self.assertEqual(["list_apps"], tool_calls(self.client))

    def test_context_reference_is_consumed_and_cannot_replay_a_launch(self) -> None:
        item = self.current_app_context()
        resolution = self.recent_application_resolution(item)
        first = self.bridge.execute_resolved_context_application(
            resolution,
            task_scope=TASK_SCOPE,
            workspace_scope=WORKSPACE_SCOPE,
            permission_decision=permission(),
            trial_approval_id="approval.context_to_action.v1",
        )
        second = self.bridge.execute_resolved_context_application(
            resolution,
            task_scope=TASK_SCOPE,
            workspace_scope=WORKSPACE_SCOPE,
            permission_decision=permission(),
            trial_approval_id="approval.context_to_action.v1",
        )

        self.assertEqual("verified", first["status"])
        self.assertEqual("blocked", second["status"])
        self.assertEqual("context_reference_not_resolved", second["retry_repair_handoff"]["reason"])
        self.assertEqual(["list_apps", "launch_app", "describe_screen"], tool_calls(self.client))


if __name__ == "__main__":
    unittest.main(verbosity=2)
