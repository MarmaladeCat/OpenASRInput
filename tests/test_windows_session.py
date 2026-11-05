"""Opt-in real microphone/native editor and real Portal, with synthetic upstreams."""

import asyncio
import ctypes
import os
import tempfile
import unittest
from pathlib import Path

from aiohttp import ClientSession
from test_windows_live import LIVE_EDITOR, WindowsEditorFixture

from openasrinput.adapters.windows import WindowsCapture
from openasrinput.application.daemon import Daemon
from openasrinput.application.runtime import ConfigRuntime
from openasrinput.infrastructure.config import ConfigStore


@unittest.skipUnless(
    LIVE_EDITOR
    and os.environ.get("OPENASRINPUT_TEST_MICROPHONE") == "1"
    and os.environ.get("OPENASRINPUT_TEST_PORTAL_URL", "").startswith("http://127.0.0.1:"),
    "requires opt-in microphone, disposable editor and local serve_windows_session.py",
)
class WindowsSessionTests(WindowsEditorFixture, unittest.TestCase):
    def setUp(self):
        try:
            super().setUp()
        except unittest.SkipTest as error:
            self.fail(str(error))  # An explicitly requested microphone run must execute.

    def hotkey(self, *keys):
        self.assertEqual(self.bridge.warning, "", "exit other Input instances before hotkey tests")
        self.assertEqual(self.bridge.context_status()["target"]["process"], self.process)
        user = ctypes.WinDLL("user32", use_last_error=True)
        # Exercise the registered host's actual WM_HOTKEY handler. Synthetic
        # keyboard events can be filtered by the desktop/IME; physical keys
        # remain a separate manual check rather than a false automated claim.
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        user.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        user.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
        user.PostMessageW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_size_t,
            ctypes.c_ssize_t,
        ]
        windows = []

        @callback_type
        def visit(window, _):
            pid = ctypes.c_ulong()
            user.GetWindowThreadProcessId(window, ctypes.byref(pid))
            title = ctypes.create_unicode_buffer(128)
            user.GetWindowTextW(window, title, len(title))
            if pid.value == self.bridge.process.pid and title.value == "OpenASRInput 语音输入":
                windows.append(window)
            return True

        user.EnumWindows(visit, 0)
        self.assertEqual(len(windows), 1)
        command = keys == (0x12, 0x58)
        self.assertTrue(
            user.PostMessageW(
                windows[0], 0x0312, 2 if command else 1, (1 if command else 4) | (keys[-1] << 16)
            )
        )

    async def round_trip(self, command, *, selected=True):
        url = os.environ["OPENASRINPUT_TEST_PORTAL_URL"]
        captures = []

        def capture(device):
            item = WindowsCapture()
            captures.append(item)
            return item

        temporary = tempfile.TemporaryDirectory(dir=self.directory)
        self.addCleanup(temporary.cleanup)
        store = ConfigStore(Path(temporary.name) / "input.json")
        store.save(
            {
                "portal": {"url": url, "apiKey": "test-asr", "profileId": "test"},
                "textEdit": {
                    "cards": [
                        {
                            "id": "inactive",
                            "name": "未选用",
                            "provider": "openai-compatible",
                            "url": url,
                            "apiKey": "wrong-key",
                            "model": "wrong-model",
                        },
                        {
                            "id": "selected",
                            "name": "指令修改🙂",
                            "provider": "openai-compatible",
                            "url": url,
                            "apiKey": "test-text",
                            "model": "test-model",
                        },
                    ],
                    "activeModelCardId": "selected" if selected else "",
                },
            },
            "defaults",
        )
        runtime = ConfigRuntime(store, self.bridge, capture_factory=capture)
        daemon = Daemon(self.bridge, session_factory=runtime.session)
        editing = command and selected

        async def until(predicate):
            async def wait():
                while not predicate():
                    for event in self.bridge.poll_events():
                        await daemon.action(event)
                    daemon.core.tick()
                    daemon.core.drain()
                    await daemon.effects()
                    await asyncio.sleep(0.02)

            try:
                await asyncio.wait_for(wait(), 10)
            except TimeoutError:
                self.fail(
                    f"session timeout: {daemon.core.state}, {daemon.core.error}, {daemon.core.transitions}"
                )

        async with ClientSession() as client:
            before = await (await client.get(url + "/fixture/status")).json()
            try:
                self.seed("原文🙂" if editing else "前缀")
                if editing:
                    self.fixture("select-all")
                self.hotkey(*((0x12, 0x58) if command else (0x10, 0x20)))
                await until(lambda: daemon.core.state == "connecting" and bool(daemon.sessions))
                running = next(iter(daemon.sessions.values()))
                await until(lambda: running.queued_bytes > 0)
                self.assertEqual(
                    daemon.core.state, "connecting", "audio must start before upstream ready"
                )
                self.assertEqual(daemon.core.mode, "edit" if editing else "dictation")
                self.wait_text("editor-text.json", "first", "原文🙂" if editing else "前缀")
                # Stop during the connection delay. Buffered PCM and the capture tail must flush.
                self.hotkey(*((0x12, 0x58) if command else (0x10, 0x20)))
                await until(lambda: daemon.core.state == "paused" and not daemon.tasks)
                self.wait_text(
                    "editor-text.json", "first", "修改完成🙂" if editing else "前缀最终文本。"
                )
                after = await (await client.get(url + "/fixture/status")).json()
                self.assertGreater(after["audioBytes"], before["audioBytes"])
                self.assertEqual(after["edits"] - before["edits"], int(editing))
                self.assertEqual(len(captures), 1)
                self.assertEqual(captures[0].process.returncode, 0)
                self.assertIsNotNone(captures[0].ready_at)
                self.assertGreaterEqual(captures[0].first_pcm_at, captures[0].ready_at)
                self.assertEqual(daemon.core.submissions[-1].status, "submitted")
            finally:
                await daemon.close()

    def test_shift_space_buffers_real_microphone_then_dictates(self):
        asyncio.run(self.round_trip(False))

    def test_alt_x_buffers_instruction_then_replaces_selection(self):
        asyncio.run(self.round_trip(True))

    def test_alt_x_without_selection_dictates_with_model_cards_disabled(self):
        asyncio.run(self.round_trip(True, selected=False))
