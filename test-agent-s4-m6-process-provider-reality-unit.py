#!/usr/bin/env python3
"""Host and captured-device-contract proofs for S4-M6-A3-R1."""

from __future__ import annotations

import inspect
import json
from pathlib import Path
import unittest

from phoneharness_process_service import (
    InstanceIdentityStrength,
    ProcessInstanceDiscriminatorKind,
    ServiceStateKind,
    SnapshotCompleteness,
)
from phoneharness_process_service_observation import (
    CandidateInstanceDiscriminator,
    MetricCompleteness,
    MetricSemanticKind,
    NormalizedResourceMetric,
    ObservationProviderRole,
    ProcessResourceMetric,
    ProviderAvailability,
    ProviderFusionDisposition,
    ProviderRoleDescriptor,
    ProviderServiceState,
    SanitizedProcessObservation,
    SanitizedServiceObservation,
    TargetRevalidationDisposition,
    app_identity_correlates,
    derive_resource_rate,
    fuse_process_observations,
    revalidate_process_observations,
    revalidate_service_observations,
)


ROOT = Path(__file__).resolve().parent
PROVIDER = "provider.launchctl.readonly"
TASK = "task.s4m6.a3r1"
SESSION = "session.device.ios17"


def process_observation(
    *,
    observation_id: str = "observation.device.0001",
    generation: int = 1,
    observed_at_ms: int = 1790824298000,
    pid: int | None = 693,
    bundle_id: str | None = "com.apple.springboard",
    discriminators: tuple[CandidateInstanceDiscriminator, ...] = (),
    state: str | None = None,
    provider: str = PROVIDER,
    process_name: str = "SpringBoard",
) -> SanitizedProcessObservation:
    return SanitizedProcessObservation(
        process_name=process_name,
        provider=provider,
        observation_id=observation_id,
        task_id=TASK,
        session_id=SESSION,
        generation=generation,
        observed_at_ms=observed_at_ms,
        pid=pid,
        bundle_id=bundle_id,
        candidate_discriminators=discriminators,
        state=state,
    )


def candidate(
    kind: ProcessInstanceDiscriminatorKind,
    *,
    proven: bool = False,
    suffix: str = "0001",
    provider: str = PROVIDER,
) -> CandidateInstanceDiscriminator:
    return CandidateInstanceDiscriminator(
        kind=kind,
        evidence_ref=f"device.evidence.{suffix}",
        provider=provider,
        stability_proven=proven,
    )


def service_observation(
    *,
    label: str = "com.apple.SpringBoard",
    availability: ProviderAvailability = ProviderAvailability.AVAILABLE,
    resolved: bool = True,
    state: ProviderServiceState = ProviderServiceState.RUNNING,
    process: SanitizedProcessObservation | None = None,
    provider: str = PROVIDER,
    observation_id: str = "observation.device.0001",
    generation: int = 1,
    observed_at_ms: int = 1790824298000,
) -> SanitizedServiceObservation:
    return SanitizedServiceObservation(
        label=label,
        provider=provider,
        availability=availability,
        resolved=resolved,
        provider_state=state,
        observation_id=observation_id,
        task_id=TASK,
        session_id=SESSION,
        generation=generation,
        observed_at_ms=observed_at_ms,
        process=process,
    )


