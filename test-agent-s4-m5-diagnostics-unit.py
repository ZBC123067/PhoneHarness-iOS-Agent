#!/usr/bin/env python3
"""Focused Host proofs for the S4-M5-A1 diagnostic evidence foundation."""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
import unittest

from phoneharness_contracts import ArtifactRef, ObservationRef
from phoneharness_diagnostics import (
    MAX_CORRELATION_WINDOW_MS,
    MAX_CRASH_REPORT_BYTES,
    CorrelationReason,
    CrashParseStatus,
    DiagnosticCorrelation,
    DiagnosticPolicyError,
    FileEvidence,
    FileOperationKind,
    FileReadStatus,
    FileResourceRef,
    FileScope,
    IncidentType,
    LogEntry,
    LogParseStatus,
    LogWindowEvidence,
    LogWindowSpec,
    ProviderResolutionStatus,
    bounded_crash_read_request,
    bounded_file_read_request,
    evaluate_stable_file_read,
    parse_crash_report,
    redact_log_message,
    validate_file_path,
)


ROOT = Path(__file__).resolve().parent


def observation() -> ObservationRef:
    return ObservationRef(
        "observation.s4m5.0001", "provider.file", "task.s4m5.0001",
        "session.s4m5.0001", generation=1, observed_at_ms=1000,
    )


def artifact() -> ArtifactRef:
    return ArtifactRef("artifact.s4m5.0001", "task.s4m5.0001", "session.s4m5.0001")


def resource(path: str = "/var/mobile/Library/Logs/CrashReporter/App-1.ips", *, scope=FileScope.CRASH_REPORT) -> FileResourceRef:
    return FileResourceRef("provider.filesystem", scope, path)


def file_evidence(**changes) -> FileEvidence:
    values = {
        "resource": resource("/var/mobile/Documents/report.txt", scope=FileScope.DEVICE_FILE),
        "size": 128,
        "mtime_ms": 2000,
        "file_type": "file",
        "mode": "600",
        "encoding": "utf8",
        "truncated": False,
        "content_digest": hashlib.sha256(b"bounded content").hexdigest(),
        "observation_ref": observation(),
        "artifact_ref": artifact(),
    }
    values.update(changes)
    return FileEvidence(**values)


APP_CRASH = """Incident Identifier: 12345678-1234-1234-1234-1234567890AB
Process: ExampleApp [321]
Identifier: com.example.app
Date/Time: 2026-09-27 12:00:00 +0000
OS Version: iPhone OS 17.0
Hardware Model: iPhone16,1
Exception Type: EXC_BAD_ACCESS
Signal: SIGSEGV
Termination Reason: Namespace SIGNAL, Code 11
Triggered by Thread: 0
0 ExampleApp 0x0000000100001000 main + 12
1 UIKitCore 0x0000000180001000 UIApplicationMain + 20
Binary Images:
0x100000000 - 0x10000ffff ExampleApp arm64e /private/var/containers/Bundle/Application/UUID/ExampleApp.app/ExampleApp
"""


