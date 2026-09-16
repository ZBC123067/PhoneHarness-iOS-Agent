#!/usr/bin/env python3
"""Static boundary tests for TEST-26 Capability Intelligence.

These tests never contact an iPhone.  They prove that TEST-26 produces only
declarative capability candidates and privacy-minimized aggregate evidence.
"""

from __future__ import annotations

import json
import unittest

from phoneharness_agent import (
    DEFAULT_SKILL_PERMISSIONS,
    DEFAULT_SKILL_PLATFORMS,
    CapabilityCatalog,
    CapabilityDefinition,
    CapabilityEvaluator,
    CapabilityEvidence,
    CapabilityIntelligenceError,
    CapabilityIntelligenceLayer,
    SkillRegistry,
)


TOOLS = frozenset({"describe_screen", "tap_element", "input_text", "type_text", "press_key"})
FORBIDDEN_KEYS = frozenset(
    {
        "goal",
        "app_identity",
        "app_id",
        "bundle_id",
        "ui",
        "coordinate",
        "coordinates",
        "rect",
        "screenshot",
        "ocr",
        "input",
        "raw_mcp_response",
        "raw_response",
    }
)


def capability(
    suffix: str,
    *,
    source_type: str = "skill_package",
    lifecycle: str = "DISCOVERED",
    required_tools: frozenset[str] = frozenset({"describe_screen"}),
    required_permissions: tuple[str, ...] = ("mcp.read_screen",),
    dependencies: tuple[str, ...] = (),
    evidence: CapabilityEvidence | None = None,
) -> CapabilityDefinition:
    return CapabilityDefinition(
        capability_id="capability.testing.%s" % suffix,
        name="testing_%s" % suffix,
        description="Reusable test capability with declarative metadata only.",
        version="1.0.0",
        source_type=source_type,
        lifecycle=lifecycle,
        required_tools=required_tools,
        required_permissions=required_permissions,
        risk_level="read_only",
        preconditions=("fresh_observation",),
        verifier="observation_nonempty",
        dependencies=dependencies,
        platform_support=("macos_host", "ios_mcp"),
        evidence=CapabilityEvidence() if evidence is None else evidence,
    )


def keys_in(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(keys_in(item) for item in value.values())) if value else set()
    if isinstance(value, (list, tuple)):
        return set().union(*(keys_in(item) for item in value)) if value else set()
    return set()


