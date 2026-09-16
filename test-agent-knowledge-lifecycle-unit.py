#!/usr/bin/env python3
"""Static contract tests for TEST-37 Knowledge Lifecycle Engine.

Fixtures contain opaque identifiers and fixed digests only. They never open an
owner document, invoke TEST-33/34/35 retrieval, call MCP, start a Planner, or
perform an action on the phone.
"""

from __future__ import annotations

import json
import stat
import tempfile
import unittest
from pathlib import Path

from phoneharness_agent import KnowledgeLifecycleEngine, KnowledgeLifecyclePolicyError


FORBIDDEN_KEYS = frozenset(
    {
        "content", "payload", "document_text", "source_path", "filename", "screenshot", "coordinate", "rect",
        "ocr", "raw_ax", "raw_mcp_response", "input", "password", "private_message", "goal", "plan",
        "field_fingerprint", "source_ref", "logical_ref", "object_id", "reference_id",
    }
)


def keys_in(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(keys_in(item) for item in value.values())) if value else set()
    if isinstance(value, (list, tuple)):
        return set().union(*(keys_in(item) for item in value)) if value else set()
    return set()


class KnowledgeLifecycleEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name) / "lifecycle-v1"
        self.engine = KnowledgeLifecycleEngine(self.root)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    @staticmethod
    def digest(value: str) -> str:
        return (value * 64)[:64]

    def register(
        self,
        logical_ref: str = "record.alpha",
        *,
        object_kind: str = "KNOWLEDGE_OBJECT",
        source_ref: str = "source.alpha",
        source_version: int = 1,
        source_priority: int = 1,
        fingerprint: str | None = None,
        valid_from: int = 100,
        valid_until: int | None = 200,
        retention_policy_id: str | None = None,
        recorded_at: int = 100,
    ):
        return self.engine.register_object(
            logical_ref=logical_ref,
            object_kind=object_kind,
            source_ref=source_ref,
            source_version=source_version,
            source_priority=source_priority,
            field_fingerprint=fingerprint or self.digest("a"),
            valid_from=valid_from,
            valid_until=valid_until,
            retention_policy_id=retention_policy_id,
            confirmed_by_user=True,
            recorded_at=recorded_at,
        )

    def test_initial_object_has_created_then_active_append_only_state_history(self) -> None:
        obj = self.register()

        self.assertEqual("ACTIVE", obj.state)
        events = [item for item in self.engine._records("state_events") if item["object_id"] == obj.object_id]
        self.assertEqual(["CREATED", "ACTIVE"], [item["to_state"] for item in events])
        self.assertTrue(self.engine.retrieval_eligibility(obj.object_id, evaluated_at=101).eligible)

    def test_updated_is_event_only_and_preserves_version_and_two_time_axes(self) -> None:
        first = self.register(valid_from=100, valid_until=199)

        result = self.engine.ingest_incremental(
            logical_ref="record.alpha",
            object_kind="KNOWLEDGE_OBJECT",
            source_ref="source.alpha",
            source_version=2,
            source_priority=1,
            field_fingerprint=self.digest("b"),
            changed_field_codes=("amount", "validity"),
            valid_from=200,
            valid_until=299,
            confirmed_by_user=True,
            recorded_at=200,
        )

        self.assertEqual("UPDATED", result.status)
        self.assertEqual("STALE", result.predecessor.state)
        self.assertEqual("ACTIVE", result.successor.state)
        self.assertEqual(2, result.successor.version)
        self.assertEqual({"from": 100, "until": 199}, first.valid_time)
        self.assertEqual({"from": 200, "until": 299}, result.successor.valid_time)
        self.assertEqual(100, first.knowledge_time["recorded_at"])
        self.assertEqual(200, result.successor.knowledge_time["recorded_at"])
        transitions = [item["to_state"] for item in self.engine._records("state_events") if item["object_id"] == first.object_id]
        self.assertEqual(["CREATED", "ACTIVE", "UPDATED", "STALE"], transitions)

    def test_unchanged_incremental_update_does_not_create_a_successor(self) -> None:
        original = self.register()

        result = self.engine.ingest_incremental(
            logical_ref="record.alpha",
            object_kind="KNOWLEDGE_OBJECT",
            source_ref="source.alpha",
            source_version=2,
            source_priority=1,
            field_fingerprint=self.digest("a"),
            changed_field_codes=(),
            valid_from=100,
            valid_until=200,
            confirmed_by_user=True,
            recorded_at=110,
        )

        self.assertEqual("UNCHANGED", result.status)
        self.assertEqual(original.object_id, result.predecessor.object_id)
        self.assertIsNone(result.successor)
        self.assertEqual(1, len(self.engine.object_history("record.alpha", evaluated_at=111)))

    def test_partial_snapshot_never_implies_deletion_but_complete_snapshot_stales_absence(self) -> None:
        present = self.register("record.present", source_ref="source.snapshot")
        absent = self.register("record.absent", source_ref="source.snapshot")

        partial = self.engine.reconcile_snapshot(
            source_ref="source.snapshot",
            present_logical_refs=("record.present",),
            complete_snapshot=False,
            confirmed_by_user=True,
            recorded_at=120,
        )
        self.assertEqual(0, partial["staled_count"])
        self.assertEqual("ACTIVE", self.engine.object_history("record.absent", evaluated_at=121)[0].state)

        complete = self.engine.reconcile_snapshot(
            source_ref="source.snapshot",
            present_logical_refs=("record.present",),
            complete_snapshot=True,
            confirmed_by_user=True,
            recorded_at=122,
        )
        self.assertEqual(1, complete["staled_count"])
        self.assertEqual("ACTIVE", self.engine.object_history("record.present", evaluated_at=123)[0].state)
        self.assertEqual("STALE", self.engine.object_history("record.absent", evaluated_at=123)[0].state)
        self.assertTrue(self.engine.retrieval_eligibility(present.object_id, evaluated_at=123).eligible)
        self.assertFalse(self.engine.retrieval_eligibility(absent.object_id, evaluated_at=123).eligible)

    def test_same_priority_source_conflict_blocks_retrieval_without_changing_active_state(self) -> None:
        first = self.register("record.conflict", source_ref="source.one", source_priority=1)

        result = self.engine.ingest_incremental(
            logical_ref="record.conflict",
            object_kind="KNOWLEDGE_OBJECT",
            source_ref="source.two",
            source_version=1,
            source_priority=1,
            field_fingerprint=self.digest("b"),
            changed_field_codes=("amount",),
            valid_from=100,
            valid_until=200,
            confirmed_by_user=True,
            recorded_at=110,
        )

        self.assertEqual("CONFLICTED", result.status)
        first_history = self.engine.object_history("record.conflict", evaluated_at=111)
        self.assertEqual("ACTIVE", first_history[0].state)
        self.assertEqual("CONFLICTED", first_history[0].resolution_status)
        eligibility = self.engine.retrieval_eligibility(first.object_id, evaluated_at=111)
        self.assertFalse(eligibility.eligible)
        self.assertEqual("CONFLICTED", eligibility.resolution_status)
        self.assertIn("lifecycle_conflict_unresolved", eligibility.reason_codes)

        repeated_update = self.engine.ingest_incremental(
            logical_ref="record.conflict",
            object_kind="KNOWLEDGE_OBJECT",
            source_ref="source.two",
            source_version=2,
            source_priority=1,
            field_fingerprint=self.digest("c"),
            changed_field_codes=("amount",),
            valid_from=100,
            valid_until=200,
            confirmed_by_user=True,
            recorded_at=112,
        )
        self.assertEqual("CONFLICTED", repeated_update.status)
        self.assertEqual("CONFLICT_DETECTED", repeated_update.reason_code)

    def test_retention_supports_type_specific_stale_and_archive_without_auto_forgetting(self) -> None:
        self.engine.set_retention_policy(
            policy_id="policy.knowledge",
            object_kind="KNOWLEDGE_OBJECT",
            stale_after_seconds=10,
            archive_after_seconds=20,
            confirmed_by_user=True,
            recorded_at=90,
        )
        obj = self.register(retention_policy_id="policy.knowledge", recorded_at=100)

        stale = self.engine.apply_retention(obj.object_id, evaluated_at=110)
        archived = self.engine.apply_retention(obj.object_id, evaluated_at=120)

        self.assertEqual("STALE", stale.state)
        self.assertEqual("ARCHIVED", archived.state)
        self.assertNotEqual("FORGOTTEN", archived.state)

    def test_forgetting_blocks_future_retrieval_and_revokes_memory_and_experience_references(self) -> None:
        obj = self.register("record.forget")
        self.engine.track_dependency(
            target_object_id=obj.object_id,
            reference_kind="MEMORY_REFERENCE",
            reference_id="memory.ref.one",
            confirmed_by_user=True,
            recorded_at=101,
        )
        self.engine.track_dependency(
            target_object_id=obj.object_id,
            reference_kind="EXPERIENCE_REFERENCE",
            reference_id="experience.ref.one",
            confirmed_by_user=True,
            recorded_at=102,
        )
        self.engine.track_dependency(
            target_object_id=obj.object_id,
            reference_kind="KNOWLEDGE_REFERENCE",
            reference_id="knowledge.ref.one",
            confirmed_by_user=True,
            recorded_at=103,
        )

        result = self.engine.forget_object(obj.object_id, confirmed_by_user=True, recorded_at=104)

        self.assertEqual("FORGOTTEN", result["state"])
        self.assertTrue(result["retrieval_blocked"])
        self.assertEqual(1, result["memory_references_revoked"])
        self.assertEqual(1, result["experience_references_revoked"])
        self.assertTrue(all(item.status == "REVOKED" for item in self.engine.dependencies_for(obj.object_id)))
        self.assertFalse(self.engine.retrieval_eligibility(obj.object_id, evaluated_at=105).eligible)
        with self.assertRaises(KnowledgeLifecyclePolicyError):
            self.engine.archive_object(obj.object_id, confirmed_by_user=True, recorded_at=106)

    def test_forgetting_requires_owner_confirmation(self) -> None:
        obj = self.register()
        with self.assertRaises(KnowledgeLifecyclePolicyError):
            self.engine.forget_object(obj.object_id, confirmed_by_user=False, recorded_at=110)
        self.assertTrue(self.engine.retrieval_eligibility(obj.object_id, evaluated_at=111).eligible)

    def test_lifecycle_audit_is_hmac_chained_and_tampering_fails_closed(self) -> None:
        self.register()
        audit_path = self.root / "audit-v1.jsonl"
        audit_path.write_text(audit_path.read_text(encoding="utf-8").replace("object_created", "tampered_entry"), encoding="utf-8")

        with self.assertRaises(KnowledgeLifecyclePolicyError):
            self.engine.audit_events()

    def test_public_summaries_and_audit_are_private_metadata_only(self) -> None:
        obj = self.register()
        self.engine.track_dependency(
            target_object_id=obj.object_id,
            reference_kind="MEMORY_REFERENCE",
            reference_id="memory.ref.one",
            confirmed_by_user=True,
            recorded_at=101,
        )
        serialised = json.dumps(
            [
                obj.summary(),
                self.engine.retrieval_eligibility(obj.object_id, evaluated_at=102).summary(),
                self.engine.dependencies_for(obj.object_id)[0].summary(),
                self.engine.audit_events(),
                self.engine.advisory_context(),
            ]
        )

        self.assertFalse(FORBIDDEN_KEYS.intersection(keys_in(json.loads(serialised))))
        self.assertNotIn("source.alpha", serialised)
        self.assertNotIn("record.alpha", serialised)
        self.assertNotIn(self.digest("a"), serialised)

    def test_storage_modes_and_invalid_lifecycle_metadata_fail_closed(self) -> None:
        self.register()
        self.assertEqual(0o700, stat.S_IMODE(self.root.stat().st_mode))
        self.assertEqual(0o600, stat.S_IMODE((self.root / "lifecycle-hmac.key").stat().st_mode))
        self.assertEqual(0o600, stat.S_IMODE((self.root / "objects-v1.jsonl").stat().st_mode))
        with self.assertRaises(KnowledgeLifecyclePolicyError):
            self.engine.register_object(
                logical_ref="record.invalid",
                object_kind="KNOWLEDGE_OBJECT",
                source_ref="source.invalid",
                source_version=1,
                source_priority=1,
                field_fingerprint="private source path",
                valid_from=100,
                confirmed_by_user=True,
                recorded_at=100,
            )

    def test_reason_codes_are_bounded_and_complete_snapshot_is_explicit(self) -> None:
        obj = self.register()
        with self.assertRaises(KnowledgeLifecyclePolicyError):
            self.engine._transition(obj.object_id, "STALE", "unapproved_reason", 110)
        with self.assertRaises(KnowledgeLifecyclePolicyError):
            self.engine.reconcile_snapshot(
                source_ref="source.alpha",
                present_logical_refs=(),
                complete_snapshot="yes",  # type: ignore[arg-type]
                confirmed_by_user=True,
                recorded_at=111,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