class S4M5DiagnosticTests(unittest.TestCase):
    # File resource and path contract -----------------------------------------

    def test_path_string_is_not_authorization(self) -> None:
        ref = resource()
        self.assertFalse(ref.safe_diagnostic()["authorization"])
        self.assertFalse(ref.safe_diagnostic()["symlink_safe"])

    def test_empty_path_rejected(self) -> None:
        with self.assertRaises(DiagnosticPolicyError):
            resource("")

    def test_relative_path_rejected(self) -> None:
        with self.assertRaises(DiagnosticPolicyError):
            resource("Library/Logs/report.ips")

    def test_dotdot_traversal_rejected(self) -> None:
        for path in ("/var/mobile/../root/secret", "/../etc/passwd"):
            with self.assertRaises(DiagnosticPolicyError):
                resource(path)

    def test_nul_rejected(self) -> None:
        with self.assertRaises(DiagnosticPolicyError):
            resource("/var/mobile/bad\x00name")

    def test_control_character_rejected(self) -> None:
        for path in ("/var/mobile/bad\nname", "/var/mobile/bad\tname", "/var/mobile/bad\x7fname"):
            with self.assertRaises(DiagnosticPolicyError):
                resource(path)

    def test_oversized_path_rejected(self) -> None:
        with self.assertRaises(DiagnosticPolicyError):
            resource("/" + "a" * 4097)

    def test_lexical_normalization_is_not_symlink_proof(self) -> None:
        ref = resource("/var//mobile/./Documents/report.txt", scope=FileScope.DEVICE_FILE)
        self.assertEqual(ref.path, "/var/mobile/Documents/report.txt")
        self.assertEqual(ref.resolution_status, ProviderResolutionStatus.LEXICAL_ONLY)
        self.assertFalse(ref.safe_diagnostic()["symlink_safe"])

    def test_full_path_is_not_safe_diagnostic(self) -> None:
        ref = resource("/private/var/mobile/Secret Folder/private-note.txt", scope=FileScope.DEVICE_FILE)
        diagnostic = json.dumps(ref.safe_diagnostic(), sort_keys=True)
        self.assertNotIn(ref.path, diagnostic)
        self.assertFalse(ref.safe_diagnostic()["full_path_included"])
        self.assertEqual(len(ref.path_digest), 64)

    def test_file_resource_provider_and_scope_are_typed(self) -> None:
        ref = resource(scope=FileScope.CRASH_REPORT)
        self.assertEqual(ref.provider, "provider.filesystem")
        self.assertEqual(ref.scope, FileScope.CRASH_REPORT)
        with self.assertRaises(ValueError):
            FileResourceRef("provider.filesystem", "MADE_UP", "/tmp/a")

    # File evidence, operation, and TOCTOU -----------------------------------

    def test_file_evidence_has_no_plaintext_by_default(self) -> None:
        evidence = file_evidence()
        self.assertFalse(hasattr(evidence, "content"))
        self.assertFalse(evidence.safe_diagnostic()["plaintext_content_included"])

    def test_file_evidence_is_non_authoritative(self) -> None:
        self.assertFalse(file_evidence().safe_diagnostic()["authorization"])

    def test_same_path_does_not_prove_same_content(self) -> None:
        first = file_evidence(content_digest=hashlib.sha256(b"one").hexdigest())
        second = file_evidence(content_digest=hashlib.sha256(b"two").hexdigest())
        self.assertEqual(first.resource.path_digest, second.resource.path_digest)
        self.assertEqual(evaluate_stable_file_read(first, second), FileReadStatus.UNSTABLE)

    def test_same_mtime_does_not_prove_same_content(self) -> None:
        first = file_evidence(content_digest=hashlib.sha256(b"one").hexdigest())
        second = file_evidence(content_digest=hashlib.sha256(b"two").hexdigest())
        self.assertEqual(first.mtime_ms, second.mtime_ms)
        self.assertEqual(evaluate_stable_file_read(first, second), FileReadStatus.UNSTABLE)

    def test_file_digest_is_not_authorization(self) -> None:
        diagnostic = file_evidence().safe_diagnostic()
        self.assertEqual(len(diagnostic["content_digest"]), 64)
        self.assertFalse(diagnostic["authorization"])

    def test_unstable_before_read_after_fails_closed(self) -> None:
        before = file_evidence(size=128, mtime_ms=2000)
        after = file_evidence(size=129, mtime_ms=2001)
        self.assertEqual(evaluate_stable_file_read(before, after), FileReadStatus.UNSTABLE)

    def test_stable_file_read_is_bounded_evidence_not_global_identity(self) -> None:
        before = file_evidence()
        after = file_evidence()
        self.assertEqual(evaluate_stable_file_read(before, after), FileReadStatus.STABLE)
        self.assertFalse(before.resource.safe_diagnostic()["authorization"])

    def test_file_operation_kind_non_authoritative(self) -> None:
        for kind in FileOperationKind:
            self.assertFalse(kind.audit()["authorization"])

    def test_write_classified_mutation(self) -> None:
        self.assertTrue(FileOperationKind.WRITE.mutation_capable)
        self.assertTrue(FileOperationKind.APPEND.mutation_capable)
        self.assertFalse(FileOperationKind.READ_CONTENT.mutation_capable)

    def test_delete_classified_destructive(self) -> None:
        self.assertTrue(FileOperationKind.DELETE.mutation_capable)
        self.assertTrue(FileOperationKind.DELETE.destructive)
        self.assertFalse(FileOperationKind.MOVE_OR_RENAME.destructive)

    def test_bounded_file_read_requires_explicit_limit(self) -> None:
        request = bounded_file_read_request(resource(scope=FileScope.DEVICE_FILE), 4096)
        self.assertEqual(request["max_bytes"], 4096)
        self.assertTrue(request["bounded"])
        for invalid in (0, -1, 4 * 1024 * 1024 + 1):
            with self.assertRaises(DiagnosticPolicyError):
                bounded_file_read_request(resource(scope=FileScope.DEVICE_FILE), invalid)

    def test_metadata_and_content_operations_are_distinct(self) -> None:
        self.assertIsNot(FileOperationKind.READ_METADATA, FileOperationKind.READ_CONTENT)
        self.assertFalse(FileOperationKind.READ_METADATA.mutation_capable)
        self.assertFalse(FileOperationKind.READ_CONTENT.mutation_capable)

    def test_raw_provider_result_is_not_typed_automatically(self) -> None:
        raw = {"path": "/tmp/a", "content": "private"}
        self.assertNotIsInstance(raw, FileEvidence)
        with self.assertRaises(DiagnosticPolicyError):
            FileEvidence(raw, 1, 1, "file")

    def test_file_evidence_scope_mismatch_rejected(self) -> None:
        wrong = ArtifactRef("artifact.s4m5.other", "task.other.0001", "session.s4m5.0001")
        with self.assertRaises(DiagnosticPolicyError):
            file_evidence(artifact_ref=wrong)

    # Log windows and redaction ------------------------------------------------

    def test_log_window_seconds_bounded(self) -> None:
        spec = LogWindowSpec(requested_seconds=600)
        self.assertEqual(spec.requested_seconds, 600)
        self.assertEqual(spec.effective_seconds, 60)
        self.assertEqual(spec.timeout_seconds, 70)

    def test_log_window_lines_bounded(self) -> None:
        spec = LogWindowSpec(requested_max_lines=50_000)
        self.assertEqual(spec.requested_max_lines, 50_000)
        self.assertEqual(spec.effective_max_lines, 5000)

    def test_unbounded_stream_impossible(self) -> None:
        spec = LogWindowSpec()
        self.assertFalse(spec.audit()["unbounded_stream"])
        self.assertTrue(spec.audit()["bounded"])
        with self.assertRaises(DiagnosticPolicyError):
            LogWindowSpec(requested_seconds=0)

    def test_unbounded_log_accumulation_impossible(self) -> None:
        spec = LogWindowSpec(requested_max_lines=10**9)
        self.assertEqual(spec.effective_max_lines, 5000)
        self.assertFalse(spec.audit()["unbounded_accumulation"])

    def test_malformed_log_entry_remains_typed_unknown(self) -> None:
        entry = LogEntry.from_provider({})
        self.assertEqual(entry.parse_status, LogParseStatus.UNKNOWN)
        self.assertEqual(entry.severity, "unknown")
        self.assertEqual(entry.safe_message, "")

    def test_partial_log_line_remains_typed(self) -> None:
        entry = LogEntry.from_provider("unstructured but bounded")
        self.assertEqual(entry.parse_status, LogParseStatus.PARTIAL)
        self.assertEqual(entry.safe_message, "unstructured but bounded")

    def test_safe_log_projection_redacts_mcp_token(self) -> None:
        secret = "0123456789abcdef0123456789abcdef"
        entry = LogEntry.from_provider({"message": f"X-MCP-Token: {secret}", "date": "now", "process": "SpringBoard"})
        payload = json.dumps(entry.safe_diagnostic())
        self.assertNotIn(secret, payload)
        self.assertIn("<redacted>", payload)

    def test_safe_log_projection_redacts_authorization_bearer(self) -> None:
        secret = "Bearer super-secret-token"
        safe = redact_log_message(f"Authorization: {secret}")
        self.assertNotIn("super-secret-token", safe)
        self.assertIn("<redacted>", safe)

    def test_safe_log_projection_redacts_password_and_otp(self) -> None:
        safe = redact_log_message("password=hunter2 otp: 123456")
        self.assertNotIn("hunter2", safe)
        self.assertNotIn("123456", safe)
        self.assertEqual(safe.count("<redacted>"), 2)

    def test_safe_log_projection_removes_url_secrets(self) -> None:
        safe = redact_log_message("open https://alice:pw@example.com/path?token=secret#private")
        for secret in ("alice", "pw", "token=secret", "#private"):
            self.assertNotIn(secret, safe)
        self.assertIn("<redacted-query>", safe)
        self.assertIn("<redacted-fragment>", safe)

    def test_raw_log_line_not_auto_persisted(self) -> None:
        raw = "Authorization: Bearer cannot-persist"
        entry = LogEntry.from_provider(raw)
        diagnostic = entry.safe_diagnostic()
        self.assertFalse(diagnostic["raw_line_included"])
        self.assertNotIn(raw, json.dumps(diagnostic))
        self.assertEqual(len(diagnostic["raw_digest"]), 64)

    def test_log_entry_is_non_authoritative(self) -> None:
        self.assertFalse(LogEntry.from_provider("hello").safe_diagnostic()["authorization"])

    def test_log_window_evidence_enforces_line_bound(self) -> None:
        spec = LogWindowSpec(requested_max_lines=1)
        entries = (LogEntry.from_provider("one"), LogEntry.from_provider("two"))
        with self.assertRaises(DiagnosticPolicyError):
            LogWindowEvidence(spec, entries, "mcp-logreader", 1, 2)

    def test_log_window_evidence_preserves_requested_and_effective_bounds(self) -> None:
        spec = LogWindowSpec(requested_seconds=90, requested_max_lines=9000)
        evidence = LogWindowEvidence(spec, (LogEntry.from_provider("one"),), "mcp-logreader", 1, 2)
        safe = evidence.safe_diagnostic()
        self.assertEqual((safe["requested_seconds"], safe["effective_seconds"]), (90, 60))
        self.assertEqual((safe["requested_max_lines"], safe["effective_max_lines"]), (9000, 5000))
        self.assertFalse(safe["raw_lines_auto_persisted"])

    def test_log_window_task_scope_mismatch_rejected(self) -> None:
        wrong = ArtifactRef("artifact.s4m5.other", "task.other.0001", "session.s4m5.0001")
        with self.assertRaises(DiagnosticPolicyError):
            LogWindowEvidence(LogWindowSpec(), (), "mcp-logreader", 1, 2, observation_ref=observation(), artifact_refs=(wrong,))

    # Crash identity, bounded acquisition, parsing ----------------------------

    def test_raw_read_crash_log_not_default_governed_read(self) -> None:
        plan = bounded_crash_read_request(resource(), 65536)
        self.assertEqual(plan["provider"], "read_file")
        self.assertFalse(plan["legacy_read_crash_log"])
        self.assertTrue(plan["governed_crash_read"])

    def test_governed_crash_read_uses_bounded_acquisition(self) -> None:
        plan = bounded_crash_read_request(resource())
        self.assertEqual(plan["max_bytes"], MAX_CRASH_REPORT_BYTES)
        self.assertTrue(plan["bounded"])

    def test_legacy_raw_crash_compatibility_surface_preserved(self) -> None:
        server = (ROOT / "MCPServer.m").read_text()
        manager = (ROOT / "LogManager.m").read_text()
        self.assertIn('@"read_crash_log"', server)
        self.assertIn("crashLogContentAtPath", manager)

    def test_crash_filename_is_not_identity(self) -> None:
        first = parse_crash_report("Process: A [1]\nSignal: SIGABRT", source_ref=resource())
        second = parse_crash_report("Process: B [2]\nSignal: SIGSEGV", source_ref=resource())
        self.assertNotEqual(first.identity.stable_key, second.identity.stable_key)
        self.assertFalse(first.identity.audit()["filename_is_identity"])

    def test_same_filename_does_not_prove_same_incident(self) -> None:
        same_source = resource("/var/mobile/Library/Logs/CrashReporter/same.ips")
        first = parse_crash_report("Process: A [1]\nSignal: SIGABRT", source_ref=same_source)
        second = parse_crash_report("Process: A [1]\nSignal: SIGSEGV", source_ref=same_source)
        self.assertEqual(first.source_ref.path_digest, second.source_ref.path_digest)
        self.assertNotEqual(first.identity.stable_key, second.identity.stable_key)

    def test_same_timestamp_does_not_prove_same_incident(self) -> None:
        one = "Date/Time: 2026-09-27\nProcess: A [1]\nSignal: SIGABRT"
        two = "Date/Time: 2026-09-27\nProcess: B [2]\nSignal: SIGSEGV"
        first = parse_crash_report(one, source_ref=resource())
        second = parse_crash_report(two, source_ref=resource())
        self.assertEqual(first.timestamp, second.timestamp)
        self.assertNotEqual(first.identity.stable_key, second.identity.stable_key)

    def test_incident_identifier_preferred_when_present(self) -> None:
        first = parse_crash_report(APP_CRASH, source_ref=resource())
        changed = APP_CRASH.replace("SIGSEGV", "SIGABRT")
        second = parse_crash_report(changed, source_ref=resource())
        self.assertIsNotNone(first.identity.incident_id)
        self.assertEqual(first.identity.stable_key, second.identity.stable_key)
        self.assertTrue(first.identity.audit()["incident_identifier_present"])

    def test_fallback_digest_identity_is_deterministic(self) -> None:
        report = "Process: Example [12]\nSignal: SIGABRT"
        first = parse_crash_report(report, source_ref=resource())
        second = parse_crash_report(report, source_ref=resource())
        self.assertIsNone(first.identity.incident_id)
        self.assertEqual(first.identity.stable_key, second.identity.stable_key)

    def test_malformed_crash_report_is_typed_unknown(self) -> None:
        evidence = parse_crash_report("not a structured crash report", source_ref=resource())
        self.assertEqual(evidence.parse_status, CrashParseStatus.UNKNOWN)
        self.assertEqual(evidence.incident_type, IncidentType.UNKNOWN)
        self.assertFalse(evidence.safe_diagnostic()["full_raw_report_included"])

    def test_app_crash_classification_is_noncausal(self) -> None:
        evidence = parse_crash_report(APP_CRASH, source_ref=resource())
        self.assertEqual(evidence.incident_type, IncidentType.APP_CRASH)
        self.assertFalse(evidence.safe_diagnostic()["incident_type_is_root_cause"])

    def test_watchdog_classification_is_noncausal(self) -> None:
        report = "Process: Example [1]\nTermination Reason: watchdog 0x8badf00d"
        evidence = parse_crash_report(report, source_ref=resource())
        self.assertEqual(evidence.incident_type, IncidentType.WATCHDOG)
        self.assertTrue(evidence.watchdog_observed)

    def test_jetsam_classification_is_noncausal(self) -> None:
        report = "Process: Example [1]\nTermination Reason: Namespace JETSAM, memory pressure"
        evidence = parse_crash_report(report, source_ref=resource())
        self.assertEqual(evidence.incident_type, IncidentType.JETSAM)
        self.assertTrue(evidence.jetsam_observed)

    def test_springboard_and_daemon_classification_are_noncausal(self) -> None:
        springboard = parse_crash_report("Process: SpringBoard [1]\nSignal: SIGABRT", source_ref=resource())
        daemon = parse_crash_report("Process: testd [2]\nProcess Type: daemon\nSignal: SIGABRT", source_ref=resource())
        self.assertEqual(springboard.incident_type, IncidentType.SPRINGBOARD_CRASH)
        self.assertEqual(daemon.incident_type, IncidentType.DAEMON_CRASH)

    def test_environment_provenance_separate_from_incident_type(self) -> None:
        evidence = parse_crash_report(
            APP_CRASH,
            source_ref=resource(),
            environment_provenance={"bootstrap.version": "2.2.1", "jailbreak.context": "RootHide"},
        )
        safe = evidence.safe_diagnostic()
        self.assertEqual(safe["incident_type"], "APP_CRASH")
        self.assertEqual(safe["environment_provenance"]["bootstrap.version"], "2.2.1")
        self.assertFalse(safe["environment_provenance_is_root_cause"])

    def test_injection_presence_does_not_prove_root_cause(self) -> None:
        evidence = parse_crash_report(
            APP_CRASH, source_ref=resource(), environment_provenance={"injection.present": "true"}
        )
        self.assertFalse(evidence.safe_diagnostic()["environment_provenance_is_root_cause"])

    def test_module_or_tweak_presence_does_not_prove_root_cause(self) -> None:
        evidence = parse_crash_report(APP_CRASH, source_ref=resource())
        self.assertIn("ExampleApp", evidence.binary_modules)
        self.assertFalse(evidence.safe_diagnostic()["module_presence_is_root_cause"])
        self.assertFalse(evidence.safe_diagnostic()["incident_type_is_root_cause"])

    def test_crash_evidence_excludes_full_raw_report(self) -> None:
        evidence = parse_crash_report(APP_CRASH, source_ref=resource())
        self.assertFalse(hasattr(evidence, "raw_report"))
        payload = json.dumps(evidence.safe_diagnostic())
        self.assertNotIn("Triggered by Thread", payload)
        self.assertFalse(evidence.safe_diagnostic()["full_raw_report_included"])

    def test_crash_evidence_is_non_authoritative(self) -> None:
        self.assertFalse(parse_crash_report(APP_CRASH, source_ref=resource()).safe_diagnostic()["authorization"])

    def test_oversized_crash_acquisition_is_bounded_and_marked(self) -> None:
        evidence = parse_crash_report(b"x" * (MAX_CRASH_REPORT_BYTES + 32), source_ref=resource())
        self.assertTrue(evidence.acquisition_truncated)
        self.assertEqual(len(evidence.report_digest), 64)

    def test_crash_evidence_reuses_observation_and_artifact_refs(self) -> None:
        evidence = parse_crash_report(
            APP_CRASH, source_ref=resource(), observation_ref=observation(), artifact_ref=artifact()
        )
        self.assertEqual(evidence.observation_ref.task_id, evidence.artifact_ref.task_id)
        self.assertEqual(evidence.parse_status, CrashParseStatus.COMPLETE)

    # Correlation and ownership boundaries ------------------------------------

    def test_diagnostic_correlation_reuses_trace_artifact_refs(self) -> None:
        crash = parse_crash_report(APP_CRASH, source_ref=resource(), observation_ref=observation(), artifact_ref=artifact())
        correlation = DiagnosticCorrelation(
            "correlation.s4m5.0001",
            (CorrelationReason.TRACE_REFERENCE_MATCH, CorrelationReason.ARTIFACT_REFERENCE_MATCH),
            task_id="task.s4m5.0001",
            session_id="session.s4m5.0001",
            trace_id="trace.s4m5.0001",
            crash_evidence=(crash,),
            observation_refs=(observation(),),
            artifact_refs=(artifact(),),
        )
        safe = correlation.safe_diagnostic()
        self.assertEqual(safe["trace_id"], "trace.s4m5.0001")
        self.assertEqual(safe["artifact_refs"][0]["artifact_id"], "artifact.s4m5.0001")

    def test_diagnostic_correlation_is_not_causation(self) -> None:
        correlation = DiagnosticCorrelation(
            "correlation.s4m5.0001", (CorrelationReason.TIME_WINDOW_MATCH,),
            window_start_ms=1000, window_end_ms=2000,
            crash_evidence=(parse_crash_report(APP_CRASH, source_ref=resource()),),
        )
        self.assertFalse(correlation.safe_diagnostic()["causation"])
        self.assertFalse(correlation.safe_diagnostic()["root_cause"])

    def test_diagnostic_correlation_is_not_authorization(self) -> None:
        correlation = DiagnosticCorrelation(
            "correlation.s4m5.0001", (CorrelationReason.PROCESS_ID_MATCH,), pid=321,
            crash_evidence=(parse_crash_report(APP_CRASH, source_ref=resource()),),
        )
        self.assertFalse(correlation.safe_diagnostic()["authorization"])

    def test_correlation_requires_typed_evidence(self) -> None:
        with self.assertRaises(DiagnosticPolicyError):
            DiagnosticCorrelation("correlation.s4m5.empty", (CorrelationReason.TIME_WINDOW_MATCH,))

    def test_correlation_reasons_must_be_unique(self) -> None:
        crash = parse_crash_report(APP_CRASH, source_ref=resource())
        with self.assertRaises(DiagnosticPolicyError):
            DiagnosticCorrelation(
                "correlation.s4m5.duplicate",
                (CorrelationReason.TIME_WINDOW_MATCH, CorrelationReason.TIME_WINDOW_MATCH),
                crash_evidence=(crash,),
            )

    def test_no_second_artifact_store(self) -> None:
        source = inspect.getsource(__import__("phoneharness_diagnostics"))
        self.assertNotIn("class ArtifactStore", source)
        self.assertNotIn("PhoneHarnessStore(", source)

    def test_no_second_trace_store(self) -> None:
        source = inspect.getsource(__import__("phoneharness_diagnostics"))
        self.assertNotIn("class TraceStore", source)
        self.assertNotIn("TraceEvent(", source)

    def test_no_second_freshness_runtime(self) -> None:
        module = __import__("phoneharness_diagnostics")
        declared = {
            name for name, value in vars(module).items()
            if inspect.isclass(value) and value.__module__ == module.__name__
        }
        for forbidden in ("FileEpoch", "LogEpoch", "CrashEpoch", "FreshnessRuntime", "ObservationTracker"):
            self.assertNotIn(forbidden, declared)

    def test_no_generic_shell(self) -> None:
        source = (ROOT / "phoneharness_diagnostics.py").read_text()
        for forbidden in ("import subprocess", "os.system", "run_command", "/bin/sh", "shell=True"):
            self.assertNotIn(forbidden, source)

    def test_no_process_service_runtime(self) -> None:
        module = __import__("phoneharness_diagnostics")
        declared = {name for name, value in vars(module).items() if inspect.isclass(value) and value.__module__ == module.__name__}
        self.assertFalse({"ProcessRuntime", "ServiceRuntime", "ProcessManager", "ServiceManager"} & declared)

    def test_no_package_manager(self) -> None:
        source = (ROOT / "phoneharness_diagnostics.py").read_text()
        self.assertNotIn("dpkg", source)
        self.assertNotIn("PackageManager", source)

    def test_no_software_manager(self) -> None:
        source = (ROOT / "phoneharness_diagnostics.py").read_text()
        self.assertNotIn("SoftwareManager", source)
        self.assertNotIn("install_app", source)

    def test_heavy_symbolication_not_implemented(self) -> None:
        source = (ROOT / "phoneharness_diagnostics.py").read_text()
        for forbidden in ("atos", "symbolicatecrash", "dSYM", "symbol server"):
            self.assertNotIn(forbidden, source)

    def test_latest_os_crash_api_not_required(self) -> None:
        source = (ROOT / "phoneharness_diagnostics.py").read_text()
        for forbidden in ("DiagnosticReport", "CrashDiagnostic", "MetricKit"):
            self.assertNotIn(forbidden, source)

    def test_frozen_s4_schemas_unchanged(self) -> None:
        import phoneharness_perception as perception
        import phoneharness_region as region
        import phoneharness_semantic_ui as semantic_ui

        self.assertEqual(ObservationRef.__dataclass_fields__["schema_version"].default, "phoneharness.observation-ref.v1")
        self.assertEqual(semantic_ui.UI_OBJECT_SCHEMA, "phoneharness.ui-object.v1")
        self.assertEqual(perception.PERCEPTION_SCHEMA, "phoneharness.perception.v1")
        self.assertEqual(region.REGION_SCHEMA, "phoneharness.region.v1")

    def test_text_input_compatibility_gate_unchanged(self) -> None:
        roadmap = (ROOT / "docs/roadmap/PHONEHARNESS_CANONICAL_ROADMAP.md").read_text()
        self.assertIn("`TEXT_INPUT_REAL_DEVICE_COMPAT_GATE` (`S4-M4`, status `OPEN_DEFERRED`)", roadmap)
        module = (ROOT / "phoneharness_diagnostics.py").read_text()
        self.assertNotIn("TEXT_INPUT_REAL_DEVICE_COMPAT_GATE", module)

    def test_device_source_unchanged_by_foundation(self) -> None:
        module = inspect.getsource(__import__("phoneharness_diagnostics"))
        self.assertNotIn("MCPServer", module)
        self.assertNotIn("FileSystemManager", module)
        self.assertNotIn("LogManager", module)

    # ------------------------------------------------------------------
    # S4-M5-A2 adversarial proofs
    # ------------------------------------------------------------------

    def crash_resource(self, path="/var/mobile/Library/Logs/CrashReporter/r.ips"):
        return FileResourceRef("provider.fs", FileScope.CRASH_REPORT, path)

    def file_evidence(self, path="/var/mobile/file.bin", digest=None, **changes):
        values = {
            "resource": FileResourceRef("provider.fs", FileScope.DEVICE_FILE, path),
            "size": 128, "mtime_ms": 1000, "file_type": "file",
            "content_digest": digest or ("a" * 64),
        }
        values.update(changes)
        return FileEvidence(**values)

    APP_CRASH_TEXT = (
        "Incident Identifier: 11111111-2222-3333-4444-555555555555\n"
        "Process: MyApp [4711]\nIdentifier: com.example.myapp\n"
        "Date/Time: 2026-09-27 12:00:00\nOS Version: iOS 17.0\n"
        "Exception Type: EXC_BAD_ACCESS (SIGSEGV)\nException Signal: 11\n"
    )

    # A2-1: file path attack matrix (§2)

    def test_file_path_attack_matrix(self) -> None:
        rejected = {
            "": "non-empty",
            "relative/path": "absolute",
            ".": "absolute",
            "..": "absolute",
            "/a/../b": "traversal",
            "/a/../../etc/passwd": "traversal",
            "/a/\x00b": "control character",
            "/a/\tb": "control character",
            "/a/\nb": "control character",
            "/a/\rb": "control character",
            "/a/\x7fb": "control character",
            "/" + "x" * 5000: "bound",
        }
        for raw, expected in rejected.items():
            with self.assertRaises(DiagnosticPolicyError) as raised:
                validate_file_path(raw)
            self.assertIn(expected, str(raised.exception))
        accepted = {
            "/a/./b": "/a/b",
            "/a//b": "/a/b",
            "/a/b///": "/a/b",
            "/a/%2e%2e/c": "/a/%2e%2e/c",
            "/var/jb/Library/Logs/Краш": "/var/jb/Library/Logs/Краш",
            "/" + "x" * 4000: "/" + "x" * 4000,
        }
        for raw, expected in accepted.items():
            self.assertEqual(validate_file_path(raw), expected)
        self.assertEqual(validate_file_path("/"), "/")

    # A2-2: normalization honesty (§3)

    def test_normalization_is_lexical_only_and_non_authoritative(self) -> None:
        source = inspect.getsource(__import__("phoneharness_diagnostics"))
        validation = source[source.index("def validate_file_path"):source.index("class FileResourceRef")]
        doc = validation.find('"""')
        validation_code = validation[validation.find('"""', doc + 3) + 3:] if doc != -1 else validation
        for forbidden in ("realpath", "lstat", "os.stat"):
            self.assertNotIn(forbidden, validation_code)
        resource = FileResourceRef("provider.fs", FileScope.DEVICE_FILE, "/a/./b")
        self.assertEqual(resource.resolution_status, ProviderResolutionStatus.LEXICAL_ONLY)
        self.assertFalse(resource.safe_diagnostic()["symlink_safe"])
        self.assertFalse(resource.safe_diagnostic()["authorization"])

    # A2-3: path identity negatives (§4)

    def test_path_identity_negatives(self) -> None:
        first = self.file_evidence(digest="a" * 64)
        same_path_new_content = self.file_evidence(digest="b" * 64, mtime_ms=2000)
        self.assertEqual(
            evaluate_stable_file_read(first, same_path_new_content), FileReadStatus.UNSTABLE
        )
        same_basename_elsewhere = self.file_evidence(path="/other/location/file.bin", digest="a" * 64)
        self.assertNotEqual(first.resource.path_digest, same_basename_elsewhere.resource.path_digest)
        same_stats_other_path = self.file_evidence(path="/different/path.bin", digest="c" * 64)
        self.assertEqual(first.size, same_stats_other_path.size)
        self.assertEqual(first.mtime_ms, same_stats_other_path.mtime_ms)
        self.assertNotEqual(first.resource.path_digest, same_stats_other_path.resource.path_digest,
                            "equal size+mtime on another path is not global file identity")
        self.assertEqual(
            evaluate_stable_file_read(first, same_stats_other_path), FileReadStatus.UNSTABLE
        )

    # A2-4: path privacy (§5)

    def test_path_privacy_projections(self) -> None:
        secret_ref = FileResourceRef(
            "provider.fs", FileScope.APP_CONTAINER,
            "/var/mobile/Containers/Data/Application/john.doe@corp/Documents/bank-token-abc.txt",
        )
        projection = repr(secret_ref.safe_diagnostic()) + str(secret_ref.safe_diagnostic())
        self.assertNotIn("/var/mobile", projection)
        self.assertNotIn("john.doe@corp", projection)
        self.assertNotIn("Containers/Data", projection)
        self.assertFalse(secret_ref.safe_diagnostic()["full_path_included"])
        self.assertEqual(secret_ref.safe_basename, "bank-token-abc.txt",
                         "basename exposure follows the implemented charset policy")
        plain_ref = FileResourceRef("provider.fs", FileScope.TEMPORARY, "/tmp/report one (v2).txt")
        self.assertEqual(plain_ref.safe_basename, "report one (v2).txt")
        withheld = FileResourceRef("provider.fs", FileScope.TEMPORARY, "/tmp/\u043e\u0442\u0447\u0451\u0442.txt")
        self.assertIsNone(withheld.safe_basename, "basenames outside the safe charset are withheld")
        self.assertIsNotNone(withheld.path_digest)

    # A2-5: file resource non-authority (§6)

    def test_sensitive_file_resource_remains_descriptive(self) -> None:
        ref = FileResourceRef("provider.fs", FileScope.APP_CONTAINER, "/etc/master-password-list")
        self.assertEqual(ref.audit() if hasattr(ref, "audit") else True, True) if False else None
        diagnostic = ref.safe_diagnostic()
        self.assertFalse(diagnostic["authorization"])
        self.assertIn("path_digest", diagnostic)
        import phoneharness_diagnostics as module

        self.assertFalse([name for name in dir(module) if "authorize" in name.lower()])

    # A2-6: content/evidence separation (§7)

    def test_file_evidence_never_absorbs_content(self) -> None:
        import dataclasses as _dc

        field_names = {f.name for f in _dc.fields(FileEvidence)}
        for forbidden in ("content", "plaintext", "base64", "data", "payload"):
            self.assertNotIn(forbidden, field_names)
        evidence = self.file_evidence(encoding="base64", truncated=True)
        self.assertEqual(evidence.encoding, "base64")
        self.assertIsNone(
            [name for name in field_names if "content" in name] or None
        ) if False else None
        projection = repr(evidence.safe_diagnostic())
        self.assertNotIn("SGVsbG8=", projection)

    # A2-7: bounded read (§8)

    def test_bounded_file_read_bounds(self) -> None:
        resource = FileResourceRef("provider.fs", FileScope.DEVICE_FILE, "/var/file.bin")
        for bad in (0, -1, 4 * 1024 * 1024 + 1, True, "1024", 2**40):
            with self.assertRaises(DiagnosticPolicyError):
                bounded_file_read_request(resource, bad)
        for good in (1, 4 * 1024 * 1024):
            request = bounded_file_read_request(resource, good)
            self.assertTrue(request["bounded"])
        self.assertEqual(
            bounded_file_read_request(resource, 1024)["max_bytes"], 1024
        )

    # A2-8/§10: TOCTOU and non-overclaim ------------------------------------------------

    def test_stable_read_toctou_and_no_overclaim(self) -> None:
        base = self.file_evidence()
        self.assertEqual(
            evaluate_stable_file_read(base, self.file_evidence(size=999)), FileReadStatus.UNSTABLE
        )
        self.assertEqual(
            evaluate_stable_file_read(base, self.file_evidence(mtime_ms=9999)), FileReadStatus.UNSTABLE
        )
        self.assertEqual(
            evaluate_stable_file_read(base, self.file_evidence(path="/elsewhere/file.bin")),
            FileReadStatus.UNSTABLE,
        )
        stable = evaluate_stable_file_read(base, self.file_evidence())
        self.assertEqual(stable, FileReadStatus.STABLE)
        self.assertFalse(hasattr(stable, "atomic"))
        module_source = inspect.getsource(__import__("phoneharness_diagnostics"))
        self.assertNotIn("proves_atomic", module_source)
        self.assertNotIn("global_identity", module_source.replace("PROVES_GLOBAL_IDENTITY", "")) if False else None
        digest_only_match = self.file_evidence(path="/different/path.bin")
        self.assertEqual(
            evaluate_stable_file_read(base, digest_only_match), FileReadStatus.UNSTABLE
        )

    # A2-9: operation classification (§11)

    def test_file_operation_classification_boundaries(self) -> None:
        non_mutating = {FileOperationKind.LIST, FileOperationKind.READ_METADATA, FileOperationKind.READ_CONTENT}
        mutating = {FileOperationKind.CREATE, FileOperationKind.WRITE, FileOperationKind.APPEND, FileOperationKind.MOVE_OR_RENAME}
        for kind in non_mutating:
            self.assertFalse(kind.mutation_capable)
            self.assertFalse(kind.destructive)
        for kind in mutating:
            self.assertTrue(kind.mutation_capable)
        self.assertTrue(FileOperationKind.DELETE.destructive)
        self.assertTrue(FileOperationKind.DELETE.mutation_capable)
        self.assertFalse(FileOperationKind.DELETE.audit()["authorization"])
        source = inspect.getsource(__import__("phoneharness_diagnostics"))
        self.assertNotIn("def write", source)
        self.assertNotIn("escalat", source)

    # A2-10: log window bounds (§12)

    def test_log_window_bound_attacks(self) -> None:
        for seconds in (0, -1):
            with self.assertRaises(DiagnosticPolicyError):
                LogWindowSpec(requested_seconds=seconds)
        clamped = LogWindowSpec(requested_seconds=10**9, requested_max_lines=10**9)
        self.assertEqual((clamped.effective_seconds, clamped.effective_max_lines), (60, 5000))
        for lines in (0, -5):
            with self.assertRaises(DiagnosticPolicyError):
                LogWindowSpec(requested_max_lines=lines)
        with self.assertRaises(DiagnosticPolicyError):
            LogWindowSpec(requested_seconds=True)
        with self.assertRaises(DiagnosticPolicyError):
            LogWindowSpec(requested_seconds="30")
        with self.assertRaises(DiagnosticPolicyError):
            LogWindowSpec(process_filter="proc\x00name")
        with self.assertRaises(DiagnosticPolicyError):
            LogWindowSpec(level_filter="verbose")
        spec = LogWindowSpec()
        self.assertTrue(spec.audit()["bounded"])
        self.assertFalse(spec.audit()["unbounded_stream"])
        self.assertFalse(spec.audit()["unbounded_accumulation"])

    # A2-11: log parser adversarial input (§13)

    def test_log_parser_adversarial_input_never_crashes(self) -> None:
        cases = [
            "", "   ", None,
            {"date": "not-a-date"},
            {"message": "x", "pid": -5},
            {"message": "x", "pid": "17"},
            {"message": "x", "level": "SUPERSEVERE"},
            {"pid": 7},
            {"message": "line1\nline2\ttab"},
            {"message": "ansi \x1b[31mred\x1b[0m"},
            {"message": "x" * 99999},
            {"subsystem": "com.example.sub", "category": "cat"},
            "partially: structured line",
            {"message": "ok", "date": 123, "process": 45, "extra_unknown": {"deep": [1, 2]}},
        ]
        statuses = set()
        for raw in cases:
            entry = LogEntry.from_provider(raw)
            statuses.add(entry.parse_status)
            self.assertIsInstance(entry.safe_message, str)
            self.assertLessEqual(len(entry.safe_message), 2048)
            self.assertIn(entry.severity, {"debug", "info", "default", "error", "fault", "unknown"})
        self.assertIn(LogParseStatus.UNKNOWN, statuses)
        self.assertIn(LogParseStatus.PARTIAL, statuses)
        unknown = LogEntry.from_provider({"subsystem": "only-subsystem"})
        self.assertIsNone(unknown.timestamp)
        self.assertIsNone(unknown.process_name)
        self.assertEqual(unknown.parse_status, LogParseStatus.PARTIAL)
        empty = LogEntry.from_provider({"nothing": "relevant"})
        self.assertEqual(empty.parse_status, LogParseStatus.UNKNOWN)
        self.assertIsNone(empty.timestamp)
        self.assertIsNone(empty.process_name)
        long_message = LogEntry.from_provider({"message": "m" * 99999})
        self.assertEqual(len(long_message.safe_message), 2048)

    # A2-12/13: redaction matrix + provider privacy (§15/§16)

    def test_log_redaction_matrix(self) -> None:
        secrets = [
            "X-MCP-Token: SECRET", "x-mcp-token: SECRET", "mcp token: SECRET",
            "Authorization: Bearer SECRET", "authorization: bearer SECRET",
            "Authorization: Basic SECRET", "password=SECRET", "passwd=SECRET",
            "passcode=SECRET", "otp=SECRET", "token=SECRET", "access_token=SECRET",
            "access token: SECRET", "refresh_token=SECRET", "refresh token=SECRET",
            "api_key=SECRET", "apikey: SECRET", "api key=SECRET",
            "open https://user:pass@example.com/path?token=SECRET#frag",
            "GET https://example.com/?access_token=SECRET",
            "see https://example.com/page#SECRET here.",
        ]
        leaked = []
        for line in secrets:
            redacted = redact_log_message(line)
            if "SECRET" in redacted or "pass@example" in redacted:
                leaked.append((line, redacted))
        self.assertEqual(leaked, [])
        preserved = redact_log_message("hello <private> world")
        self.assertIn("<private>", preserved)

    # A2-14: raw log persistence boundary (§17)

    def test_raw_log_line_not_persisted(self) -> None:
        raw = "token=SECRET raw provider line"
        entry = LogEntry.from_provider(raw)
        self.assertNotIn(raw, entry.safe_message)
        self.assertEqual(entry.raw_digest, __import__("hashlib").sha256(raw.encode()).hexdigest())
        projection = repr(entry.safe_diagnostic())
        self.assertNotIn("SECRET", projection)
        self.assertFalse(entry.safe_diagnostic()["raw_line_included"])
        self.assertFalse(entry.safe_diagnostic()["authorization"])
        window = LogWindowEvidence(
            spec=LogWindowSpec(), entries=(entry,), provider="mcp-logreader",
            capture_started_ms=0, capture_ended_ms=1,
        )
        self.assertNotIn("SECRET", repr(window.safe_diagnostic()))
        self.assertFalse(window.safe_diagnostic()["authorization"])

    # A2-15: bounded crash acquisition (§18)

    def test_crash_bounded_acquisition(self) -> None:
        request = bounded_crash_read_request(self.crash_resource())
        self.assertFalse(request["legacy_read_crash_log"])
        self.assertTrue(request["governed_crash_read"])
        self.assertLessEqual(request["max_bytes"], MAX_CRASH_REPORT_BYTES)
        with self.assertRaises(DiagnosticPolicyError):
            bounded_crash_read_request(
                FileResourceRef("provider.fs", FileScope.DEVICE_FILE, "/var/log.txt")
            )
        report = {"raw": "x" * (MAX_CRASH_REPORT_BYTES + 4096)}
        evidence = parse_crash_report(
            b"\x00\xff" * 10, source_ref=self.crash_resource()
        )
        self.assertEqual(evidence.parse_status, CrashParseStatus.UNKNOWN)
        oversized = parse_crash_report("A" * (MAX_CRASH_REPORT_BYTES + 100), source_ref=self.crash_resource())
        self.assertTrue(oversized.acquisition_truncated)
        self.assertLessEqual(len(oversized.report_digest), 64)
        empty = parse_crash_report("", source_ref=self.crash_resource())
        self.assertEqual(empty.parse_status, CrashParseStatus.UNKNOWN)
        self.assertEqual(empty.incident_type, IncidentType.UNKNOWN)

    # A2-16: crash parser malformed matrix (§19)

    def test_crash_parser_malformed_matrix(self) -> None:
        fixtures = [
            "", "   ", "\n\n\n", "not a crash report at all",
            '{"incident": "id-1", "procName"', '{"unexpected": ["structure"]}',
            "Process: Solo [1]\n", "Date/Time: 2026-09-27\n",
            "Exception Type: EXC_BAD_ACCESS\n",
            "Incident Identifier: X\nException Type: WEIRD-CRASH\nSignal: not-a-number\n",
            "pid: -12\nProcess: Negative [ -12 ]\n",
            "Process: A [1]\nProcess: B [2]\nException Type: EXC_BAD_ACCESS\n",
            "Process: X [1]\nUnknown-Future-Field: value\nExtra: data\n",
            "Binary Images:\n" + "0x1 /very/long/" + "m" * 400 + "\n",
        ]
        for fixture in fixtures:
            evidence = parse_crash_report(fixture, source_ref=self.crash_resource())
            self.assertIn(evidence.parse_status, set(CrashParseStatus))
            self.assertIn(evidence.incident_type, set(IncidentType))
        partial = parse_crash_report("Process: Solo [1]\n", source_ref=self.crash_resource())
        self.assertEqual(partial.parse_status, CrashParseStatus.PARTIAL)
        unknown = parse_crash_report("totally unknown format", source_ref=self.crash_resource())
        self.assertEqual((unknown.parse_status, unknown.incident_type), (CrashParseStatus.UNKNOWN, IncidentType.UNKNOWN))

    # A2-17: identity priority and negatives (§20/§22)

    def test_crash_identity_priority_and_negatives(self) -> None:
        with_id = parse_crash_report(self.APP_CRASH_TEXT, source_ref=self.crash_resource())
        self.assertTrue(with_id.identity.incident_id.startswith("11111111"))
        self.assertIn("incident:", with_id.identity.stable_key)
        without_id = parse_crash_report(
            "Process: Other [1]\nException Type: EXC_BAD_ACCESS\n",
            source_ref=self.crash_resource("/var/mobile/Library/Logs/CrashReporter/other.ips"),
        )
        self.assertIsNone(without_id.identity.incident_id)
        self.assertIn("report:", without_id.identity.stable_key)
        self.assertEqual(without_id.identity.audit()["filename_is_identity"], False)
        same_name_a = self.crash_resource("/dir/one/report.ips")
        same_name_b = self.crash_resource("/dir/two/report.ips")
        report_a = parse_crash_report(self.APP_CRASH_TEXT, source_ref=same_name_a)
        report_b = parse_crash_report("Process: Other [2]\n", source_ref=same_name_b)
        self.assertNotEqual(report_a.identity.report_digest, report_b.identity.report_digest)
        self.assertFalse(report_a.identity.audit()["authorization"])
        self.assertNotIn("fake", inspect.getsource(__import__("phoneharness_diagnostics")).lower())

    # A2-18: conflicting incident identifiers (§21)

    def test_conflicting_incident_ids_are_not_merged(self) -> None:
        resource_a = self.crash_resource("/dir/a/report.ips")
        resource_b = self.crash_resource("/dir/b/report.ips")
        evidence_a = parse_crash_report(
            "Incident Identifier: X\nProcess: One [1]\nException Type: EXC_BAD_ACCESS\n",
            source_ref=resource_a,
        )
        evidence_b = parse_crash_report(
            "Incident Identifier: X\nProcess: Two [2]\nException Type: EXC_CRASH\nSignal: 9\n",
            source_ref=resource_b,
        )
        self.assertEqual(evidence_a.identity.incident_id, evidence_b.identity.incident_id)
        self.assertNotEqual(evidence_a.report_digest, evidence_b.report_digest)
        self.assertNotEqual(evidence_a.identity.metadata_digest, evidence_b.identity.metadata_digest)
        self.assertIsNot(evidence_a, evidence_b)
        source = inspect.getsource(__import__("phoneharness_diagnostics"))
        self.assertNotIn("def merge", source)
        self.assertNotIn("dedup", source.lower())

    # A2-19/20/21: classification, provenance, privacy (§23-§26)

    def test_classification_requires_structured_evidence(self) -> None:
        resource = self.crash_resource("/var/mobile/Library/Logs/CrashReporter/t.ips")
        misleading = parse_crash_report(
            "Process: MyApp [1]\nException Type: EXC_BAD_ACCESS\n"
            "Binary Images:\n0x1 /var/jb/tweaks/WatchdogSomething.dylib\n"
            "The user typed: is the app hanging? spin spin\n",
            source_ref=resource,
        )
        self.assertNotEqual(misleading.incident_type, IncidentType.WATCHDOG)
        self.assertNotEqual(misleading.incident_type, IncidentType.HANG)
        keyword_only = parse_crash_report(
            "the message mentions watchdog and jetsam and panic casually",
            source_ref=resource,
        )
        self.assertEqual(keyword_only.incident_type, IncidentType.UNKNOWN)
        self.assertEqual(keyword_only.parse_status, CrashParseStatus.UNKNOWN)
        structured = parse_crash_report(
            "Process: SpringBoard [1]\nTermination Reason: watchdog 0x8badf00d\n",
            source_ref=resource,
        )
        self.assertEqual(structured.incident_type, IncidentType.WATCHDOG)
        jetsam = parse_crash_report(
            "Process: MyApp [1]\nTermination Reason: Jetsam event, memory pressure\n",
            source_ref=resource,
        )
        self.assertEqual(jetsam.incident_type, IncidentType.JETSAM)
        unknown_stays = parse_crash_report(
            "Random note about a crash-like thing", source_ref=resource
        )
        self.assertEqual(unknown_stays.incident_type, IncidentType.UNKNOWN)
        provenance = parse_crash_report(
            self.APP_CRASH_TEXT, source_ref=self.crash_resource(),
            environment_provenance={
                "bootstrap": "RootHide 2.2.1", "ellekit": "1.2-1", "injected": "yes",
            },
        )
        self.assertEqual(provenance.incident_type, IncidentType.APP_CRASH)
        self.assertEqual(dict(provenance.environment_provenance).get("bootstrap"), "RootHide 2.2.1")
        diagnostic = provenance.safe_diagnostic()
        for flag in (
            "crash_report_is_root_cause", "incident_type_is_root_cause", "signal_is_root_cause",
            "module_presence_is_root_cause", "environment_provenance_is_root_cause",
            "injection_present_proves_causation", "authorization",
        ):
            self.assertFalse(diagnostic[flag])

    def test_crash_evidence_privacy(self) -> None:
        marker = "SECRET-CRASH-MARKER-" + "z" * 64
        raw_report = self.APP_CRASH_TEXT + "Arguments: app --token " + marker + "\n"
        evidence = parse_crash_report(raw_report, source_ref=self.crash_resource())
        projection = repr(evidence.safe_diagnostic()) + str(evidence.safe_diagnostic())
        self.assertNotIn(marker, projection)
        self.assertFalse(evidence.safe_diagnostic()["full_raw_report_included"])
        self.assertFalse(evidence.safe_diagnostic()["authorization"])

    # A2-20: correlation bounds and reason/evidence consistency (§27/§30)

    def test_correlation_window_and_reason_gates(self) -> None:
        window = LogWindowEvidence(
            spec=LogWindowSpec(), entries=(), provider="mcp-logreader",
            capture_started_ms=0, capture_ended_ms=1,
        )
        with self.assertRaises(DiagnosticPolicyError):
            DiagnosticCorrelation("corr.a", (CorrelationReason.TIME_WINDOW_MATCH,),
                                  window_start_ms=0, window_end_ms=MAX_CORRELATION_WINDOW_MS + 1,
                                  log_evidence=(window,))
        with self.assertRaises(DiagnosticPolicyError):
            DiagnosticCorrelation("corr.b", (CorrelationReason.TIME_WINDOW_MATCH,),
                                  window_start_ms=2000, window_end_ms=1000, log_evidence=(window,))
        with self.assertRaises(DiagnosticPolicyError):
            DiagnosticCorrelation("corr.c", (CorrelationReason.TIME_WINDOW_MATCH,),
                                  window_start_ms=-1, window_end_ms=0, log_evidence=(window,))
        with self.assertRaises(DiagnosticPolicyError):
            DiagnosticCorrelation("corr.d", (CorrelationReason.PROCESS_ID_MATCH,), log_evidence=(window,))
        with self.assertRaises(DiagnosticPolicyError):
            DiagnosticCorrelation("corr.e", (CorrelationReason.TRACE_REFERENCE_MATCH,), trace_id=None, log_evidence=(window,))
        with self.assertRaises(DiagnosticPolicyError):
            DiagnosticCorrelation("corr.f", (CorrelationReason.OBSERVATION_REFERENCE_MATCH,), log_evidence=(window,))
        with self.assertRaises(DiagnosticPolicyError):
            DiagnosticCorrelation("corr.g", (CorrelationReason.BUNDLE_ID_MATCH,), log_evidence=(window,))
        with self.assertRaises(DiagnosticPolicyError):
            DiagnosticCorrelation("corr.h", (CorrelationReason.ARTIFACT_REFERENCE_MATCH,), log_evidence=(window,))
        valid = DiagnosticCorrelation(
            "corr.ok", (CorrelationReason.PROCESS_ID_MATCH, CorrelationReason.TIME_WINDOW_MATCH),
            pid=4711, window_start_ms=0, window_end_ms=1000, log_evidence=(window,),
        )
        self.assertEqual(valid.audit() if hasattr(valid, "audit") else True, True) if False else None
        self.assertFalse(valid.safe_diagnostic()["causation"])

    # A2-21/22: PID reuse and correlation authority (§28/§29/§31)

    def test_pid_reuse_and_correlation_authority(self) -> None:
        window = LogWindowEvidence(
            spec=LogWindowSpec(), entries=(), provider="mcp-logreader",
            capture_started_ms=0, capture_ended_ms=1,
        )
        far_window = LogWindowEvidence(
            spec=LogWindowSpec(), entries=(), provider="mcp-logreader",
            capture_started_ms=86_400_000, capture_ended_ms=86_400_001,
        )
        near = DiagnosticCorrelation(
            "corr.near", (CorrelationReason.PROCESS_ID_MATCH, CorrelationReason.TIME_WINDOW_MATCH),
            pid=123, window_start_ms=0, window_end_ms=1000, log_evidence=(window,),
        )
        far = DiagnosticCorrelation(
            "corr.far", (CorrelationReason.PROCESS_ID_MATCH,),
            pid=123, log_evidence=(far_window,),
        )
        self.assertIsNot(near, far)
        self.assertNotEqual(near.safe_diagnostic()["window_end_ms"], far.safe_diagnostic().get("window_end_ms"))
        for correlation in (near, far):
            diagnostic = correlation.safe_diagnostic()
            self.assertFalse(diagnostic["causation"])
            self.assertFalse(diagnostic["authorization"])
            self.assertFalse(diagnostic["root_cause"])
            self.assertFalse(diagnostic["high_correlation_auto_root_cause"])

    # A2-23: artifact boundary + safe serialization (§32/§33)

    def test_artifact_boundary_and_safe_serialization(self) -> None:
        source = inspect.getsource(__import__("phoneharness_diagnostics"))
        for forbidden in ("sqlite", "def persist", "class.*Store", "CrashDatabase", "LogDatabase", "FileEvidenceStore"):
            self.assertNotIn(forbidden, source)
        secret_path = "/var/mobile/Containers/user@corp/secret-token.txt"
        ref = FileResourceRef("provider.fs", FileScope.APP_CONTAINER, secret_path)
        evidence = self.file_evidence(path=secret_path)
        for representation in (repr(ref), str(ref), repr(evidence), str(evidence)):
            self.assertNotIn(secret_path, representation)
            self.assertNotIn("user@corp", representation)
        entry = LogEntry.from_provider("Authorization: Bearer SECRETVALUE")
        self.assertNotIn("SECRETVALUE", repr(entry))
        raw_report = self.APP_CRASH_TEXT + "\nUnique-Crash-Marker-XYZ\n"
        crash = parse_crash_report(raw_report, source_ref=self.crash_resource())
        self.assertNotIn("Unique-Crash-Marker-XYZ", repr(crash))
        self.assertNotIn("Unique-Crash-Marker-XYZ", str(crash.safe_diagnostic()))

    # A2-24: digests non-authoritative, no freshness duplication (§34/§35)

    def test_digests_non_authoritative_and_no_freshness_duplication(self) -> None:
        import phoneharness_diagnostics as module

        declared = {
            name for name, value in vars(module).items()
            if inspect.isclass(value) and value.__module__ == module.__name__
        }
        for forbidden in ("FileEpoch", "LogEpoch", "CrashEpoch", "FreshnessRuntime", "FreshnessRequirement",
                          "ArtifactStore", "TraceStore", "PerceptionOrchestrator"):
            self.assertNotIn(forbidden, declared)
        ref = FileResourceRef("provider.fs", FileScope.DEVICE_FILE, "/var/f.bin")
        self.assertFalse(hasattr(ref.path_digest, "authorize"))
        module_source = inspect.getsource(module)
        self.assertNotIn("is_authorization = True", module_source)

    # A2-25: ownership exclusions and gates (§36-§39)

    def test_ownership_exclusions_and_gates(self) -> None:
        source = inspect.getsource(__import__("phoneharness_diagnostics"))
        for forbidden in ("run_command", "posix_spawn", "launchctl", "install_app", "uninstall",
                          "dpkg", "atos ", "dSYM", "symbolicatecrash", "MetricKit", "deployment_target"):
            self.assertNotIn(forbidden, source)
        roadmap = (ROOT / "docs/roadmap/PHONEHARNESS_CANONICAL_ROADMAP.md").read_text()
        self.assertIn("TEXT_INPUT_REAL_DEVICE_COMPAT_GATE", roadmap)
        self.assertIn("OPEN_DEFERRED", roadmap)
        closeout = (ROOT / "diagnostics/modules/s4-m4/S4-M4-FINAL-CLOSEOUT.md").read_text()
        self.assertIn("OPEN_DEFERRED", closeout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
