"""Interactive physical-key check, only in an explicitly designated test editor."""

import ctypes
import time
import unittest

from test_windows_live import LIVE_EDITOR, WindowsEditorFixture

from openasrinput.domain.bridge import CursorFrame


@unittest.skipUnless(LIVE_EDITOR, "requires explicit disposable editor and Windows helper")
class PhysicalKeys(WindowsEditorFixture, unittest.TestCase):
    def test_physical_keys(self):
        self.assertEqual(self.bridge.warning, "")
        user = ctypes.WinDLL("user32", use_last_error=True)
        user.GetForegroundWindow.restype = ctypes.c_void_p
        user.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        for index, (label, expected) in enumerate(
            (("Shift+Space", "toggle"), ("Alt+X", "command"), ("Enter", "pause"), ("Esc", "cancel"))
        ):
            lease = None
            print(f"WAIT {label}", flush=True)
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                pid = ctypes.c_ulong()
                user.GetWindowThreadProcessId(user.GetForegroundWindow(), ctypes.byref(pid))
                if pid.value != self.process:
                    lease = None
                    self.bridge.poll_events()
                    time.sleep(0.05)
                    continue
                if lease is None:
                    lease = self.bridge.begin_context()
                    self.bridge.poll_events()
                    if lease is None:
                        time.sleep(0.05)
                        continue
                    self.bridge.show_cursor(
                        lease,
                        1,
                        CursorFrame(
                            "listening",
                            f"按键验收 {index + 1}/4：请按 {label}，然后等待下一条提示。",
                            "",
                        ),
                    )
                events = self.bridge.poll_events()
                if expected in events:
                    print(f"PASS physical {label}", flush=True)
                    break
                if "context-lost" in events:
                    lease = None
                time.sleep(0.02)
            else:
                self.fail(f"physical {label} was not received")
            time.sleep(0.4)
        self.fixture("focus", "first")


if __name__ == "__main__":
    unittest.main(verbosity=2)
