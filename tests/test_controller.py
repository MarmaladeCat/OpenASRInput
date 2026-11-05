import unittest

from openasrinput.application.controller import Controller
from openasrinput.domain.bridge import MemoryBridge
from openasrinput.domain.ledger import AUDIO


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.host = MemoryBridge()
        self.host.focus("first")
        self.now = 0
        self.core = Controller(self.host, clock=lambda: self.now)
        self.seq = 0

    def start(self, sid="session-1"):
        self.core.toggle()
        self.assertEqual(self.core.take_effects()[0].kind, "session.create")
        self.assertTrue(self.core.bind_session(self.core.generation, sid))
        self.seq = 0
        self.event("session.ready", audio=AUDIO, finalizeTimeoutMs=2000)
        self.assertEqual(self.core.take_effects()[0].kind, "audio.start")

    def event(self, kind, **fields):
        self.seq += 1
        event = {"type": kind, "sessionId": self.core.ledger.session_id, "seq": self.seq, **fields}
        self.core.on_event(self.core.generation, event)
        return event

    def final(self, text="定稿。", uid="u1", revision=2):
        return self.event("transcript.final", utteranceId=uid, revision=revision, text=text)

    def test_no_target_has_no_network_or_microphone_effect(self):
        self.host.focus(None)
        self.core.toggle()
        self.assertEqual(self.core.state, "idle")
        self.assertEqual(self.core.take_effects(), [])
        self.assertIn("聚焦", self.core.error)

    def test_partial_never_submits_and_final_only_at_safe_boundary(self):
        self.start()
        self.event("transcript.partial", utteranceId="u1", revision=1, text="错误预览")
        self.core.drain()
        self.assertEqual(self.host.commits, [])
        final = self.final()
        self.assertEqual(self.host.commits, [])
        self.core.drain()
        self.core.on_event(self.core.generation, final)
        self.core.drain()
        self.assertEqual([row[2] for row in self.host.commits], ["定稿。"])

    def test_sentence_order_across_resume(self):
        self.start()
        self.final("第一句。")
        self.core.drain()
        self.assertEqual(self.core.submissions[0].status, "submitted")
        self.core.toggle()
        self.assertEqual(
            [e.kind for e in self.core.take_effects()], ["audio.stop-flush", "audio.end"]
        )
        self.core.toggle()
        generation = self.core.generation
        self.event("session.finished", finalCount=1)
        self.assertEqual(self.core.state, "connecting")
        self.assertEqual(self.core.generation, generation + 1)
        self.core.take_effects()
        self.core.bind_session(self.core.generation, "session-2")
        self.seq = 0
        self.event("session.ready", audio=AUDIO, finalizeTimeoutMs=2000)
        self.final("第二句。", "u2")
        self.core.drain()
        self.assertEqual([row[2] for row in self.host.commits], ["第一句。", "第二句。"])

    def test_rime_candidate_rejects_start_without_changing_composition(self):
        self.host.composing = True
        self.core.toggle()
        self.assertEqual(self.core.state, "idle")
        self.assertTrue(self.host.composing)
        self.assertEqual(self.core.take_effects(), [])

    def test_focus_change_and_return_never_reuses_old_lease(self):
        self.start()
        self.final()
        self.host.focus("second")
        self.core.context_changed()
        self.assertEqual(self.core.state, "pausing")
        self.host.focus("first")
        self.core.drain()
        self.assertEqual(self.host.commits, [])
        self.assertEqual(self.core.submissions[0].status, "retained")
        self.final("迟到定稿。", "u2")
        self.core.drain()
        self.assertEqual(self.core.submissions[-1].status, "retained")

    def test_bridge_revalidates_if_context_event_has_not_arrived_yet(self):
        self.start()
        self.final()
        self.host.focus("second")
        self.core.drain()
        self.assertEqual(self.host.commits, [])

    def test_ambiguous_ack_is_retained_without_retry(self):
        self.start()
        self.final()
        original = self.host.submit

        def lost_ack(*args):
            original(*args)
            raise ConnectionError("ack lost")

        self.host.submit = lost_ack
        self.core.drain()
        self.core.drain()
        self.assertEqual(len(self.host.commits), 1)
        self.assertEqual(self.core.submissions[0].reason, "unknown")

    def test_host_commit_id_is_idempotent_and_payload_is_bound(self):
        lease = self.host.begin_context()
        self.assertEqual(self.host.submit(lease, "c1", "text"), "accepted")
        self.assertEqual(self.host.submit(lease, "c1", "text"), "accepted")
        self.assertEqual(self.host.submit(lease, "c1", "changed"), "failed")
        self.assertEqual(len(self.host.commits), 1)

    def test_failed_ack_retains_the_lease_queue_including_later_finals(self):
        self.start()
        self.final("第一句。")
        self.final("第二句。", "u2")
        calls = []

        def failed(*args):
            calls.append(args)
            return "failed"

        self.host.submit = failed
        self.core.drain()
        self.final("第三句。", "u3")
        self.core.drain()
        self.assertEqual(len(calls), 1)
        self.assertTrue(all(item.status == "retained" for item in self.core.submissions))

    def test_cancel_never_removes_committed_text(self):
        self.start()
        self.final()
        self.core.drain()
        self.host.composing = True
        self.final("放弃内容", "u2")
        self.core.cancel()
        self.host.composing = False
        self.core.drain()
        self.assertEqual([row[2] for row in self.host.commits], ["定稿。"])
        self.assertEqual(self.core.submissions[-1].status, "cancelled")

    def test_finalization_timeout_keeps_preview_unconfirmed(self):
        self.start()
        self.event("transcript.partial", utteranceId="u1", revision=1, text="未定稿")
        self.core.toggle()
        self.now = 2.1
        self.core.tick()
        self.assertEqual(self.core.state, "failed")
        self.assertEqual(self.core.residuals[0]["status"], "unconfirmed")
        self.core.drain()
        self.assertEqual(self.host.commits, [])

    def test_recording_cap_pauses_and_releases_capture(self):
        self.start()
        self.now = 295
        self.core.tick()
        self.assertEqual(self.core.state, "pausing")
        self.assertEqual(
            [e.kind for e in self.core.take_effects()], ["audio.stop-flush", "audio.end"]
        )

    def test_pause_during_connecting_does_not_start_microphone(self):
        self.core.toggle()
        self.core.take_effects()
        self.core.toggle()
        self.core.bind_session(self.core.generation, "session-1")
        self.event("session.ready", audio=AUDIO, finalizeTimeoutMs=2000)
        self.assertEqual(self.core.state, "pausing")
        self.assertNotIn("audio.start", [e.kind for e in self.core.take_effects()])

    def test_stale_generation_response_is_rejected_after_cancel(self):
        self.core.toggle()
        generation = self.core.generation
        self.core.cancel()
        self.core.toggle()
        self.assertFalse(self.core.bind_session(generation, "old"))
        self.assertTrue(self.core.bind_session(self.core.generation, "new"))
        self.core.on_event(generation, {"type": "session.ready", "sessionId": "old", "seq": 1})
        self.assertEqual(self.core.state, "connecting")

    def test_sequence_gap_stops_and_retains_instead_of_committing(self):
        self.start()
        self.core.on_event(
            self.core.generation,
            {
                "type": "transcript.final",
                "sessionId": "session-1",
                "seq": 3,
                "utteranceId": "u1",
                "revision": 1,
                "text": "不完整事件",
            },
        )
        self.assertEqual(self.core.state, "failed")
        self.assertEqual(self.core.submissions, [])

    def test_final_count_mismatch_cannot_trigger_auto_resume(self):
        self.start()
        self.host.composing = True
        self.final()
        self.core.toggle()
        self.core.toggle()
        self.event("session.finished", finalCount=2)
        self.assertEqual(self.core.state, "failed")
        self.assertFalse(self.core.resume_requested)
        self.assertEqual(self.core.submissions[0].status, "retained")

    def test_stable_final_is_never_rewritten(self):
        self.start()
        self.final()
        self.core.drain()
        self.final("擅自改写", revision=3)
        self.assertEqual(self.core.state, "failed")
        self.assertEqual([row[2] for row in self.host.commits], ["定稿。"])

    def test_old_revision_and_duplicate_final_are_ignored(self):
        self.start()
        self.event("transcript.partial", utteranceId="u1", revision=2, text="新预览")
        self.event("transcript.partial", utteranceId="u1", revision=1, text="旧预览")
        self.assertEqual(self.core.ledger.preview, "新预览")
        self.final(revision=3)
        self.final(revision=4)
        self.core.drain()
        self.assertEqual(len(self.host.commits), 1)
        self.assertEqual(self.core.ledger.final_count, 1)
