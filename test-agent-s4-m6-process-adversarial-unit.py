#!/usr/bin/env python3
"""Adversarial, fail-closed Host proofs for S4-M6-A2."""

from __future__ import annotations

import inspect
import json
import math
import os
from pathlib import Path
import unittest

from phoneharness_contracts import ObservationFreshness, ObservationRef
from phoneharness_diagnostics import (
    CorrelationReason,
    DiagnosticCorrelation,
    FileResourceRef,
    FileScope,
    LogEntry,
    parse_crash_report,
)
from phoneharness_process_service import (
    ClassificationBasisKind,
    InstanceCertainty,
    InstanceIdentityStrength,
    ProcessClassificationEvidence,
    ProcessIdentity,
    ProcessInstanceDiscriminator,
    ProcessInstanceDiscriminatorKind,
    ProcessInstanceEvidence,
    ProcessOperationDescriptor,
    ProcessOperationKind,
    ProcessServicePolicyError,
    ProcessSnapshot,
    ProcessTargetClass,
    ServiceIdentity,
    ServiceOperationDescriptor,
    ServiceOperationKind,
    ServiceStateEvidence,
    ServiceStateKind,
    SnapshotCompleteness,
    ai_native_contract,
    capability_definition_candidates,
    classify_process_target,
    revalidate_process_target,
    revalidate_service_target,
)


ROOT = Path(__file__).resolve().parent
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64

THREAT_CASE_COUNTS = {
    "PROCESS_IDENTITY_ADVERSARIAL_CASES": 22,
    "PID_REUSE_CASES": 8,
    "PROCESS_SNAPSHOT_NEGATIVE_CASES": 16,
    "PROCESS_TARGET_CLASS_CASES": 12,
    "SERVICE_IDENTITY_ADVERSARIAL_CASES": 10,
    "SERVICE_STATE_NEGATIVE_CASES": 13,
    "FRESHNESS_REVALIDATION_CASES": 12,
    "AUTHORITY_CONFUSION_CASES": 11,
    "ACK_SUCCESS_CONFUSION_CASES": 6,
    "S4_M4_BOUNDARY_CASES": 4,
    "S4_M5_COMPOSITION_CASES": 4,
    "S4_M7_BOUNDARY_CASES": 7,
    "SERIALIZATION_SAFETY_CASES": 10,
    "AI_NATIVE_ADVERSARIAL_CASES": 10,
}


def observation(
    *,
    suffix: str = "0001",
    producer: str = "provider.proc",
    task: str = "task.s4m6.0001",
    session: str = "session.s4m6.0001",
    generation: int = 1,
    observed_at_ms: int = 1000,
    freshness: ObservationFreshness = ObservationFreshness.FRESH,
) -> ObservationRef:
    return ObservationRef(
        f"observation.s4m6.{suffix}",
        producer,
        task,
        session,
        generation=generation,
        observed_at_ms=observed_at_ms,
        freshness=freshness,
    )


def identity(
    name: str = "ExampleApp",
    *,
    bundle: str | None = "com.example.app",
    digest: str | None = DIGEST_A,
    provider: str = "provider.proc",
) -> ProcessIdentity:
    return ProcessIdentity(name, bundle, digest, provider)


def instance(
    *,
    pid: int | None = 101,
    marker: str | None = "generation.101",
    process_identity: ProcessIdentity | None = None,
    provider: str = "provider.proc",
    ref: ObservationRef | None = None,
    observed_at_ms: int = 1000,
    discriminators: tuple[ProcessInstanceDiscriminator, ...] = (),
) -> ProcessInstanceEvidence:
    if ref is None and pid is not None and marker is not None:
        ref = observation(producer=provider, observed_at_ms=observed_at_ms)
    return ProcessInstanceEvidence(
        process_identity or identity(provider=provider),
        pid,
        marker,
        ref,
        provider,
        observed_at_ms,
        discriminators,
    )


def snapshot(
    process_instance: ProcessInstanceEvidence | None = None,
    *,
    observed_at_ms: int = 1000,
    ref: ObservationRef | None = None,
    **changes: object,
) -> ProcessSnapshot:
    current_ref = ref or observation(observed_at_ms=observed_at_ms)
    current_instance = process_instance or instance(
        ref=current_ref, observed_at_ms=observed_at_ms
    )
    return ProcessSnapshot(
        current_instance,
        observed_at_ms,
        current_ref,
        **changes,
    )


