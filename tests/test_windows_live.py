import ctypes
import json
import os
import time
import unittest
from pathlib import Path
from uuid import uuid4

from openasrinput.adapters.windows import WindowsBridge
from openasrinput.domain.bridge import CursorFrame
from openasrinput.infrastructure.config import atomic_json

LIVE_EDITOR = (
    os.name == "nt"
    and os.environ.get("OPENASRINPUT_TEST_EDITOR_DIR")
    and os.environ.get("OPENASRINPUT_TEST_TARGET_PROCESS_ID")
    and Path(os.environ.get("OPENASRINPUT_WINDOWS_HELPER", "")).is_file()
)


class WindowsEditorFixture:
    def setUp(self):
        self.directory = Path(os.environ["OPENASRINPUT_TEST_EDITOR_DIR"]).resolve()
        self.assertIn("test-results", [part.lower() for part in self.directory.parts])
        identity = self.read("editor-identity.json")
        self.assertEqual(identity["title"], "OpenASRInput Windows Test Editor")
        self.process = int(os.environ["OPENASRINPUT_TEST_TARGET_PROCESS_ID"])
        self.assertEqual(identity["processId"], self.process)
        self.bridge = WindowsBridge()
        self.addCleanup(self.bridge.close)
        deadline = time.monotonic() + 3
        while True:
            lease = self.bridge.begin_context()
            target = self.bridge.context_status().get("target") or {}
            if (
                lease is not None and target.get("process") == self.process
            ) or time.monotonic() >= deadline:
                break
            time.sleep(0.05)
        if lease is None or target.get("process") != self.process:
            self.skipTest(
                f"the designated disposable editor is not foreground/editable: {self.bridge.context_status()}"
            )
        self.fixture("focus", "first")

    def read(self, filename):
        return json.loads((self.directory / filename).read_text(encoding="utf-8"))

    def fixture(self, action, control="first", **options):
        nonce = str(uuid4())
        atomic_json(
            self.directory / "editor-command.json",
            {"nonce": nonce, "action": action, "control": control, **options},
        )
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                answer = self.read("editor-answer.json")
                if answer.get("nonce") == nonce:
                    self.assertTrue(answer["ok"], answer.get("error"))
                    if control.startswith("web-"):
                        time.sleep(0.1)  # The renderer publishes focus/selection asynchronously.
                    return
            except (OSError, ValueError):
                pass
            time.sleep(0.01)
        self.fail("disposable editor test API timed out")

    def seed(self, text):
        self.fixture("select-all")
        lease = self.bridge.begin_context()
        self.assertIsNotNone(lease)
        result = self.bridge.submit(lease, str(uuid4()), text)
        self.assertEqual(
            result,
            "accepted",
            {"context": self.bridge.context_status(), "error": self.bridge.last_commit_error},
        )
        self.assertEqual(self.read("editor-text.json")["first"], text)
        return lease

    def browser(self):
        if not (self.directory / "browser-ready.json").exists():
            self.skipTest("requires the disposable WebView2 editor")

    def editable_lease(self, control):
        self.fixture("focus", control)
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            lease = self.bridge.begin_context()
            if lease is not None and self.bridge.valid(lease):
                # Chromium publishes UIA focus asynchronously. Prepare a stable
                # fixture before testing the session, rather than binding while
                # a preceding fixture focus/selection command is still settling.
                time.sleep(0.12)
                if self.bridge.valid(lease):
                    return lease
            time.sleep(0.02)
        self.fail("designated editor did not publish a stable editable lease")

    def wait_text(self, filename, field, expected):
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            if self.read(filename).get(field) == expected:
                return
            time.sleep(0.02)
        self.assertEqual(self.read(filename).get(field), expected)

    def send_keys(self, changes):
        """Send marked-as-injected keys only to the verified disposable editor."""
        user = ctypes.WinDLL("user32", use_last_error=True)
        user.GetForegroundWindow.restype = ctypes.c_void_p
        user.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        process = ctypes.c_ulong()
        user.GetWindowThreadProcessId(user.GetForegroundWindow(), ctypes.byref(process))
        self.assertEqual(process.value, self.process, "never inject into a foreign foreground")

        class Keyboard(ctypes.Structure):
            _fields_ = [
                ("key", ctypes.c_ushort),
                ("scan", ctypes.c_ushort),
                ("flags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("extra", ctypes.c_size_t),
            ]

        class Payload(ctypes.Union):
            _fields_ = [("keyboard", Keyboard), ("padding", ctypes.c_byte * 32)]

        class Input(ctypes.Structure):
            _fields_ = [("kind", ctypes.c_ulong), ("payload", Payload)]

        self.assertEqual(ctypes.sizeof(Input), 40)
        inputs = (Input * len(changes))(
            *(
                Input(
                    1,
                    Payload(
                        keyboard=Keyboard(0, user.MapVirtualKeyW(key, 0), 8 if down else 10, 0, 0)
                    ),
                )
                for key, down in changes
            )
        )
        user.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(Input), ctypes.c_int]
        for event in inputs:
            self.assertEqual(user.SendInput(1, ctypes.byref(event), ctypes.sizeof(Input)), 1)
            # Hold modifiers through target dispatch, as a remapped human key
            # does, rather than enqueueing press/release in one zero-duration batch.
            time.sleep(0.04)


