#!/usr/bin/env python3
"""TEST-52 no-bootstrap route: compile real ObjC control flow with Host doubles.

The iOS AX framework leaves are not linked or invoked. These tests prove route
control flow and evidence transport, not availability of real device fields.
"""

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent


def section(text, start, end):
    begin = text.index(start)
    return text[begin:text.index(end, begin)]


def function(text, signature):
    begin = text.index(signature)
    return text[begin:text.index("\n}\n", begin) + 3]


def gate_args(**overrides):
    return {"test52_read_only": True, "include_semantic_state": True,
            "include_semantic_diagnostics": True, **overrides}


def evidence_payload():
    unknown = {"value": "unknown", "source": "unavailable"}
    return {"bundleId": "example.fixture", "pid": 123, "contextId": 10, "displayId": 1,
            "device_generation_source": "unavailable", "semantic_state_requested": True,
            "elements": [{"semantic_leaf_ref": "c.0", "text": "synthetic-private-text",
                "rect": {"x": 1, "y": 1, "width": 10, "height": 10},
                "semantic_state": {
                    "semantic_role": {"value": "search_field", "source": "xc_attribute"},
                    "editable": unknown, "focused": unknown, "value_match": unknown,
                    "secure": {"value": False, "source": "inferred"},
                    "visible": unknown, "enabled": {"value": True, "source": "ax_attribute"},
                    "actionable": unknown, "same_leaf_identity": "unknown",
                    "same_leaf_identity_source": "unavailable"}}]}


class NativeRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="test52-no-bootstrap-")
        cls.addClassCleanup(cls.temp.cleanup)
        directory = Path(cls.temp.name)
        manager = (ROOT / "AccessibilityManager.m").read_text()
        server = (ROOT / "MCPServer.m").read_text()
        harness = (ROOT / "testdata/native/test52_no_bootstrap_harness.m").read_text()
        methods = section(manager, "- (void)getCompactUIElementsWithMaxElements:",
                          "#pragma mark - Get Element At Point")
        methods += section(manager, "- (NSDictionary *)activateVoiceOverRuntimeForContext:(MCPAXQueryContext *)context\n                                              reason:(NSString *)reason {",
                           "- (void)refreshQueryContext:")
        helpers = "\n".join(function(server, name) for name in (
            "static BOOL MCPNumberFromArgs(", "static BOOL MCPStringFromArgs(",
            "static BOOL MCPBoolFromArgs(", "static void MCPAddWhitelistedKeys("))
        sanitizers = section(server, "- (NSDictionary *)sanitizeFrontmostInfo:(NSDictionary *)info debug:(BOOL)debug {",
                             "- (NSDictionary *)sanitizeElementAtPointPayload:")
        sanitizers += section(server, "- (NSDictionary *)sanitizeAccessibilityFailurePayload:(NSDictionary *)payload debug:(BOOL)debug {",
                              "#pragma mark - Accessibility Execution")
        handler = section(server, "- (NSDictionary *)executeGetUIElements:(id)reqId args:(NSDictionary *)args {",
                          "- (NSDictionary *)executeGetElementAtPoint:")
        source = harness.replace("// INSERT_MANAGER_METHODS", methods)
        source = source.replace("// INSERT_SERVER_HELPERS", helpers)
        source = source.replace("// INSERT_SERVER_METHODS", sanitizers + handler)
        file = directory / "probe.m"
        file.write_text(source)
        cls.binary = directory / "probe"
        result = subprocess.run(["xcrun", "--sdk", "macosx", "clang", "-fobjc-arc", "-fblocks",
            "-Werror", "-framework", "Foundation", "-framework", "CoreGraphics", "-I", str(ROOT),
            str(file), str(ROOT / "MCPAXQueryContext.m"), "-o", str(cls.binary)],
            capture_output=True, text=True, timeout=90)
        if result.returncode:
            raise AssertionError("Host ObjC harness compile failed:\n" + result.stderr)

    def run_probe(self, mode="success", args=None, payload=None, requests=None, **options):
        fixture = {"mode": mode, "args": args if args is not None else gate_args(),
                   "payload": payload if payload is not None else evidence_payload(), **options}
        if requests is not None:
            fixture["requests"] = requests
        result = subprocess.run([str(self.binary), json.dumps(fixture)],
            capture_output=True, text=True, timeout=20)
        self.assertEqual(0, result.returncode, result.stderr)
        return json.loads(result.stdout)

    def assert_no_fallback(self, result):
        for key in ("bootstrap_count", "voiceover_fallback_count", "bootstrap_policy_count", "mutation_count"):
            self.assertEqual(0, result[key], key)

    def assert_unavailable(self, result):
        self.assert_no_fallback(result)
        response = result["results"][0]["response"]
        self.assertTrue(response["isError"])
        payload = response["structuredContent"]
        self.assertEqual("UNAVAILABLE", payload["observation_status"])
        self.assertEqual("FAIL_CLOSED", payload["authorization_status"])
        self.assertEqual([], payload["elements"])
        self.assertEqual(0, result["secondary_context_count"])
        self.assertNotIn("fixture-private-error", json.dumps(response))

    def test_primary_failure_does_not_bootstrap_or_retry(self):
        result = self.run_probe("fail")
        self.assert_unavailable(result)
        self.assertEqual(1, result["read_count"])
        self.assertEqual(1, result["context_count"])

    def test_exception_fails_closed_without_fallback(self):
        self.assert_unavailable(self.run_probe("exception"))

    def test_context_failure_and_exception_do_not_read_ax(self):
        for mode in ("no_context", "context_exception"):
            with self.subTest(mode=mode):
                result = self.run_probe(mode)
                self.assert_unavailable(result)
                self.assertEqual(0, result["read_count"])

    def test_timeout_cannot_start_fallback_later(self):
        result = self.run_probe("timeout")
        self.assert_unavailable(result)
        self.assertEqual(1, result["read_count"])

    def test_partial_result_with_error_is_unavailable(self):
        self.assert_unavailable(self.run_probe("partial_error"))

    def test_empty_and_malformed_elements_are_unavailable(self):
        for elements in ([], None, {"error": "synthetic"}):
            with self.subTest(elements=elements):
                self.assert_unavailable(self.run_probe(payload={"elements": elements}))

    def test_success_preserves_provenance_and_unavailable_generation(self):
        original = evidence_payload()
        result = self.run_probe(payload=original)
        self.assert_no_fallback(result)
        response = result["results"][0]["response"]
        self.assertFalse(response["isError"])
        payload = response["structuredContent"]
        self.assertEqual("FAIL_CLOSED", payload["authorization_status"])
        self.assertEqual(original["elements"][0]["semantic_state"], payload["elements"][0]["semantic_state"])
        self.assertEqual("unavailable", payload["device_generation_source"])
        self.assertEqual("c.0", payload["elements"][0]["semantic_leaf_ref"])

    def test_gate_output_excludes_raw_text_geometry_and_tap(self):
        response = self.run_probe()["results"][0]["response"]["structuredContent"]
        self.assertNotIn("synthetic-private-text", json.dumps(response))
        for key in ("text", "value", "rect", "visible_rect", "tap", "clickable"):
            self.assertNotIn(key, response["elements"][0])

    def test_malformed_gate_flag_rejected_before_observation(self):
        for value in ("true", "false", 0, 1, None, {}, []):
            with self.subTest(value=value):
                result = self.run_probe(args=gate_args(test52_read_only=value))
                self.assert_no_fallback(result)
                self.assertTrue(result["results"][0]["response"]["isError"])
                self.assertEqual(0, result["context_count"])

    def test_diagnostic_prerequisites_checked_before_read(self):
        for args in (gate_args(include_semantic_state=False), gate_args(include_semantic_diagnostics=False),
                     gate_args(debug=True), gate_args(semantic_expected_value_sha256="a" * 64)):
            with self.subTest(args=args):
                result = self.run_probe(args=args)
                self.assert_no_fallback(result)
                self.assertTrue(result["results"][0]["response"]["isError"])
                self.assertEqual(0, result["context_count"])

    def test_unknown_action_parameters_rejected(self):
        for extra in ({"tool_name": "input_text"}, {"text": "synthetic"}, {"tap": {"x": 1, "y": 1}}):
            result = self.run_probe(args=gate_args(**extra))
            self.assert_no_fallback(result)
            self.assertTrue(result["results"][0]["response"]["isError"])
            self.assertEqual(0, result["context_count"])

    def test_native_caller_cannot_enable_value_reads_or_skip_diagnostics(self):
        for args in (gate_args(include_semantic_state=False), gate_args(include_semantic_diagnostics=False),
                     gate_args(semantic_expected_value_sha256="a" * 64)):
            result = self.run_probe(args=args, native_call=True)
            self.assert_no_fallback(result)
            self.assertEqual(0, result["context_count"])
            self.assertTrue(result["results"][0]["response"]["isError"])

    def test_concurrent_read_only_requests_cannot_trigger_fallback(self):
        result = self.run_probe("fail", requests=[gate_args(), gate_args()], concurrent=True)
        self.assert_no_fallback(result)
        self.assertEqual(2, result["read_count"])
        self.assertEqual(2, result["context_count"])
        self.assertTrue(all(item["response"]["isError"] for item in result["results"]))

    def test_original_native_selector_retains_legacy_fallback(self):
        result = self.run_probe("retry_success", legacy_call=True)
        self.assertEqual(1, result["bootstrap_count"])
        self.assertEqual(2, result["read_count"])
        self.assertFalse(result["results"][0]["response"]["isError"])

    def test_legacy_default_retains_bootstrap_and_retry(self):
        result = self.run_probe("retry_success", args={"include_semantic_state": True})
        self.assertEqual(1, result["bootstrap_count"])
        self.assertEqual(1, result["voiceover_fallback_count"])
        self.assertEqual(2, result["read_count"])
        self.assertFalse(result["results"][0]["response"]["isError"])

    def test_explicit_false_keeps_legacy_output(self):
        result = self.run_probe(args={"test52_read_only": False, "include_semantic_state": True})
        self.assertFalse(result["results"][0]["response"]["isError"])
        self.assertIn("text", result["results"][0]["response"]["structuredContent"]["elements"][0])

    def test_mode_does_not_leak_to_following_legacy_request(self):
        result = self.run_probe("fail", requests=[gate_args(), {}, gate_args()])
        self.assertEqual([0, 1, 0], [item["bootstrap"] for item in result["results"]])
        self.assertEqual([1, 5, 1], [item["reads"] for item in result["results"]])

    def test_native_payload_still_fails_existing_risk_with_executor_zero(self):
        spec = importlib.util.spec_from_file_location("track_a", ROOT / "test-agent-ax-evidence-correctness-unit.py")
        existing = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(existing)
        response = self.run_probe()["results"][0]["response"]["structuredContent"]
        existing.RiskBoundaryTests().assert_no_executor(response)


class SourceBoundaryTests(unittest.TestCase):
    def test_route_schema_is_explicit_default_off(self):
        source = (ROOT / "MCPServer.m").read_text()
        schema = section(source, '@"name": @"get_ui_elements"', '@"name": @"get_element_at_point"')
        self.assertIn('@"test52_read_only"', schema)
        self.assertIn("default: false", schema)

    def test_no_host_execution_or_provider_policy_change(self):
        source = (ROOT / "AccessibilityManager.m").read_text()
        methods = section(source, "- (void)getCompactUIElementsWithMaxElements:",
                          "#pragma mark - Get Element At Point")
        self.assertIn("noBootstrapReadOnly", methods)
        for forbidden in ("PlanExecutor", "typeText:", "setText:", "tapScreen", "pressKey:", "executeTool:"):
            self.assertNotIn(forbidden, methods)


if __name__ == "__main__":
    unittest.main()