def service_identity(
    *,
    label: str = "com.example.service",
    provider: str = "provider.service",
    digest: str | None = DIGEST_A,
) -> ServiceIdentity:
    return ServiceIdentity(label, provider, digest)


def service_state(
    state: ServiceStateKind,
    *,
    identity_value: ServiceIdentity | None = None,
    producer: str = "provider.service",
    task: str = "task.s4m6.0001",
    session: str = "session.s4m6.0001",
    observed_at_ms: int = 1000,
    freshness: ObservationFreshness = ObservationFreshness.FRESH,
    process_instance: ProcessInstanceEvidence | None = None,
) -> ServiceStateEvidence:
    ref = observation(
        producer=producer,
        task=task,
        session=session,
        observed_at_ms=observed_at_ms,
        freshness=freshness,
    )
    if state is ServiceStateKind.RUNNING and process_instance is None:
        process_instance = instance(
            provider=producer,
            process_identity=identity(provider=producer),
            ref=ref,
            observed_at_ms=observed_at_ms,
        )
    return ServiceStateEvidence(
        identity_value or service_identity(),
        state,
        observed_at_ms,
        ref,
        process_instance,
    )


def classification(
    target: ProcessInstanceEvidence,
    target_class: ProcessTargetClass,
    basis: ClassificationBasisKind,
) -> ProcessClassificationEvidence:
    return ProcessClassificationEvidence(
        target.identity,
        basis,
        f"classification.{target_class.value.lower()}",
        "provider.policy",
    )


