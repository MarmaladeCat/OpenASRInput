"""Selection capability must not gate dictation, but target validity still does."""

import unittest

from openasrinput.adapters.native import NativeBridge
from openasrinput.adapters.windows import WindowsBridge
from openasrinput.application.controller import Controller
from openasrinput.domain.bridge import MemoryBridge


class OptionalSelectionTests(unittest.TestCase):
    def test_both_platforms_start_dictation_without_selection_capability(self):
        for adapter in (NativeBridge, WindowsBridge):
            with self.subTest(adapter=adapter.__name__):
                host = MemoryBridge()
                host.focus("editor")
                host.request = lambda *args: "unsupported"
                host.selection = lambda lease: adapter.selection(host, lease)
                core = Controller(host)
                core.toggle(command=True)
                self.assertEqual((core.state, core.mode, core.error), ("connecting", "dictation", ""))
                self.assertEqual([e.kind for e in core.take_effects()], ["session.create"])

    def test_empty_or_selected_text_selects_the_corresponding_mode(self):
        for text, mode in (("", "dictation"), ("选中文本", "edit")):
            host = MemoryBridge()
            host.focus("editor")
            host.selected_text = text
            core = Controller(host)
            core.toggle(command=True)
            self.assertEqual(core.mode, mode)
            self.assertEqual(core.selected_text, text)

    def test_focus_change_during_optional_query_prevents_recording(self):
        host = MemoryBridge()
        host.focus("editor")
        def selection(lease):
            host.focus("another-editor")
            return ""
        host.selection = selection
        core = Controller(host)
        core.toggle(command=True)
        self.assertEqual(core.state, "failed")
        self.assertNotIn("session.create", [e.kind for e in core.take_effects()])

    def test_stale_transport_failure_and_oversized_selection_are_not_dictation(self):
        for adapter in (NativeBridge, WindowsBridge):
            host = MemoryBridge()
            host.focus("editor")
            host.request = lambda *args: "stale"
            with self.assertRaises(ValueError):
                adapter.selection(host, host.begin_context())
        for failure in (ValueError("stale"), OSError("disconnected")):
            host = MemoryBridge()
            host.focus("editor")
            def selection(lease):
                raise failure
            host.selection = selection
            core = Controller(host)
            core.toggle(command=True)
            self.assertEqual(core.state, "failed")
