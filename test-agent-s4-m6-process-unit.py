#!/usr/bin/env python3
"""Contract-first Host proofs for S4-M6-A1 Process / Service types."""

from __future__ import annotations

import inspect
import json
from pathlib import Path
import unittest

from phoneharness_contracts import (
    ActionCandidateSet,
    ObservationFreshness,
    ObservationRef,
    ObservedTargetRef,
)
from phoneharness_diagnostics import LogEntry
from phoneharness_process_service import (
    AI_LEARNING_HOOK_RULE,
    ClassificationBasisKind,
    InstanceCertainty,
    ProcessClassificationEvidence,
    ProcessIdentity,
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
    ai_learning_hook,
    ai_native_contract,
    capability_definition_candidates,
    classify_process_target,
    revalidate_process_target,
    revalidate_service_target,
)


ROOT = Path(__file__).resolve().parent
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def observation(
    *,
    suffix: str = "0001",
    observed_at_ms: int = 1000,
    freshness: ObservationFreshness = ObservationFreshness.FRESH,
) -> ObservationRef:
    return ObservationRef(
        f"observation.s4m6.{suffix}",
        "provider.proc",
        "task.s4m6.0001",
        "session.s4m6.0001",
        generation=1,
        observed_at_ms=observed_at_ms,
        freshness=freshness,
    )


def identity(
    name: str = "SpringBoard",
    *,
    bundle: str | None = None,
    digest: str | None = DIGEST_A,
    provider: str = "provider.proc",
) -> ProcessIdentity:
    return ProcessIdentity(
        process_name=name,
        bundle_id=bundle,
        executable_digest=digest,
        provider=provider,
    )


def instance(
    *,
    pid: int | None = 2089,
    marker: str | None = "generation.970",
    name: str = "SpringBoard",
    digest: str | None = DIGEST_A,
    provider: str = "provider.proc",
    observation_ref: ObservationRef | None = None,
    observed_at_ms: int = 1000,
) -> ProcessInstanceEvidence:
    ref = observation_ref
    if ref is None and pid is not None and marker is not None:
        ref = observation(observed_at_ms=observed_at_ms)
    return ProcessInstanceEvidence(
        identity=identity(name, digest=digest, provider=provider),
        pid=pid,
        generation_marker=marker,
        observation_ref=ref,
        provider=provider,
        observed_at_ms=observed_at_ms,
    )


def snapshot(
    *,
    process_instance: ProcessInstanceEvidence | None = None,
    observed_at_ms: int = 1000,
    observation_ref: ObservationRef | None = None,
    **kwargs,
) -> ProcessSnapshot:
    ref = observation_ref or observation(observed_at_ms=observed_at_ms)
    return ProcessSnapshot(
        instance=process_instance or instance(observation_ref=ref, observed_at_ms=observed_at_ms),
        observed_at_ms=observed_at_ms,
        observation_ref=ref,
        **kwargs,
    )


def service_identity(
    *, provider: str = "provider.service", digest: str | None = DIGEST_A
) -> ServiceIdentity:
    return ServiceIdentity(
        "com.example.service", provider=provider, definition_digest=digest
    )


def service_state(
    state: ServiceStateKind,
    *,
    identity_value: ServiceIdentity | None = None,
    observed_at_ms: int = 1000,
    observation_ref: ObservationRef | None = None,
    process_instance: ProcessInstanceEvidence | None = None,
) -> ServiceStateEvidence:
    ref = observation_ref or observation(observed_at_ms=observed_at_ms)
    if state is ServiceStateKind.RUNNING and process_instance is None:
        process_instance = instance(observation_ref=ref, observed_at_ms=observed_at_ms)
    return ServiceStateEvidence(
        identity_value or service_identity(),
        state,
        observed_at_ms,
        ref,
        process_instance,
    )