class S4M6AdversarialContractTests(unittest.TestCase):
    def test_threat_inventory_is_explicit_and_bounded(self) -> None:
        self.assertEqual(sum(THREAT_CASE_COUNTS.values()), 145)
        self.assertEqual(len(THREAT_CASE_COUNTS), 14)

    def test_process_instance_mismatch_matrix_fails_closed(self) -> None:
        prepared = instance()
        cases = (
            instance(marker="generation.102"),
            instance(process_identity=identity(name="OtherApp")),
            instance(pid=102),
            instance(provider="provider.other"),
        )
        for candidate in cases:
            with self.subTest(candidate=candidate.safe_diagnostic()):
                self.assertFalse(prepared.same_instance_as(candidate))

    def test_partial_and_unknown_instance_evidence_never_matches(self) -> None:
        prepared = instance()
        cases = (
            instance(marker=None, ref=None),
            instance(pid=None, marker="generation.101", ref=None),
            instance(pid=None, marker=None, ref=None),
        )
        expected = (
            InstanceCertainty.PARTIAL,
            InstanceCertainty.PARTIAL,
            InstanceCertainty.UNKNOWN,
        )
        self.assertEqual(tuple(value.certainty for value in cases), expected)
        self.assertTrue(all(not prepared.same_instance_as(value) for value in cases))

    def test_instance_identity_strength_ladder_is_explicit(self) -> None:
        values = (
            instance(pid=None, marker=None, ref=None),
            instance(pid=101, marker=None, ref=None),
            instance(pid=None, marker="generation.101", ref=None),
            instance(),
        )
        self.assertEqual(
            tuple(value.identity_strength for value in values),
            (
                InstanceIdentityStrength.NONE,
                InstanceIdentityStrength.PID_ONLY,
                InstanceIdentityStrength.PARTIAL,
                InstanceIdentityStrength.STRONG_PROVIDER_EVIDENCE,
            ),
        )
        self.assertTrue(
            all(not value.safe_diagnostic()["authorization"] for value in values)
        )

    def test_typed_discriminator_options_remain_provider_abstract(self) -> None:
        for kind in ProcessInstanceDiscriminatorKind:
            discriminator = ProcessInstanceDiscriminator(
                kind,
                f"discriminator.{kind.value.lower()}",
                "provider.proc",
            )
            value = instance(
                marker=None,
                ref=observation(),
                discriminators=(discriminator,),
            )
            with self.subTest(kind=kind):
                self.assertEqual(
                    value.identity_strength,
                    InstanceIdentityStrength.STRONG_PROVIDER_EVIDENCE,
                )
                self.assertFalse(value.safe_diagnostic()["authorization"])

    def test_same_pid_conflicting_strong_discriminators_reject(self) -> None:
        old = ProcessInstanceDiscriminator(
            ProcessInstanceDiscriminatorKind.START_TIME,
            "start.1000",
            "provider.proc",
        )
        new = ProcessInstanceDiscriminator(
            ProcessInstanceDiscriminatorKind.START_TIME,
            "start.2000",
            "provider.proc",
        )
        prepared = instance(marker=None, discriminators=(old,))
        current = instance(marker=None, discriminators=(new,))
        self.assertFalse(prepared.same_instance_as(current))

    def test_strong_preparation_cannot_be_revalidated_by_fresh_pid_only(self) -> None:
        prepared = instance()
        fresh_ref = observation(suffix="fresh-weak")
        weak = instance(pid=prepared.pid, marker=None, ref=fresh_ref)
        current = snapshot(weak, ref=fresh_ref)
        self.assertEqual(weak.identity_strength, InstanceIdentityStrength.PID_ONLY)
        self.assertFalse(
            revalidate_process_target(prepared, current, now_ms=1100, max_age_ms=500)
        )

    def test_weak_preparation_cannot_match_conflicting_fresh_evidence(self) -> None:
        prepared = instance(pid=101, marker=None, ref=None)
        current = snapshot(instance(pid=101, marker="generation.replacement"))
        self.assertEqual(prepared.identity_strength, InstanceIdentityStrength.PID_ONLY)
        self.assertFalse(
            revalidate_process_target(prepared, current, now_ms=1100, max_age_ms=500)
        )

    def test_duplicate_or_untyped_discriminators_fail_closed(self) -> None:
        first = ProcessInstanceDiscriminator(
            ProcessInstanceDiscriminatorKind.UNIQUE_ID,
            "unique.first",
            "provider.proc",
        )
        second = ProcessInstanceDiscriminator(
            ProcessInstanceDiscriminatorKind.UNIQUE_ID,
            "unique.second",
            "provider.proc",
        )
        with self.assertRaises(ProcessServicePolicyError):
            instance(marker=None, discriminators=(first, second))
        with self.assertRaises(ProcessServicePolicyError):
            instance(marker=None, discriminators=("untyped",))  # type: ignore[arg-type]

    def test_invalid_pid_matrix_is_rejected(self) -> None:
        for bad_pid in (0, -1, True, 1.5, "101"):
            with self.subTest(pid=bad_pid), self.assertRaises(ProcessServicePolicyError):
                instance(pid=bad_pid)  # type: ignore[arg-type]

    def test_process_provenance_conflicts_are_rejected_at_construction(self) -> None:
        wrong_provider = observation(producer="provider.other")
        wrong_time = observation(observed_at_ms=999)
        with self.assertRaises(ProcessServicePolicyError):
            instance(ref=wrong_provider)
        with self.assertRaises(ProcessServicePolicyError):
            instance(ref=wrong_time, observed_at_ms=1000)

    def test_cross_scope_process_revalidation_is_rejected(self) -> None:
        prepared = instance(ref=observation(task="task.s4m6.prepare"))
        fresh_ref = observation(task="task.s4m6.other")
        fresh = snapshot(instance(ref=fresh_ref), ref=fresh_ref)
        self.assertFalse(
            revalidate_process_target(prepared, fresh, now_ms=1100, max_age_ms=500)
        )

    def test_pid_reuse_sequence_never_retargets(self) -> None:
        prepared = instance(pid=404, marker="generation.old")
        reused_ref = observation(suffix="reuse")
        reused = instance(
            pid=404,
            marker="generation.new",
            process_identity=identity(name="ReplacementApp", digest=DIGEST_B),
            ref=reused_ref,
        )
        fresh = snapshot(reused, ref=reused_ref)
        self.assertFalse(
            revalidate_process_target(prepared, fresh, now_ms=1100, max_age_ms=500)
        )

    def test_process_freshness_exact_boundary_passes_and_next_tick_fails(self) -> None:
        prepared = instance()
        current = snapshot(instance())
        self.assertTrue(
            revalidate_process_target(prepared, current, now_ms=1500, max_age_ms=500)
        )
        self.assertFalse(
            revalidate_process_target(prepared, current, now_ms=1501, max_age_ms=500)
        )

    def test_process_clock_reversal_is_rejected(self) -> None:
        self.assertFalse(
            revalidate_process_target(
                instance(), snapshot(), now_ms=999, max_age_ms=500
            )
        )

    def test_snapshot_missing_values_remain_unknown_not_zero(self) -> None:
        value = snapshot()
        self.assertEqual(value.completeness, SnapshotCompleteness.UNKNOWN)
        for field in (
            value.cpu_observation,
            value.memory_observation_bytes,
            value.thread_count,
            value.wakeup_observation,
            value.foreground_relation,
            value.state,
        ):
            self.assertIsNone(field)
        self.assertEqual(value.observed_fields, ())

    def test_snapshot_partial_never_becomes_complete(self) -> None:
        value = snapshot(state="running", cpu_observation=0.0)
        self.assertEqual(value.completeness, SnapshotCompleteness.PARTIAL)
        self.assertEqual(value.cpu_observation, 0.0)
        self.assertNotIn("memory", value.observed_fields)

    def test_snapshot_impossible_metric_matrix_is_rejected(self) -> None:
        cases = (
            {"cpu_observation": -0.1},
            {"cpu_observation": 100.1},
            {"cpu_observation": math.nan},
            {"cpu_observation": math.inf},
            {"memory_observation_bytes": -1},
            {"thread_count": -1},
            {"wakeup_observation": -1},
            {"thread_count": True},
        )
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ProcessServicePolicyError):
                snapshot(**changes)

    def test_snapshot_instance_and_observation_must_be_same_event(self) -> None:
        first = observation(suffix="first")
        second = observation(suffix="second")
        with self.assertRaises(ProcessServicePolicyError):
            snapshot(instance(ref=first), ref=second)

    def test_stale_resource_snapshot_cannot_revalidate(self) -> None:
        ref = observation(freshness=ObservationFreshness.STALE)
        value = snapshot(instance(ref=ref), ref=ref)
        self.assertFalse(
            revalidate_process_target(instance(), value, now_ms=1100, max_age_ms=500)
        )

    def test_missing_classification_degrades_to_unknown(self) -> None:
        target = instance()
        self.assertEqual(
            classify_process_target(target).target_class,
            ProcessTargetClass.UNKNOWN_TARGET,
        )
        self.assertEqual(
            classify_process_target(
                target,
                claimed_class=ProcessTargetClass.NORMAL_USER_PROCESS,
                evidence=None,
            ).target_class,
            ProcessTargetClass.UNKNOWN_TARGET,
        )

    def test_arbitrary_names_never_infer_target_class(self) -> None:
        for name in ("PhoneHarness", "ios-mcp", "launchd", "securityd", "safe-user-app"):
            target = instance(process_identity=identity(name=name))
            with self.subTest(name=name):
                self.assertEqual(
                    classify_process_target(target).target_class,
                    ProcessTargetClass.UNKNOWN_TARGET,
                )

    def test_classification_evidence_is_bound_to_exact_subject(self) -> None:
        first = instance(process_identity=identity(name="First"))
        second = instance(process_identity=identity(name="Second"))
        evidence = classification(
            first,
            ProcessTargetClass.NORMAL_USER_PROCESS,
            ClassificationBasisKind.PROVIDER_ATTESTED,
        )
        with self.assertRaises(ProcessServicePolicyError):
            classify_process_target(
                second,
                claimed_class=ProcessTargetClass.NORMAL_USER_PROCESS,
                evidence=evidence,
            )

    def test_protected_target_classes_are_never_auto_mutable(self) -> None:
        cases = (
            (
                ProcessTargetClass.CONTROL_PLANE_SELF,
                ClassificationBasisKind.CONTROL_PLANE_REGISTRY,
            ),
            (ProcessTargetClass.SYSTEM_CRITICAL, ClassificationBasisKind.SYSTEM_POLICY),
            (ProcessTargetClass.SECURITY_SENSITIVE, ClassificationBasisKind.SYSTEM_POLICY),
        )
        for target_class, basis in cases:
            target = instance()
            protection = classify_process_target(
                target,
                claimed_class=target_class,
                evidence=classification(target, target_class, basis),
            )
            with self.subTest(target_class=target_class):
                self.assertFalse(protection.mutation_candidate_allowed)
                self.assertFalse(protection.auto_mutatable)
                self.assertFalse(protection.safe_diagnostic()["authorization"])

    def test_normal_target_is_only_candidate_never_authorized(self) -> None:
        target = instance()
        protection = classify_process_target(
            target,
            claimed_class=ProcessTargetClass.NORMAL_USER_PROCESS,
            evidence=classification(
                target,
                ProcessTargetClass.NORMAL_USER_PROCESS,
                ClassificationBasisKind.PROVIDER_ATTESTED,
            ),
        )
        self.assertTrue(protection.mutation_candidate_allowed)
        self.assertFalse(protection.auto_mutatable)
        self.assertFalse(protection.safe_diagnostic()["authorization"])

    def test_invalid_classification_basis_is_rejected(self) -> None:
        target = instance()
        evidence = classification(
            target,
            ProcessTargetClass.NORMAL_USER_PROCESS,
            ClassificationBasisKind.PROVIDER_ATTESTED,
        )
        with self.assertRaises(ProcessServicePolicyError):
            classify_process_target(
                target,
                claimed_class=ProcessTargetClass.CONTROL_PLANE_SELF,
                evidence=evidence,
            )

    def test_process_operation_descriptors_never_gain_runtime_meaning(self) -> None:
        for kind in ProcessOperationKind:
            value = ProcessOperationDescriptor(
                f"descriptor.process.{kind.value.lower()}",
                kind,
                instance(),
                requires_privilege="ROOT",
            )
            diagnostic = value.safe_diagnostic()
            with self.subTest(kind=kind):
                self.assertFalse(value.prepared_operation_auto_executable)
                self.assertFalse(diagnostic["authorization"])
                self.assertFalse(diagnostic["privilege_is_authorization"])
                self.assertFalse(diagnostic["provider_ack_is_semantic_success"])

    def test_malformed_and_cross_domain_process_operations_are_rejected(self) -> None:
        for kind in ("START", "RESTART", "KILLALL", ""):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                ProcessOperationDescriptor("descriptor.process.bad", kind, instance())  # type: ignore[arg-type]
        with self.assertRaises(ProcessServicePolicyError):
            ProcessOperationDescriptor(
                "descriptor.process.bad-privilege",
                ProcessOperationKind.SIGNAL,
                instance(),
                requires_privilege="ADMIN",
            )

    def test_service_identity_dimensions_are_not_collapsed(self) -> None:
        baseline = service_identity()
        self.assertFalse(baseline.same_service_as(service_identity(digest=DIGEST_B)))
        self.assertFalse(
            baseline.same_service_as(service_identity(provider="provider.other"))
        )
        diagnostic = baseline.safe_diagnostic()
        self.assertFalse(diagnostic["label_is_process_instance"])
        self.assertFalse(diagnostic["label_is_pid"])
        self.assertFalse(diagnostic["authorization"])
        self.assertFalse(hasattr(baseline, "executable"))

    def test_missing_and_invalid_service_labels_are_rejected(self) -> None:
        for label in ("", "x", "bad label", "/service/path", 123):
            with self.subTest(label=label), self.assertRaises(ProcessServicePolicyError):
                service_identity(label=label)  # type: ignore[arg-type]

    def test_service_state_values_remain_distinct(self) -> None:
        values = {state.value for state in ServiceStateKind}
        self.assertEqual(
            values,
            {"RUNNING", "STOPPED", "UNKNOWN", "TRANSITIONING", "UNAVAILABLE"},
        )
        states = {
            state: service_state(state).state
            for state in (
                ServiceStateKind.STOPPED,
                ServiceStateKind.UNKNOWN,
                ServiceStateKind.TRANSITIONING,
                ServiceStateKind.UNAVAILABLE,
            )
        }
        self.assertEqual(len(set(states.values())), 4)

    def test_running_service_requires_typed_current_instance(self) -> None:
        ref = observation(producer="provider.service")
        with self.assertRaises(ProcessServicePolicyError):
            ServiceStateEvidence(
                service_identity(), ServiceStateKind.RUNNING, 1000, ref, None
            )

    def test_service_state_timestamp_and_instance_provenance_conflicts_reject(self) -> None:
        wrong_time = observation(producer="provider.service", observed_at_ms=999)
        with self.assertRaises(ProcessServicePolicyError):
            ServiceStateEvidence(
                service_identity(), ServiceStateKind.UNKNOWN, 1000, wrong_time
            )
        service_ref = observation(producer="provider.service", suffix="service")
        process_ref = observation(producer="provider.service", suffix="process")
        with self.assertRaises(ProcessServicePolicyError):
            ServiceStateEvidence(
                service_identity(),
                ServiceStateKind.RUNNING,
                1000,
                service_ref,
                instance(
                    provider="provider.service",
                    process_identity=identity(provider="provider.service"),
                    ref=process_ref,
                ),
            )

    def test_service_revalidation_matrix_fails_closed(self) -> None:
        prepared = service_state(ServiceStateKind.STOPPED)
        cases = (
            service_state(ServiceStateKind.STOPPED, observed_at_ms=1),
            service_state(ServiceStateKind.UNKNOWN),
            service_state(
                ServiceStateKind.STOPPED,
                identity_value=service_identity(digest=DIGEST_B),
            ),
            service_state(ServiceStateKind.STOPPED, producer="provider.other"),
            service_state(ServiceStateKind.STOPPED, task="task.s4m6.other"),
            service_state(ServiceStateKind.STOPPED, session="session.s4m6.other"),
        )
        for current in cases:
            with self.subTest(current=current.safe_diagnostic()):
                self.assertFalse(
                    revalidate_service_target(
                        prepared, current, now_ms=1100, max_age_ms=500
                    )
                )

    def test_running_service_revalidation_rejects_process_replacement(self) -> None:
        prepared = service_state(ServiceStateKind.RUNNING)
        fresh_ref = observation(producer="provider.service")
        replacement = instance(
            pid=202,
            marker="generation.202",
            provider="provider.service",
            process_identity=identity(provider="provider.service"),
            ref=fresh_ref,
        )
        current = ServiceStateEvidence(
            service_identity(),
            ServiceStateKind.RUNNING,
            1000,
            fresh_ref,
            replacement,
        )
        self.assertFalse(
            revalidate_service_target(prepared, current, now_ms=1100, max_age_ms=500)
        )

    def test_service_freshness_boundary_is_exact(self) -> None:
        prepared = service_state(ServiceStateKind.STOPPED)
        current = service_state(ServiceStateKind.STOPPED)
        self.assertTrue(
            revalidate_service_target(prepared, current, now_ms=1500, max_age_ms=500)
        )
        self.assertFalse(
            revalidate_service_target(prepared, current, now_ms=1501, max_age_ms=500)
        )

    def test_provider_failure_and_timeout_do_not_become_stopped(self) -> None:
        unavailable = service_state(ServiceStateKind.UNAVAILABLE)
        unknown = service_state(ServiceStateKind.UNKNOWN)
        self.assertIsNot(unavailable.state, ServiceStateKind.STOPPED)
        self.assertIsNot(unknown.state, ServiceStateKind.STOPPED)
        self.assertFalse(unavailable.semantic_facts()["unknown_is_stopped"])
        self.assertFalse(unknown.semantic_facts()["unknown_is_stopped"])

    def test_service_operation_descriptors_never_dispatch_or_succeed(self) -> None:
        for kind in ServiceOperationKind:
            value = ServiceOperationDescriptor(
                f"descriptor.service.{kind.value.lower()}",
                kind,
                service_identity(),
                requires_privilege="ROOT",
            )
            diagnostic = value.safe_diagnostic()
            with self.subTest(kind=kind):
                self.assertFalse(value.prepared_operation_auto_executable)
                self.assertFalse(diagnostic["authorization"])
                self.assertFalse(diagnostic["provider_ack_is_semantic_success"])

    def test_malformed_and_cross_domain_service_operations_are_rejected(self) -> None:
        for kind in ("TERMINATE", "SIGNAL", "KICKSTART", ""):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                ServiceOperationDescriptor("descriptor.service.bad", kind, service_identity())  # type: ignore[arg-type]

    def test_authority_confusion_matrix_is_false(self) -> None:
        target = instance()
        protection = classify_process_target(target)
        values = (
            target.identity.safe_diagnostic()["authorization"],
            snapshot().safe_diagnostic()["authorization"],
            protection.safe_diagnostic()["authorization"],
            service_identity().safe_diagnostic()["authorization"],
            service_state(ServiceStateKind.UNKNOWN).safe_diagnostic()["authorization"],
            snapshot().semantic_facts()["authorization"],
            ai_native_contract()["authorization"],
            ProcessOperationDescriptor(
                "descriptor.process.auth", ProcessOperationKind.SIGNAL, target
            ).safe_diagnostic()["authorization"],
            ServiceOperationDescriptor(
                "descriptor.service.auth", ServiceOperationKind.RESTART, service_identity()
            ).safe_diagnostic()["authorization"],
        )
        self.assertEqual(values, (False,) * len(values))

    def test_capability_and_privilege_are_not_authority(self) -> None:
        candidates = capability_definition_candidates()
        self.assertTrue(candidates)
        self.assertTrue(all(item["descriptor_only"] for item in candidates))
        descriptor = ProcessOperationDescriptor(
            "descriptor.process.root",
            ProcessOperationKind.TERMINATE,
            instance(),
            requires_privilege="ROOT",
        )
        self.assertFalse(descriptor.safe_diagnostic()["privilege_is_authorization"])

    def test_ack_success_and_unknown_outcome_are_not_promoted(self) -> None:
        process_diag = ProcessOperationDescriptor(
            "descriptor.process.ack", ProcessOperationKind.SIGNAL, instance()
        ).safe_diagnostic()
        service_diag = ServiceOperationDescriptor(
            "descriptor.service.ack", ServiceOperationKind.RESTART, service_identity()
        ).safe_diagnostic()
        self.assertFalse(process_diag["provider_ack_is_semantic_success"])
        self.assertFalse(service_diag["provider_ack_is_semantic_success"])
        source = inspect.getsource(__import__("phoneharness_process_service"))
        self.assertNotIn("blind_retry", source.lower())
        self.assertNotIn("exit_0_is_success", source.lower())
        self.assertNotIn("dispatch_delivered = true", source.lower())

    def test_s4_m4_app_lifecycle_ownership_is_not_duplicated(self) -> None:
        source = inspect.getsource(__import__("phoneharness_process_service"))
        for forbidden in (
            "FBSSystemService",
            "LSApplicationWorkspace",
            "launchApp",
            "frontmostApplication",
        ):
            self.assertNotIn(forbidden, source)
        self.assertNotIn("START", {kind.value for kind in ProcessOperationKind})

    def test_s4_m5_log_and_crash_composition_remains_noncausal(self) -> None:
        log = LogEntry.from_provider(
            {"message": "bounded event", "pid": 101, "process": "ExampleApp"}
        )
        crash_source = FileResourceRef(
            "provider.filesystem",
            FileScope.CRASH_REPORT,
            "/var/mobile/Library/Logs/CrashReporter/ExampleApp.ips",
        )
        crash = parse_crash_report(
            "Process: ExampleApp [101]\nIdentifier: com.example.app\nSignal: SIGABRT",
            source_ref=crash_source,
        )
        correlation = DiagnosticCorrelation(
            "correlation.s4m6.0001",
            (
                CorrelationReason.PROCESS_ID_MATCH,
                CorrelationReason.BUNDLE_ID_MATCH,
                CorrelationReason.TIME_WINDOW_MATCH,
            ),
            bundle_id="com.example.app",
            pid=101,
            window_start_ms=900,
            window_end_ms=1100,
            crash_evidence=(crash,),
        )
        self.assertEqual(log.pid, snapshot().instance.pid)
        diagnostic = correlation.safe_diagnostic()
        self.assertFalse(diagnostic["causation"])
        self.assertFalse(diagnostic["root_cause"])
        self.assertFalse(diagnostic["authorization"])

    def test_s4_m7_shell_boundary_is_closed(self) -> None:
        source = inspect.getsource(__import__("phoneharness_process_service")).lower()
        for forbidden in (
            "run_command",
            "subprocess",
            "/bin/sh",
            "launchctl",
            "killall",
            "os.system",
            "posix_spawn",
        ):
            self.assertNotIn(forbidden, source)

    def test_safe_serialization_is_minimized_and_secret_free(self) -> None:
        sensitive_name = "password=do-not-persist"
        value = ProcessIdentity(process_name=sensitive_name, provider="provider.proc")
        payload = json.dumps(
            {
                "identity": value.safe_diagnostic(),
                "instance": instance().safe_diagnostic(),
                "snapshot": snapshot().safe_diagnostic(),
                "service": service_state(ServiceStateKind.UNKNOWN).safe_diagnostic(),
            },
            sort_keys=True,
        ).lower()
        for forbidden in (
            sensitive_name,
            "mcp_token",
            "authorization_header",
            "credential",
            "/private/var/",
            "environment",
        ):
            self.assertNotIn(forbidden, payload)

    def test_diagnostic_json_roundtrip_never_strengthens_certainty(self) -> None:
        partial = instance(marker=None, ref=None).safe_diagnostic()
        restored = json.loads(json.dumps(partial))
        self.assertEqual(restored["certainty"], InstanceCertainty.PARTIAL.value)
        self.assertEqual(restored["identity_strength"], InstanceIdentityStrength.PID_ONLY.value)
        self.assertFalse(restored["authorization"])

        unknown = classify_process_target(instance()).safe_diagnostic()
        restored_unknown = json.loads(json.dumps(unknown))
        self.assertEqual(restored_unknown["target_class"], "UNKNOWN_TARGET")
        self.assertFalse(restored_unknown["mutation_candidate_allowed"])

    def test_path_like_names_and_control_text_are_rejected(self) -> None:
        for value in ("/private/var/secret", "folder\\binary", "bad\nname"):
            with self.subTest(value=value), self.assertRaises(ProcessServicePolicyError):
                ProcessIdentity(process_name=value, provider="provider.proc")

    def test_non_string_identifiers_and_digests_are_rejected(self) -> None:
        with self.assertRaises(ProcessServicePolicyError):
            ProcessIdentity(process_name=123, provider="provider.proc")  # type: ignore[arg-type]
        with self.assertRaises(ProcessServicePolicyError):
            ProcessIdentity(process_name="App", executable_digest=123)  # type: ignore[arg-type]
        with self.assertRaises(ProcessServicePolicyError):
            ServiceIdentity(123)  # type: ignore[arg-type]

    def test_ai_native_surface_is_shared_descriptive_and_non_authoritative(self) -> None:
        contract = ai_native_contract()
        self.assertTrue(contract["SHARED_SEMANTIC_CONTEXT_CONNECTED"])
        self.assertFalse(contract["authorization"])
        self.assertFalse(contract["SECOND_AI_RUNTIME_ADDED"])
        self.assertFalse(contract["SECOND_WORLD_MODEL_ADDED"])
        self.assertFalse(contract["SECOND_MEMORY_SYSTEM_ADDED"])
        self.assertIn("shared semantic context", contract["AI_CONTEXT_INTEGRATION"])

    def test_no_module_local_intelligence_or_context_store(self) -> None:
        source = inspect.getsource(__import__("phoneharness_process_service")).lower()
        for forbidden in (
            "import openai",
            "llm_client",
            "knowledge_store",
            "memory_store",
            "world_model_store",
            "semantic_context_database",
            "sqlite",
        ):
            self.assertNotIn(forbidden, source)

    def test_p24_timing_evidence_is_honest_without_latency_claims(self) -> None:
        value = snapshot()
        self.assertEqual(value.observed_at_ms, 1000)
        self.assertEqual(value.observation_ref.observed_at_ms, 1000)
        self.assertEqual(value.instance.provider, value.observation_ref.producer)
        source = inspect.getsource(__import__("phoneharness_process_service")).lower()
        self.assertNotIn("zero_latency", source)
        self.assertNotIn("exactly_one_second", source)

    def test_module_contains_no_execution_or_environment_access(self) -> None:
        source = inspect.getsource(__import__("phoneharness_process_service"))
        self.assertNotIn("os.environ", source)
        self.assertNotIn("os.kill", source)
        self.assertNotIn("signal.signal", source)
        self.assertNotIn("Popen", source)
        self.assertFalse(hasattr(__import__("phoneharness_process_service"), "execute"))
        self.assertNotIn(str(os.environ), source)

    def test_provider_specific_process_apis_remain_reserved_for_a3(self) -> None:
        source = inspect.getsource(__import__("phoneharness_process_service")).lower()
        for forbidden in (
            "proc_pid",
            "audit_token_t",
            "sysctl",
            "libproc",
            "roothide",
            "bootstrap 2.2.1",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