@unittest.skipUnless(
    LIVE_EDITOR, "requires an explicit disposable WindowsTestEditor sandbox and helper"
)
class WindowsEditorTests(WindowsEditorFixture, unittest.TestCase):
    def test_optional_value_failures_preserve_text_confirmation(self):
        for mode in ("value-read", "value-after-change"):
            with self.subTest(mode=mode):
                try:
                    self.fixture("set", "provider", text="前缀后缀")
                    self.fixture("fault", "provider", mode=mode)
                    lease = self.editable_lease("provider")
                    self.fixture("select", "provider", start=2, length=0)
                    commit = str(uuid4())
                    result = self.bridge.submit(lease, commit, "中文🙂")
                    self.assertEqual(result, "accepted", self.bridge.context_status())
                    self.wait_text("editor-text.json", "provider", "前缀中文🙂后缀")
                    self.assertEqual(
                        self.bridge.context_status()["lastInsertionMethod"], "native-char"
                    )
                    self.assertIn(
                        self.bridge.context_status()["lastInsertionVerification"],
                        ("text-change-confirmed", "caret-text-confirmed"),
                    )
                    self.assertEqual(self.bridge.submit(lease, commit, "中文🙂"), "accepted")
                    self.wait_text("editor-text.json", "provider", "前缀中文🙂后缀")
                finally:
                    self.fixture("fault", "provider", mode="none")
                    self.fixture("focus", "first")

    def test_missing_confirmation_keeps_panel_preview_and_performs_no_write(self):
        try:
            self.fixture("set", "provider", text="原文必须保留")
            self.fixture("fault", "provider", mode="no-evidence")
            lease = self.editable_lease("provider")
            self.assertEqual(
                self.bridge.show_cursor(lease, 1, CursorFrame("listening", "面板预览", "")),
                "accepted",
            )
            self.assertEqual(self.bridge.context_status()["screenMode"], "panel-only")
            self.wait_text("editor-text.json", "provider", "原文必须保留")
            commit = str(uuid4())
            self.assertEqual(self.bridge.submit(lease, commit, "不得盲写"), "failed")
            self.wait_text("editor-text.json", "provider", "原文必须保留")
            self.assertEqual(self.bridge.submit(lease, commit, "不得盲写"), "failed")
            self.wait_text("editor-text.json", "provider", "原文必须保留")
        finally:
            self.fixture("fault", "provider", mode="none")
            self.fixture("focus", "first")

    def test_target_becoming_readonly_revokes_lease_and_can_recover(self):
        for control in ("first", "rich", "web-first", "web-second", "provider"):
            with self.subTest(control=control):
                filename = "browser-text.json" if control.startswith("web-") else "editor-text.json"
                field = control[4:] if control.startswith("web-") else control
                try:
                    lease = self.editable_lease(control)
                    self.fixture("select-all", control)
                    self.assertEqual(
                        self.bridge.submit(lease, str(uuid4()), "保留原文"), "accepted"
                    )
                    self.fixture("readonly", control, enabled=True)
                    self.assertFalse(self.bridge.valid(lease))
                    self.assertEqual(self.bridge.submit(lease, str(uuid4()), "迟到结果"), "stale")
                    self.wait_text(filename, field, "保留原文")
                    self.fixture("readonly", control, enabled=False)
                    recovered = self.editable_lease(control)
                    self.fixture("select-all", control)
                    self.assertEqual(
                        self.bridge.submit(recovered, str(uuid4()), "恢复输入"), "accepted"
                    )
                    self.wait_text(filename, field, "恢复输入")
                finally:
                    self.fixture("readonly", control, enabled=False)
                    self.fixture("focus", "first")

    def test_shift_space_can_request_start_with_a_text_caret(self):
        for control in ("first", "rich", "web-first", "web-second"):
            with self.subTest(control=control):
                try:
                    lease = self.editable_lease(control)
                    self.bridge.clear_cursor(lease)
                    self.bridge.poll_events()
                    self.send_keys([(16, True), (32, True), (32, False), (16, False)])
                    events = []
                    deadline = time.monotonic() + 2
                    while time.monotonic() < deadline and "toggle" not in events:
                        events.extend(self.bridge.poll_events())
                        time.sleep(0.02)
                    self.assertEqual(events, ["toggle"], "Shift+Space must request a round once")
                    # The controller handles the event by acquiring a fresh target.
                    lease = self.bridge.begin_context()
                    self.assertIsNotNone(lease, self.bridge.context_status())
                    self.assertTrue(self.bridge.valid(lease))
                    self.bridge.clear_cursor(lease)
                finally:
                    self.fixture("focus", "first")

    def test_three_layer_preview_revision_final_and_cancel(self):
        for control in ("first", "rich", "web-first", "web-second"):
            with self.subTest(control=control):
                try:
                    if control.startswith("web-"):
                        self.browser()
                    self.fixture("select-all", control)
                    lease = self.editable_lease(control)
                    self.assertEqual(self.bridge.submit(lease, str(uuid4()), "前缀"), "accepted")
                    revision = 0

                    def preview(text):
                        nonlocal revision
                        revision += 1
                        result = self.bridge.show_cursor(
                            lease, revision, CursorFrame("listening", text, "")
                        )
                        if result != "accepted":
                            self.fail(
                                str(
                                    {
                                        "status": self.bridge.context_status(),
                                        "browser": self.read("browser-text.json"),
                                    }
                                )
                            )

                    filename = (
                        "browser-text.json" if control.startswith("web-") else "editor-text.json"
                    )
                    field = control[4:] if control.startswith("web-") else control
                    preview("今天晴天")
                    self.wait_text(filename, field, "前缀今天晴天")
                    status = self.bridge.context_status()
                    self.assertEqual(status["screenBufferCharacters"], 4)
                    self.assertEqual(status["panelBufferCharacters"], 0)
                    self.assertEqual(status["confirmedCharacters"], 2)
                    preview("今天下雨🙂")
                    self.wait_text(filename, field, "前缀今天下雨🙂")
                    commit = str(uuid4())
                    self.assertEqual(self.bridge.submit(lease, commit, "今天下雨🙂。"), "accepted")
                    self.assertEqual(self.bridge.submit(lease, commit, "今天下雨🙂。"), "accepted")
                    self.wait_text(filename, field, "前缀今天下雨🙂。")
                    self.assertEqual(self.bridge.context_status()["screenBufferCharacters"], 0)
                    preview("尚未确认")
                    self.wait_text(filename, field, "前缀今天下雨🙂。尚未确认")
                    if control == "first":
                        self.send_keys([(27, True), (27, False)])
                    else:
                        self.bridge.clear_cursor(lease)
                    self.wait_text(filename, field, "前缀今天下雨🙂。")
                finally:
                    self.fixture("focus", "first")

    def test_chromium_preview_coalesces_pending_tail_and_promotes_once(self):
        self.browser()
        try:
            self.fixture("select-all", "web-first")
            lease = self.editable_lease("web-first")
            self.assertEqual(self.bridge.submit(lease, str(uuid4()), "前缀"), "accepted")
            preview = "第一版识别文字🙂" * 10
            self.assertEqual(
                self.bridge.show_cursor(lease, 1, CursorFrame("listening", preview, "")), "accepted"
            )
            status = self.bridge.context_status()
            self.assertGreater(status["panelBufferCharacters"], 0)
            self.assertGreater(status["screenBufferCharacters"], 0)
            self.assertEqual(status["confirmedCharacters"], 2)
            preview = "修订后的文字🙂" * 8
            for revision in range(2, 30):
                self.assertEqual(
                    self.bridge.show_cursor(lease, revision, CursorFrame("listening", preview, "")),
                    "accepted",
                )
                if self.bridge.context_status()["panelBufferCharacters"] == 0:
                    break
            self.wait_text("browser-text.json", "first", "前缀" + preview)
            commit = str(uuid4())
            self.assertEqual(self.bridge.submit(lease, commit, preview), "accepted")
            self.assertEqual(self.bridge.submit(lease, commit, preview), "accepted")
            self.bridge.clear_cursor(lease)
            self.wait_text("browser-text.json", "first", "前缀" + preview)
        finally:
            self.fixture("focus", "first")

    def test_long_finals_complete_and_replay_once_in_native_and_chromium(self):
        text = "长文本完整输入🙂。" * 40
        for control in ("first", "rich", "web-first", "web-second"):
            with self.subTest(control=control):
                try:
                    if control.startswith("web-"):
                        self.browser()
                    self.fixture("select-all", control)
                    lease = self.editable_lease(control)
                    commit = str(uuid4())
                    deadline = time.monotonic() + 40
                    while True:
                        result = self.bridge.submit(lease, commit, text)
                        if result != "deferred" or time.monotonic() >= deadline:
                            break
                        time.sleep(0.02)
                    self.assertEqual(result, "accepted")
                    filename = (
                        "browser-text.json" if control.startswith("web-") else "editor-text.json"
                    )
                    field = control[4:] if control.startswith("web-") else control
                    self.wait_text(filename, field, text)
                    self.assertEqual(self.bridge.submit(lease, commit, text), "accepted")
                    self.wait_text(filename, field, text)
                finally:
                    self.fixture("focus", "first")

    def test_chromium_pending_final_cannot_resume_after_clear(self):
        self.browser()
        try:
            self.fixture("select-all", "web-first")
            lease = self.editable_lease("web-first")
            commit, text = str(uuid4()), "继续输入🙂" * 50
            self.assertEqual(self.bridge.submit(lease, commit, text), "deferred")
            time.sleep(0.1)
            prefix = self.read("browser-text.json")["first"]
            self.assertTrue(prefix and text.startswith(prefix) and prefix != text)
            self.bridge.clear_cursor(lease)
            self.assertEqual(self.bridge.submit(lease, commit, text), "stale")
            self.wait_text("browser-text.json", "first", prefix)
        finally:
            self.fixture("focus", "first")

    def test_injected_enter_and_escape_control_session_without_replacing_selection(self):
        for control in ("first", "rich", "web-first", "web-second"):
            with self.subTest(control=control):
                if control.startswith("web-"):
                    self.browser()
                try:
                    self.fixture("select-all", control)
                    lease = self.editable_lease(control)
                    self.assertEqual(
                        self.bridge.submit(lease, str(uuid4()), "保留选区🙂"), "accepted"
                    )
                    self.fixture("select-all", control)
                    lease = self.bridge.begin_context()
                    self.assertEqual(self.bridge.selection(lease), "保留选区🙂")
                    self.bridge.show_cursor(lease, 1, CursorFrame("edit-listening", "指令录音", ""))
                    filename = (
                        "browser-text.json" if control.startswith("web-") else "editor-text.json"
                    )
                    field = control[4:] if control.startswith("web-") else control
                    for key, action in ((13, "pause"), (27, "cancel")):
                        self.bridge.poll_events()
                        self.send_keys([(key, True), (key, True), (key, False)])
                        events = []
                        deadline = time.monotonic() + 2
                        while time.monotonic() < deadline and action not in events:
                            events.extend(self.bridge.poll_events())
                            time.sleep(0.02)
                        time.sleep(0.15)
                        events.extend(self.bridge.poll_events())
                        self.assertEqual(events, [action], f"{control}: injected key must act once")
                        self.wait_text(filename, field, "保留选区🙂")
                    self.assertFalse(self.bridge.valid(lease), "Escape revokes the bound session")
                finally:
                    self.fixture("focus", "first")

    def test_injected_enter_passes_outside_session_and_with_modifier(self):
        def forwarded(changes):
            before = len(self.read("editor-keys.json"))
            self.send_keys(changes)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                try:
                    events = self.read("editor-keys.json")[before:]
                    if events and not events[-1]["down"]:
                        return events, self.read("editor-text.json")["first"]
                except (OSError, ValueError):
                    pass
                time.sleep(0.02)
            self.fail("Unconsumed Enter release did not reach the disposable editor")

        for modified in (False, True):
            with self.subTest(modified=modified):
                changes = [(13, True), (13, False)]
                if modified:
                    self.send_keys([(16, True)])
                    held = ctypes.WinDLL("user32").GetAsyncKeyState(16) & 0x8000
                    self.send_keys([(16, False)])
                    if not held:
                        self.skipTest(
                            "desktop filters synthetic Shift down; cannot simulate Shift+Enter"
                        )
                    changes = [(16, True), *changes, (16, False)]
                self.seed("passthrough")
                self.bridge.close()
                # Compare actual target delivery with no bridge. The desktop IME
                # can consume injected keydowns before the editor sees them, so
                # SendInput acceptance alone cannot promise a newline.
                baseline = forwarded(changes)
                self.bridge = WindowsBridge()
                self.addCleanup(self.bridge.close)
                lease = self.seed("passthrough")
                if not modified:
                    self.bridge.clear_cursor(lease)
                    self.assertIsNone(self.bridge.context_status()["target"])
                self.bridge.poll_events()
                self.assertEqual(forwarded(changes), baseline)
                self.assertEqual(self.bridge.poll_events(), [])
                if modified:
                    self.assertTrue(self.bridge.valid(lease))

    def test_rich_edit_unicode_newline_and_selection(self):
        lease = self.editable_lease("rich")
        self.fixture("select-all", "rich")
        text = "前🙂后\n第二行"
        self.assertEqual(self.bridge.submit(lease, str(uuid4()), text), "accepted")
        self.wait_text("editor-text.json", "rich", text)
        self.fixture("select", "rich", start=3, length=1)
        self.assertEqual(self.bridge.submit(lease, str(uuid4()), "中文"), "accepted")
        self.wait_text("editor-text.json", "rich", "前🙂中文\n第二行")
        self.fixture("focus", "first")

    def test_chromium_textarea_and_contenteditable_confirm_actual_text(self):
        self.browser()
        try:
            for control in ("web-first", "web-second"):
                with self.subTest(control=control):
                    self.fixture("select-all", control)
                    lease = self.editable_lease(control)
                    text = "中文语音输入🙂测试"
                    commit = str(uuid4())
                    self.assertEqual(self.bridge.submit(lease, commit, text), "accepted")
                    self.wait_text("browser-text.json", control[4:], text)
                    self.assertEqual(
                        self.bridge.context_status()["lastInsertionMethod"], "native-char"
                    )
                    self.assertIn(
                        self.bridge.context_status()["lastInsertionVerification"],
                        ("value-change-confirmed", "caret-text-confirmed", "text-change-confirmed"),
                    )
                    self.assertEqual(self.bridge.submit(lease, commit, text), "accepted")
                    self.wait_text("browser-text.json", control[4:], text)
        finally:
            self.fixture("focus", "first")

    def test_chromium_selection_and_late_final_do_not_cross_targets(self):
        self.browser()
        try:
            lease = self.editable_lease("web-first")
            self.fixture("select-all", "web-first")
            self.assertEqual(self.bridge.submit(lease, str(uuid4()), "甲乙丙丁"), "accepted")
            self.fixture("select", "web-first", start=1, length=2)
            self.assertEqual(self.bridge.submit(lease, str(uuid4()), "🙂X"), "accepted")
            self.wait_text("browser-text.json", "first", "甲🙂X丁")
            before = self.read("browser-text.json")
            self.fixture("focus", "web-second")
            self.assertFalse(self.bridge.valid(lease))
            self.assertEqual(self.bridge.submit(lease, str(uuid4()), "不得跨目标"), "stale")
            self.assertEqual(self.read("browser-text.json"), before)
        finally:
            self.fixture("focus", "first")

    def test_chromium_rejected_characters_are_unknown_and_never_replayed(self):
        self.browser()
        try:
            lease = self.editable_lease("web-ignored")
            self.fixture("select-all", "web-ignored")
            before = self.read("browser-text.json")["ignored"]
            commit = str(uuid4())
            self.assertEqual(self.bridge.submit(lease, commit, "不得假报成功"), "unknown")
            self.wait_text("browser-text.json", "ignored", before)
            self.assertEqual(self.bridge.submit(lease, commit, "不得假报成功"), "unknown")
            self.wait_text("browser-text.json", "ignored", before)
        finally:
            self.fixture("focus", "first")

    def test_chromium_password_and_readonly_are_rejected(self):
        self.browser()
        try:
            before = self.read("browser-text.json")
            for control in ("web-password", "web-readonly"):
                self.fixture("focus", control)
                self.assertIsNone(self.bridge.begin_context())
            self.assertEqual(self.read("browser-text.json"), before)
        finally:
            self.fixture("focus", "first")

    def test_insertion_at_cursor_unicode_newline_idempotency_and_undo(self):
        lease = self.seed("前🙂后")
        self.fixture("select", start=3, length=0)  # UTF-16 position after the emoji.
        commit = str(uuid4())
        self.assertEqual(self.bridge.submit(lease, commit, "中\n英"), "accepted")
        expected = "前🙂中\r\n英后"
        self.assertEqual(self.read("editor-text.json")["first"], expected)
        context = self.bridge.context_status()
        self.assertEqual(context["lastInsertionMethod"], "native-edit")
        self.assertEqual(self.bridge.submit(lease, commit, "中\n英"), "accepted")
        self.assertEqual(self.read("editor-text.json")["first"], expected)
        self.assertEqual(self.bridge.context_status()["commitCount"], context["commitCount"])
        self.fixture("undo")
        self.assertEqual(self.read("editor-text.json")["first"], "前🙂后")

    def test_only_selected_range_is_replaced(self):
        lease = self.seed("甲乙丙丁")
        self.fixture("select", start=1, length=2)
        self.assertEqual(self.bridge.submit(lease, str(uuid4()), "🙂X"), "accepted")
        self.assertEqual(self.read("editor-text.json")["first"], "甲🙂X丁")

    def test_command_selection_preview_replace_and_replay(self):
        for control in ("first", "rich", "web-first", "web-second"):
            with self.subTest(control=control):
                if control.startswith("web-"):
                    self.browser()
                try:
                    self.fixture("select-all", control)
                    lease = self.editable_lease(control)
                    self.assertEqual(self.bridge.submit(lease, str(uuid4()), "原文🙂"), "accepted")
                    self.fixture("select-all", control)
                    lease = self.bridge.begin_context()
                    self.assertEqual(self.bridge.selection(lease), "原文🙂")
                    filename = (
                        "browser-text.json" if control.startswith("web-") else "editor-text.json"
                    )
                    field = control[4:] if control.startswith("web-") else control
                    self.assertEqual(
                        self.bridge.show_cursor(
                            lease, 1, CursorFrame("edit-processing", "改成简短中文", "")
                        ),
                        "accepted",
                    )
                    self.wait_text(filename, field, "原文🙂")
                    commit = str(uuid4())
                    self.assertEqual(self.bridge.submit(lease, commit, "修改完成🙂"), "accepted")
                    self.wait_text(filename, field, "修改完成🙂")
                    self.assertEqual(self.bridge.submit(lease, commit, "修改完成🙂"), "accepted")
                    self.wait_text(filename, field, "修改完成🙂")
                finally:
                    self.fixture("focus", "first")

    def test_command_rejects_moved_equal_text_selection(self):
        for control in ("first", "rich", "web-first"):
            with self.subTest(control=control):
                if control.startswith("web-"):
                    self.browser()
                try:
                    self.fixture("select-all", control)
                    lease = self.editable_lease(control)
                    self.assertEqual(
                        self.bridge.submit(lease, str(uuid4()), "相同-相同"), "accepted"
                    )
                    self.fixture("select", control, start=0, length=2)
                    lease = self.bridge.begin_context()
                    self.assertEqual(self.bridge.selection(lease), "相同")
                    self.fixture("select", control, start=3, length=2)
                    self.assertEqual(self.bridge.submit(lease, str(uuid4()), "不得替换"), "stale")
                    filename = (
                        "browser-text.json" if control.startswith("web-") else "editor-text.json"
                    )
                    self.wait_text(
                        filename,
                        control[4:] if control.startswith("web-") else control,
                        "相同-相同",
                    )
                finally:
                    self.fixture("focus", "first")

    def test_command_without_selection_returns_empty_for_dictation(self):
        lease = self.seed("原文")
        self.fixture("select", start=2, length=0)
        self.assertEqual(self.bridge.selection(lease), "")

    def test_command_selection_limit_counts_unicode_characters_not_utf16_units(self):
        text = "🙂" * 9000
        lease = self.seed(text)
        self.fixture("select-all")
        self.assertEqual(self.bridge.selection(lease), text)
        self.assertEqual(self.bridge.submit(lease, str(uuid4()), "已精简"), "accepted")
        self.wait_text("editor-text.json", "first", "已精简")
        lease = self.seed("字" * 16001)
        self.fixture("select-all")
        with self.assertRaises(ValueError):
            self.bridge.selection(lease)
        self.wait_text("editor-text.json", "first", "字" * 16001)

    def test_cancelled_command_rejects_late_replacement(self):
        lease = self.seed("取消保留原文")
        self.fixture("select-all")
        self.assertEqual(self.bridge.selection(lease), "取消保留原文")
        self.bridge.clear_cursor(lease)
        self.assertEqual(self.bridge.submit(lease, str(uuid4()), "迟到修改"), "stale")
        self.wait_text("editor-text.json", "first", "取消保留原文")

    def test_empty_final_does_not_delete_selected_text(self):
        text = "空定稿不能删除选区🙂"
        lease = self.seed(text)
        self.fixture("select-all")
        self.assertEqual(self.bridge.submit(lease, str(uuid4()), ""), "accepted")
        self.assertEqual(self.read("editor-text.json")["first"], text)

    def test_focus_switch_rejects_late_final_without_writing_either_field(self):
        lease = self.seed("旧目标")
        before = self.read("editor-text.json")
        self.fixture("focus", "second")
        self.assertFalse(self.bridge.valid(lease))
        self.assertEqual(self.bridge.submit(lease, str(uuid4()), "不得跨目标输入"), "stale")
        self.assertEqual(self.read("editor-text.json"), before)
        self.fixture("focus", "first")

    def test_password_and_readonly_controls_are_rejected(self):
        before = self.read("editor-text.json")
        for control in ("password", "readonly"):
            with self.subTest(control=control):
                self.fixture("focus", control)
                self.assertIsNone(self.bridge.begin_context())
        self.assertEqual(self.read("editor-text.json"), before)
        self.fixture("focus", "first")
