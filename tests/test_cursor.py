import struct
import unittest

from openasrinput.application.controller import Controller
from openasrinput.domain.bridge import CursorFrame, MemoryBridge
from openasrinput.domain.ledger import AUDIO
from openasrinput.domain.waveform import Waveform


class CursorTests(unittest.TestCase):
    def test_deferred_windows_commit_survives_session_finished_until_modifier_release(self):
        submit = self.host.submit
        self.host.submit = lambda *_args: "deferred"
        self.event("transcript.final", utteranceId="u1", revision=1, text="保留到松开按键")
        self.core.drain()
        self.event("session.finished", finalCount=1)
        self.core.drain()
        self.assertEqual(self.core.state, "pausing")
        self.assertTrue(self.host.valid(self.core.lease))
        self.host.submit = submit
        self.core.drain()
        self.assertEqual(self.core.state, "paused")
        self.assertEqual([item[2] for item in self.host.commits], ["保留到松开按键"])

    def test_identical_frame_is_resent_after_monitor_surface_loss(self):
        now = [0.0]
        self.core.clock = lambda: now[0]
        self.core.drain()
        frame = self.host.cursor_frame
        self.host.cursor_frame = None  # Shell hotplug hid its actor, target is still valid.
        now[0] = 0.1
        self.core.drain()
        self.assertIsNone(self.host.cursor_frame)
        now[0] = 0.3
        self.core.drain()
        self.assertEqual(self.host.cursor_frame, frame)
        self.assertEqual(self.host.commits, [])

    def test_focus_loss_is_reported_as_a_reason_not_a_half_second_timeout(self):
        self.host.focus("other")
        self.core.tick()
        self.assertEqual(self.core.stop_reason, "context-lost")
        self.assertEqual(self.core.state, "pausing")

    def setUp(self):
        self.host = MemoryBridge()
        self.host.focus("input")
        self.core = Controller(self.host)
        self.core.toggle()
        self.core.bind_session(self.core.generation, "s1")
        self.seq = 0
        self.event("session.ready", audio=AUDIO, finalizeTimeoutMs=1000)

    def event(self, kind, **fields):
        self.seq += 1
        self.core.on_event(
            self.core.generation,
            {
                "type": kind,
                "sessionId": "s1",
                "seq": self.seq,
                **fields,
            },
        )

    def test_partial_revision_replaces_cursor_text_without_committing(self):
        self.event("transcript.partial", utteranceId="u1", revision=1, text="工圆")
        self.core.drain()
        self.assertEqual(self.host.cursor_frame.text, "工圆")
        self.event("transcript.partial", utteranceId="u1", revision=2, text="公园。")
        self.core.drain()
        self.assertEqual(self.host.cursor_frame.text, "公园。")
        self.assertEqual(self.host.commits, [])
        self.event("transcript.final", utteranceId="u1", revision=3, text="公园。")
        self.core.drain()
        self.assertEqual(self.host.cursor_frame.text, "")
        self.assertEqual([row[2] for row in self.host.commits], ["公园。"])

    def test_waveform_is_separate_from_application_preedit(self):
        self.core.on_audio(self.core.generation, struct.pack("<320h", *([16000] * 320)))
        self.core.drain()
        self.assertIn("▆", self.host.cursor_frame.waveform)
        self.assertEqual(self.host.cursor_frame.text, "")
        self.assertEqual(self.host.commits, [])

    def test_focus_change_removes_display_and_never_moves_it_to_new_input(self):
        self.event("transcript.partial", utteranceId="u1", revision=1, text="旧输入框")
        self.core.drain()
        self.host.focus("second")
        self.core.context_changed()
        self.core.drain()
        self.assertIsNone(self.host.cursor_frame)
        self.assertEqual(self.host.commits, [])

    def test_cancel_clears_wave_and_preview_without_commit(self):
        self.event("transcript.partial", utteranceId="u1", revision=1, text="放弃")
        self.core.drain()
        self.core.cancel()
        self.core.drain()
        self.assertIsNone(self.host.cursor_frame)
        self.assertEqual(self.host.commits, [])

    def test_old_frame_and_old_clear_cannot_replace_new_lease(self):
        lease = self.core.lease
        self.host.show_cursor(lease, 2, CursorFrame("listening", "新文本", "▃"))
        self.host.show_cursor(lease, 1, CursorFrame("listening", "旧文本", "▁"))
        self.assertEqual(self.host.cursor_frame.text, "新文本")
        new = self.host.begin_context()
        self.host.show_cursor(new, 1, CursorFrame("listening", "新一轮", "▆"))
        self.host.clear_cursor(lease)
        self.assertEqual(self.host.cursor_frame.text, "新一轮")


class WaveformTests(unittest.TestCase):
    def test_silence_has_no_fabricated_activity(self):
        wave = Waveform(columns=4)
        self.assertEqual(wave.feed(bytes(6400)), "▁▁▁▁")

    def test_split_sample_and_frame_boundaries_preserve_actual_signal(self):
        data = struct.pack("<320h", *([-32768] * 320))
        wave = Waveform(columns=4)
        self.assertEqual(wave.feed(data[:3]), "▁▁▁▁")
        self.assertEqual(wave.feed(data[3:]), "▁▁▁█")
        wave.reset()
        self.assertEqual(wave.bars, "▁▁▁▁")
