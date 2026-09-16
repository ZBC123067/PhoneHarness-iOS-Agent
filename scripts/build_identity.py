#!/usr/bin/env python3
"""Generate privacy-safe PhoneHarness build identity and package evidence.

The staged identity is bundled with a package before its digest exists. The
separate finalized evidence record then binds that identity to the completed
`.deb` digest and test baseline. Neither record stores source contents, device
identifiers, user data, or device observations.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


BUILD_IDENTITY_SCHEMA = "phoneharness.build-identity.v1"
BUILD_EVIDENCE_SCHEMA = "phoneharness.build-evidence.v1"
DEVICE_EVIDENCE_SCHEMA = "phoneharness.device-evidence.v1"
MAX_FEATURE_FLAGS = 32
FEATURE_FLAG_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
CONTROL_FIELD_PATTERN = re.compile(r"^([A-Za-z][A-Za-z0-9-]*):\s*(.*)$")
SAFE_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,95}")
THEOS_DERIVED_VERSION_SUFFIX = re.compile(r"[0-9]+(?:\+[A-Za-z0-9.+~_-]+)?$")
EXCLUDED_PARTS = frozenset(
    {".git", ".theos", "packages", "__pycache__", "backups", "evidence", "outputs", ".codex"}
)


class BuildIdentityError(ValueError):
    """Raised when safe build provenance cannot be established."""


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.exists() and path.is_symlink():
        raise BuildIdentityError("refusing symbolic-link output")
    encoded = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    temporary = path.parent / (".%s.%d.tmp" % (path.name, os.getpid()))
    try:
        with temporary.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BuildIdentityError("build identity is unreadable") from error
    if not isinstance(payload, dict):
        raise BuildIdentityError("build identity must be an object")
    return payload


def parse_control(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise BuildIdentityError("control metadata is unreadable") from error
    fields: dict[str, str] = {}
    for line in lines:
        match = CONTROL_FIELD_PATTERN.match(line)
        if match:
            fields[match.group(1)] = match.group(2).strip()
    required = ("Package", "Version", "Architecture")
    if any(not fields.get(key) for key in required):
        raise BuildIdentityError("control metadata is incomplete")
    return fields


def sanitized_feature_flags(raw: str) -> list[str]:
    values = []
    for candidate in (part.strip().lower() for part in raw.split(",")):
        if not candidate:
            continue
        if FEATURE_FLAG_PATTERN.fullmatch(candidate) is None:
            raise BuildIdentityError("feature flags must be safe identifiers")
        values.append(candidate)
    if len(values) > MAX_FEATURE_FLAGS:
        raise BuildIdentityError("too many feature flags")
    return sorted(set(values))


def tracked_source_digest(root: Path) -> tuple[str, int]:
    """Hash safe source inputs without preserving file names or source contents."""

    digest = hashlib.sha256()
    count = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink() or EXCLUDED_PARTS.intersection(path.relative_to(root).parts):
            continue
        relative = path.relative_to(root).as_posix()
        if relative.startswith(("docs/", "testdata/")) or path.suffix in {".bak", ".save"}:
            continue
        if path.name.endswith(".backup") or ".before-" in path.name:
            continue
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\n")
        count += 1
    if not count:
        raise BuildIdentityError("no build source inputs found")
    return digest.hexdigest(), count


def git_value(root: Path, arguments: list[str], unavailable: str, *, allow_empty: bool = False) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return unavailable
    value = result.stdout.strip()
    if result.returncode != 0:
        return unavailable
    return value if value or allow_empty else unavailable


def source_revision(root: Path) -> dict[str, Any]:
    commit = git_value(root, ["rev-parse", "HEAD"], "UNAVAILABLE")
    status = git_value(root, ["status", "--porcelain=v1"], "UNAVAILABLE", allow_empty=True)
    return {
        "git_commit": commit,
        "working_tree_status": "UNAVAILABLE" if status == "UNAVAILABLE" else ("DIRTY" if status else "CLEAN"),
    }


def staged_identity(
    root: Path,
    control_path: Path,
    package_scheme: str,
    target: str,
    feature_flags: list[str],
) -> dict[str, Any]:
    fields = parse_control(control_path)
    source_digest, source_count = tracked_source_digest(root)
    identity: dict[str, Any] = {
        "schema": BUILD_IDENTITY_SCHEMA,
        "build_time_utc": utc_now(),
        "package": {
            "name": fields["Package"],
            "version": fields["Version"],
            "declared_architecture": fields["Architecture"],
        },
        "source": {
            **source_revision(root),
            "source_input_digest_sha256": source_digest,
            "source_input_count": source_count,
        },
        "build_target": {
            "package_scheme": package_scheme or "UNSPECIFIED",
            "theos_target": target or "UNSPECIFIED",
            "target_device_profile": "NOT_BOUND",
        },
        "feature_flags": feature_flags,
        "test_baseline": {"status": "NOT_BOUND"},
    }
    fingerprint = hashlib.sha256(canonical_json(identity)).hexdigest()
    identity["build_id"] = "phb-" + fingerprint[:24]
    return identity


def require_staged_identity(payload: dict[str, Any]) -> None:
    required = {"schema", "build_id", "build_time_utc", "package", "source", "build_target", "feature_flags", "test_baseline"}
    if set(payload) != required or payload.get("schema") != BUILD_IDENTITY_SCHEMA:
        raise BuildIdentityError("build identity schema is invalid")
    package = payload.get("package")
    source = payload.get("source")
    if not isinstance(package, dict) or not isinstance(source, dict):
        raise BuildIdentityError("build identity metadata is invalid")
    if not all(isinstance(package.get(key), str) and package[key] for key in ("name", "version", "declared_architecture")):
        raise BuildIdentityError("package identity is invalid")
    if not isinstance(source.get("source_input_digest_sha256"), str) or re.fullmatch(r"[0-9a-f]{64}", source["source_input_digest_sha256"]) is None:
        raise BuildIdentityError("source digest is invalid")


def deb_fields(package: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for output_key, control_field in (("name", "Package"), ("version", "Version"), ("architecture", "Architecture")):
        try:
            result = subprocess.run(
                ["dpkg-deb", "-f", str(package), control_field],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise BuildIdentityError("package metadata tool unavailable") from error
        value = result.stdout.strip()
        if result.returncode != 0 or not value or "\n" in value:
            raise BuildIdentityError("package metadata is unreadable")
        values[output_key] = value
    return values


def package_version_matches_declared_version(declared_version: str, artifact_version: str) -> bool:
    """Accept only the explicit Debian build suffix that Theos adds at packaging time."""

    if artifact_version == declared_version:
        return True
    if not artifact_version.startswith(declared_version + "-"):
        return False
    suffix = artifact_version[len(declared_version) + 1 :]
    return THEOS_DERIVED_VERSION_SUFFIX.fullmatch(suffix) is not None


def finalized_evidence(identity: dict[str, Any], package: Path, test_baseline: dict[str, Any]) -> dict[str, Any]:
    require_staged_identity(identity)
    if not package.is_file() or package.is_symlink():
        raise BuildIdentityError("package is unavailable")
    fields = deb_fields(package)
    staged_package = identity["package"]
    if (
        fields["name"] != staged_package["name"]
        or fields["architecture"] != staged_package["declared_architecture"]
        or not package_version_matches_declared_version(staged_package["version"], fields["version"])
    ):
        raise BuildIdentityError("package metadata does not match staged identity")
    if set(test_baseline) != {"static", "unit", "regression"}:
        raise BuildIdentityError("test baseline has an invalid schema")
    for result in test_baseline.values():
        if not isinstance(result, dict) or set(result) != {"status", "count"}:
            raise BuildIdentityError("test baseline is invalid")
        if result["status"] not in {"PASS", "FAIL", "NOT_RUN"} or not isinstance(result["count"], int) or result["count"] < 0:
            raise BuildIdentityError("test baseline is invalid")
    return {
        "schema": BUILD_EVIDENCE_SCHEMA,
        "recorded_at_utc": utc_now(),
        "build_id": identity["build_id"],
        "package": {
            **fields,
            "sha256": sha256_file(package),
            "size_bytes": package.stat().st_size,
        },
        "source": identity["source"],
        "build_target": identity["build_target"],
        "feature_flags": identity["feature_flags"],
        "test_baseline": test_baseline,
        "device_validation": {"status": "NOT_BOUND"},
    }


def require_finalized_evidence(payload: dict[str, Any]) -> None:
    required = {
        "schema",
        "recorded_at_utc",
        "build_id",
        "package",
        "source",
        "build_target",
        "feature_flags",
        "test_baseline",
        "device_validation",
    }
    if set(payload) != required or payload.get("schema") != BUILD_EVIDENCE_SCHEMA:
        raise BuildIdentityError("build evidence schema is invalid")
    package = payload.get("package")
    if not isinstance(package, dict) or not all(
        isinstance(package.get(key), str) and package[key]
        for key in ("name", "version", "architecture", "sha256")
    ):
        raise BuildIdentityError("build evidence package is invalid")
    if re.fullmatch(r"[0-9a-f]{64}", package["sha256"]) is None:
        raise BuildIdentityError("build evidence package digest is invalid")
    if not isinstance(package.get("size_bytes"), int) or package["size_bytes"] < 1:
        raise BuildIdentityError("build evidence package size is invalid")
    baseline = payload.get("test_baseline")
    if not isinstance(baseline, dict) or set(baseline) != {"static", "unit", "regression"}:
        raise BuildIdentityError("build evidence baseline is invalid")
    if payload.get("device_validation") != {"status": "NOT_BOUND"}:
        raise BuildIdentityError("build evidence device binding is invalid")


def safe_identifier(value: str, label: str) -> str:
    normalized = value.strip()
    if SAFE_IDENTIFIER_PATTERN.fullmatch(normalized) is None:
        raise BuildIdentityError("%s must be a safe identifier" % label)
    return normalized


def device_evidence(
    build_evidence: dict[str, Any],
    device_profile: str,
    test_id: str,
    result: str,
    classification: str,
    evidence_codes: list[str],
) -> dict[str, Any]:
    """Bind a focused target-device gate to one immutable package evidence record."""

    require_finalized_evidence(build_evidence)
    normalized_result = result.strip().upper()
    normalized_classification = classification.strip().upper()
    if normalized_result not in {"PASS", "FAIL", "NOT_RUN"}:
        raise BuildIdentityError("device result is invalid")
    if normalized_classification not in {"DEVICE_PASS", "FUNCTIONAL_FAILURE", "ENVIRONMENT_ISSUE"}:
        raise BuildIdentityError("device classification is invalid")
    if (normalized_result == "PASS") != (normalized_classification == "DEVICE_PASS"):
        raise BuildIdentityError("device result and classification do not agree")
    if normalized_result == "NOT_RUN" and normalized_classification != "ENVIRONMENT_ISSUE":
        raise BuildIdentityError("not-run device evidence must be an environment issue")
    if not evidence_codes or len(evidence_codes) > 16:
        raise BuildIdentityError("device evidence codes are invalid")
    normalized_codes = sorted({safe_identifier(code, "evidence code") for code in evidence_codes})
    return {
        "schema": DEVICE_EVIDENCE_SCHEMA,
        "recorded_at_utc": utc_now(),
        "build_id": build_evidence["build_id"],
        "package": dict(build_evidence["package"]),
        "test_baseline": json.loads(canonical_json(build_evidence["test_baseline"]).decode("utf-8")),
        "target_device": {"profile": safe_identifier(device_profile, "device profile")},
        "device_validation": {
            "test_id": safe_identifier(test_id, "test id"),
            "result": normalized_result,
            "classification": normalized_classification,
            "evidence_codes": normalized_codes,
        },
    }


def parse_result(status: str, count: int) -> dict[str, Any]:
    normalized = status.strip().upper()
    if normalized not in {"PASS", "FAIL", "NOT_RUN"} or count < 0:
        raise BuildIdentityError("invalid test result")
    return {"status": normalized, "count": count}


def stage_command(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    identity = staged_identity(
        root,
        Path(args.control).resolve(),
        args.package_scheme,
        args.target,
        sanitized_feature_flags(args.feature_flags),
    )
    atomic_json_write(Path(args.output).resolve(), identity)
    return 0


def finalize_command(args: argparse.Namespace) -> int:
    identity = read_json(Path(args.identity).resolve())
    evidence = finalized_evidence(
        identity,
        Path(args.package).resolve(),
        {
            "static": parse_result(args.static_status, args.static_count),
            "unit": parse_result(args.unit_status, args.unit_count),
            "regression": parse_result(args.regression_status, args.regression_count),
        },
    )
    atomic_json_write(Path(args.output).resolve(), evidence)
    return 0


def device_bind_command(args: argparse.Namespace) -> int:
    evidence = read_json(Path(args.build_evidence).resolve())
    record = device_evidence(
        evidence,
        args.device_profile,
        args.test_id,
        args.result,
        args.classification,
        args.evidence_code,
    )
    atomic_json_write(Path(args.output).resolve(), record)
    return 0


def parser() -> argparse.ArgumentParser:
    root = Path(__file__).resolve().parents[1]
    command = argparse.ArgumentParser(description="PhoneHarness build identity utility")
    subcommands = command.add_subparsers(dest="command", required=True)

    stage = subcommands.add_parser("stage")
    stage.add_argument("--root", default=str(root))
    stage.add_argument("--control", default=str(root / "control"))
    stage.add_argument("--output", required=True)
    stage.add_argument("--package-scheme", default="UNSPECIFIED")
    stage.add_argument("--target", default="UNSPECIFIED")
    stage.add_argument("--feature-flags", default="")
    stage.set_defaults(handler=stage_command)

    finalize = subcommands.add_parser("finalize")
    finalize.add_argument("--identity", required=True)
    finalize.add_argument("--package", required=True)
    finalize.add_argument("--output", required=True)
    finalize.add_argument("--static-status", default="NOT_RUN")
    finalize.add_argument("--static-count", type=int, default=0)
    finalize.add_argument("--unit-status", default="NOT_RUN")
    finalize.add_argument("--unit-count", type=int, default=0)
    finalize.add_argument("--regression-status", default="NOT_RUN")
    finalize.add_argument("--regression-count", type=int, default=0)
    finalize.set_defaults(handler=finalize_command)

    device_bind = subcommands.add_parser("device-bind")
    device_bind.add_argument("--build-evidence", required=True)
    device_bind.add_argument("--output", required=True)
    device_bind.add_argument("--device-profile", required=True)
    device_bind.add_argument("--test-id", required=True)
    device_bind.add_argument("--result", required=True)
    device_bind.add_argument("--classification", required=True)
    device_bind.add_argument("--evidence-code", action="append", default=[])
    device_bind.set_defaults(handler=device_bind_command)
    return command


def main() -> int:
    try:
        args = parser().parse_args()
        return args.handler(args)
    except BuildIdentityError as error:
        print("build_identity: %s" % error, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
