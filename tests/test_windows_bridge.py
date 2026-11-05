import asyncio
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from openasrinput.adapters.audio_devices import selected_device
from openasrinput.adapters.windows import (
    WindowsBridge,
    audio_device_interface,
    audio_devices,
    default_audio_device,
)
from openasrinput.domain.bridge import CursorFrame
from openasrinput.infrastructure.config import DEFAULTS


@unittest.skipUnless(
    os.name == "nt" and Path(os.environ.get("OPENASRINPUT_WINDOWS_HELPER", "")).is_file(),
    "requires a built Windows helper via OPENASRINPUT_WINDOWS_HELPER",
)
class WindowsNativeSmokeTests(unittest.TestCase):
    def test_preview_keeps_explicit_test_editor_lease(self):
        expected = os.environ.get("OPENASRINPUT_TEST_TARGET_PROCESS_ID")
        if not expected:
            self.skipTest("requires an explicitly focused disposable test editor process")
        bridge = WindowsBridge()
        try:
            lease = bridge.begin_context()
            context = bridge.context_status()
            if lease is None or (context.get("target") or {}).get("process") != int(expected):
                self.skipTest("the designated test editor is not the current editable target")
            self.assertEqual(
                bridge.show_cursor(lease, 1, CursorFrame("listening", "焦点回归预览", "▁█")),
                "accepted",
            )
            # Let the real WinForms UIA focus event and native timer arrive.
            time.sleep(0.4)
            self.assertTrue(bridge.valid(lease))
            context = bridge.context_status()
            self.assertTrue(context["active"])
            self.assertEqual(context["target"], context["observed"])
            self.assertEqual(context["lastLoss"], "")
        finally:
            bridge.close()

    def test_real_winexe_pipes_work_without_a_console(self):
        # Exercise CREATE_NO_WINDOW, not the Python transport fixture. Console
        # encoding setters used to crash the WinExe before its HELLO message.
        bridge = WindowsBridge()
        try:
            self.assertEqual(bridge.request("PANEL_BACKEND"), "windows")
            hotkeys = set(bridge.request("HOTKEYS").split(","))
            self.assertIn("alt-x", hotkeys)
            self.assertNotIn("alt-z", hotkeys)
            # The desktop IME may reserve Shift+Space independently of this change.
            self.assertNotIn("Alt+X", bridge.warning)
            self.assertEqual(bridge.configure_panel(DEFAULTS["overlay"]), "accepted")
            self.assertEqual(bridge.configure_keyboard(False), "accepted")
            self.assertEqual(bridge.context_status()["backend"], "windows")
        finally:
            bridge.close()
        self.assertEqual(bridge.process.returncode, 0)

    def test_real_device_enumeration_returns_utf8_json_without_a_console(self):
        listing = asyncio.run(audio_devices())
        self.assertIsInstance(listing["devices"], list)
        for device in listing["devices"]:
            self.assertIsInstance(device["id"], str)
            self.assertIsInstance(device["title"], str)
            self.assertNotIn("\ufffd", device["title"])

    def test_default_microphone_has_a_stable_calibration_identity_without_recording(self):
        listing = asyncio.run(audio_devices())
        if not listing["devices"]:
            self.skipTest("no Windows recording device is available")
        identity = default_audio_device()
        self.assertIn(identity, [device["id"] for device in listing["devices"]])
        self.assertTrue(audio_device_interface(identity))
        selected = asyncio.run(selected_device(identity))
        self.assertEqual(selected["id"], identity)
        self.assertTrue(selected["calibratable"])
        self.assertEqual(
            selected["fingerprint"], asyncio.run(selected_device(identity))["fingerprint"]
        )


class WindowsTransportTests(unittest.TestCase):
    def test_optional_context_diagnostics_keep_older_peer_usable(self):
        server = r"""
import sys
print("0\tHELLO\tOpenASRInput.Bridge\t1", flush=True)
for line in sys.stdin:
    f = line.rstrip("\n").split("\t")
    if f[1] == "CONTEXT_STATUS":
        print(f[0] + "\tERROR\tinvalid-request", flush=True)
    else:
        value = "shift-space,alt-x" if f[1] == "HOTKEYS" else "1"
        print(f[0] + "\tOK\t" + value, flush=True)
"""
        bridge = WindowsBridge([sys.executable, "-u", "-c", server])
        try:
            self.assertEqual(bridge.context_status(), {})
            serial = bridge.serial
            self.assertEqual(bridge.context_status(), {})
            self.assertEqual(bridge.serial, serial)
            self.assertEqual(bridge.begin_context().lease_id, "1")
        finally:
            bridge.close()

    def test_interleaved_events_do_not_extend_request_deadline(self):
        server = r"""
import sys
print("0\tHELLO\tOpenASRInput.Bridge\t1", flush=True)
for line in sys.stdin:
    f = line.rstrip("\n").split("\t")
    if f[1] == "HOTKEYS":
        print(f[0] + "\tOK\tshift-space,alt-x", flush=True)
    else:
        print("0\tEVENT\ttoggle", flush=True)
"""
        bridge = WindowsBridge([sys.executable, "-u", "-c", server])
        try:
            # Time spent processing an event consumes the original request budget.
            with patch("openasrinput.adapters.windows.time.monotonic", side_effect=[0, 0, 4]):
                with self.assertRaisesRegex(RuntimeError, "响应超时"):
                    bridge.begin_context()
            self.assertEqual(bridge.poll_events(), ["toggle"])
        finally:
            bridge.close()

    def test_stdio_bridge_preserves_interleaved_events_and_utf8(self):
        server = r"""
import sys
print("0\tHELLO\tOpenASRInput.Bridge\t1", flush=True)
for line in sys.stdin:
    f = line.rstrip("\n").split("\t")
    value = "accepted"
    if f[1] == "HOTKEYS": value = "shift-space,alt-x"
    if f[1] == "BEGIN": value = "1"
    if f[1] == "VALID": value = "true"
    if f[1] == "SHOW":
        assert bytes.fromhex(f[4]).decode() == "跨平台预览🙂"
        print("0\tEVENT\ttoggle", flush=True)
    if f[1] == "COMMIT":
        assert bytes.fromhex(f[4]).decode() == "定稿🙂"
    print(f[0] + "\tOK\t" + value, flush=True)
"""
        bridge = WindowsBridge([sys.executable, "-u", "-c", server])
        try:
            self.assertEqual(bridge.configure_panel(DEFAULTS["overlay"]), "accepted")
            self.assertEqual(bridge.warning, "")
            lease = bridge.begin_context()
            self.assertTrue(bridge.valid(lease))
            self.assertEqual(
                bridge.show_cursor(lease, 1, CursorFrame("listening", "跨平台预览🙂", "▁█")),
                "accepted",
            )
            self.assertEqual(bridge.poll_events(), ["toggle"])
            self.assertEqual(bridge.submit(lease, "commit-1", "定稿🙂"), "accepted")
        finally:
            bridge.close()
