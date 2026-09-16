#!/usr/bin/env python3
"""Static contracts for TEST-40.3 governed capability and Skill intelligence.

The suite exercises only Mac-hosted metadata contracts.  It does not create or
run Shortcuts, invoke App Intents, call MCP, contact an iPhone, or perform a
device action.
"""

from __future__ import annotations

import unittest

from phoneharness_agent import (
    AppIntentDefinition,
    AppIntentRegistry,
    CapabilityCatalog,
    CapabilityDefinition,
    CapabilityEvidence,
    CapabilityIntelligenceError,
    CapabilityMethodDefinition,
    CapabilityMethodRegistry,
    ShortcutDefinition,
    ShortcutRegistry,
    SkillGovernanceCatalog,
    SkillManifest,
)


def capability_catalog() -> CapabilityCatalog:
    return CapabilityCatalog(
        (
            CapabilityDefinition(
                capability_id="capability.generic.search.v1",
                name="generic_search",
                description="generic_search_capability",
                version="1.0.0",
                source_type="skill_package",
                lifecycle="DISCOVERED",
                required_tools=frozenset(),
                required_permissions=("permission.generic",),
                risk_level="interaction",
                preconditions=(),
                verifier="result_visible",
                dependencies=(),
                platform_support=("macos_host",),
            ),
        )
    )


def active_method(method_id: str, method_type: str, *, source: str = "built_in") -> CapabilityMethodDefinition:
    return CapabilityMethodDefinition(
        method_id=method_id,
        capability_id="capability.generic.search.v1",
        name="generic_search_method",
        purpose="generic_search",
        version="1.0.0",
        method_type=method_type,
        source=source,
        lifecycle="ACTIVE",
        availability="available",
        required_permissions=("permission.generic",),
        risk_level="interaction",
        input_schema=("query_value",),
        output_schema=("result_state",),
        verifier="result_visible",
        platform_support=("macos_host",),
        evidence=CapabilityEvidence(success_count=4, failure_count=1, confidence=0.90, last_verified=100),
        verification_status="device_pass",
        latency_class="fast",
    )


