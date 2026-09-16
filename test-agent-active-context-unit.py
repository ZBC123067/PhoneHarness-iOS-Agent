#!/usr/bin/env python3
"""Static contract tests for TEST-38 Active Context Engine.

These tests create only temporary Mac-hosted metadata. They do not instantiate
an MCP client or contact the iPhone, a model, a Planner, or an Executor.
"""

from __future__ import annotations

import inspect
import json
import stat
import tempfile
import unittest
from pathlib import Path

from phoneharness_agent import (
    ActiveContextEngine,
    ActiveContextPolicyError,
    ActiveContextStateError,
    IdentityConsentFoundation,
    KnowledgeLifecycleEngine,
    LifecycleEligibility,
    PermissionDecision,
    PermissionRequest,
)


OWNER = "context-owner-unit-0001"
OTHER_OWNER = "context-owner-unit-9999"

FORBIDDEN_KEYS = frozenset(
    {
        "goal",
        "conversation",
        "message",
        "content",
        "document",
        "screenshot",
        "coordinate",
        "coordinates",
        "rect",
        "ui",
        "ocr",
        "raw_ax",
        "raw_mcp_response",
        "input",
        "clipboard",
        "password",
        "token",
        "tool_arguments",
        "action_arguments",
        "replay",
    }
)


def keys_in(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(keys_in(item) for item in value.values())) if value else set()
    if isinstance(value, (list, tuple)):
        return set().union(*(keys_in(item) for item in value)) if value else set()
    return set()


class ActiveContextEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name) / "active-context-v1"
        self.engine = ActiveContextEngine(self.root)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def create(self, **overrides: object) -> dict[str, object]:
        values: dict[str, object] = {
            "task_ref": "task.shipping.quote.01",
            "workspace_ref": "workspace.shipping.rate",
            "goal_ref": "goal.handle.01",
            "intent_category": "knowledge_answer",
            "domain_code": "shipping",
            "expiration_policy": "TASK_BOUND",
            "priority": "NORMAL",
            "now": 100,
        }
        values.update(overrides)
        return self.engine.create(OWNER, **values)  # type: ignore[arg-type]

    @staticmethod
    def allowed_permission() -> PermissionDecision:
        return PermissionDecision(
            True,
            ("approved",),
            "person.owner",
            "knowledge.ownership.01",
            "consent.knowledge.read.01",
            "READ",
            None,
            "test-36.0",
        )

    @staticmethod
    def allowed_lifecycle() -> LifecycleEligibility:
        return LifecycleEligibility(True, "ACTIVE", "CLEAR", ("eligible",))

    def test_context_and_task_are_separate_and_private(self) -> None:
        context = self.create()
        raw = (self.root / "contexts-v1.json").read_text(encoding="utf-8")
        persisted = json.loads(raw)

        self.assertEqual("CREATED", context["state"])
        self.assertEqual(1, context["context_version"])
        self.assertEqual("task.shipping.quote.01", context["task_ref"])
        self.assertNotIn("task_id", context)
        self.assertEqual(0o700, stat.S_IMODE(self.root.stat().st_mode))
        self.assertEqual(0o600, stat.S_IMODE((self.root / "contexts-v1.json").stat().st_mode))
        self.assertEqual(0o600, stat.S_IMODE((self.root / ".contexts-v1.json.lock").stat().st_mode))
        self.assertEqual(["contexts", "schema_version"], sorted(persisted))
        self.assertFalse(FORBIDDEN_KEYS.intersection(keys_in(persisted)))
        for forbidden_value in ("raw sensitive goal", "0.5", "screenshot", "private message"):
            self.assertNotIn(forbidden_value, raw)

    def test_state_machine_requires_valid_transitions_and_resume_invalidates_pending_action(self) -> None:
        context = self.create()
        context_id = str(context["context_id"])
        with self.assertRaises(ActiveContextStateError):
            self.engine.complete(context_id, OWNER, now=101)

        active = self.engine.activate(context_id, OWNER, now=101)
        paused = self.engine.pause(context_id, OWNER, now=102)
        resumed = self.engine.resume(context_id, OWNER, now=103)
        completed = self.engine.complete(context_id, OWNER, now=104)
        archived = self.engine.archive(context_id, OWNER, now=105)

        self.assertEqual("ACTIVE", active["state"])
        self.assertEqual("PAUSED", paused["state"])
        self.assertEqual("ACTIVE", resumed["state"])
        self.assertEqual("INVALIDATED", resumed["pending_action_state"])
        self.assertTrue(resumed["fresh_observation_required"])
        self.assertTrue(resumed["fresh_plan_required"])
        self.assertTrue(resumed["fresh_authorization_required"])
        self.assertTrue(resumed["fresh_risk_assessment_required"])
        self.assertEqual(
            ["reobserve", "replan", "reauthorize", "risk_reassess"],
            resumed["resume_requirements"],
        )
        self.assertEqual("COMPLETED", completed["state"])
        self.assertEqual("ARCHIVED", archived["state"])
        with self.assertRaises(ActiveContextStateError):
            self.engine.activate(context_id, OWNER, now=106)

    def test_expiration_policy_is_enforced_without_execution(self) -> None:
        context = self.create(expiration_policy="EPHEMERAL")
        context_id = str(context["context_id"])
        self.engine.activate(context_id, OWNER, now=101)
        expired = self.engine.inspect(context_id, OWNER, now=1000)

        self.assertEqual("EXPIRED", expired["state"])
        self.assertEqual("expiration_elapsed", expired["last_reason_code"])
        with self.assertRaises(ActiveContextStateError):
            self.engine.resume(context_id, OWNER, now=1001)
        self.assertEqual("ARCHIVED", self.engine.archive(context_id, OWNER, now=1002)["state"])

    def test_context_isolation_rejects_cross_workspace_and_cross_domain_references(self) -> None:
        shipping = self.create()
        car = self.create(
            task_ref="task.car.repair.01",
            workspace_ref="workspace.automotive.repair",
            goal_ref="goal.handle.02",
            domain_code="automotive",
        )
        shipping_id = str(shipping["context_id"])
        car_id = str(car["context_id"])

        self.engine.add_entity_reference(shipping_id, OWNER, "entity.shipping.route.01", "shipping", now=101)
        with self.assertRaises(ActiveContextPolicyError):
            self.engine.add_entity_reference(shipping_id, OWNER, "entity.car.vehicle.01", "automotive", now=102)
        with self.assertRaises(ActiveContextPolicyError):
            self.engine.attach_knowledge_reference(
                car_id,
                OWNER,
                knowledge_ref="knowledge.shipping.rate.01",
                workspace_ref="workspace.shipping.rate",
                domain_code="shipping",
                permission=self.allowed_permission(),
                lifecycle=self.allowed_lifecycle(),
                source_class="IMPORTED_DATA",
                confidence=900,
                valid_from=100,
                valid_until=200,
                last_verified=100,
                now=103,
            )

        self.assertEqual(["entity.shipping.route.01"], self.engine.inspect(shipping_id, OWNER, now=104)["entity_refs"])
        self.assertEqual([], self.engine.inspect(car_id, OWNER, now=104)["knowledge_refs"])

    def test_knowledge_admission_requires_permission_and_lifecycle_eligibility(self) -> None:
        context_id = str(self.create()["context_id"])
        attached = self.engine.attach_knowledge_reference(
            context_id,
            OWNER,
            knowledge_ref="knowledge.shipping.rate.01",
            workspace_ref="workspace.shipping.rate",
            domain_code="shipping",
            permission=self.allowed_permission(),
            lifecycle=self.allowed_lifecycle(),
            source_class="IMPORTED_DATA",
            confidence=900,
            valid_from=100,
            valid_until=200,
            last_verified=100,
            now=101,
        )

        self.assertEqual(1, attached["knowledge_reference_count"])
        self.assertEqual(["knowledge.shipping.rate.01"], attached["knowledge_refs"])
        self.assertEqual("ACTIVE", attached["knowledge_metadata"][0]["lifecycle_state"])
        self.assertEqual("CLEAR", attached["knowledge_metadata"][0]["resolution_status"])

        denied_permission = PermissionDecision(
            False, ("consent_revoked",), None, None, None, "READ", None, "test-36.0"
        )
        with self.assertRaises(ActiveContextPolicyError):
            self.engine.attach_knowledge_reference(
                context_id,
                OWNER,
                knowledge_ref="knowledge.shipping.rate.02",
                workspace_ref="workspace.shipping.rate",
                domain_code="shipping",
                permission=denied_permission,
                lifecycle=self.allowed_lifecycle(),
                source_class="IMPORTED_DATA",
                confidence=900,
                valid_from=100,
                valid_until=200,
                last_verified=100,
                now=102,
            )
        with self.assertRaises(ActiveContextPolicyError):
            self.engine.attach_knowledge_reference(
                context_id,
                OWNER,
                knowledge_ref="knowledge.shipping.rate.03",
                workspace_ref="workspace.shipping.rate",
                domain_code="shipping",
                permission=self.allowed_permission(),
                lifecycle=LifecycleEligibility(False, "FORGOTTEN", "CLEAR", ("lifecycle_state_not_active",)),
                source_class="IMPORTED_DATA",
                confidence=900,
                valid_from=100,
                valid_until=200,
                last_verified=100,
                now=103,
            )
        self.assertEqual(1, self.engine.inspect(context_id, OWNER, now=104)["knowledge_reference_count"])

    def test_knowledge_admission_consumes_real_test36_and_test37_eligibility_results(self) -> None:
        foundation = IdentityConsentFoundation(Path(self.temporary_directory.name) / "identity-consent")
        foundation.create_identity(
            identity_id="person.owner",
            identity_kind="PERSONAL",
            claims={"locale": "zh-Hans"},
            confirmed_by_user=True,
            created_at=100,
        )
        foundation.classify_ownership(
            ownership_ref="knowledge.shipping.ownership",
            ownership_class="PERSONAL",
            controlling_identity_id="person.owner",
            confirmed_by_user=True,
            classified_at=101,
        )
        foundation.set_workspace_permissions(
            workspace_ref="workspace.shipping.rate",
            permission_actions=("READ",),
            confirmed_by_user=True,
            recorded_at=102,
        )
        foundation.grant_consent(
            consent_id="consent.shipping.read",
            identity_id="person.owner",
            ownership_ref="knowledge.shipping.ownership",
            purpose_code="knowledge.answer",
            audience_scope="owner_only",
            permission_actions=("READ",),
            consent_uses=("REFERENCE_ONLY",),
            retention_category="until_revoked",
            confirmed_by_user=True,
            created_at=103,
        )
        permission = foundation.resolve_permission(
            PermissionRequest(
                identity_id="person.owner",
                ownership_ref="knowledge.shipping.ownership",
                ownership_class="PERSONAL",
                workspace_ref="workspace.shipping.rate",
                purpose_code="knowledge.answer",
                audience_scope="owner_only",
                action="READ",
                consent_use="REFERENCE_ONLY",
                risk_policy_allows=True,
            ),
            evaluated_at=104,
        )
        lifecycle_engine = KnowledgeLifecycleEngine(Path(self.temporary_directory.name) / "lifecycle")
        object_record = lifecycle_engine.register_object(
            logical_ref="knowledge.shipping.rate.01",
            object_kind="KNOWLEDGE_OBJECT",
            source_ref="source.shipping.rate.01",
            source_version=1,
            source_priority=1,
            field_fingerprint="a" * 64,
            valid_from=100,
            valid_until=200,
            confirmed_by_user=True,
            recorded_at=104,
        )

        attached = self.engine.attach_knowledge_reference(
            str(self.create()["context_id"]),
            OWNER,
            knowledge_ref="knowledge.shipping.rate.01",
            workspace_ref="workspace.shipping.rate",
            domain_code="shipping",
            permission=permission,
            lifecycle=lifecycle_engine.retrieval_eligibility(object_record.object_id, evaluated_at=105),
            source_class="IMPORTED_DATA",
            confidence=900,
            valid_from=100,
            valid_until=200,
            last_verified=104,
            now=105,
        )
        self.assertEqual(1, attached["knowledge_reference_count"])

    def test_snapshot_and_context_bound_trace_are_safe_and_non_replayable(self) -> None:
        context_id = str(self.create()["context_id"])
        self.engine.activate(context_id, OWNER, now=101)
        self.engine.add_entity_reference(context_id, OWNER, "entity.shipping.route.01", "shipping", now=102)
        snapshot = self.engine.create_snapshot(context_id, OWNER, now=103)
        trace = self.engine.trace(context_id, OWNER, now=104)
        serialised = json.dumps([snapshot, trace])

        self.assertEqual(context_id, snapshot["context_id"])
        self.assertEqual("non_replayable_metadata_only", snapshot["action_replay"])
        self.assertEqual(context_id, trace[0]["context_id"])
        self.assertTrue(all("event_type" in event and "context_version" in event for event in trace))
        self.assertFalse(FORBIDDEN_KEYS.intersection(keys_in(json.loads(serialised))))
        self.assertNotIn("task.shipping.quote.01", serialised)

    def test_restart_recovery_creates_only_a_resume_shell_and_never_contacts_mcp(self) -> None:
        context = self.create()
        context_id = str(context["context_id"])
        self.engine.activate(context_id, OWNER, now=101)

        restarted = ActiveContextEngine(self.root)
        recovery = restarted.recover_after_restart(now=102)
        resumed = restarted.resume(context_id, OWNER, now=103)

        self.assertEqual([context_id], recovery["paused_context_ids"])
        self.assertEqual([], recovery["device_actions_sent"])
        self.assertEqual("ACTIVE", resumed["state"])
        self.assertEqual(
            ["reobserve", "replan", "reauthorize", "risk_reassess"],
            resumed["resume_requirements"],
        )
        source = inspect.getsource(ActiveContextEngine)
        self.assertNotIn("MCPClient", source)
        self.assertNotIn("call_tool", source)
        self.assertNotIn("PlanExecutor", source)

    def test_owner_and_private_permission_boundaries_fail_closed(self) -> None:
        context_id = str(self.create()["context_id"])
        with self.assertRaises(ActiveContextPolicyError):
            self.engine.inspect(context_id, OTHER_OWNER, now=101)

        self.engine.activate(context_id, OWNER, now=102)
        path = self.root / "contexts-v1.json"
        path.chmod(0o644)
        with self.assertRaises(OSError):
            self.engine.inspect(context_id, OWNER, now=103)


if __name__ == "__main__":
    unittest.main(verbosity=2)
