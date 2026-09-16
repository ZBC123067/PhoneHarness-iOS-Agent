#!/usr/bin/env python3
"""TEST-52 AX semantic field observability contracts.

The host tests exercise the fail-closed normalization boundary. Source checks
ensure that the device package keeps legacy output opt-in and derives all
authoritative field state from the same compact AX leaf.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
import unittest

from phoneharness_agent import (
    MCPClient,
    SemanticAXSourceProbe,
    SemanticSearchFieldEvidence,
    SemanticSourceProbeError,
    TEST52_AX_SOURCE_PROBE_COUNTERS,
    TEST52_AX_SOURCE_PROBE_FIELDS,
    TEST52_AX_SOURCE_PROBE_SCHEMA,
)


ROOT = Path(__file__).resolve().parent


def state(value, source: str) -> dict:
    return {"value": value, "source": source}


def compact_field(**overrides) -> dict:
    semantic_state = {
        "semantic_role": state("search_field", "xc_attribute"),
        "editable": state(True, "ax_attribute"),
        "secure": state(False, "xc_attribute"),
        "enabled": state(True, "ax_attribute"),
        "focused": state(False, "ax_attribute"),
        "visible": state(True, "xc_attribute"),
        "actionable": state(True, "xc_attribute"),
        "value_match": state("unknown", "unavailable"),
        "same_leaf_identity": True,
    }
    semantic_state.update(overrides.pop("semantic_state", {}))
    result = {
        "id": "c.0",
        "path": "c.0",
        "text": "Search",
        "semantic_leaf_ref": "c.0",
        "semantic_state": semantic_state,
    }
    result.update(overrides)
    return result


def synthetic_snapshot_field(**overrides) -> SemanticSearchFieldEvidence:
    """Explicit host-only snapshot evidence, never a claim about the MCP crawler."""
    normalized = SemanticSearchFieldEvidence.from_compact_element(compact_field(**overrides))
    return replace(normalized, same_leaf_identity=True, same_leaf_source="direct_snapshot",
                   snapshot_ref="synthetic.snapshot")


def aggregate_diagnostic_payload(**overrides) -> dict:
    fields = {
        field: {
            **{counter: 0 for counter in TEST52_AX_SOURCE_PROBE_COUNTERS},
            "error_category_counts": {},
        }
        for field in TEST52_AX_SOURCE_PROBE_FIELDS
    }
    fields["editable"].update(
        {
            "attribute_present_count": 1,
            "ax_single_read_success_count": 1,
            "settable_or_availability_count": 1,
        }
    )
    diagnostic = {
        "schema": TEST52_AX_SOURCE_PROBE_SCHEMA,
        "node_count": 1,
        "same_leaf_identity_count": 1,
        "fields": fields,
    }
    diagnostic.update(overrides)
    return {"semantic_diagnostics": diagnostic}


class FakeMCPClient(MCPClient):
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict]] = []
        self._semantic_search_observation_version = 0
        import threading

        self._semantic_search_observation_lock = threading.Lock()

    def call_tool(self, name: str, arguments: dict) -> dict:
        self.calls.append((name, dict(arguments)))
        return self.payload


class AXSemanticFieldObservabilityTests(unittest.TestCase):
    def test_legacy_default_remains_opt_in(self) -> None:
        server = (ROOT / "MCPServer.m").read_text(encoding="utf-8")
        self.assertIn('MCPBoolFromArgs(args, @"include_semantic_state", NO', server)
        self.assertIn('@"include_semantic_state"', server)

    def test_diagnostic_protocol_is_explicit_default_off_and_state_dependent(self) -> None:
        server = (ROOT / "MCPServer.m").read_text(encoding="utf-8")
        self.assertIn('MCPBoolFromArgs(args, @"include_semantic_diagnostics", NO', server)
        self.assertIn("include_semantic_diagnostics requires include_semantic_state=true", server)
        self.assertIn('@"semantic_diagnostics_requested"', server)
        self.assertIn('@"semantic_diagnostics"', server)

    def test_diagnostic_request_is_wired_to_same_compact_ax_source(self) -> None:
        manager_header = (ROOT / "AccessibilityManager.h").read_text(encoding="utf-8")
        manager = (ROOT / "AccessibilityManager.m").read_text(encoding="utf-8")
        source_header = (ROOT / "MCPAXNodeSource.h").read_text(encoding="utf-8")
        source = (ROOT / "MCPAXNodeSource.m").read_text(encoding="utf-8")
        for text in (manager_header, manager, source_header, source):
            self.assertIn("includeSemanticDiagnostics", text)
        self.assertIn("MCPAXNodeAccumulateSemanticDiagnostics", source)
        self.assertIn('payload[@"semantic_diagnostics"]', source)

    def test_diagnostic_parser_accepts_aggregate_only_schema(self) -> None:
        probe = SemanticAXSourceProbe.from_payload(aggregate_diagnostic_payload())
        summary = probe.safe_summary()
        self.assertEqual(TEST52_AX_SOURCE_PROBE_SCHEMA, summary["schema"])
        self.assertEqual(1, summary["node_count"])
        self.assertEqual(1, summary["same_leaf_identity_count"])
        self.assertEqual(1, summary["fields"]["editable"]["attribute_present_count"])
        rendered = repr(summary).casefold()
        for forbidden in ("screenshot", "coordinate", "raw_value", "password", "selector_text"):
            self.assertNotIn(forbidden, rendered)

    def test_diagnostic_parser_rejects_missing_or_unknown_schema(self) -> None:
        with self.assertRaises(SemanticSourceProbeError):
            SemanticAXSourceProbe.from_payload({})
        with self.assertRaises(SemanticSourceProbeError):
            SemanticAXSourceProbe.from_payload(
                aggregate_diagnostic_payload(schema="phoneharness.test52.unknown")
            )

    def test_diagnostic_parser_rejects_extra_fields_and_private_error_categories(self) -> None:
        payload = aggregate_diagnostic_payload()
        payload["semantic_diagnostics"]["private_content"] = "not allowed"
        with self.assertRaises(SemanticSourceProbeError):
            SemanticAXSourceProbe.from_payload(payload)

        payload = aggregate_diagnostic_payload()
        payload["semantic_diagnostics"]["fields"]["editable"]["error_category_counts"] = {
            "raw value": 1
        }
        with self.assertRaises(SemanticSourceProbeError):
            SemanticAXSourceProbe.from_payload(payload)

    def test_diagnostic_counts_cannot_exceed_node_count(self) -> None:
        payload = aggregate_diagnostic_payload()
        payload["semantic_diagnostics"]["fields"]["editable"]["attribute_present_count"] = 2
        with self.assertRaises(SemanticSourceProbeError):
            SemanticAXSourceProbe.from_payload(payload)

    def test_batch_type_diagnostic_is_aggregate_indexed_and_parser_safe(self) -> None:
        bridge = (ROOT / "MCPAXAttributeBridge.m").read_text(encoding="utf-8")
        for token in (
            "batch_%@_index_%@_%@",
            '@"AXRole": @"axrole"',
            '@"AXSubrole": @"axsubrole"',
            '@"AXEnabled": @"axenabled"',
            '@"AXFocused": @"axfocused"',
            '@[@"zero", @"one", @"two", @"three"]',
        ):
            self.assertIn(token, bridge)

        payload = aggregate_diagnostic_payload()
        payload["semantic_diagnostics"]["fields"]["enabled"]["error_category_counts"] = {
            "batch_axenabled_index_two_error_object": 1
        }
        summary = SemanticAXSourceProbe.from_payload(payload).safe_summary()
        self.assertEqual(
            1,
            summary["fields"]["enabled"]["error_category_counts"][
                "batch_axenabled_index_two_error_object"
            ],
        )

    def test_batch_error_null_and_unknown_wrappers_are_never_counted_as_success(self) -> None:
        bridge = (ROOT / "MCPAXAttributeBridge.m").read_text(encoding="utf-8")
        self.assertIn('return axValueType == 5 ? @"error_object" : @"ax_value"', bridge)
        start = bridge.index("static BOOL MCPAXBridgeSemanticProbeValueIsValid")
        end = bridge.index("static NSString *MCPAXBridgeSemanticProbeAttributeToken", start)
        validator = bridge[start:end]
        self.assertIn('![category isEqualToString:@"boolean"] && ![category isEqualToString:@"number"]', validator)
        self.assertIn('number == 0.0 || number == 1.0', validator)
        self.assertIn('MCPAXBridgeSemanticProbeValueIsValid(value, name)', bridge)

    def test_bridge_filters_explicit_error_placeholders_without_coercing_valid_values(self) -> None:
        bridge = (ROOT / "MCPAXAttributeBridge.m").read_text(encoding="utf-8")
        helper_start = bridge.index("static BOOL MCPAXBridgeIsExplicitlyUnavailableAttributeValue")
        helper_end = bridge.index("static BOOL MCPAXBridgeSemanticProbeValueIsValid")
        helper = bridge[helper_start:helper_end]
        self.assertIn('isEqualToString:@"null_object"', helper)
        self.assertIn('isEqualToString:@"error_object"', helper)
        for valid_category in ("boolean", "number", "string", "ax_value", "unknown_wrapper"):
            self.assertNotIn(f'isEqualToString:@"{valid_category}"', helper)

        self.assertEqual(
            3,
            bridge.count("MCPAXBridgeIsExplicitlyUnavailableAttributeValue(value)"),
        )
        self.assertIn(
            "MCPAXBridgeIsExplicitlyUnavailableAttributeValue(object)",
            bridge,
        )

    def test_direct_boolean_true_and_false_remain_authoritative_values(self) -> None:
        for value in (True, False):
            with self.subTest(value=value):
                evidence = SemanticSearchFieldEvidence.from_compact_element(
                    compact_field(semantic_state={"focused": state(value, "ax_attribute")})
                )
                self.assertIsNotNone(evidence)
                self.assertEqual(value, evidence.focused)
                self.assertEqual("ax_attribute", evidence.focused_source)

    def test_batch_type_diagnostic_does_not_emit_runtime_values_or_descriptions(self) -> None:
        bridge = (ROOT / "MCPAXAttributeBridge.m").read_text(encoding="utf-8")
        classifier_start = bridge.index("static NSString *MCPAXBridgeSemanticBatchObjectCategory")
        classifier_end = bridge.index("static NSString *MCPAXBridgeSemanticProbeAttributeToken")
        classifier = bridge[classifier_start:classifier_end]
        self.assertNotIn("description]", classifier)
        self.assertNotIn("UTF8String", classifier)
        self.assertNotIn("NSLog", classifier)

    def test_legacy_response_without_diagnostic_remains_supported(self) -> None:
        client = FakeMCPClient({"elements": [compact_field()]})
        observation = client.observe_semantic_search_page(task_id="task.52", context_id="context.52")
        self.assertEqual(1, len(observation.fields))
        self.assertNotIn("include_semantic_diagnostics", client.calls[0][1])

    def test_device_uses_same_leaf_and_direct_settable_probe(self) -> None:
        bridge = (ROOT / "MCPAXAttributeBridge.m").read_text(encoding="utf-8")
        source = (ROOT / "MCPAXNodeSource.m").read_text(encoding="utf-8")
        self.assertIn("AXUIElementIsAttributeSettable", bridge)
        self.assertIn('@"same_leaf_identity"', source)
        self.assertIn('@"semantic_leaf_ref"', source)
        self.assertNotIn('editable = editable_value is True or "searchfield"', (ROOT / "phoneharness_agent.py").read_text())

    def test_bridge_error_placeholder_match_uses_node_source_sentinels(self) -> None:
        bridge = (ROOT / "MCPAXAttributeBridge.m").read_text(encoding="utf-8")
        classifier_start = bridge.index("static NSString *MCPAXBridgeSemanticBatchObjectCategory")
        classifier_end = bridge.index("static NSString *MCPAXBridgeSemanticProbeAttributeToken")
        classifier = bridge[classifier_start:classifier_end]
        self.assertIn('containsString:@"error:-252"', classifier)
        self.assertIn('containsString:@"kaxvalueaxerrortype"', classifier)
        self.assertNotIn('containsString:@"axerror"', classifier)

    def test_semantic_probe_has_bounded_main_thread_budget(self) -> None:
        source = (ROOT / "MCPAXNodeSource.m").read_text(encoding="utf-8")
        self.assertIn("kMCPAXNodeSemanticProbeLimit", source)
        self.assertIn("probeSkippedCount", source)
        self.assertIn('payload[@"semantic_probe_limit"]', source)
        self.assertIn('payload[@"semantic_probe_skipped_count"]', source)

    def test_compact_same_leaf_claim_is_not_eligible(self) -> None:
        evidence = SemanticSearchFieldEvidence.from_compact_element(compact_field())
        self.assertIsNotNone(evidence)
        self.assertFalse(evidence.eligible())

    def test_synthetic_snapshot_direct_field_is_eligible(self) -> None:
        self.assertTrue(synthetic_snapshot_field().eligible())

    def test_role_alone_never_proves_editability(self) -> None:
        raw = compact_field(semantic_state={"editable": state("unknown", "unavailable")})
        evidence = SemanticSearchFieldEvidence.from_compact_element(raw)
        self.assertIsNotNone(evidence)
        self.assertFalse(evidence.eligible())

    def test_secure_and_unknown_secure_fail_closed(self) -> None:
        for value, source in ((True, "xc_attribute"), ("unknown", "unavailable"), (False, "inferred")):
            with self.subTest(value=value, source=source):
                evidence = SemanticSearchFieldEvidence.from_compact_element(
                    compact_field(semantic_state={"secure": state(value, source)})
                )
                self.assertIsNotNone(evidence)
                self.assertFalse(evidence.eligible())

    def test_inferred_state_is_not_action_authority(self) -> None:
        for key in ("editable", "enabled", "visible", "actionable"):
            with self.subTest(key=key):
                evidence = SemanticSearchFieldEvidence.from_compact_element(
                    compact_field(semantic_state={key: state(True, "inferred")})
                )
                self.assertIsNotNone(evidence)
                self.assertFalse(evidence.eligible())

    def test_missing_or_malformed_state_fails_closed(self) -> None:
        for raw in ({}, {"semantic_state": {}}, compact_field(semantic_state={"enabled": {"value": True}})):
            with self.subTest(raw=raw):
                evidence = SemanticSearchFieldEvidence.from_compact_element(raw)
                self.assertTrue(evidence is None or not evidence.eligible())

    def test_observation_does_not_rehit_rect_center(self) -> None:
        client = FakeMCPClient({"elements": [compact_field()], "frontmost": {"bundle_id": "public.test"}})
        observation = client.observe_semantic_search_page(task_id="task.52", context_id="context.52")
        self.assertEqual(1, len(observation.fields))
        self.assertEqual(["get_ui_elements"], [name for name, _ in client.calls])
        self.assertTrue(client.calls[0][1]["include_semantic_state"])

    def test_ephemeral_value_comparison_uses_digest_and_returns_no_value(self) -> None:
        query = "PhoneHarness"
        raw = compact_field(
            semantic_state={"value_match": state(True, "ax_attribute")}
        )
        client = FakeMCPClient({"elements": [raw]})
        observation = client.observe_semantic_search_page(
            task_id="task.52", context_id="context.52", expected_query=query
        )
        args = client.calls[0][1]
        self.assertEqual(hashlib.sha256(query.encode()).hexdigest(), args["semantic_expected_value_sha256"])
        self.assertNotIn(query, repr(observation.safe_summary()))
        self.assertTrue(observation.fields[0].value_matches_expected)

    def test_safe_summary_contains_no_selector_or_raw_value(self) -> None:
        evidence = SemanticSearchFieldEvidence.from_compact_element(compact_field(text="private value"))
        self.assertIsNotNone(evidence)
        rendered = repr(evidence.safe_summary())
        self.assertNotIn("private value", rendered)
        self.assertNotIn("selector_text", rendered)

    def test_same_leaf_identity_is_required(self) -> None:
        evidence = SemanticSearchFieldEvidence.from_compact_element(
            compact_field(semantic_state={"same_leaf_identity": False})
        )
        self.assertIsNotNone(evidence)
        self.assertFalse(evidence.eligible())

    def test_semantic_leaf_reference_is_required(self) -> None:
        for raw in (compact_field(semantic_leaf_ref=""), compact_field(semantic_leaf_ref=None)):
            with self.subTest(raw=raw):
                self.assertIsNone(SemanticSearchFieldEvidence.from_compact_element(raw))

    def test_empty_selector_is_ineligible(self) -> None:
        evidence = SemanticSearchFieldEvidence.from_compact_element(compact_field(text="  "))
        self.assertIsNotNone(evidence)
        self.assertFalse(evidence.eligible())

    def test_unknown_semantic_role_is_ineligible(self) -> None:
        evidence = SemanticSearchFieldEvidence.from_compact_element(
            compact_field(semantic_state={"semantic_role": state("unknown", "unavailable")})
        )
        self.assertIsNotNone(evidence)
        self.assertFalse(evidence.eligible())

    def test_non_text_semantic_role_is_ineligible(self) -> None:
        evidence = SemanticSearchFieldEvidence.from_compact_element(
            compact_field(semantic_state={"semantic_role": state("button", "xc_attribute")})
        )
        self.assertIsNotNone(evidence)
        self.assertFalse(evidence.eligible())

    def test_unknown_provenance_is_sanitized_to_unavailable(self) -> None:
        evidence = SemanticSearchFieldEvidence.from_compact_element(
            compact_field(semantic_state={"enabled": state(True, "private_selector")})
        )
        self.assertIsNotNone(evidence)
        self.assertEqual("unavailable", evidence.enabled_source)
        self.assertFalse(evidence.eligible())

    def test_false_required_state_is_ineligible(self) -> None:
        for key in ("editable", "enabled", "visible", "actionable"):
            with self.subTest(key=key):
                evidence = SemanticSearchFieldEvidence.from_compact_element(
                    compact_field(semantic_state={key: state(False, "ax_attribute")})
                )
                self.assertIsNotNone(evidence)
                self.assertFalse(evidence.eligible())

    def test_focus_verification_requires_direct_true_evidence(self) -> None:
        cases = ((True, "ax_attribute", True), (True, "inferred", False), (False, "ax_attribute", False))
        for value, source, expected in cases:
            with self.subTest(value=value, source=source):
                evidence = synthetic_snapshot_field(semantic_state={"focused": state(value, source)})
                self.assertIsNotNone(evidence)
                self.assertEqual(expected, evidence.focus_is_verified())

    def test_value_verification_requires_direct_true_evidence(self) -> None:
        cases = ((True, "ax_attribute", True), (True, "inferred", False), (False, "ax_attribute", False))
        for value, source, expected in cases:
            with self.subTest(value=value, source=source):
                evidence = synthetic_snapshot_field(semantic_state={"value_match": state(value, source)})
                self.assertIsNotNone(evidence)
                self.assertEqual(expected, evidence.expected_value_is_verified())

    def test_no_expected_query_sends_no_digest(self) -> None:
        client = FakeMCPClient({"elements": [compact_field()]})
        client.observe_semantic_search_page(task_id="task.52", context_id="context.52")
        self.assertNotIn("semantic_expected_value_sha256", client.calls[0][1])

    def test_protocol_rejects_invalid_digest_and_requires_opt_in(self) -> None:
        server = (ROOT / "MCPServer.m").read_text(encoding="utf-8")
        self.assertIn("semantic_expected_value_sha256 requires include_semantic_state=true", server)
        self.assertIn("exactly 64 lowercase hex characters", server)

    def test_device_does_not_return_expected_digest_or_raw_value(self) -> None:
        source = (ROOT / "MCPAXNodeSource.m").read_text(encoding="utf-8")
        semantic_block = source[source.index('semanticState[@"value_match"]'):]
        self.assertNotIn('semanticState[@"raw_value"]', semantic_block)
        self.assertNotIn('semanticState[@"expected_value_sha256"]', semantic_block)


if __name__ == "__main__":
    unittest.main()