class CapabilitySkillGovernanceTests(unittest.TestCase):
    def test_capability_method_prefers_app_intent_over_lower_reliability_paths(self) -> None:
        methods = CapabilityMethodRegistry(capability_catalog())
        methods.register(active_method("method.generic.appintent.v1", "app_intent"))
        methods.register(active_method("method.generic.shortcut.v1", "apple_shortcut"))
        methods.register(active_method("method.generic.mcp.v1", "mcp"))

        recommendation = methods.recommend(
            "capability.generic.search.v1",
            available_permissions={"permission.generic"},
            available_platforms={"macos_host"},
        )

        self.assertEqual("recommended", recommendation["status"])
        self.assertEqual("app_intent", recommendation["recommended_method"]["method_type"])
        self.assertEqual("none", recommendation["execution_authority"])
        self.assertEqual("planner_risk_executor_verifier", recommendation["next_gate"])

    def test_method_with_missing_permission_is_blocked_before_any_action_path(self) -> None:
        methods = CapabilityMethodRegistry(capability_catalog(), (active_method("method.generic.mcp.v1", "mcp"),))
        recommendation = methods.recommend(
            "capability.generic.search.v1",
            available_permissions=set(),
            available_platforms={"macos_host"},
        )

        self.assertEqual("blocked", recommendation["status"])
        self.assertIsNone(recommendation["recommended_method"])
        self.assertIn("missing_required_permissions", recommendation["candidates"][0]["reason_codes"])
        self.assertNotIn("execute", CapabilityMethodRegistry.__dict__)
        self.assertNotIn("call_tool", CapabilityMethodRegistry.__dict__)

    def test_external_method_candidate_cannot_be_promoted_without_a_later_review_phase(self) -> None:
        methods = CapabilityMethodRegistry(capability_catalog())
        with self.assertRaises(CapabilityIntelligenceError):
            methods.register(active_method("method.generic.external.v1", "apple_shortcut", source="external_candidate"))

    def test_shortcut_contract_records_metadata_not_action_graph(self) -> None:
        methods = CapabilityMethodRegistry(capability_catalog())
        shortcuts = ShortcutRegistry(methods)
        contract = shortcuts.register(
            ShortcutDefinition(
                shortcut_id="shortcut.generic.search.v1",
                name="generic_search_shortcut",
                purpose="generic_search",
                capability_id="capability.generic.search.v1",
                version="1.0.0",
                source="user_created",
                lifecycle="CANDIDATE",
                availability="unknown",
                required_permissions=("permission.generic",),
                risk_level="interaction",
                input_schema=("query_value",),
                output_schema=("result_state",),
                verifier="result_visible",
                platform_support=("macos_host",),
            )
        )

        self.assertEqual("apple_shortcut", contract["method_type"])
        self.assertEqual("not_stored", contract["shortcut_action_graph"])
        self.assertEqual("none", contract["execution_authority"])
        self.assertNotIn("shortcut_actions", contract)

    def test_app_intent_contract_is_future_entry_metadata_not_ios_code(self) -> None:
        methods = CapabilityMethodRegistry(capability_catalog())
        intents = AppIntentRegistry(methods)
        contract = intents.register(
            AppIntentDefinition(
                intent_id="appintent.generic.start.v1",
                name="generic_start_intent",
                purpose="start_task",
                capability_id="capability.generic.search.v1",
                version="1.0.0",
                lifecycle="CANDIDATE",
                availability="unknown",
                required_permissions=("permission.generic",),
                risk_level="interaction",
                input_schema=("goal_reference",),
                output_schema=("task_status",),
                verifier="result_visible",
                platform_support=("macos_host",),
                exposure="start_agent_task",
            )
        )

        self.assertEqual("app_intent", contract["method_type"])
        self.assertEqual("not_implemented", contract["ios_entrypoint"])
        self.assertEqual("none", contract["execution_authority"])

    def test_skill_candidate_lifecycle_requires_evidence_and_audits_every_transition(self) -> None:
        governance = SkillGovernanceCatalog()
        created = governance.register(
            SkillManifest(
                skill_id="generic.search.skill.v1",
                name="generic_search_skill",
                description="generic_search_skill",
                version="1.0.0",
                domain="general",
                source="user_taught",
                trust_state="user_confirmed",
                lifecycle="CREATED",
                required_capabilities=("capability.generic.search.v1",),
                dependencies=(),
                requested_permissions=("permission.generic",),
                risk_level="interaction",
                verifier="result_visible",
                platform_support=("macos_host",),
            ),
            timestamp=10,
        )
        self.assertEqual("CREATED", created["lifecycle"])
        governance.transition("generic.search.skill.v1", "CANDIDATE", reason_code="teaching_received", timestamp=11)
        governance.transition("generic.search.skill.v1", "REVIEWED", reason_code="review_completed", timestamp=12)
        governance.record_evidence(
            "generic.search.skill.v1",
            passed=True,
            confidence=0.91,
            verification_status="device_pass",
            timestamp=13,
        )
        governance.transition("generic.search.skill.v1", "VERIFIED", reason_code="validation_passed", timestamp=14)
        active = governance.transition("generic.search.skill.v1", "ACTIVE", reason_code="graduation_approved", timestamp=15)

        self.assertEqual("ACTIVE", active["lifecycle"])
        self.assertEqual(1, active["usage_history"]["success_count"])
        audit = governance.audit_records(skill_id="generic.search.skill.v1")
        self.assertEqual(6, len(audit))
        self.assertEqual("ACTIVE", audit[-1]["lifecycle"])
        self.assertTrue(all(set(event) == {"skill_id", "previous_lifecycle", "lifecycle", "reason_code", "timestamp"} for event in audit))

    def test_external_skill_candidate_stays_outside_runtime_activation(self) -> None:
        governance = SkillGovernanceCatalog()
        with self.assertRaises(CapabilityIntelligenceError):
            governance.register(
                SkillManifest(
                    skill_id="external.generic.skill.v1",
                    name="external_generic_skill",
                    description="external_generic_skill",
                    version="1.0.0",
                    domain="general",
                    source="external_candidate",
                    trust_state="untrusted",
                    lifecycle="VERIFIED",
                    required_capabilities=("capability.generic.search.v1",),
                    dependencies=(),
                    requested_permissions=(),
                    risk_level="interaction",
                    verifier="result_visible",
                    platform_support=("macos_host",),
                    evidence=CapabilityEvidence(success_count=1, confidence=0.90, last_verified=20),
                    verification_status="device_pass",
                )
            )

    def test_skill_manifest_cannot_select_or_execute(self) -> None:
        self.assertNotIn("select", SkillGovernanceCatalog.__dict__)
        self.assertNotIn("execute", SkillGovernanceCatalog.__dict__)
        self.assertNotIn("call_tool", SkillGovernanceCatalog.__dict__)


if __name__ == "__main__":
    unittest.main(verbosity=2)
