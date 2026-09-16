#!/usr/bin/env python3
"""TEST-47 contracts for aggregate Capability Method health evidence.

This suite is entirely local and declarative.  It never creates a Planner,
Router, Executor, MCP client, device action, or persistent evidence store.
"""

from __future__ import annotations

import json
import unittest

from phoneharness_agent import (
    CAPABILITY_METHOD_HEALTH_VERSION,
    CapabilityCatalog,
    CapabilityDefinition,
    CapabilityEvidence,
    CapabilityIntelligenceError,
    CapabilityMethodDefinition,
    CapabilityMethodRegistry,
)


FORBIDDEN_KEYS = frozenset(
    {
        "goal",
        "query",
        "prompt",
        "content",
        "screenshot",
        "ocr",
        "coordinate",
        "rect",
        "ui",
        "url",
        "password",
        "token",
        "action",
        "parameters",
        "trace",
        "raw_mcp",
        "response",
    }
)


def keys_in(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(keys_in(item) for item in value.values())) if value else set()
    if isinstance(value, (list, tuple)):
        return set().union(*(keys_in(item) for item in value)) if value else set()
    return set()


def evidence() -> CapabilityEvidence:
    return CapabilityEvidence(success_count=4, failure_count=0, confidence=0.90, last_verified=100)


def catalog() -> CapabilityCatalog:
    return CapabilityCatalog(
        (
            CapabilityDefinition(
                capability_id="capability.generic.lookup.v1",
                name="generic_lookup",
                description="generic_lookup_capability",
                version="1.0.0",
                source_type="skill_package",
                lifecycle="PREFERRED",
                required_tools=frozenset(),
                required_permissions=("permission.generic",),
                risk_level="interaction",
                preconditions=(),
                verifier="result_visible",
                dependencies=(),
                platform_support=("macos_host",),
                evidence=evidence(),
            ),
        )
    )


def method(method_id: str, method_type: str) -> CapabilityMethodDefinition:
    return CapabilityMethodDefinition(
        method_id=method_id,
        capability_id="capability.generic.lookup.v1",
        name="generic_lookup_method",
        purpose="generic_lookup",
        version="1.0.0",
        method_type=method_type,
        source="built_in",
        lifecycle="ACTIVE",
        availability="available",
        required_permissions=("permission.generic",),
        risk_level="interaction",
        input_schema=("request_reference",),
        output_schema=("result_state",),
        verifier="result_visible",
        platform_support=("macos_host",),
        evidence=evidence(),
        verification_status="device_pass",
        latency_class="fast",
    )


def registry(*definitions: CapabilityMethodDefinition) -> CapabilityMethodRegistry:
    return CapabilityMethodRegistry(catalog(), definitions)