class CapabilityIntelligenceTests(unittest.TestCase):
    def test_evidence_schema_has_exactly_four_approved_aggregate_fields(self) -> None:
        evidence = CapabilityEvidence(success_count=2, failure_count=1, confidence=0.75, last_verified=100)
        self.assertEqual(
            {"success_count", "failure_count", "confidence", "last_verified"},
            set(evidence.summary()),
        )
        self.assertEqual(0.75, evidence.summary()["confidence"])

    def test_skill_registry_discovery_creates_generic_skill_package_catalog_only(self) -> None:
        catalog = CapabilityCatalog.from_skill_registry(SkillRegistry())
        contracts = catalog.contracts()
        self.assertEqual(
            {
                "capability.screen.observe.v1",
                "capability.screen.verify_visible_text.v1",
                "capability.browser.search_current_page.v1",
                "capability.maps.open_native_link.v1",
                "capability.apps.launch_installed.v1",
            },
            {contract["capability_id"] for contract in contracts},
        )
        self.assertTrue(all(contract["source_type"] == "skill_package" for contract in contracts))
        self.assertTrue(all(contract["lifecycle"] == "DISCOVERED" for contract in contracts))
        self.assertFalse(FORBIDDEN_KEYS.intersection(keys_in(contracts)))

    def test_evaluator_marks_live_requirements_as_available_without_selecting_one(self) -> None:
        layer = CapabilityIntelligenceLayer.from_skill_registry(SkillRegistry())
        evaluation = layer.evaluate_candidates(available_tools=TOOLS)
        summary = evaluation.summary()
        observed = next(
            candidate for candidate in summary["candidates"] if candidate["capability_id"] == "capability.screen.observe.v1"
        )
        self.assertTrue(observed["eligible"])
        self.assertEqual("AVAILABLE", observed["lifecycle"])
        self.assertEqual(3, summary["eligible_candidate_count"])
        self.assertNotIn("selected", summary)
        self.assertNotIn("selection", summary)

    def test_missing_tool_rejects_only_the_affected_candidate(self) -> None:
        layer = CapabilityIntelligenceLayer.from_skill_registry(SkillRegistry())
        summary = layer.evaluate_candidates(available_tools={"describe_screen"}).summary()
        search = next(
            candidate
            for candidate in summary["candidates"]
            if candidate["capability_id"] == "capability.browser.search_current_page.v1"
        )
        self.assertFalse(search["eligible"])
        self.assertIn("missing_required_tools", search["reason_codes"])
        self.assertEqual(2, summary["eligible_candidate_count"])

    def test_missing_permission_and_platform_reject_capability(self) -> None:
        layer = CapabilityIntelligenceLayer.from_skill_registry(SkillRegistry())
        missing_permission = layer.evaluate_candidates(available_tools=TOOLS, available_permissions=()).summary()
        screen = missing_permission["candidates"][0]
        self.assertFalse(screen["eligible"])
        self.assertEqual(["missing_required_permissions"], screen["reason_codes"])

        missing_platform = layer.evaluate_candidates(available_tools=TOOLS, available_platforms={"macos_host"}).summary()
        screen = missing_platform["candidates"][0]
        self.assertFalse(screen["eligible"])
        self.assertEqual(["unsupported_platform"], screen["reason_codes"])

    def test_dependency_unavailability_prevents_a_trusted_candidate(self) -> None:
        base = capability("base", required_tools=frozenset({"unavailable_tool"}))
        dependent = capability("dependent", dependencies=(base.capability_id,))
        catalog = CapabilityCatalog((base, dependent))
        summary = CapabilityEvaluator().evaluate(
            catalog,
            available_tools={"describe_screen"},
            available_permissions=DEFAULT_SKILL_PERMISSIONS,
            available_platforms=DEFAULT_SKILL_PLATFORMS,
        ).summary()
        child = next(candidate for candidate in summary["candidates"] if candidate["capability_id"] == dependent.capability_id)
        self.assertFalse(child["eligible"])
        self.assertEqual(["dependency_unavailable"], child["reason_codes"])

    def test_successful_verifier_evidence_promotes_to_verified_without_raw_data(self) -> None:
        catalog = CapabilityCatalog((capability("evidence"),))
        recorded = catalog.record_evidence(
            "capability.testing.evidence",
            passed=True,
            confidence=0.9,
            verified_at=123,
        )
        self.assertEqual("VERIFIED", recorded["lifecycle"])
        self.assertEqual(
            {"success_count": 1, "failure_count": 0, "confidence": 0.9, "last_verified": 123},
            recorded["evidence"],
        )
        self.assertFalse(FORBIDDEN_KEYS.intersection(keys_in(recorded)))
        candidate = CapabilityEvaluator().evaluate(
            catalog,
            available_tools={"describe_screen"},
            available_permissions=DEFAULT_SKILL_PERMISSIONS,
            available_platforms=DEFAULT_SKILL_PLATFORMS,
        ).summary()["candidates"][0]
        self.assertEqual("VERIFIED", candidate["lifecycle"])
        self.assertTrue(candidate["eligible"])

    def test_failed_verifier_evidence_increments_only_approved_statistics(self) -> None:
        catalog = CapabilityCatalog((capability("failure"),))
        recorded = catalog.record_evidence(
            "capability.testing.failure",
            passed=False,
            confidence=0.2,
        )
        self.assertEqual(
            {"success_count": 0, "failure_count": 1, "confidence": 0.2, "last_verified": None},
            recorded["evidence"],
        )
        self.assertEqual("DISCOVERED", recorded["lifecycle"])

    def test_all_source_types_and_lifecycles_are_validated_as_metadata(self) -> None:
        source_types = ("native_shortcut", "learned_workflow", "skill_package", "computer_use", "external_tool")
        lifecycles = ("DISCOVERED", "AVAILABLE", "VERIFIED", "PREFERRED", "DEPRECATED")
        catalog = CapabilityCatalog()
        for index, (source_type, lifecycle) in enumerate(zip(source_types, lifecycles)):
            evidence = (
                CapabilityEvidence(success_count=1, confidence=0.8, last_verified=100)
                if lifecycle in {"VERIFIED", "PREFERRED"}
                else CapabilityEvidence()
            )
            catalog.register(
                capability(
                    "state%d" % index,
                    source_type=source_type,
                    lifecycle=lifecycle,
                    evidence=evidence,
                )
            )
        self.assertEqual(set(source_types), {contract["source_type"] for contract in catalog.contracts()})
        self.assertEqual(set(lifecycles), {contract["lifecycle"] for contract in catalog.contracts()})

    def test_invalid_source_lifecycle_and_evidence_are_rejected(self) -> None:
        with self.assertRaises(CapabilityIntelligenceError):
            CapabilityEvidence(success_count=-1)
        with self.assertRaises(CapabilityIntelligenceError):
            CapabilityCatalog((capability("badsource", source_type="unknown"),))
        with self.assertRaises(CapabilityIntelligenceError):
            CapabilityCatalog((capability("badverified", lifecycle="VERIFIED"),))
        with self.assertRaises(CapabilityIntelligenceError):
            CapabilityEvaluator().evaluate(
                CapabilityCatalog((capability("metadata"),)),
                available_tools=[{"unexpected": "object"}],  # type: ignore[list-item]
                available_permissions=DEFAULT_SKILL_PERMISSIONS,
                available_platforms=DEFAULT_SKILL_PLATFORMS,
            )

    def test_layer_has_no_execution_or_planning_interface(self) -> None:
        layer = CapabilityIntelligenceLayer.from_skill_registry(SkillRegistry())
        self.assertFalse(hasattr(layer, "client"))
        self.assertFalse(hasattr(layer, "execute"))
        self.assertFalse(hasattr(layer, "plan"))
        self.assertFalse(hasattr(layer, "select"))
        serialized = json.dumps(layer.evaluate_candidates(available_tools=TOOLS).summary(), ensure_ascii=False)
        self.assertNotIn("raw_mcp_response", serialized)
        self.assertNotIn("screenshot", serialized)


if __name__ == "__main__":
    unittest.main(verbosity=2)
