import importlib.util
import unittest
from pathlib import Path

from openasrinput.infrastructure.config import normalize
from openasrinput.infrastructure.frameworks import select_framework

spec = importlib.util.spec_from_file_location(
    "ibus_bridge", Path(__file__).resolve().parents[1] / "src/native/ibus/engine.py"
)
ibus = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ibus)


class FrameworkTests(unittest.TestCase):
    def test_auto_requires_running_service_and_rejects_ambiguity(self):
        self.assertEqual(select_framework(running=["ibus"], environ={}), "ibus")
        with self.assertRaises(RuntimeError):
            select_framework(running=[], environ={"GTK_IM_MODULE": "ibus"})
        with self.assertRaises(RuntimeError):
            select_framework(running=["fcitx4", "fcitx5"], environ={"GTK_IM_MODULE": "fcitx"})
        self.assertEqual(
            select_framework(running=["ibus", "fcitx5"], environ={"GTK_IM_MODULE": "ibus"}), "ibus"
        )
        with self.assertRaises(RuntimeError):
            select_framework("fcitx4", environ={"XDG_SESSION_TYPE": "wayland"})

    def test_saved_framework_validation(self):
        self.assertEqual(normalize({})["input"]["framework"], "auto")
        for value in ("auto", "ibus", "fcitx4", "fcitx5"):
            self.assertEqual(
                normalize({"input": {"framework": value}})["input"]["framework"], value
            )
        for value in (None, [], "unknown"):
            with self.assertRaises(ValueError):
                normalize({"input": {"framework": value}})

    def test_ibus_context_isolation_and_commit_deduplication(self):
        class Engine:
            private = False
            commits = []

            def preview(self, *args):
                pass

            def commit(self, text):
                self.commits.append(text)

        bridge = ibus.BridgeState()
        events = []
        bridge.event = events.append
        engine = Engine()
        bridge.focus(engine)
        lease = bridge.request("BEGIN")
        self.assertEqual(bridge.request("SELECTION", lease), "unsupported")
        args = (lease, "commit-1", "中文".encode().hex())
        self.assertEqual(bridge.request("COMMIT", *args), "accepted")
        self.assertEqual(bridge.request("COMMIT", *args), "accepted")
        self.assertEqual(engine.commits, ["中文"])
        bridge.focus(None)
        self.assertEqual(events, ["context-lost"])
        self.assertEqual(bridge.request("COMMIT", lease, "late", "61"), "stale")
        bridge.focus(engine)
        self.assertNotEqual(bridge.request("BEGIN"), lease)
        engine.private = True
        self.assertEqual(bridge.request("BEGIN"), "unavailable")

    def test_ibus_selection_snapshot_and_panel_only_instruction(self):
        class Engine:
            private = False
            surrounding = ("前文你好😀世界后文", 2, 7)
            cursor = (20, 30, 1, 18)

            def __init__(self):
                self.commits, self.preedits, self.messages = [], [], []
                self.deletions = 0

            def preview(self, *args):
                self.preedits.append(args)

            def auxiliary(self, text):
                self.messages.append(text)

            def commit(self, text):
                self.commits.append(text)

            def delete_selection(self):
                self.deletions += 1

        bridge = ibus.BridgeState()
        engine = Engine()
        bridge.focus(engine)
        lease = bridge.request("BEGIN")
        self.assertEqual(bytes.fromhex(bridge.request("SELECTION", lease)).decode(), "你好😀世界")
        before = list(engine.preedits)
        bridge.request(
            "SHOW", lease, "1", "翻译".encode().hex(), "", "edit-listening".encode().hex()
        )
        self.assertEqual(engine.preedits, before)
        engine.cursor = (21, 30, 1, 18)
        self.assertEqual(bridge.request("COMMIT", lease, "moved", "61"), "stale")
        engine.cursor = (20, 30, 1, 18)
        engine.surrounding = ("正文已变化", 0, 1)
        self.assertEqual(bridge.request("COMMIT", lease, "changed", "61"), "stale")
        engine.surrounding = ("前文你好😀世界后文", 2, 7)
        args = (lease, "replace", "Hello".encode().hex())
        self.assertEqual(bridge.request("COMMIT", *args), "accepted")
        self.assertEqual(bridge.request("COMMIT", *args), "accepted")
        self.assertEqual(engine.commits, ["Hello"])
        self.assertEqual(bridge.request("COMMIT", lease, "another-id", ""), "stale")
        self.assertEqual(bridge.request("COMMIT", lease, "replace", "62"), "failed")
        lease = bridge.request("BEGIN")
        self.assertEqual(bridge.request("COMMIT", lease, "empty-dictation", ""), "accepted")
        self.assertEqual(engine.commits, ["Hello"])
        self.assertEqual(engine.deletions, 0)
        self.assertEqual(bytes.fromhex(bridge.request("SELECTION", lease)).decode(), "你好😀世界")
        self.assertEqual(bridge.request("COMMIT", lease, "empty-command", ""), "accepted")
        self.assertEqual(bridge.request("COMMIT", lease, "empty-command", ""), "accepted")
        self.assertEqual(bridge.request("COMMIT", lease, "empty-again", ""), "stale")
        self.assertEqual(engine.commits, ["Hello"])
        self.assertEqual(engine.deletions, 1)
        bridge.focus(None)
        self.assertEqual(bridge.request("COMMIT", lease, "late", "61"), "stale")
