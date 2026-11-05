import ctypes
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from openasrinput.entrypoints.windows import application, stop_signal
from openasrinput.infrastructure.config import ROOT

try:
    import aiohttp
except ImportError:
    aiohttp = None


@unittest.skipIf(aiohttp is None, "requires settings dependency")
class WindowsApplicationTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(os.name == "nt", "Windows named-event lifecycle")
    async def test_installer_can_signal_only_this_process_and_handle_is_removed(self):
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenEventW.argtypes = [ctypes.c_uint, ctypes.c_bool, ctypes.c_wchar_p]
        kernel.OpenEventW.restype = ctypes.c_void_p
        kernel.SetEvent.argtypes = [ctypes.c_void_p]
        name = f"Local\\OpenASRInput-Stop-{os.getpid()}"
        with stop_signal(kernel) as requested:
            self.assertFalse(requested())
            sender = kernel.OpenEventW(2, False, name)
            self.assertTrue(sender)
            try:
                self.assertTrue(kernel.SetEvent(sender))
                self.assertTrue(requested())
                self.assertFalse(requested())
            finally:
                kernel.CloseHandle(sender)
        self.assertFalse(kernel.OpenEventW(2, False, name))

    async def test_exit_status_failure_still_closes_bridge_and_removes_ready_file(self):
        (ROOT / "test-results").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "test-results") as directory:
            ready = Path(directory) / "settings-ready.json"
            ready.write_text("{}")
            bridge = MagicMock()
            runtime = MagicMock()
            runtime.stopped.side_effect = PermissionError("status locked")
            daemon = MagicMock()
            daemon.run = AsyncMock(side_effect=RuntimeError("session failure"))
            with (
                patch("openasrinput.adapters.windows.WindowsBridge", return_value=bridge),
                patch("openasrinput.application.runtime.ConfigRuntime", return_value=runtime),
                patch("openasrinput.application.daemon.Daemon", return_value=daemon),
                patch("openasrinput.presentation.settings_server.serve", new=AsyncMock()),
                self.assertLogs(level="ERROR"),
            ):
                with self.assertRaisesRegex(RuntimeError, "session failure"):
                    await application(MagicMock(), ready, False)
            bridge.close.assert_called_once_with()
            self.assertFalse(ready.exists())
            self.assertEqual(runtime.error, "session failure")