class CapabilityMethodHealthTests(unittest.TestCase):
    def test_health_record_is_aggregate_only_and_explainable(self) -> None:
        methods = registry(method("method.generic.appintent.v1", "app_intent"))
        record = methods.record_health(
            "method.generic.appintent.v1",
            platform="macos_host",
            compatibility="compatible",
            verification_status="device_pass",
            passed=True,
            validated_at=200,
        )

        self.assertEqual(CAPABILITY_METHOD_HEALTH_VERSION, record["capability_method_health_version"])
        self.assertEqual("generic_lookup", record["capability_name"])
        self.assertEqual("generic_lookup_method", record["method_name"])
        self.assertEqual(1, record["success_count"])
        self.assertEqual(1.0, record["success_rate"])
        self.assertEqual([], record["failure_categories"])
        self.assertEqual(200, record["last_validation"])
        self.assertTrue(FORBIDDEN_KEYS.isdisjoint(keys_in(record)))
        self.assertTrue(FORBIDDEN_KEYS.isdisjoint(keys_in(json.loads(json.dumps(methods.contracts())))))

    def test_observed_health_changes_existing_method_recommendation(self) -> None:
        methods = registry(
            method("method.generic.appintent.v1", "app_intent"),
            method("method.generic.mcp.v1", "mcp"),
        )
        for timestamp in (200, 201, 202):
            methods.record_health(
                "method.generic.appintent.v1",
                platform="macos_host",
                compatibility="compatible",
                verification_status="static_pass",
                passed=False,
                failure_category="verifier_failed",
                recovered=True,
                validated_at=timestamp,
            )
        for timestamp in (203, 204, 205):
            methods.record_health(
                "method.generic.mcp.v1",
                platform="macos_host",
                compatibility="compatible",
                verification_status="device_pass",
                passed=True,
                validated_at=timestamp,
            )

        recommendation = methods.recommend(
            "capability.generic.lookup.v1",
            available_permissions=("permission.generic",),
            available_platforms=("macos_host",),
        )
        self.assertEqual("recommended", recommendation["status"])
        self.assertEqual("method.generic.mcp.v1", recommendation["recommended_method"]["method_id"])
        self.assertIn("method_health_applied", recommendation["reason_codes"])
        self.assertEqual(3, recommendation["recommended_method"]["method_health"]["success_count"])

    def test_incompatible_health_blocks_method_without_dispatch(self) -> None:
        methods = registry(method("method.generic.appintent.v1", "app_intent"))
        methods.record_health(
            "method.generic.appintent.v1",
            platform="macos_host",
            compatibility="incompatible",
            verification_status="failed",
            passed=False,
            failure_category="compatibility_incompatible",
            validated_at=200,
        )
        recommendation = methods.recommend(
            "capability.generic.lookup.v1",
            available_permissions=("permission.generic",),
            available_platforms=("macos_host",),
        )
        self.assertEqual("blocked", recommendation["status"])
        self.assertIn("method_health_incompatible", recommendation["candidates"][0]["reason_codes"])
        self.assertEqual("none", recommendation["execution_authority"])

    def test_failed_verification_blocks_method_without_automatic_retry(self) -> None:
        methods = registry(method("method.generic.appintent.v1", "app_intent"))
        methods.record_health(
            "method.generic.appintent.v1",
            platform="macos_host",
            compatibility="compatible",
            verification_status="failed",
            passed=False,
            failure_category="unknown_side_effect",
            validated_at=200,
        )
        candidate = methods.assess(
            "capability.generic.lookup.v1",
            available_permissions=("permission.generic",),
            available_platforms=("macos_host",),
        )[0]
        self.assertFalse(candidate.eligible)
        self.assertIn("method_health_verification_failed", candidate.reason_codes)
        self.assertNotIn("retry", candidate.reason_codes)

    def test_failure_taxonomy_and_platform_are_fail_closed(self) -> None:
        methods = registry(method("method.generic.appintent.v1", "app_intent"))
        with self.assertRaisesRegex(CapabilityIntelligenceError, "declared by the capability method"):
            methods.record_health(
                "method.generic.appintent.v1",
                platform="ios_device",
                compatibility="compatible",
                verification_status="device_pass",
                passed=True,
            )
        with self.assertRaisesRegex(CapabilityIntelligenceError, "known failure category"):
            methods.record_health(
                "method.generic.appintent.v1",
                platform="macos_host",
                compatibility="compatible",
                verification_status="failed",
                passed=False,
                failure_category="user_private_error",
            )
        with self.assertRaisesRegex(CapabilityIntelligenceError, "cannot include a failure category"):
            methods.record_health(
                "method.generic.appintent.v1",
                platform="macos_host",
                compatibility="compatible",
                verification_status="device_pass",
                passed=True,
                failure_category="verifier_failed",
            )

    def test_recovery_count_is_aggregated_without_replay_information(self) -> None:
        methods = registry(method("method.generic.appintent.v1", "app_intent"))
        methods.record_health(
            "method.generic.appintent.v1",
            platform="macos_host",
            compatibility="compatible",
            verification_status="static_pass",
            passed=False,
            failure_category="recovery_required",
            recovered=True,
            validated_at=200,
        )
        record = methods.health_records()[0]
        self.assertEqual(1, record["failure_count"])
        self.assertEqual(1, record["recovery_count"])
        self.assertEqual([{"category": "recovery_required", "count": 1}], record["failure_categories"])
        self.assertTrue(FORBIDDEN_KEYS.isdisjoint(keys_in(record)))

    def test_registry_remains_advisory_without_runtime_ports(self) -> None:
        methods = registry(method("method.generic.appintent.v1", "app_intent"))
        for forbidden in ("call_tool", "dispatch", "execute", "authorize", "plan"):
            self.assertNotIn(forbidden, CapabilityMethodRegistry.__dict__)
            self.assertNotIn(forbidden, methods.__dict__)
        recommendation = methods.recommend(
            "capability.generic.lookup.v1",
            available_permissions=("permission.generic",),
            available_platforms=("macos_host",),
        )
        self.assertEqual("none", recommendation["execution_authority"])
        self.assertEqual("planner_risk_executor_verifier", recommendation["next_gate"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
