#!/usr/bin/env python3
"""TDD coverage for the P3 build identity and package evidence contract."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent
MODULE_PATH = ROOT / "scripts" / "build_identity.py"
SPEC = importlib.util.spec_from_file_location("phoneharness_build_identity", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class BuildIdentityTests(unittest.TestCase):
    def make_root(self) -> tuple[tempfile.TemporaryDirectory[str], Path, Path]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        (root / "control").write_text(
            "Package: com.example.phoneharness\nVersion: 1.0.0\nArchitecture: iphoneos-arm64e\n",
            encoding="utf-8",
        )
        (root / "Makefile").write_text("TWEAK_NAME = example\n", encoding="utf-8")
        (root / "MCPServer.m").write_text("int example = 1;\n", encoding="utf-8")
        return temporary, root, root / "control"

    def make_deb(self, root: Path, *, version: str = "1.0.0") -> Path:
        if shutil.which("dpkg-deb") is None:
            self.skipTest("dpkg-deb is unavailable")
        package_root = root / "debroot"
        (package_root / "DEBIAN").mkdir(parents=True, exist_ok=True)
        (package_root / "DEBIAN" / "control").write_text(
            "Package: com.example.phoneharness\nVersion: %s\nArchitecture: iphoneos-arm64e\nDescription: test\n" % version,
            encoding="utf-8",
        )
        package = root / "test.deb"
        subprocess.run(["dpkg-deb", "-b", str(package_root), str(package)], check=True, capture_output=True)
        return package

    def test_staged_identity_is_safe_deterministic_schema(self) -> None:
        temporary, root, control = self.make_root()
        self.addCleanup(temporary.cleanup)
        identity = MODULE.staged_identity(root, control, "roothide", "iphone:clang:latest:15.0", ["p2-visual"])
        self.assertEqual(MODULE.BUILD_IDENTITY_SCHEMA, identity["schema"])
        self.assertRegex(identity["build_id"], r"^phb-[0-9a-f]{24}$")
        self.assertEqual("NOT_BOUND", identity["build_target"]["target_device_profile"])
        self.assertEqual(["p2-visual"], identity["feature_flags"])
        encoded = json.dumps(identity, sort_keys=True)
        for forbidden in (str(root), "MCPServer.m", "int example"):
            self.assertNotIn(forbidden, encoded)

    def test_git_clean_status_is_not_reported_unavailable(self) -> None:
        temporary, root, control = self.make_root()
        self.addCleanup(temporary.cleanup)
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "add", "control", "Makefile", "MCPServer.m"], check=True)
        subprocess.run(
            ["git", "-C", str(root), "-c", "user.name=PhoneHarness", "-c", "user.email=test@example.invalid", "commit", "-qm", "baseline"],
            check=True,
        )
        identity = MODULE.staged_identity(root, control, "roothide", "target", [])
        self.assertEqual("CLEAN", identity["source"]["working_tree_status"])

    def test_feature_flags_and_control_require_safe_input(self) -> None:
        temporary, root, control = self.make_root()
        self.addCleanup(temporary.cleanup)
        with self.assertRaises(MODULE.BuildIdentityError):
            MODULE.sanitized_feature_flags("safe,inject\\nvalue")
        control.write_text("Package: incomplete\n", encoding="utf-8")
        with self.assertRaises(MODULE.BuildIdentityError):
            MODULE.staged_identity(root, control, "roothide", "target", [])

    def test_finalized_evidence_binds_deb_digest_and_baseline(self) -> None:
        temporary, root, control = self.make_root()
        self.addCleanup(temporary.cleanup)
        identity = MODULE.staged_identity(root, control, "roothide", "target", [])
        package = self.make_deb(root)
        evidence = MODULE.finalized_evidence(
            identity,
            package,
            {
                "static": {"status": "PASS", "count": 1},
                "unit": {"status": "PASS", "count": 3},
                "regression": {"status": "PASS", "count": 42},
            },
        )
        self.assertEqual(MODULE.BUILD_EVIDENCE_SCHEMA, evidence["schema"])
        self.assertEqual(identity["build_id"], evidence["build_id"])
        self.assertEqual(MODULE.sha256_file(package), evidence["package"]["sha256"])
        self.assertEqual("NOT_BOUND", evidence["device_validation"]["status"])

    def test_finalization_rejects_package_mismatch_and_invalid_baseline(self) -> None:
        temporary, root, control = self.make_root()
        self.addCleanup(temporary.cleanup)
        identity = MODULE.staged_identity(root, control, "roothide", "target", [])
        package = self.make_deb(root)
        identity["package"]["version"] = "2.0.0"
        with self.assertRaises(MODULE.BuildIdentityError):
            MODULE.finalized_evidence(identity, package, {"static": {}, "unit": {}, "regression": {}})

    def test_finalization_rejects_architecture_mismatch(self) -> None:
        temporary, root, control = self.make_root()
        self.addCleanup(temporary.cleanup)
        identity = MODULE.staged_identity(root, control, "roothide", "target", [])
        package = self.make_deb(root)
        identity["package"]["declared_architecture"] = "iphoneos-arm"
        with self.assertRaises(MODULE.BuildIdentityError):
            MODULE.finalized_evidence(
                identity,
                package,
                {key: {"status": "PASS", "count": 1} for key in ("static", "unit", "regression")},
            )

    def test_finalization_accepts_only_theos_derived_debian_version_suffix(self) -> None:
        temporary, root, control = self.make_root()
        self.addCleanup(temporary.cleanup)
        identity = MODULE.staged_identity(root, control, "roothide", "target", [])
        evidence = MODULE.finalized_evidence(
            identity,
            self.make_deb(root, version="1.0.0-1+debug"),
            {key: {"status": "PASS", "count": 1} for key in ("static", "unit", "regression")},
        )
        self.assertEqual("1.0.0-1+debug", evidence["package"]["version"])
        with self.assertRaises(MODULE.BuildIdentityError):
            MODULE.finalized_evidence(
                identity,
                self.make_deb(root, version="1.0.1-1+debug"),
                {key: {"status": "PASS", "count": 1} for key in ("static", "unit", "regression")},
            )

    def test_atomic_output_and_schema_rejection(self) -> None:
        temporary, root, control = self.make_root()
        self.addCleanup(temporary.cleanup)
        output = root / "evidence" / "identity.json"
        identity = MODULE.staged_identity(root, control, "roothide", "target", [])
        MODULE.atomic_json_write(output, identity)
        self.assertEqual(identity["build_id"], MODULE.read_json(output)["build_id"])
        self.assertEqual(0o644, output.stat().st_mode & 0o777)
        with self.assertRaises(MODULE.BuildIdentityError):
            MODULE.require_staged_identity({"schema": MODULE.BUILD_IDENTITY_SCHEMA})

    def test_device_binding_preserves_package_and_baseline_without_private_data(self) -> None:
        temporary, root, control = self.make_root()
        self.addCleanup(temporary.cleanup)
        identity = MODULE.staged_identity(root, control, "roothide", "target", [])
        package = self.make_deb(root)
        evidence = MODULE.finalized_evidence(
            identity,
            package,
            {
                "static": {"status": "PASS", "count": 7},
                "unit": {"status": "PASS", "count": 6},
                "regression": {"status": "PASS", "count": 43},
            },
        )
        device_record = MODULE.device_evidence(
            evidence,
            "iPhone15Pro-iOS17.0-RootHide-ElleKit",
            "P3BuildIdentity",
            "PASS",
            "DEVICE_PASS",
            ["package-installed", "manifest-matched"],
        )
        self.assertEqual(evidence["package"], device_record["package"])
        self.assertEqual(evidence["test_baseline"], device_record["test_baseline"])
        self.assertEqual("DEVICE_PASS", device_record["device_validation"]["classification"])
        self.assertNotIn(str(root), json.dumps(device_record, sort_keys=True))

    def test_device_binding_rejects_ambiguous_or_private_inputs(self) -> None:
        temporary, root, control = self.make_root()
        self.addCleanup(temporary.cleanup)
        identity = MODULE.staged_identity(root, control, "roothide", "target", [])
        evidence = MODULE.finalized_evidence(
            identity,
            self.make_deb(root),
            {key: {"status": "PASS", "count": 1} for key in ("static", "unit", "regression")},
        )
        with self.assertRaises(MODULE.BuildIdentityError):
            MODULE.device_evidence(evidence, "iPhone15Pro", "P3", "PASS", "ENVIRONMENT_ISSUE", ["installed"])
        with self.assertRaises(MODULE.BuildIdentityError):
            MODULE.device_evidence(evidence, "iPhone15Pro", "P3", "NOT_RUN", "FUNCTIONAL_FAILURE", ["wait"])
        with self.assertRaises(MODULE.BuildIdentityError):
            MODULE.device_evidence(evidence, "iPhone15Pro", "P3", "FAIL", "FUNCTIONAL_FAILURE", ["private text"])

    def test_makefile_stages_the_exact_identity_manifest(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        self.assertIn("scripts/build_identity.py stage", makefile)
        self.assertIn("BUILD_IDENTITY.json", makefile)
        self.assertIn("p3-build-identity", makefile)


if __name__ == "__main__":
    unittest.main(verbosity=2)