class S4M6ProcessProviderRealityTests(unittest.TestCase):
    def test_real_bounded_observation_maps_to_frozen_types(self) -> None:
        snapshot = process_observation().to_snapshot()
        self.assertEqual(snapshot.instance.identity.process_name, "SpringBoard")
        self.assertEqual(snapshot.instance.identity.bundle_id, "com.apple.springboard")
        self.assertEqual(snapshot.completeness, SnapshotCompleteness.UNKNOWN)
        self.assertFalse(snapshot.safe_diagnostic()["authorization"])

    def test_missing_metrics_remain_unknown_not_zero(self) -> None:
        snapshot = process_observation().to_snapshot()
        self.assertIsNone(snapshot.cpu_observation)
        self.assertIsNone(snapshot.memory_observation_bytes)
        self.assertIsNone(snapshot.thread_count)
        self.assertIsNone(snapshot.wakeup_observation)
        self.assertEqual(snapshot.observed_fields, ())
        self.assertTrue(snapshot.safe_diagnostic()["missing_value_means_zero"] is False)

    def test_pid_only_evidence_remains_pid_only(self) -> None:
        snapshot = process_observation().to_snapshot()
        self.assertEqual(
            snapshot.instance.identity_strength,
            InstanceIdentityStrength.PID_ONLY,
        )
        self.assertFalse(snapshot.instance.same_instance_as(snapshot.instance))

    def test_unproven_device_discriminators_do_not_strengthen_identity(self) -> None:
        observed = (
            candidate(ProcessInstanceDiscriminatorKind.UNIQUE_ID),
            candidate(
                ProcessInstanceDiscriminatorKind.PROVIDER_GENERATION_MARKER,
                suffix="0002",
            ),
        )
        record = process_observation(discriminators=observed).safe_semantic_record()
        self.assertEqual(record["identity_strength"], "PID_ONLY")
        self.assertEqual(record["accepted_discriminator_count"], 0)
        self.assertEqual(
            set(record["candidate_discriminator_kinds"]),
            {"UNIQUE_ID", "PROVIDER_GENERATION_MARKER"},
        )

    def test_proven_strong_evidence_is_still_not_authorization(self) -> None:
        observed = (
            candidate(ProcessInstanceDiscriminatorKind.UNIQUE_ID, proven=True),
        )
        record = process_observation(discriminators=observed).safe_semantic_record()
        self.assertEqual(record["identity_strength"], "STRONG_PROVIDER_EVIDENCE")
        self.assertFalse(record["authorization"])

    def test_provider_error_never_becomes_stopped(self) -> None:
        evidence = service_observation(
            availability=ProviderAvailability.PERMISSION_DENIED,
            resolved=False,
            state=ProviderServiceState.UNKNOWN,
        ).to_evidence()
        self.assertEqual(evidence.state, ServiceStateKind.UNAVAILABLE)

    def test_absent_service_discovery_never_becomes_stopped(self) -> None:
        evidence = service_observation(
            availability=ProviderAvailability.AVAILABLE,
            resolved=False,
            state=ProviderServiceState.UNKNOWN,
        ).to_evidence()
        self.assertEqual(evidence.state, ServiceStateKind.UNAVAILABLE)

    def test_loaded_not_running_service_can_be_stopped(self) -> None:
        evidence = service_observation(
            resolved=True,
            state=ProviderServiceState.NOT_RUNNING,
        ).to_evidence()
        self.assertEqual(evidence.state, ServiceStateKind.STOPPED)
        self.assertIsNone(evidence.instance)

    def test_running_without_instance_remains_unknown(self) -> None:
        evidence = service_observation(process=None).to_evidence()
        self.assertEqual(evidence.state, ServiceStateKind.UNKNOWN)

    def test_running_with_same_provenance_maps_to_running(self) -> None:
        evidence = service_observation(process=process_observation()).to_evidence()
        self.assertEqual(evidence.state, ServiceStateKind.RUNNING)
        self.assertIsNotNone(evidence.instance)

    def test_process_service_provenance_mismatch_rejected(self) -> None:
        with self.assertRaises(ValueError):
            service_observation(
                process=process_observation(
                    observation_id="observation.device.other",
                )
            )

    def test_serialization_preserves_identity_strength_completeness_and_provenance(self) -> None:
        record = process_observation().safe_semantic_record()
        decoded = json.loads(json.dumps(record, sort_keys=True))
        self.assertEqual(decoded["identity_strength"], "PID_ONLY")
        self.assertEqual(decoded["snapshot_completeness"], "UNKNOWN")
        self.assertTrue(decoded["provenance_present"])
        self.assertFalse(decoded["authorization"])

    def test_serialization_cannot_strengthen_unproven_candidate(self) -> None:
        record = process_observation(
            discriminators=(
                candidate(ProcessInstanceDiscriminatorKind.UNIQUE_ID),
            )
        ).safe_semantic_record()
        decoded = json.loads(json.dumps(record))
        self.assertEqual(decoded["identity_strength"], "PID_ONLY")
        self.assertEqual(decoded["accepted_discriminator_count"], 0)

    def test_bundle_correlation_is_descriptive_only(self) -> None:
        observation = process_observation()
        self.assertTrue(app_identity_correlates(observation, "com.apple.springboard"))
        self.assertFalse(app_identity_correlates(observation, "com.example.other"))
        record = observation.safe_semantic_record()
        self.assertFalse(record["app_lifecycle_authority"])
        self.assertFalse(record["authorization"])

    def test_s4_m5_composition_remains_descriptive_noncausal(self) -> None:
        record = process_observation().safe_semantic_record()
        self.assertFalse(record["causal_proof"])
        self.assertFalse(record["authorization"])

    def test_s4_m7_shell_authority_remains_closed(self) -> None:
        source = inspect.getsource(
            __import__("phoneharness_process_service_observation")
        )
        for forbidden in (
            "subprocess",
            "os.system",
            "Popen",
            "run_command",
            "killall",
            "launchctl ",
            "/bin/sh",
        ):
            self.assertNotIn(forbidden, source)
        self.assertFalse(process_observation().safe_semantic_record()["shell_authority"])

    def test_module_does_not_add_device_transport_or_mutation(self) -> None:
        source = (ROOT / "phoneharness_process_service_observation.py").read_text()
        for forbidden in (
            "paramiko",
            "requests.",
            "socket.",
            "terminate(",
            "suspend(",
            "resume(",
            "service_start",
            "service_stop",
            "service_restart",
        ):
            self.assertNotIn(forbidden, source)

    def test_semantic_context_record_is_bounded_and_non_authoritative(self) -> None:
        process_record = process_observation().safe_semantic_record()
        service_record = service_observation(
            process=process_observation()
        ).safe_semantic_record()
        for record in (process_record, service_record):
            encoded = json.dumps(record, sort_keys=True)
            self.assertLess(len(encoded), 2048)
            self.assertNotIn("path", encoded.lower())
            self.assertNotIn("token", encoded.lower())
            self.assertNotIn("environment", encoded.lower())
            self.assertFalse(record["authorization"])

    def test_direct_libproc_provider_normalizes_without_authority(self) -> None:
        provider = "provider.libproc.readonly"
        observed = process_observation(
            provider=provider,
            discriminators=(
                candidate(
                    ProcessInstanceDiscriminatorKind.START_TIME,
                    proven=True,
                    provider=provider,
                ),
            ),
        )
        record = observed.safe_semantic_record()
        self.assertEqual(record["provider"], provider)
        self.assertEqual(record["identity_strength"], "STRONG_PROVIDER_EVIDENCE")
        self.assertFalse(record["authorization"])

    def test_start_time_serialization_is_typed_and_opaque(self) -> None:
        provider = "provider.libproc.readonly"
        record = process_observation(
            provider=provider,
            discriminators=(
                candidate(
                    ProcessInstanceDiscriminatorKind.START_TIME,
                    proven=True,
                    provider=provider,
                    suffix="start-time-proof",
                ),
            ),
        ).safe_semantic_record()
        encoded = json.dumps(record, sort_keys=True)
        self.assertIn("START_TIME", record["candidate_discriminator_kinds"])
        self.assertNotIn("start-time-proof", encoded)
        self.assertNotIn("pbi_start", encoded)

    def test_provider_round_trip_does_not_strengthen_pid_only(self) -> None:
        record = json.loads(
            json.dumps(process_observation(provider="provider.libproc.readonly").safe_semantic_record())
        )
        self.assertEqual(record["identity_strength"], "PID_ONLY")
        self.assertEqual(record["accepted_discriminator_count"], 0)

    def test_fusion_same_pid_and_identity_composes_conservatively(self) -> None:
        result = fuse_process_observations(
            process_observation(provider="provider.launchctl.readonly"),
            process_observation(provider="provider.libproc.readonly"),
        )
        self.assertEqual(result.disposition, ProviderFusionDisposition.COMPOSED)
        self.assertEqual(
            result.effective_identity_strength,
            InstanceIdentityStrength.PID_ONLY,
        )
        self.assertFalse(result.safe_semantic_record()["authorization"])
        self.assertFalse(
            result.safe_semantic_record()["certainty_strengthened_by_fusion"]
        )

    def test_fusion_pid_conflict_fails_closed(self) -> None:
        result = fuse_process_observations(
            process_observation(provider="provider.launchctl.readonly", pid=693),
            process_observation(provider="provider.libproc.readonly", pid=694),
        )
        self.assertEqual(result.disposition, ProviderFusionDisposition.CONFLICT)
        self.assertEqual(result.effective_identity_strength, InstanceIdentityStrength.NONE)

    def test_fusion_logical_identity_conflict_fails_closed(self) -> None:
        result = fuse_process_observations(
            process_observation(provider="provider.launchctl.readonly"),
            process_observation(
                provider="provider.libproc.readonly",
                process_name="DifferentProcess",
            ),
        )
        self.assertEqual(result.disposition, ProviderFusionDisposition.CONFLICT)
        self.assertFalse(result.logical_identity_consistent)

    def test_fusion_conflicting_strong_discriminator_fails_closed(self) -> None:
        launchctl_provider = "provider.launchctl.readonly"
        libproc_provider = "provider.libproc.readonly"
        result = fuse_process_observations(
            process_observation(
                provider=launchctl_provider,
                discriminators=(
                    candidate(
                        ProcessInstanceDiscriminatorKind.START_TIME,
                        proven=True,
                        suffix="one",
                        provider=launchctl_provider,
                    ),
                ),
            ),
            process_observation(
                provider=libproc_provider,
                discriminators=(
                    candidate(
                        ProcessInstanceDiscriminatorKind.START_TIME,
                        proven=True,
                        suffix="two",
                        provider=libproc_provider,
                    ),
                ),
            ),
        )
        self.assertEqual(result.disposition, ProviderFusionDisposition.CONFLICT)
        self.assertFalse(result.discriminator_consistent)

    def test_single_provider_fallback_remains_partial(self) -> None:
        result = fuse_process_observations(
            None,
            process_observation(provider="provider.launchctl.readonly"),
        )
        self.assertEqual(result.disposition, ProviderFusionDisposition.PARTIAL)
        self.assertEqual(result.provider_count, 1)
        self.assertFalse(result.safe_semantic_record()["authorization"])

    def test_total_provider_failure_remains_unavailable(self) -> None:
        result = fuse_process_observations(None, None)
        self.assertEqual(result.disposition, ProviderFusionDisposition.UNAVAILABLE)
        self.assertEqual(result.effective_identity_strength, InstanceIdentityStrength.NONE)

    def test_missing_start_time_never_creates_generation_marker(self) -> None:
        snapshot = process_observation(provider="provider.libproc.readonly").to_snapshot()
        self.assertEqual(snapshot.instance.identity_strength, InstanceIdentityStrength.PID_ONLY)
        self.assertEqual(snapshot.instance.instance_discriminators, ())
        self.assertIsNone(snapshot.instance.generation_marker)

    def test_audit_token_candidate_is_evidence_not_authority(self) -> None:
        provider = "provider.libproc.readonly"
        record = process_observation(
            provider=provider,
            discriminators=(
                candidate(
                    ProcessInstanceDiscriminatorKind.AUDIT_TOKEN_DERIVED_IDENTITY,
                    proven=True,
                    provider=provider,
                ),
            ),
        ).safe_semantic_record()
        self.assertEqual(record["identity_strength"], "STRONG_PROVIDER_EVIDENCE")
        self.assertFalse(record["authorization"])

    def test_bundle_and_executable_identity_do_not_create_instance_strength(self) -> None:
        observed = SanitizedProcessObservation(
            process_name="SpringBoard",
            provider="provider.libproc.readonly",
            observation_id="observation.device.0002",
            task_id=TASK,
            session_id=SESSION,
            generation=2,
            observed_at_ms=1790824299000,
            bundle_id="com.apple.springboard",
            executable_digest="a" * 64,
        )
        self.assertEqual(
            observed.to_snapshot().instance.identity_strength,
            InstanceIdentityStrength.PARTIAL,
        )
        self.assertIsNone(observed.to_snapshot().instance.pid)
        self.assertEqual(observed.to_snapshot().instance.instance_discriminators, ())
        self.assertFalse(observed.safe_semantic_record()["authorization"])

    def test_direct_probe_source_has_no_mutation_surface(self) -> None:
        source = (
            ROOT
            / "diagnostics/modules/s4-m6/s4_m6_a3_r2_libproc_probe.c"
        ).read_text()
        for forbidden in (
            "kill(",
            "killall",
            "proc_terminate",
            "proc_suspend",
            "proc_resume",
            "launchctl",
            "system(",
            "execve(",
        ):
            self.assertNotIn(forbidden, source)
        self.assertIn("proc_listallpids", source)
        self.assertIn("proc_pid_rusage", source)

    def test_provider_fusion_record_is_bounded_and_data_minimized(self) -> None:
        encoded = json.dumps(
            fuse_process_observations(
                process_observation(provider="provider.launchctl.readonly"),
                process_observation(provider="provider.libproc.readonly"),
            ).safe_semantic_record(),
            sort_keys=True,
        )
        self.assertLess(len(encoded), 1024)
        for forbidden in ("path", "token", "environment", "credential"):
            self.assertNotIn(forbidden, encoded.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
