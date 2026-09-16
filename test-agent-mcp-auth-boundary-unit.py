#!/usr/bin/env python3
"""Batch 1B host-side auth boundary tests.

Offline only: no iPhone connection, no device action, no live MCP endpoint.
These tests lock the fail-closed token behavior added to the MCP transport and
the matching fail-closed markers in the device source.
"""

from __future__ import annotations

import os
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from phoneharness_agent import DEFAULT_MCP_URL, MCPCallError, MCPClient

ROOT = Path(__file__).resolve().parent
TOKEN_ENV = "PHONEHARNESS_MCP_TOKEN"


class MCPClientAuthTokenTests(unittest.TestCase):
    def test_missing_token_fails_closed_before_any_network_io(self) -> None:
        client = MCPClient("http://127.0.0.1:1/mcp")
        removed = os.environ.pop(TOKEN_ENV, None)
        try:
            with self.assertRaises(MCPCallError):
                client._rpc("tools/list", {})
        finally:
            if removed is not None:
                os.environ[TOKEN_ENV] = removed

    def test_configured_token_is_sent_as_header(self) -> None:
        client = MCPClient("http://127.0.0.1:1/mcp")
        captured: dict[str, str] = {}
        original_urlopen = urllib.request.urlopen

        def fake_urlopen(request, timeout=None):
            captured["token"] = request.get_header("X-mcp-token")
            raise urllib.error.URLError("stop-after-header-capture")

        os.environ[TOKEN_ENV] = "a" * 32
        urllib.request.urlopen = fake_urlopen
        try:
            with self.assertRaises(MCPCallError):
                client._rpc("tools/list", {})
        finally:
            urllib.request.urlopen = original_urlopen
            os.environ.pop(TOKEN_ENV, None)
        self.assertEqual("a" * 32, captured.get("token"))

    def test_default_transport_targets_loopback(self) -> None:
        self.assertIn("127.0.0.1:8090", DEFAULT_MCP_URL)


class DeviceSourceAuthBoundaryTests(unittest.TestCase):
    def test_server_enforces_token_on_every_request(self) -> None:
        server = (ROOT / "MCPServer.m").read_text(encoding="utf-8")
        self.assertIn('headers[@"x-mcp-token"]', server)
        self.assertIn("MCPConstantTimeEqualStrings", server)
        self.assertIn('status:401 message:@"Unauthorized"', server)
        self.assertIn("mcp_auth_rejected", server)
        self.assertIn("auth_match=false", server)

    def test_server_defaults_to_loopback_and_lan_is_explicit(self) -> None:
        server = (ROOT / "MCPServer.m").read_text(encoding="utf-8")
        self.assertIn("allowLanAccess ? htonl(INADDR_ANY) : htonl(INADDR_LOOPBACK)", server)
        self.assertIn("IOSMCPAllowLanAccess()", server)

    def test_upload_directory_is_restricted_and_purged(self) -> None:
        server = (ROOT / "MCPServer.m").read_text(encoding="utf-8")
        self.assertIn("purgeStaleUploadFiles", server)
        self.assertIn("NSFilePosixPermissions: @0700", server)
        self.assertIn("O_CREAT | O_EXCL | O_WRONLY, 0600", server)
        self.assertNotIn("NSFilePosixPermissions: @0777", server)

    def test_mcp_root_rejects_unvalidated_ldid_shapes(self) -> None:
        helper = (ROOT / "mcp-root" / "main.c").read_text(encoding="utf-8")
        self.assertIn("static int validate_ldid_arguments(int argc, char *argv[])", helper)
        self.assertIn("MCP_ALLOWED_COMMAND_LDID && !validate_ldid_arguments", helper)
        self.assertIn("mcp-ldid target must be inside an application bundle container", helper)


if __name__ == "__main__":
    unittest.main()
