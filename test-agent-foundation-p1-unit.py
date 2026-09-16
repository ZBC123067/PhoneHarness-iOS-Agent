#!/usr/bin/env python3
"""Host-only contracts for the audited native MCP P1 corrections.

These tests do not contact an iPhone or an MCP endpoint.  They lock the native
source contracts and exercise the host POSIX process-group behavior used by the
timeout design.  A device build and device regression remain separate evidence.
"""

from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import time
import unittest


ROOT = Path(__file__).resolve().parent


def _header_safe_filename(value: str) -> str:
    """Reference policy for the HTTP quoted filename value."""
    sanitized: list[str] = []
    has_safe_character = False
    for character in value:
        if ord(character) < 0x20 or ord(character) == 0x7F or character in {'"', "\\"}:
            sanitized.append("_")
        else:
            sanitized.append(character)
            has_safe_character = True
    return "".join(sanitized) if has_safe_character else "file"


class DownloadHeaderContractTests(unittest.TestCase):
    def test_control_and_quoted_filename_characters_are_neutralized(self) -> None:
        self.assertEqual("report.pdf", _header_safe_filename("report.pdf"))
        self.assertEqual("file", _header_safe_filename("\r\n"))
        self.assertEqual("a__X-Test: injected___", _header_safe_filename('a\r\nX-Test: injected"\\\x7f'))

    def test_device_source_uses_the_safe_filename_for_content_disposition(self) -> None:
        server = (ROOT / "MCPServer.m").read_text(encoding="utf-8")
        helper_start = server.index("static NSString *MCPHeaderSafeFilename")
        helper_end = server.index("- (void)handleDownloadFileRequestPath", helper_start)
        helper = server[helper_start:helper_end]
        self.assertIn("< 0x20", helper)
        self.assertIn("0x7F", helper)
        self.assertIn('appendString:@"_"', helper)
        self.assertIn("safeDownloadName", server)
        self.assertNotIn("fileSize, downloadName];", server)


class FileSystemDocumentationContractTests(unittest.TestCase):
    def test_runtime_instructions_do_not_advertise_a_nonexistent_root_fallback(self) -> None:
        server = (ROOT / "MCPServer.m").read_text(encoding="utf-8")
        lowered = server.lower()
        self.assertNotIn("fall back to the privileged mcp-root helper", lowered)
        self.assertNotIn("falls back to the privileged mcp-root helper", lowered)
        self.assertIn("do not invoke a shell or mcp-root fallback", lowered)


class ProcessGroupTimeoutContractTests(unittest.TestCase):
    def test_device_source_creates_and_kills_an_isolated_process_group(self) -> None:
        source = (ROOT / "MCPProcessUtil.m").read_text(encoding="utf-8")
        self.assertIn("POSIX_SPAWN_SETPGROUP", source)
        self.assertIn("posix_spawnattr_setpgroup(attr, 0)", source)
        self.assertEqual(2, source.count("kill(-pid, SIGKILL)"))
        self.assertNotIn("kill(pid, SIGKILL)", source)

    def test_host_process_group_kill_terminates_a_background_child(self) -> None:
        process = subprocess.Popen(
            ["/bin/sh", "-lc", "sleep 30 & child=$!; printf '%s\\n' \"$child\"; wait"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            start_new_session=True,
        )
        child_line = process.stdout.readline().strip() if process.stdout else ""
        self.assertTrue(child_line.isdigit())
        child_pid = int(child_line)
        try:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=3)
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                try:
                    os.kill(child_pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.05)
            else:
                self.fail("background child survived process-group termination")
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=3)
            if process.stdout:
                process.stdout.close()


if __name__ == "__main__":
    unittest.main()
