#!/usr/bin/env python3
"""Static contract tests for TEST-34 Knowledge Understanding.

Fixtures are synthetic and owner-local.  These tests never contact an iPhone,
call MCP, run a Planner, create a capability, or execute an action.
"""

from __future__ import annotations

import json
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path

from phoneharness_agent import (
    KnowledgeUnderstandingLayer,
    KnowledgeUnderstandingPolicyError,
    PersonalKnowledgeFoundation,
)


FORBIDDEN_KEYS = frozenset(
    {
        "goal",
        "plan",
        "screenshot",
        "coordinate",
        "coordinates",
        "rect",
        "ocr",
        "raw_ax",
        "raw_mcp_response",
        "input",
        "password",
        "private_message",
        "bundle_id",
        "app_identity",
    }
)


def keys_in(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(keys_in(item) for item in value.values())) if value else set()
    if isinstance(value, (list, tuple)):
        return set().union(*(keys_in(item) for item in value)) if value else set()
    return set()


class KnowledgeUnderstandingLayerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name) / "knowledge-v1"
        self.sources = Path(self.temporary_directory.name) / "sources"
        self.sources.mkdir()
        self.foundation = PersonalKnowledgeFoundation(root)
        self.layer = KnowledgeUnderstandingLayer(self.foundation)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def source(self, name: str, payload: bytes) -> Path:
        path = self.sources / name
        path.write_bytes(payload)
        return path

    def import_file(
        self,
        name: str,
        payload: bytes,
        *,
        category: str,
        imported_at: int = 100,
        validity: str = "current",
        valid_until: int | None = None,
    ):
        return self.foundation.import_file(
            self.source(name, payload),
            category=category,
            confidence=0.90,
            priority=2,
            validity=validity,
            valid_until=valid_until,
            confirmed_by_user=True,
            imported_at=imported_at,
        )

    def understand(self, artifact, entity_type: str, timestamp: int = 110):
        return self.layer.understand(
            artifact,
            entity_type=entity_type,
            confirmed_by_user=True,
            processed_at=timestamp,
        )

    def test_rate_entity_keeps_required_governance_and_drops_unrelated_columns(self) -> None:
        artifact = self.import_file(
            "rates.csv",
            b"POL,POD,container,currency,amount,internal_note\nCNSHA,USLAX,40HC,USD,1250,do-not-store-this\n",
            category="business",
        )
        result = self.understand(artifact, "rate")

        self.assertEqual("PUBLISHED", result.status)
        self.assertEqual(1, len(result.entities))
        entity = result.entities[0]
        self.assertEqual(
            {"POL": "CNSHA", "POD": "USLAX", "container": "40HC", "currency": "USD", "amount": "1250", "validity": "current"},
            entity.attributes,
        )
        self.assertEqual("owner_confirmed_file", entity.source)
        self.assertEqual("owner_file", entity.source_type)
        self.assertEqual(0.90, entity.confidence)
        self.assertEqual("current", entity.validity)
        self.assertEqual(1, entity.version)
        self.assertEqual("owner_confirmed", entity.authority)
        self.assertEqual(110, entity.last_verified)
        self.assertEqual(1, len(result.relationships))

        serialized = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (self.foundation._root / "semantic-v1").glob("*.jsonl")
        )
        self.assertNotIn("do-not-store-this", serialized)
        self.assertFalse(FORBIDDEN_KEYS.intersection(keys_in(json.loads(next(iter(serialized.splitlines()))))))

    def test_schedule_customer_and_sop_entities_have_only_their_allowlisted_fields(self) -> None:
        schedule = self.import_file(
            "schedule.json",
            b'{"schedules":[{"vessel":"North Star","voyage":"ns001","POL":"CNSHA","POD":"MYBKI","ETD":"2026-09-01","ETA":"2026-09-05","secret":"ignore"}]}',
            category="business",
        )
        customer = self.import_file(
            "customer.json",
            b'{"company":"Example Logistics","preference":"weekly update","language":"en","communication_style":"concise","private_message":"ignore"}',
            category="customer",
        )
        sop = self.import_file(
            "sop.json",
            b'{"name":"quote review","condition":"new quote","step_count":3,"expected_outcome":"reviewed","raw_ax":"ignore"}',
            category="workflow",
        )

        self.assertEqual("PUBLISHED", self.understand(schedule, "schedule").status)
        self.assertEqual("PUBLISHED", self.understand(customer, "customer", 111).status)
        self.assertEqual("PUBLISHED", self.understand(sop, "sop", 112).status)
        self.assertEqual(
            {"vessel", "voyage", "POL", "POD", "ETD", "ETA"},
            set(self.layer.query("schedule", confirmed_by_user=True, queried_at=113)[0].attributes),
        )
        self.assertEqual(
            {"company", "preference", "language", "communication_style"},
            set(self.layer.query("customer", confirmed_by_user=True, queried_at=113)[0].attributes),
        )
        self.assertEqual(
            {"name", "condition", "step_count", "expected_outcome"},
            set(self.layer.query("sop", confirmed_by_user=True, queried_at=113)[0].attributes),
        )

    def test_rate_xlsx_uses_the_same_normalized_schema_as_csv(self) -> None:
        source = self.sources / "rates.xlsx"
        rows = [
            ["POL", "POD", "container", "currency", "amount"],
            ["CNSHA", "USLAX", "40HC", "USD", "1250.00"],
        ]
        xml_rows = []
        for row_index, values in enumerate(rows, start=1):
            cells = "".join(
                '<c r="%s%d" t="inlineStr"><is><t>%s</t></is></c>' % (chr(ord("A") + column), row_index, value)
                for column, value in enumerate(values)
            )
            xml_rows.append('<row r="%d">%s</row>' % (row_index, cells))
        worksheet = (
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetData>%s</sheetData></worksheet>' % "".join(xml_rows)
        )
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("xl/workbook.xml", "<workbook/>")
            archive.writestr("xl/worksheets/sheet1.xml", worksheet)
        artifact = self.foundation.import_file(
            source,
            category="business",
            confidence=0.90,
            priority=2,
            confirmed_by_user=True,
            imported_at=100,
        )

        result = self.understand(artifact, "rate")
        self.assertEqual("PUBLISHED", result.status)
        self.assertEqual("1250", result.entities[0].attributes["amount"])
        self.assertEqual("CNSHA", result.entities[0].attributes["POL"])

    def test_conflicting_current_rate_is_quarantined_and_does_not_replace_valid_fact(self) -> None:
        first = self.import_file(
            "rate-a.csv", b"POL,POD,container,currency,amount\nCNSHA,USLAX,40HC,USD,1250\n", category="business"
        )
        second = self.import_file(
            "rate-b.csv", b"POL,POD,container,currency,amount\nCNSHA,USLAX,40HC,USD,1300\n", category="business", imported_at=101
        )
        self.assertEqual("PUBLISHED", self.understand(first, "rate").status)
        conflicted = self.understand(second, "rate", 111)

        self.assertEqual("CONFLICTED", conflicted.status)
        self.assertEqual(1, conflicted.conflict_count)
        self.assertEqual((), conflicted.entities)
        current = self.layer.query("rate", confirmed_by_user=True, queried_at=112)
        self.assertEqual(1, len(current))
        self.assertEqual("1250", current[0].attributes["amount"])
        self.assertEqual(1, self.layer.advisory_context()["conflict_count"])

    def test_new_source_version_makes_previous_semantic_entity_stale_until_reunderstood(self) -> None:
        artifact = self.import_file(
            "rates.csv", b"POL,POD,container,currency,amount\nCNSHA,USLAX,40HC,USD,1250\n", category="business"
        )
        self.assertEqual("PUBLISHED", self.understand(artifact, "rate").status)
        updated = self.foundation.update_file(
            artifact.knowledge_id,
            self.source("updated.csv", b"POL,POD,container,currency,amount\nCNSHA,USLAX,40HC,USD,1280\n"),
            confidence=0.95,
            priority=2,
            confirmed_by_user=True,
            imported_at=120,
        )

        self.assertEqual((), self.layer.query("rate", confirmed_by_user=True, queried_at=121))
        refreshed = self.understand(updated, "rate", 122)
        self.assertEqual("PUBLISHED", refreshed.status)
        self.assertEqual("1280", self.layer.query("rate", confirmed_by_user=True, queried_at=123)[0].attributes["amount"])

    def test_expired_and_wrong_category_inputs_are_blocked_and_audited_without_payload_exposure(self) -> None:
        expired = self.import_file(
            "expired.csv",
            b"POL,POD,container,currency,amount\nCNSHA,USLAX,40HC,USD,1250\n",
            category="business",
            validity="expiring",
            valid_until=105,
        )
        wrong_category = self.import_file(
            "personal.csv",
            b"POL,POD,container,currency,amount\nCNSHA,USLAX,40HC,USD,1250\n",
            category="personal",
            imported_at=101,
        )

        self.assertEqual("artifact_validity_is_expired", self.understand(expired, "rate", 106).reason_code)
        self.assertEqual("artifact_category_does_not_match_entity_type", self.understand(wrong_category, "rate", 106).reason_code)
        jobs = self.layer._store.records("jobs")
        self.assertEqual(["BLOCKED", "BLOCKED"], [job["status"] for job in jobs])
        self.assertNotIn("CNSHA", json.dumps(jobs))

    def test_private_semantic_store_permissions_and_poisoned_records_are_rejected(self) -> None:
        artifact = self.import_file(
            "rates.csv", b"POL,POD,container,currency,amount\nCNSHA,USLAX,40HC,USD,1250\n", category="business"
        )
        self.understand(artifact, "rate")
        store_root = self.foundation._root / "semantic-v1"
        self.assertTrue(self.layer._store.private_modes_ok())
        self.assertEqual(0o700, stat.S_IMODE(store_root.stat().st_mode))
        self.assertEqual(0o600, stat.S_IMODE((store_root / "entities-v1.jsonl").stat().st_mode))

        with (store_root / "entities-v1.jsonl").open("a", encoding="utf-8") as handle:
            handle.write('{"screenshot":"must-not-be-used","signature":"not-valid"}\n')
        self.assertEqual(1, len(self.layer.query("rate", confirmed_by_user=True, queried_at=111)))
        (store_root / "entities-v1.jsonl").chmod(0o644)
        with self.assertRaises(KnowledgeUnderstandingPolicyError):
            self.layer.query("rate", confirmed_by_user=True, queried_at=111)

    def test_processing_requires_owner_confirmation_and_has_no_action_interfaces(self) -> None:
        artifact = self.import_file(
            "rates.csv", b"POL,POD,container,currency,amount\nCNSHA,USLAX,40HC,USD,1250\n", category="business"
        )
        with self.assertRaises(KnowledgeUnderstandingPolicyError):
            self.layer.understand(artifact, entity_type="rate", confirmed_by_user=False, processed_at=110)
        prohibited = {
            "execute", "call_tool", "plan", "create_skill", "create_shortcut", "run_workflow", "send_message", "launch_app"
        }
        self.assertTrue(all(not hasattr(self.layer, method) for method in prohibited))
        context = self.layer.advisory_context()
        self.assertEqual("none", context["decision_effect"])
        self.assertEqual("none", context["planner_access"])
        self.assertEqual("none", context["raw_content_access"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
