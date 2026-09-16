#!/usr/bin/env python3
"""Track A host gates. No device, native build, or real MCP transport."""

import copy
from dataclasses import replace
import importlib.util
import tempfile
import unittest
from pathlib import Path

import phoneharness_agent as p

ROOT = Path(__file__).resolve().parent


def load_fixture(filename):
    spec = importlib.util.spec_from_file_location(filename.replace("-", "_"), ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ax = load_fixture("test-agent-ax-semantic-field-observability-unit.py")
governance = load_fixture("test-agent-input-orchestrator-governance-unit.py")
search = load_fixture("test-agent-semantic-search-transaction-unit.py")


def payload():
    return {"bundleId": "example.fixture", "pid": 123, "contextId": 10, "displayId": 1,
            "elements": [ax.compact_field(semantic_state={
                "focused": ax.state(True, "ax_attribute"),
                "value_match": ax.state(True, "xc_attribute"),
            })]}


class RawClient(p.MCPClient):
    def __init__(self, data):
        super().__init__("http://unused.invalid")
        self.data = data
        self.external_actions = []

    def call_tool(self, name, arguments):
        if name != "get_ui_elements":
            self.external_actions.append(name)
            raise AssertionError("no action is allowed in the evidence fixture")
        return copy.deepcopy(self.data)


class NormalizationTests(unittest.TestCase):
    def observation(self, data):
        return RawClient(data).observe_semantic_search_page(task_id="task.test", context_id="context.test")

    def test_unproven_same_leaf_flag_is_unavailable(self):
        field = self.observation(payload()).fields[0]
        self.assertIsNone(field.same_leaf_identity)
        self.assertEqual("unavailable", field.same_leaf_source)
        self.assertFalse(field.eligible())

    def test_forged_snapshot_metadata_is_not_accepted(self):
        data = payload()
        data.update(device_generation="forged", snapshot_source="direct_snapshot")
        data["elements"][0]["semantic_state"].update(snapshot_id="fake", same_leaf_identity=True)
        field = self.observation(data).fields[0]
        self.assertIsNone(field.same_leaf_identity)
        self.assertFalse(field.eligible())

    def test_boolean_strings_numbers_and_error_objects_are_unavailable(self):
        for value in ("true", "false", "AXError:-25205", "placeholder", 0, 1, 2,
                      None, {"error": -25205}, [], float("nan")):
            for key in ("editable", "secure", "focused", "enabled", "visible", "actionable", "value_match"):
                with self.subTest(key=key, value=value):
                    raw = ax.compact_field(semantic_state={key: ax.state(value, "xc_attribute")})
                    field = p.SemanticSearchFieldEvidence.from_compact_element(raw)
                    attribute = "value_matches_expected" if key == "value_match" else key
                    source = "value_match_source" if key == "value_match" else key + "_source"
                    self.assertIsNone(getattr(field, attribute))
                    self.assertEqual("unavailable", getattr(field, source))

    def test_derived_secure_false_is_never_authoritative(self):
        field = ax.synthetic_snapshot_field(semantic_state={"secure": ax.state(False, "inferred")})
        self.assertTrue(field.has_same_leaf_identity())
        self.assertFalse(field.eligible())

    def test_unknown_state_does_not_retain_direct_provenance(self):
        raw = ax.compact_field(semantic_state={"focused": ax.state("unknown", "ax_attribute")})
        field = p.SemanticSearchFieldEvidence.from_compact_element(raw)
        self.assertEqual("unavailable", field.focused_source)

    def test_invalid_role_does_not_retain_direct_provenance(self):
        for value in ("unknown", "placeholder", "AXError:-25205", "", True, {"error": -25205}):
            raw = ax.compact_field(semantic_state={"semantic_role": ax.state(value, "ax_attribute")})
            field = p.SemanticSearchFieldEvidence.from_compact_element(raw)
            self.assertEqual("unknown", field.role)
            self.assertEqual("unavailable", field.role_source)

    def test_unproven_leaf_cannot_verify_focus_or_value(self):
        field = self.observation(payload()).fields[0]
        self.assertFalse(field.focus_is_verified())
        self.assertFalse(field.expected_value_is_verified())

    def test_freshness_is_explicitly_host_derived(self):
        observation = self.observation(payload())
        self.assertEqual("host_derived", observation.freshness_source)
        self.assertIsNone(observation.device_generation)
        self.assertEqual("unavailable", observation.device_generation_source)
        self.assertEqual("host_derived", observation.safe_summary()["freshness_source"])

    def test_repeated_payload_gets_no_new_device_generation(self):
        client = RawClient(payload())
        first = client.observe_semantic_search_page(task_id="task.test", context_id="context.test")
        second = client.observe_semantic_search_page(task_id="task.test", context_id="context.test")
        self.assertGreater(second.observation_version, first.observation_version)
        self.assertEqual(first.page_fingerprint, second.page_fingerprint)
        self.assertIsNone(second.device_generation)
        self.assertFalse(second.fields[0].eligible())

    def test_actual_bundle_id_changes_fingerprint(self):
        first, second = payload(), payload()
        second["bundleId"] = "example.other"
        self.assertNotEqual(self.observation(first).page_fingerprint, self.observation(second).page_fingerprint)

    def test_actual_device_context_changes_fingerprint(self):
        for key in ("contextId", "displayId", "pid"):
            first, second = payload(), payload()
            second[key] += 1
            self.assertNotEqual(self.observation(first).page_fingerprint, self.observation(second).page_fingerprint)

    def test_bundle_alias_mismatch_rejected(self):
        data = payload()
        data["frontmost"] = {"bundle_id": "example.other"}
        with self.assertRaises(p.MCPCallError):
            self.observation(data)

    def test_context_alias_mismatch_rejected(self):
        data = payload()
        data["frontmostContext"] = {"contextId": 999}
        with self.assertRaises(p.MCPCallError):
            self.observation(data)

    def test_matching_aliases_have_same_fingerprint(self):
        first, second = payload(), payload()
        second["frontmost"] = {"bundle_id": first["bundleId"]}
        second["frontmostContext"] = {"contextId": first["contextId"]}
        self.assertEqual(self.observation(first).page_fingerprint, self.observation(second).page_fingerprint)

    def test_malformed_identity_rejected(self):
        for key, value in (("bundleId", {}), ("pid", True), ("contextId", "10"), ("displayId", -1)):
            data = payload()
            data[key] = value
            with self.subTest(key=key), self.assertRaises(p.MCPCallError):
                self.observation(data)


class RiskBoundaryTests(unittest.TestCase):
    def assert_no_executor(self, data):
        with tempfile.TemporaryDirectory() as directory:
            client = RawClient(data)
            risk = p.RiskController()
            engine = p.ActiveContextEngine(Path(directory) / "context")
            owner = "synthetic-owner"
            context = engine.create(owner, task_ref="task.evidence", workspace_ref="workspace.test",
                                    goal_ref="goal.test", intent_category="text_entry", domain_code="test")
            engine.activate(context["context_id"], owner)
            runtime = p.GovernedInputTextRuntime(client, capability_method_registry=governance.registry(),
                action_obligation_ledger=p.ActionObligationLedger(Path(directory) / "ledger"), risk_controller=risk)
            with self.assertRaises(p.InputTextActionBindingError):
                risk.authorize_input_target("abc", client=client, context_engine=engine,
                    context_id=context["context_id"], owner_token=owner, keyboard="apple_qwerty")
            self.assertEqual(0, runtime.plan_executor_invocation_count)
            self.assertEqual([], client.external_actions)

    def test_raw_same_leaf_claim_executor_zero(self):
        self.assert_no_executor(payload())

    def test_derived_and_unknown_evidence_executor_zero(self):
        for key in ("editable", "secure", "focused", "visible"):
            for source in ("inferred", "unavailable"):
                data = payload()
                data["elements"][0]["semantic_state"][key]["source"] = source
                self.assert_no_executor(data)

    def test_cross_snapshot_stitched_state_executor_zero(self):
        data = payload()
        data["device_generation"] = "snapshot.new"
        data["elements"][0]["semantic_state"]["focused"]["generation"] = "snapshot.old"
        self.assert_no_executor(data)

    def test_stale_payload_with_new_host_receipt_executor_zero(self):
        data = payload()
        data.update(observed_at=1, device_generation="snapshot.old")
        self.assert_no_executor(data)

    def test_bundle_identity_mismatch_executor_zero(self):
        data = payload()
        data["frontmost_bundle_id"] = "example.different"
        self.assert_no_executor(data)


class SnapshotCorrelationTests(unittest.TestCase):
    """Synthetic typed snapshots exercise contracts, not device capabilities."""

    def test_cross_snapshot_leaf_rejected_before_execution(self):
        current = search.observation(1)
        stitched = replace(current, fields=(replace(current.fields[0], snapshot_ref="synthetic.old"),))
        client = search.FakeSearchClient([stitched])
        with tempfile.TemporaryDirectory() as directory:
            runtime = p.GovernedSemanticSearchRuntime(client,
                action_obligation_ledger=p.ActionObligationLedger(Path(directory) / "ledger"))
            result = runtime.execute_query("fixture", task_id="task.search", context_id="context.search",
                                           permission_decision=search.permission())
        self.assertEqual("blocked", result["status"])
        self.assertEqual("STALE_CONTEXT", result["reason_code"])
        self.assertEqual(0, result["device_action_count"])
        self.assertEqual([], result["method_health_effect"])
        self.assertEqual([], client.calls)

    def test_reused_device_generation_with_new_host_version_rejected(self):
        store = p.SemanticSearchTransactionStore()
        first = search.observation(1)
        bound = store.begin_explicit("fixture", first, task_id="task.search", context_id="context.search")
        replay = replace(first, observation_version=2, observed_at=102)
        with self.assertRaisesRegex(p.SemanticSearchPolicyError, "snapshot was reused"):
            store.observe(bound.transaction_id, replay, task_id="task.search", context_id="context.search")

    def test_missing_snapshot_provenance_rejected(self):
        current = search.observation(1)
        for changed in (replace(current, device_generation_source="host_derived"),
                        replace(current, device_generation=None),
                        replace(current, fields=(replace(current.fields[0], same_leaf_source="unavailable"),))):
            self.assertFalse(changed.snapshot_is_correlated())

    def test_result_snapshot_without_field_cannot_authorize_input(self):
        current = search.observation(1, fields=(), result_state=True)
        self.assertTrue(current.snapshot_is_correlated())
        with self.assertRaisesRegex(p.SemanticSearchPolicyError, "INELIGIBLE"):
            p.SemanticSearchTransactionStore().begin_explicit("fixture", current,
                task_id="task.search", context_id="context.search")


class NativeSourceContracts(unittest.TestCase):
    """Source assertions only; these do not compile or run Objective-C."""

    def setUp(self):
        self.node = (ROOT / "MCPAXNodeSource.m").read_text()
        self.bridge = (ROOT / "MCPAXAttributeBridge.m").read_text()
        start = self.node.rindex("- (NSDictionary * _Nullable)serializeCompactLeafElement:")
        self.compact = self.node[start:self.node.index("- (NSDictionary * _Nullable)compactElementsForPid:", start)]

    def test_secure_type_is_inferred(self):
        start = self.compact.index("BOOL secureKnown")
        end = self.compact.index("NSNumber *enabledValue", start)
        block = self.compact[start:end]
        self.assertNotIn('secureSource = @"xc_attribute"', block)
        self.assertNotIn('secureSource = @"ax_attribute"', block)
        self.assertIn('secureSource = @"inferred"', block)

    def test_native_same_leaf_is_not_asserted(self):
        self.assertNotIn('@"same_leaf_identity": @YES', self.compact)
        self.assertIn('@"same_leaf_identity": @"unknown"', self.compact)
        self.assertIn('@"same_leaf_identity_source": @"unavailable"', self.compact)

    def test_semantic_boolean_uses_strict_decoder(self):
        for key in ("AXEnabled", "AXFocused", "isVisible", "isUserInteractionEnabled"):
            self.assertRegex(self.compact, r'MCPAXNodeSemanticBoolean\([^\n]+\[@"' + key + r'"\]\)')
        start = self.node.index("static NSNumber *MCPAXNodeSemanticBoolean")
        end = self.node.index("\n}\n", start)
        self.assertNotIn("NSString", self.node[start:end])

    def test_all_probe_reads_validate_type(self):
        for assignment in ("batchRead[name]", "singleRead[name]", "xcRead[key]"):
            start = self.bridge.index(assignment + " = @(")
            end = self.bridge.index(";", start)
            self.assertIn("MCPAXBridgeSemanticProbeValueIsValid", self.bridge[start:end])

    def test_secure_diagnostic_does_not_count_type_probes_as_property(self):
        definition = next(line.strip() for line in self.bridge.splitlines() if '@{ @"field": @"secure"' in line)
        self.assertEqual('@{ @"field": @"secure", @"ax": @[], @"xc": @[], @"settable": @NO },', definition)
        self.assertIn('@"direct_secure_property_unavailable"', self.bridge)

    def test_numeric_fallback_filters_error_sentinels(self):
        start = self.bridge.index("- (NSDictionary<NSNumber *, id> * _Nullable)copyNumericAttributeMap:")
        end = self.bridge.index("- (NSArray * _Nullable)copyNumericAttributeArray:", start)
        self.assertIn("MCPAXBridgeIsExplicitlyUnavailableAttributeValue(value)", self.bridge[start:end])

    def test_unknown_snapshot_is_not_counted_as_same_leaf(self):
        self.assertNotIn('diagnostics[@"same_leaf_identity_count"] = @([diagnostics[@"same_leaf_identity_count"] integerValue] + 1)', self.node)


if __name__ == "__main__":
    unittest.main()
