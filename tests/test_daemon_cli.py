"""Public daemon entry: platform transport, tray exit and failed-start cleanup."""

import unittest
from unittest.mock import AsyncMock, Mock, patch

from openasrinput.adapters import host
from openasrinput.entrypoints.cli import run_daemon


class DaemonCliTests(unittest.IsolatedAsyncioTestCase):
    def test_windows_uses_stdio_without_opening_a_unix_socket(self):
        with (
            patch.object(host.sys, "platform", "win32"),
            patch("openasrinput.adapters.windows.WindowsBridge") as windows,
            patch("openasrinput.adapters.native.NativeBridge") as native,
        ):
            self.assertIs(host.bridge_for_platform("unused"), windows.return_value)
            native.assert_not_called()

    async def test_tray_exit_stops_the_shared_daemon_and_closes_bridge(self):
        bridge = Mock(quit_requested=True)
        runtime = Mock(tick=AsyncMock())
        with (
            patch.object(host, "bridge_for_platform", return_value=bridge),
            patch("openasrinput.application.runtime.ConfigRuntime", return_value=runtime),
        ):
            await run_daemon(Mock(), "socket", {})
        runtime.tick.assert_not_awaited()
        runtime.stopped.assert_called_once()
        bridge.close.assert_called_once()

    async def test_failed_runtime_construction_still_closes_native_process(self):
        bridge = Mock()
        with (
            patch.object(host, "bridge_for_platform", return_value=bridge),
            patch("openasrinput.application.runtime.ConfigRuntime", side_effect=OSError("config")),
        ):
            with self.assertRaisesRegex(OSError, "config"):
                await run_daemon(Mock(), "socket", {})
        bridge.close.assert_called_once()

    async def test_failed_status_write_still_closes_native_process(self):
        bridge = Mock(quit_requested=True)
        runtime = Mock(stopped=Mock(side_effect=OSError("status")))
        with (
            patch.object(host, "bridge_for_platform", return_value=bridge),
            patch("openasrinput.application.runtime.ConfigRuntime", return_value=runtime),
        ):
            with self.assertRaisesRegex(OSError, "status"):
                await run_daemon(Mock(), "socket", {})
        bridge.close.assert_called_once()