class S4M6ProcessServiceTests(unittest.TestCase):
    def test_process_identity_requires_real_evidence(self) -> None:
        with self.assertRaises(ProcessServicePolicyError):
            ProcessIdentity(provider="provider.proc")

    def test_process_identity_uses_digest_not_full_path(self) -> None:
        value = identity()
        self.assertFalse(hasattr(value, "executable_projection"))
        self.assertEqual(value.executable_digest, DIGEST_A)
        self.assertNotIn("path", json.dumps(value.safe_diagnostic()).lower())

    def test_process_identity_exact_comparison_rejects_disjoint_evidence(self) -> None:
        by_name = ProcessIdentity(process_name="App", provider="provider.proc")
        by_bundle = ProcessIdentity(bundle_id="com.example.app", provider="provider.proc")
        self.assertFalse(by_name.same_logical_identity_as(by_bundle))

    def test_process_identity_provider_is_part_of_identity(self) -> None:
        self.assertFalse(
            identity(provider="provider.one").same_logical_identity_as(
                identity(provider="provider.two")
            )
        )

    def test_pid_must_be_positive_when_present(self) -> None:
        with self.assertRaises(ProcessServicePolicyError):
            instance(pid=0)
        with self.assertRaises(ProcessServicePolicyError):
            instance(pid=-1)

    def test_pid_alone_is_partial_not_stable_identity(self) -> None:
        value = instance(marker=None, observation_ref=None)
        self.assertEqual(value.certainty, InstanceCertainty.PARTIAL)
        self.assertFalse(value.safe_diagnostic()["PID_MATCH_ALONE_PROVES_SAME_PROCESS_INSTANCE"])

    def test_generation_without_observation_is_partial(self) -> None:
        value = instance(pid=None, marker="generation.1", observation_ref=None)
        self.assertEqual(value.certainty, InstanceCertainty.PARTIAL)

    def test_identity_without_instance_markers_is_unknown(self) -> None:
        value = instance(pid=None, marker=None, observation_ref=None)
        self.assertEqual(value.certainty, InstanceCertainty.UNKNOWN)

    def test_complete_instance_evidence_is_strong(self) -> None:
        self.assertEqual(instance().certainty, InstanceCertainty.STRONG)

    def test_pid_reuse_never_matches(self) -> None:
        prepared = instance(pid=300, marker="generation.old")
        reused = instance(pid=300, marker="generation.new", name="Other")
        self.assertFalse(prepared.same_instance_as(reused))

    def test_same_pid_generation_and_identity_matches(self) -> None:
        self.assertTrue(instance().same_instance_as(instance()))

    def test_same_generation_but_different_pid_fails(self) -> None:
        self.assertFalse(instance(pid=10).same_instance_as(instance(pid=11)))

    def test_same_instance_requires_strong_evidence_on_both_sides(self) -> None:
        self.assertFalse(instance().same_instance_as(instance(marker=None)))

    def test_process_snapshot_missing_metrics_are_unknown_not_zero(self) -> None:
        value = snapshot()
        self.assertEqual(value.completeness, SnapshotCompleteness.UNKNOWN)
        self.assertIsNone(value.cpu_observation)
        self.assertFalse(value.safe_diagnostic()["missing_value_means_zero"])

    def test_process_snapshot_partial_and_complete_are_explicit(self) -> None:
        partial = snapshot(state="running")
        complete = snapshot(
            state="running",
            cpu_observation=1.0,
            memory_observation_bytes=2,
            thread_count=3,
            wakeup_observation=4,
            foreground_relation="foreground",
        )
        self.assertEqual(partial.completeness, SnapshotCompleteness.PARTIAL)
        self.assertEqual(complete.completeness, SnapshotCompleteness.COMPLETE)

    def test_process_snapshot_rejects_invalid_metrics(self) -> None:
        with self.assertRaises(ProcessServicePolicyError):
            snapshot(cpu_observation=100.1)
        with self.assertRaises(ProcessServicePolicyError):
            snapshot(memory_observation_bytes=-1)

    def test_process_revalidation_passes_only_for_fresh_same_instance(self) -> None:
        prepared = instance()
        fresh = snapshot(process_instance=instance())
        self.assertTrue(
            revalidate_process_target(prepared, fresh, now_ms=1100, max_age_ms=500)
        )

    def test_process_revalidation_rejects_stale_observation(self) -> None:
        self.assertFalse(
            revalidate_process_target(
                instance(), snapshot(), now_ms=2000, max_age_ms=500
            )
        )

    def test_process_revalidation_rejects_nonfresh_s4m0_ref(self) -> None:
        ref = observation(freshness=ObservationFreshness.UNKNOWN)
        stale = snapshot(
            process_instance=instance(observation_ref=ref), observation_ref=ref
        )
        self.assertFalse(
            revalidate_process_target(instance(), stale, now_ms=1100, max_age_ms=500)
        )

    def test_process_revalidation_rejects_observation_timestamp_mismatch(self) -> None:
        ref = observation(observed_at_ms=999)
        with self.assertRaises(ProcessServicePolicyError):
            snapshot(observed_at_ms=1000, observation_ref=ref)

    def test_unknown_target_is_never_safe(self) -> None:
        protection = classify_process_target(instance())
        self.assertEqual(protection.target_class, ProcessTargetClass.UNKNOWN_TARGET)
        self.assertFalse(protection.mutation_candidate_allowed)
        self.assertFalse(protection.auto_mutatable)

    def test_arbitrary_string_cannot_be_classification_evidence(self) -> None:
        with self.assertRaises(TypeError):
            classify_process_target(instance(), basis="trust me")  # type: ignore[call-arg]

    def test_control_plane_class_requires_control_plane_registry(self) -> None:
        target = instance()
        evidence = ProcessClassificationEvidence(
            target.identity,
            ClassificationBasisKind.CONTROL_PLANE_REGISTRY,
            "registry.control-plane.1",
            "provider.policy",
        )
        protection = classify_process_target(
            target,
            claimed_class=ProcessTargetClass.CONTROL_PLANE_SELF,
            evidence=evidence,
        )
        self.assertFalse(protection.mutation_candidate_allowed)
        self.assertTrue(protection.mutation_requires_user_confirmation)

    def test_invalid_target_class_basis_pair_fails_closed(self) -> None:
        target = instance()
        evidence = ProcessClassificationEvidence(
            target.identity,
            ClassificationBasisKind.PROVIDER_ATTESTED,
            "provider.evidence.1",
            "provider.proc",
        )
        with self.assertRaises(ProcessServicePolicyError):
            classify_process_target(
                target,
                claimed_class=ProcessTargetClass.CONTROL_PLANE_SELF,
                evidence=evidence,
            )

    def test_normal_user_target_is_candidate_not_authorized(self) -> None:
        target = instance()
        evidence = ProcessClassificationEvidence(
            target.identity,
            ClassificationBasisKind.PROVIDER_ATTESTED,
            "provider.evidence.2",
            "provider.proc",
        )
        protection = classify_process_target(
            target,
            claimed_class=ProcessTargetClass.NORMAL_USER_PROCESS,
            evidence=evidence,
        )
        self.assertTrue(protection.mutation_candidate_allowed)
        self.assertFalse(protection.safe_diagnostic()["authorization"])
        self.assertFalse(protection.auto_mutatable)

    def test_process_operation_kinds_match_contract(self) -> None:
        self.assertEqual(
            {kind.value for kind in ProcessOperationKind},
            {"OBSERVE", "TERMINATE", "SIGNAL", "SUSPEND", "RESUME"},
        )
        self.assertNotIn("START", {kind.value for kind in ProcessOperationKind})

    def test_process_descriptor_is_nonexecutable_and_nonauthoritative(self) -> None:
        value = ProcessOperationDescriptor(
            "process.operation.1",
            ProcessOperationKind.TERMINATE,
            instance(),
            requires_privilege="ROOT",
            readback_supported=True,
        )
        diagnostic = value.safe_diagnostic()
        self.assertFalse(value.prepared_operation_auto_executable)
        self.assertFalse(diagnostic["authorization"])
        self.assertFalse(diagnostic["privilege_is_authorization"])
        self.assertFalse(diagnostic["provider_ack_is_semantic_success"])

    def test_service_identity_is_not_process_identity(self) -> None:
        diagnostic = service_identity().safe_diagnostic()
        self.assertFalse(diagnostic["label_is_process_instance"])
        self.assertFalse(diagnostic["label_is_pid"])
        self.assertNotIn("pid", service_identity().__dict__)

    def test_service_identity_provider_and_definition_are_identity(self) -> None:
        baseline = service_identity()
        self.assertFalse(baseline.same_service_as(service_identity(provider="provider.other")))
        self.assertFalse(baseline.same_service_as(service_identity(digest=DIGEST_B)))

    def test_service_unknown_is_not_stopped(self) -> None:
        unknown = service_state(ServiceStateKind.UNKNOWN)
        stopped = service_state(ServiceStateKind.STOPPED)
        self.assertNotEqual(unknown.state, stopped.state)
        self.assertFalse(unknown.safe_diagnostic()["unknown_forced_to_stopped"])

    def test_running_service_requires_current_instance_evidence(self) -> None:
        with self.assertRaises(ProcessServicePolicyError):
            ServiceStateEvidence(
                service_identity(),
                ServiceStateKind.RUNNING,
                1000,
                observation(),
            )

    def test_service_state_requires_observation_ref(self) -> None:
        with self.assertRaises(ProcessServicePolicyError):
            ServiceStateEvidence(  # type: ignore[arg-type]
                service_identity(), ServiceStateKind.UNKNOWN, 1000, None
            )

    def test_service_freshness_reuses_s4m0_ref(self) -> None:
        value = service_state(ServiceStateKind.STOPPED)
        self.assertTrue(value.is_fresh(now_ms=1200, max_age_ms=500))
        self.assertFalse(value.is_fresh(now_ms=2000, max_age_ms=500))

    def test_service_revalidation_rejects_stale_state(self) -> None:
        prepared = service_state(ServiceStateKind.STOPPED)
        fresh = service_state(ServiceStateKind.STOPPED)
        self.assertFalse(
            revalidate_service_target(prepared, fresh, now_ms=2000, max_age_ms=500)
        )

    def test_service_revalidation_rejects_different_identity(self) -> None:
        prepared = service_state(ServiceStateKind.STOPPED)
        other = service_state(
            ServiceStateKind.STOPPED,
            identity_value=service_identity(provider="provider.other"),
        )
        self.assertFalse(
            revalidate_service_target(prepared, other, now_ms=1100, max_age_ms=500)
        )

    def test_service_revalidation_rejects_changed_state(self) -> None:
        prepared = service_state(ServiceStateKind.STOPPED)
        changed = service_state(ServiceStateKind.UNKNOWN)
        self.assertFalse(
            revalidate_service_target(prepared, changed, now_ms=1100, max_age_ms=500)
        )

    def test_running_service_revalidation_rejects_replaced_process(self) -> None:
        prepared = service_state(
            ServiceStateKind.RUNNING,
            process_instance=instance(pid=10, marker="generation.1"),
        )
        fresh = service_state(
            ServiceStateKind.RUNNING,
            process_instance=instance(pid=11, marker="generation.2"),
        )
        self.assertFalse(
            revalidate_service_target(prepared, fresh, now_ms=1100, max_age_ms=500)
        )

    def test_service_revalidation_accepts_fresh_same_stopped_service(self) -> None:
        prepared = service_state(ServiceStateKind.STOPPED)
        fresh = service_state(ServiceStateKind.STOPPED)
        self.assertTrue(
            revalidate_service_target(prepared, fresh, now_ms=1100, max_age_ms=500)
        )

    def test_service_operation_kinds_match_contract(self) -> None:
        self.assertEqual(
            {kind.value for kind in ServiceOperationKind},
            {"OBSERVE", "START", "STOP", "RESTART"},
        )

    def test_service_descriptor_does_not_execute_launchctl(self) -> None:
        value = ServiceOperationDescriptor(
            "service.operation.1",
            ServiceOperationKind.RESTART,
            service_identity(),
            requires_privilege="ROOT",
        )
        self.assertFalse(value.prepared_operation_auto_executable)
        self.assertFalse(value.safe_diagnostic()["authorization"])
        source = inspect.getsource(__import__("phoneharness_process_service"))
        self.assertNotIn("launchctl", source)

    def test_capability_surface_contains_all_descriptor_kinds(self) -> None:
        candidates = capability_definition_candidates()
        self.assertEqual(len(candidates), 9)
        self.assertEqual(len({item["capability_id"] for item in candidates}), 9)
        self.assertTrue(all(item["descriptor_only"] for item in candidates))

    def test_mutating_capability_candidates_keep_device_gate(self) -> None:
        mutating = [
            item
            for item in capability_definition_candidates()
            if item["risk_class"] != "read_only"
        ]
        self.assertTrue(mutating)
        self.assertTrue(
            all(
                item["compatibility_gate"] == "BOOTSTRAP_2_2_1_COMPAT_GATE"
                for item in mutating
            )
        )

    def test_ai_native_contract_is_shared_and_nonauthoritative(self) -> None:
        contract = ai_native_contract()
        self.assertTrue(contract["SHARED_SEMANTIC_CONTEXT_CONNECTED"])
        self.assertFalse(contract["authorization"])
        self.assertFalse(contract["SECOND_AI_RUNTIME_ADDED"])
        self.assertFalse(contract["SECOND_WORLD_MODEL_ADDED"])
        self.assertFalse(contract["SECOND_MEMORY_SYSTEM_ADDED"])

    def test_ai_learning_hook_cannot_write_permanent_causal_memory(self) -> None:
        hook = ai_learning_hook()
        self.assertFalse(hook["S4_M6_WRITES_PERMANENT_CAUSAL_MEMORY"])
        self.assertFalse(hook["ONE_PROCESS_SPIKE_CREATES_PERMANENT_RULE"])
        self.assertIn("shared Stage-5", AI_LEARNING_HOOK_RULE)

    def test_process_semantic_facts_are_typed_and_noncausal(self) -> None:
        facts = snapshot(cpu_observation=99.0).semantic_facts()
        self.assertIsInstance(facts["observed_fields"], tuple)
        self.assertFalse(facts["is_root_cause"])
        self.assertFalse(facts["authorization"])

    def test_service_semantic_facts_are_nonauthoritative(self) -> None:
        facts = service_state(ServiceStateKind.UNKNOWN).semantic_facts()
        self.assertFalse(facts["unknown_is_stopped"])
        self.assertFalse(facts["authorization"])

    def test_log_pid_composition_remains_descriptive_not_causal(self) -> None:
        entry = LogEntry.from_provider(
            {"message": "event", "pid": 2089, "process": "SpringBoard"}
        )
        process = snapshot()
        self.assertEqual(entry.pid, process.instance.pid)
        self.assertFalse(process.semantic_facts()["is_root_cause"])

    def test_safe_diagnostics_do_not_leak_paths_or_secret_fields(self) -> None:
        payload = json.dumps(
            {
                "identity": identity().safe_diagnostic(),
                "instance": instance().safe_diagnostic(),
                "snapshot": snapshot().safe_diagnostic(),
            },
            sort_keys=True,
        ).lower()
        for forbidden in ("/var/", "password", "passcode", "token", "credential"):
            self.assertNotIn(forbidden, payload)

    def test_no_generic_shell_provider_or_continuous_monitor(self) -> None:
        source = inspect.getsource(__import__("phoneharness_process_service"))
        for forbidden in (
            "run_command",
            "subprocess",
            "os.system",
            "posix_spawn",
            "/bin/sh",
            "processdatabase",
            "servicedatabase",
            "processepoch",
            "serviceepoch",
        ):
            self.assertNotIn(forbidden, source.lower())

    def test_no_second_app_launcher_or_frontmost_owner(self) -> None:
        source = inspect.getsource(__import__("phoneharness_process_service"))
        for forbidden in ("FBSSystemService", "LSApplicationWorkspace", "launchApp"):
            self.assertNotIn(forbidden, source)

    def test_unknown_dispatch_is_not_converted_to_retry(self) -> None:
        source = inspect.getsource(__import__("phoneharness_process_service"))
        self.assertNotIn("retry", source.lower())
        self.assertNotIn("unknown_outcome = false", source.lower())

    def test_frozen_upstream_schemas_remain_unchanged(self) -> None:
        self.assertEqual(
            ObservationRef.__dataclass_fields__["schema_version"].default,
            "phoneharness.observation-ref.v1",
        )
        self.assertEqual(
            ObservedTargetRef.__dataclass_fields__["schema_version"].default,
            "phoneharness.observed-target-ref.v1",
        )
        self.assertEqual(
            ActionCandidateSet.__dataclass_fields__["schema_version"].default,
            "phoneharness.action-candidate-set.v1",
        )

    def test_recovery_copy_is_not_imported_as_production(self) -> None:
        source = inspect.getsource(__import__("phoneharness_process_service"))
        self.assertNotIn("diagnostics/recovery", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
