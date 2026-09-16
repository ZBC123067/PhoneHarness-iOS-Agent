#!/usr/bin/env python3
"""Static privacy, import, and governance tests for TEST-33.

Every fixture is synthetic and lives in a temporary owner-local directory.
These tests never contact an iPhone, retrieve imported content, plan a task,
call MCP, or create/run a Skill, Shortcut, or Workflow.
"""

from __future__ import annotations

import json
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path

from phoneharness_agent import (
    PERSONAL_KNOWLEDGE_VERSION,
    PersonalKnowledgeFoundation,
    PersonalKnowledgePolicyError,
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
        "app_identity",
        "bundle_id",
        "path",
        "filename",
        "content_fingerprint",
        "knowledge_id",
    }
)


def keys_in(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(keys_in(item) for item in value.values())) if value else set()
    if isinstance(value, (list, tuple)):
        return set().union(*(keys_in(item) for item in value)) if value else set()
    return set()


class PersonalKnowledgeFoundationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name) / "knowledge-v1"
        self.source_dir = Path(self.temporary_directory.name) / "sources"
        self.source_dir.mkdir()
        self.foundation = PersonalKnowledgeFoundation(self.root)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def source(self, name: str, payload: bytes) -> Path:
        path = self.source_dir / name
        path.write_bytes(payload)
        return path

    def import_csv(self, *, category: str = "business", timestamp: int = 100):
        return self.foundation.import_file(
            self.source("fixture.csv", b"route,days\nexample,3\n"),
            category=category,
            confidence=0.90,
            priority=2,
            confirmed_by_user=True,
            imported_at=timestamp,
        )

    def test_profile_import_keeps_raw_values_inside_the_private_vault(self) -> None:
        artifact = self.foundation.import_personal_profile(
            {"identity": "Avery Example", "job": "operations", "languages": ["en", "zh"]},
            confidence=0.80,
            priority=3,
            confirmed_by_user=True,
            imported_at=10,
        )
        context = self.foundation.advisory_context()
        serialized = json.dumps(context, ensure_ascii=False)
        self.assertEqual("profile_json", artifact.content_format)
        self.assertIn(artifact.knowledge_id, "".join(item.name for item in (self.root / "artifacts").iterdir()))
        self.assertNotIn("Avery Example", serialized)
        self.assertNotIn("operations", serialized)
        self.assertFalse(FORBIDDEN_KEYS.intersection(keys_in(context)))
        self.assertEqual(0o700, stat.S_IMODE(self.root.stat().st_mode))
        self.assertEqual(0o700, stat.S_IMODE((self.root / "artifacts").stat().st_mode))
        self.assertEqual(0o600, stat.S_IMODE((self.root / "catalog-v1.jsonl").stat().st_mode))
        self.assertEqual(0o600, stat.S_IMODE((self.root / "catalog-hmac.key").stat().st_mode))

    def test_supported_file_formats_have_only_structural_classification(self) -> None:
        xlsx = self.source("fixture.xlsx", b"")
        with zipfile.ZipFile(xlsx, "w") as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("xl/workbook.xml", "<workbook/>")
            archive.writestr("xl/worksheets/sheet1.xml", "<worksheet/>")
        fixtures = {
            "fixture.csv": (b"header\nvalue\n", "tabular", 2),
            "fixture.json": (b'{"policy":"synthetic"}', "document", 1),
            "fixture.md": (b"# Synthetic\nRule\n", "document", 3),
            "fixture.txt": (b"Synthetic text", "document", 1),
            "fixture.pdf": (b"%PDF-1.4\n/Type /Page\n", "pdf", 1),
            "fixture.xls": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1synthetic", "workbook", 1),
        }
        artifacts = [
            self.foundation.import_file(
                self.source(name, payload),
                category="business",
                confidence=0.75,
                priority=1,
                confirmed_by_user=True,
                imported_at=20 + index,
            )
            for index, (name, (payload, _, _)) in enumerate(fixtures.items())
        ]
        artifacts.append(
            self.foundation.import_file(
                xlsx,
                category="business",
                confidence=0.75,
                priority=1,
                confirmed_by_user=True,
                imported_at=30,
            )
        )
        normalized_formats = {"md": "markdown", "txt": "text"}
        expected = {
            (normalized_formats.get(name.rsplit(".", 1)[1], name.rsplit(".", 1)[1]), structure, count)
            for name, (_, structure, count) in fixtures.items()
        }
        expected.add(("xlsx", "workbook", 1))
        actual = {(artifact.content_format, artifact.structure_type, artifact.structure_count) for artifact in artifacts}
        self.assertEqual(expected, actual)

    def test_all_knowledge_categories_are_governed_without_content_exposure(self) -> None:
        for index, category in enumerate(sorted(PersonalKnowledgeFoundation.CATEGORIES)):
            self.foundation.import_file(
                self.source("%s-%d.txt" % (category, index), b"synthetic"),
                category=category,
                confidence=0.50,
                priority=0,
                confirmed_by_user=True,
                imported_at=40 + index,
            )
        context = self.foundation.advisory_context()
        self.assertEqual(
            {category: 1 for category in sorted(PersonalKnowledgeFoundation.CATEGORIES)},
            context["knowledge_counts"]["by_category"],
        )
        self.assertEqual("none", context["raw_content_access"])
        self.assertFalse(FORBIDDEN_KEYS.intersection(keys_in(context)))

    def test_governance_metadata_includes_required_fields_and_validity(self) -> None:
        artifact = self.foundation.import_file(
            self.source("schedule.csv", b"service,eta\nsynthetic,3\n"),
            category="business",
            confidence=0.95,
            priority=3,
            confirmed_by_user=True,
            validity="expiring",
            valid_until=200,
            imported_at=100,
        )
        summary = artifact.metadata_summary()
        self.assertEqual(
            {
                "category",
                "source",
                "source_type",
                "content_format",
                "structure_type",
                "structure_count",
                "imported_at",
                "valid_from",
                "validity",
                "valid_until",
                "confidence",
                "priority",
                "version",
            },
            set(summary),
        )
        self.assertEqual("owner_confirmed_file", summary["source"])
        self.assertEqual(100, summary["imported_at"])
        self.assertEqual(200, summary["valid_until"])
        self.assertEqual("expiring", summary["validity"])
        self.assertEqual(1, summary["version"])

    def test_profile_update_is_versioned_and_context_exposes_only_latest_metadata(self) -> None:
        initial = self.foundation.import_personal_profile(
            {"company": "First Synthetic Company"},
            confidence=0.70,
            priority=1,
            confirmed_by_user=True,
            imported_at=110,
        )
        updated = self.foundation.update_personal_profile(
            initial.knowledge_id,
            {"company": "Second Synthetic Company"},
            confidence=0.90,
            priority=2,
            confirmed_by_user=True,
            imported_at=120,
        )
        context = self.foundation.advisory_context()
        self.assertEqual(initial.knowledge_id, updated.knowledge_id)
        self.assertEqual(2, updated.version)
        self.assertEqual(1, len(context["governed_artifacts"]))
        self.assertEqual(2, context["governed_artifacts"][0]["version"])
        self.assertNotIn("First Synthetic Company", json.dumps(context))
        self.assertNotIn("Second Synthetic Company", json.dumps(context))
        self.assertEqual(2, len(self.foundation._records()))

    def test_file_update_preserves_handle_and_uses_append_only_versions(self) -> None:
        initial = self.import_csv(timestamp=130)
        source = self.source("replacement.csv", b"route,days\nnew,4\n")
        updated = self.foundation.update_file(
            initial.knowledge_id,
            source,
            confidence=0.80,
            priority=2,
            confirmed_by_user=True,
            imported_at=140,
        )
        records = self.foundation._records()
        latest = self.foundation._latest_record(initial.knowledge_id)
        self.assertEqual(initial.knowledge_id, updated.knowledge_id)
        self.assertEqual(2, updated.version)
        self.assertEqual(1, latest["supersedes_version"])
        self.assertEqual([1, 2], sorted(record["version"] for record in records))

    def test_confirmation_schema_and_malformed_files_are_rejected(self) -> None:
        with self.assertRaises(PersonalKnowledgePolicyError):
            self.foundation.import_personal_profile(
                {"identity": "synthetic"}, confidence=0.5, priority=0, confirmed_by_user=False
            )
        with self.assertRaises(PersonalKnowledgePolicyError):
            self.foundation.import_personal_profile(
                {"password": "no"}, confidence=0.5, priority=0, confirmed_by_user=True
            )
        with self.assertRaises(PersonalKnowledgePolicyError):
            self.foundation.import_file(
                self.source("invalid.json", b"{"),
                category="business",
                confidence=0.5,
                priority=0,
                confirmed_by_user=True,
            )
        with self.assertRaises(PersonalKnowledgePolicyError):
            self.foundation.import_file(
                self.source("invalid.pdf", b"not a pdf"),
                category="business",
                confidence=0.5,
                priority=0,
                confirmed_by_user=True,
            )
        with self.assertRaises(PersonalKnowledgePolicyError):
            self.foundation.import_file(
                self.source("unsupported.bin", b"synthetic"),
                category="business",
                confidence=0.5,
                priority=0,
                confirmed_by_user=True,
            )

    def test_poisoned_catalog_record_is_ignored(self) -> None:
        self.foundation._ensure_private_vault()
        poisoned = {
            "schema_version": "6.0",
            "knowledge_version": "test-33.0",
            "record_id": "poisoned",
            "recorded_at": 1,
            "record_type": "knowledge_artifact",
            "write_boundary": "explicit_user_import",
            "knowledge_id": "11111111-1111-1111-1111-111111111111",
            "category": "business",
            "source": "owner_confirmed_file",
            "source_type": "owner_file",
            "content_format": "csv",
            "structure_type": "tabular",
            "structure_count": 1,
            "content_fingerprint": "0" * 64,
            "byte_size": 1,
            "imported_at": 1,
            "valid_from": 1,
            "validity": "current",
            "valid_until": None,
            "confidence": 0.5,
            "priority": 0,
            "version": 1,
            "supersedes_version": None,
            "screenshot": "must-not-be-read",
        }
        with self.foundation._catalog_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(poisoned) + "\n")
        context = self.foundation.advisory_context()
        self.assertEqual([], context["governed_artifacts"])

    def test_broad_permissions_are_rejected_before_catalog_read(self) -> None:
        self.import_csv(timestamp=150)
        original_mode = stat.S_IMODE(self.foundation._catalog_path.stat().st_mode)
        self.foundation._catalog_path.chmod(0o644)
        with self.assertRaises(PersonalKnowledgePolicyError):
            self.foundation.advisory_context()
        self.foundation._catalog_path.chmod(original_mode)

    def test_foundation_has_no_retrieval_execution_or_automation_interface(self) -> None:
        prohibited_methods = {
            "read_content",
            "search",
            "retrieve",
            "execute",
            "call_tool",
            "plan",
            "create_skill",
            "create_shortcut",
            "run_workflow",
            "send_message",
        }
        self.assertTrue(all(not hasattr(self.foundation, method) for method in prohibited_methods))
        context = self.foundation.advisory_context()
        self.assertEqual(PERSONAL_KNOWLEDGE_VERSION, context["personal_knowledge_version"])
        self.assertEqual("governance_only", context["mode"])
        self.assertEqual("none", context["decision_effect"])
        self.assertEqual("none", context["planner_access"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
