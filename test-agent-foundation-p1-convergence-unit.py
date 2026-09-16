#!/usr/bin/env python3
"""P1-5/P1-6 host-only topology and concurrent-state convergence tests."""

from __future__ import annotations

import inspect
import threading
import unittest

from phoneharness_agent import (
    CapabilityCatalog,
    CapabilityDefinition,
    CapabilityEvidence,
    CapabilityMethodDefinition,
    CapabilityMethodRegistry,
    DynamicPlanner,
    PlannerSemanticContext,
    SemanticActionBindingError,
    SemanticActionBindingStore,
    SemanticExecutionRuntime,
    SemanticObservation,
    Snapshot,
    runtime_path_classifications,
)


def semantic_context() -> PlannerSemanticContext:
    return PlannerSemanticContext.from_semantic_observation(
        SemanticObservation(
            source="AX",
            timestamp=100,
            confidence=0.9,
            page_type="search",
            intents=({"intent": "search", "count": 1, "actionable": True},),
            actionable=True,
        )
    )


def search_snapshot() -> Snapshot:
    return Snapshot(
        frontmost_name="",
        frontmost_bundle_id="",
        element_count=1,
        source="AX",
        elements=({"text": "Search", "clickable": True},),
    )


def method_registry() -> CapabilityMethodRegistry:
    capability = CapabilityDefinition(
        capability_id="capability.foundation.health.v1",
        name="foundation_health",
        description="foundation_health_capability",
        version="1.0.0",
        source_type="skill_package",
        lifecycle="PREFERRED",
        required_tools=frozenset(),
        required_permissions=("permission.foundation",),
        risk_level="interaction",
        preconditions=(),
        verifier="foundation_result",
        dependencies=(),
        platform_support=("macos_host",),
        evidence=CapabilityEvidence(success_count=1, confidence=0.9, last_verified=100),
    )
    method = CapabilityMethodDefinition(
        method_id="method.foundation.health.v1",
        capability_id=capability.capability_id,
        name="foundation_health_method",
        purpose="foundation_health",
        version="1.0.0",
        method_type="mcp",
        source="built_in",
        lifecycle="CANDIDATE",
        availability="available",
        required_permissions=("permission.foundation",),
        risk_level="interaction",
        input_schema=(),
        output_schema=(),
        verifier="foundation_result",
        platform_support=("macos_host",),
        evidence=CapabilityEvidence(success_count=1, confidence=0.9, last_verified=100),
        verification_status="static_pass",
        latency_class="fast",
    )
    return CapabilityMethodRegistry(CapabilityCatalog((capability,)), (method,))


class FoundationP1ConvergenceTests(unittest.TestCase):
    def test_one_canonical_execution_path_and_legacy_paths_declare_existing_governance(self) -> None:
        paths = runtime_path_classifications()
        canonical = [item for item in paths if item.status == "CANONICAL"]
        legacy = [item for item in paths if item.status == "LEGACY_COMPATIBILITY"]

        self.assertEqual(["TaskCoordinator.run_dynamic_step"], [item.entrypoint for item in canonical])
        self.assertEqual(3, len(legacy))
        self.assertTrue(all(item.reachable for item in legacy))
        self.assertTrue(all("PlanExecutor" in item.required_governance for item in legacy))
        self.assertTrue(all("Verifier" in item.required_governance for item in legacy))

        legacy_source = inspect.getsource(SemanticExecutionRuntime)
        self.assertIn("PlanExecutor(", legacy_source)
        self.assertNotIn("self.client.call_tool(", legacy_source)
        self.assertIn("def plan(", inspect.getsource(DynamicPlanner))

    def test_concurrent_semantic_binding_claim_has_one_winner_and_no_replay(self) -> None:
        store = SemanticActionBindingStore(ttl_seconds=60)
        binding = store.bind_search_control(search_snapshot(), semantic_context(), now=100)
        start = threading.Barrier(8)
        successes: list[dict[str, object]] = []
        failures: list[Exception] = []
        result_lock = threading.Lock()

        def claim() -> None:
            start.wait(timeout=3)
            try:
                result = store.resolve(
                    binding.binding_id,
                    tool="tap_element",
                    step_id="focus-bound-search-control",
                    now=101,
                )
                with result_lock:
                    successes.append(result)
            except Exception as error:  # Expected losers fail closed.
                with result_lock:
                    failures.append(error)

        workers = [threading.Thread(target=claim) for _ in range(8)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=3)

        self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertEqual([{"text": "Search", "match": "exact"}], successes)
        self.assertEqual(7, len(failures))
        self.assertTrue(all(isinstance(error, SemanticActionBindingError) for error in failures))

    def test_concurrent_method_health_updates_preserve_every_aggregate_attempt(self) -> None:
        registry = method_registry()
        start = threading.Barrier(16)
        failures: list[Exception] = []
        failure_lock = threading.Lock()

        def record() -> None:
            start.wait(timeout=3)
            try:
                registry.record_health(
                    "method.foundation.health.v1",
                    platform="macos_host",
                    compatibility="compatible",
                    verification_status="static_pass",
                    passed=True,
                    validated_at=200,
                )
            except Exception as error:  # No writer is expected to lose an update.
                with failure_lock:
                    failures.append(error)

        workers = [threading.Thread(target=record) for _ in range(16)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=3)

        self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertEqual([], failures)
        records = registry.health_records(method_id="method.foundation.health.v1")
        self.assertEqual(1, len(records))
        self.assertEqual(16, records[0]["success_count"])
        self.assertEqual(0, records[0]["failure_count"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
