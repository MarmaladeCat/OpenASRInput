import asyncio
import unittest
import zlib
from contextlib import asynccontextmanager
from unittest.mock import patch

from test_portal_client import PortalFixture, web

from openasrinput.adapters.portal import PortalRequestError
from openasrinput.application.daemon import Daemon, RunningSession, SessionSettings
from openasrinput.domain.audio_processing import AudioProcessor
from openasrinput.domain.bridge import MemoryBridge


class SyntheticCapture:
    def __init__(self):
        self.stopped = asyncio.Event()
        self.started = False
        self.closed = False

    async def start(self):
        self.started = True

    async def chunks(self):
        yield bytes(640)
        await self.stopped.wait()
        yield b"\x01\x00"  # Last complete sample, flushed BEFORE audio.end.

    async def stop(self):
        self.closed = True
        self.stopped.set()


@unittest.skipIf(web is None, "optional aiohttp transport dependency is not installed")
class DaemonTests(PortalFixture, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.host = MemoryBridge()
        self.host.focus("input")
        self.captures = []

        def factory():
            capture = SyntheticCapture()
            self.captures.append(capture)
            return capture

        self.daemon = Daemon(self.host, self.client, capture_factory=factory)

    async def asyncTearDown(self):
        if self.ready_gate:
            self.ready_gate.set()
        await self.daemon.close()
        await super().asyncTearDown()

    async def until(self, predicate):
        async def wait():
            while not predicate():
                await asyncio.sleep(0.005)

        await asyncio.wait_for(wait(), 2)

    async def test_pause_flushes_tail_then_resume_opens_new_capture_and_session(self):
        await self.daemon.action("toggle")
        await self.until(lambda: self.daemon.core.state == "listening" and len(self.pcm) == 1)
        self.assertEqual(len(self.captures), 1)
        await self.daemon.action("toggle")
        await self.until(lambda: self.daemon.core.state == "paused" and not self.daemon.tasks)
        self.assertTrue(self.captures[0].closed)
        self.assertEqual(self.pcm, [bytes(640), b"\x01\x00"])
        self.assertEqual([row[2] for row in self.host.commits], ["模拟定稿。"])
        self.assertIsNone(self.host.cursor_frame)
        await self.daemon.action("toggle")
        await self.until(lambda: self.daemon.core.state == "listening")
        self.assertEqual(self.sessions, 2)
        self.assertEqual(len(self.captures), 2)
        await self.daemon.action("cancel")
        await self.until(lambda: not self.daemon.tasks)
        self.assertTrue(self.captures[1].closed)
        self.assertEqual(len(self.host.commits), 1)

    async def test_pause_during_connecting_stops_capture_then_flushes_buffer_after_ready(self):
        self.ready_gate = asyncio.Event()
        await self.daemon.action("toggle")
        await self.until(lambda: len(self.ws_headers) == 1)
        self.assertTrue(self.captures[0].started)
        self.assertEqual(self.pcm, [])
        await self.daemon.action("pause")
        self.assertTrue(self.captures[0].closed)
        self.ready_gate.set()
        await self.until(lambda: not self.daemon.tasks)
        self.assertEqual(self.pcm, [bytes(640), b"\x01\x00"])
        self.assertEqual(self.daemon.core.state, "paused")

    async def test_calibration_check_buffers_raw_audio_then_processes_prefix_and_tail_once(self):
        verified = asyncio.Event()
        prefix, tail = b"\xe8\x03" * 320, b"\x84\x03" * 320

        class Capture(SyntheticCapture):
            async def chunks(self):
                yield prefix
                await self.stopped.wait()
                yield tail

        capture = Capture()

        async def prepare(client):
            await verified.wait()
            return {"gain": 2, "highpassHz": 70}

        @asynccontextmanager
        async def settings():
            yield SessionSettings(self.client, lambda: capture, prepare_audio=prepare)

        self.daemon.session_factory = settings
        await self.daemon.action("toggle")
        await self.until(
            lambda: self.daemon.sessions.get(1) and self.daemon.sessions[1].queued_bytes == 640
        )
        self.assertTrue(capture.started)
        self.assertEqual(self.daemon.sessions[1].queue[0], prefix)
        self.assertEqual(self.pcm, [])
        verified.set()
        await self.until(lambda: len(self.pcm) == 1)
        await self.daemon.action("pause")
        await self.until(lambda: not self.daemon.tasks)
        self.assertEqual(b"".join(self.pcm), AudioProcessor(2, 70).process(prefix + tail))

    async def test_enter_flushes_remaining_final_once_and_does_not_resume(self):
        await self.daemon.action("toggle")
        await self.until(lambda: self.daemon.core.state == "listening" and len(self.pcm) == 1)
        await self.daemon.action("pause")  # Native Enter event.
        await self.daemon.action("pause")  # Repeated Enter must never resume capture.
        await self.until(lambda: self.daemon.core.state == "paused" and not self.daemon.tasks)
        self.assertEqual(self.pcm, [bytes(640), b"\x01\x00"])
        self.assertEqual([row[2] for row in self.host.commits], ["模拟定稿。"])
        self.assertEqual(self.daemon.core.stop_reason, "enter")
        self.assertIsNone(self.host.cursor_frame)
        self.assertEqual(len(self.captures), 1)

    async def test_escape_discards_preview_and_never_commits_late_final(self):
        await self.daemon.action("toggle")
        await self.until(lambda: self.daemon.core.state == "listening")
        generation = self.daemon.core.generation
        self.daemon.core.on_event(
            generation,
            {
                "type": "transcript.partial",
                "sessionId": self.daemon.core.ledger.session_id,
                "seq": 2,
                "utteranceId": "cancelled-preview",
                "revision": 1,
                "text": "取消这句话",
            },
        )
        self.daemon.core.drain()
        self.assertIsNotNone(self.host.cursor_frame)
        await self.daemon.action("cancel")
        self.daemon.core.on_event(
            generation,
            {
                "type": "transcript.final",
                "sessionId": self.daemon.core.ledger.session_id,
                "seq": 3,
                "utteranceId": "cancelled-preview",
                "revision": 2,
                "text": "迟到定稿",
            },
        )
        self.daemon.core.drain()
        await self.until(lambda: not self.daemon.tasks)
        self.assertEqual(self.daemon.core.state, "idle")
        self.assertEqual(self.host.commits, [])
        self.assertIsNone(self.host.cursor_frame)

    async def test_pause_during_device_start_flushes_buffered_tail(self):
        starting, release = asyncio.Event(), asyncio.Event()
        capture = SyntheticCapture()

        async def slow_start():
            starting.set()
            await release.wait()
            capture.started = True

        capture.start = slow_start
        self.daemon.capture_factory = lambda: capture
        await self.daemon.action("toggle")
        await starting.wait()
        await self.daemon.action("pause")
        release.set()
        await self.until(lambda: not self.daemon.tasks)
        self.assertEqual(self.pcm, [bytes(640), b"\x01\x00"])
        self.assertTrue(capture.closed)
        self.assertEqual(self.daemon.core.state, "paused")

    async def test_pause_before_session_task_runs_never_opens_microphone(self):
        await self.daemon.action("toggle")
        await self.daemon.action("pause")
        await self.until(lambda: not self.daemon.tasks)
        self.assertFalse(self.captures[0].started)
        self.assertEqual(self.pcm, [])
        self.assertEqual(self.daemon.core.state, "paused")

    async def test_cancel_during_ready_negotiation_discards_buffer_and_stops_capture(self):
        self.ready_gate = asyncio.Event()
        await self.daemon.action("toggle")
        await self.until(lambda: len(self.ws_headers) == 1)
        await self.daemon.action("cancel")
        self.ready_gate.set()
        await self.until(lambda: not self.daemon.tasks)
        self.assertTrue(self.captures[0].closed)
        self.assertEqual(self.pcm, [])
        self.assertEqual(self.host.commits, [])
        self.assertEqual(self.daemon.core.state, "idle")
        self.assertEqual(self.cancelled, ["s1"])

    async def test_late_http_create_response_is_cancelled_after_stopping_device(self):
        created, release = asyncio.Event(), asyncio.Event()
        original = self.client.create_session

        async def slow_create():
            session = await original()
            created.set()
            await release.wait()
            return session

        self.client.create_session = slow_create
        await self.daemon.action("toggle")
        await created.wait()
        await self.daemon.action("cancel")
        release.set()
        await self.until(lambda: not self.daemon.tasks)
        self.assertTrue(self.captures[0].closed)
        self.assertEqual(self.pcm, [])
        self.assertEqual(self.cancelled, ["s1"])

    async def test_focus_loss_pauses_capture_and_retains_late_final(self):
        await self.daemon.action("toggle")
        await self.until(lambda: self.daemon.core.state == "listening")
        self.host.focus("other")
        await self.daemon.action("context-lost")
        await self.until(lambda: not self.daemon.tasks)
        self.assertTrue(self.captures[0].closed)
        self.assertEqual(self.host.commits, [])
        self.assertEqual(self.daemon.core.submissions[0].status, "retained")

    async def test_microphone_start_failure_releases_session_and_native_panel(self):
        class UnavailableCapture(SyntheticCapture):
            async def start(self):
                raise PermissionError("device denied")

        self.daemon.capture_factory = UnavailableCapture
        await self.daemon.action("toggle")
        await self.until(lambda: not self.daemon.tasks)
        self.assertEqual(self.daemon.core.state, "failed")
        self.assertIn("denied", self.daemon.core.error)
        self.assertEqual(self.host.commits, [])
        self.assertIsNone(self.host.cursor_frame)
        self.assertEqual(self.cancelled, [f"s{i + 1}" for i in range(self.sessions)])

    async def test_missing_profile_shows_notice_once_and_stops_microphone(self):
        async def missing():
            raise PortalRequestError("PROFILE_NOT_FOUND", "识别配置不存在", 404)

        self.client.create_session = missing
        await self.daemon.action("toggle")
        await self.until(lambda: not self.daemon.tasks)
        self.assertEqual(self.daemon.core.state, "failed")
        self.assertTrue(self.captures[0].closed)
        self.assertIn("尚未配置识别档案「local」", self.host.notices[0])
        self.assertEqual(self.host.commits, [])
        self.assertIsNone(self.host._leased)
        self.daemon.core.drain()
        self.daemon.core.drain()
        self.assertEqual(len(self.host.notices), 1)

    async def test_disconnected_portal_shows_actionable_notice(self):
        async def disconnected():
            raise ConnectionRefusedError("connection failed")

        self.client.capabilities = disconnected
        await self.daemon.action("toggle")
        await self.until(lambda: not self.daemon.tasks)
        self.assertIn("无法连接 Portal", self.host.notices[0])
        self.assertTrue(self.captures[0].closed)

    async def test_stream_disconnect_stops_recording_before_slow_remote_cleanup(self):
        from openasrinput.adapters.portal import PortalStream

        cleanup, release = asyncio.Event(), asyncio.Event()
        receive = PortalStream.receive

        async def disconnected(stream, **kwargs):
            if stream.ledger.ready:
                raise ConnectionResetError("stream lost")
            return await receive(stream, **kwargs)

        async def cancel_session(_sid):
            cleanup.set()
            await release.wait()

        self.client.cancel_session = cancel_session
        with patch.object(PortalStream, "receive", disconnected):
            await self.daemon.action("toggle")
            try:
                await asyncio.wait_for(cleanup.wait(), 2)
                self.assertTrue(self.captures[0].closed)
                self.assertEqual(self.daemon.core.state, "failed")
                self.assertEqual(len(self.host.notices), 1)
            finally:
                release.set()
                await self.until(lambda: not self.daemon.tasks)

    async def test_blocked_upload_times_out_after_recording_is_stopped(self):
        from openasrinput.adapters.portal import PortalStream

        sending = asyncio.Event()

        async def blocked(_stream, _chunk):
            sending.set()
            await asyncio.Event().wait()

        self.daemon.upload_timeout = 0.05
        with patch.object(PortalStream, "send_pcm", blocked):
            await self.daemon.action("toggle")
            await asyncio.wait_for(sending.wait(), 2)
            await self.daemon.action("pause")
            await self.until(lambda: not self.daemon.tasks)
        self.assertTrue(self.captures[0].closed)
        self.assertEqual(self.daemon.core.state, "failed")
        self.assertEqual(self.host.commits, [])

    async def test_broken_lazy_import_releases_connecting_state_and_allows_retry(self):
        @asynccontextmanager
        async def broken_runtime():
            raise zlib.error("incorrect header check")
            yield  # pragma: no cover

        original_import = __import__

        def broken_import(name, *args, **kwargs):
            if name == "aiohttp":
                raise zlib.error("incorrect header check")
            return original_import(name, *args, **kwargs)

        self.daemon.session_factory = broken_runtime
        with patch("builtins.__import__", side_effect=broken_import):
            await self.daemon.action("toggle")
            task = self.daemon.tasks[self.daemon.core.generation]
            await task
        self.assertEqual(self.daemon.core.state, "failed")
        self.assertIn("incorrect header check", self.host.notices[0])
        self.assertIsNone(self.host._leased)
        self.assertIsNone(self.host.cursor_frame)
        self.assertEqual(self.captures, [])
        self.daemon.session_factory = self.daemon.default_session
        await self.daemon.action("toggle")
        await self.until(lambda: self.daemon.core.state == "listening")

    async def test_local_waveform_is_presented_before_a_blocked_upload(self):
        import struct
        from types import SimpleNamespace

        uploading, release = asyncio.Event(), asyncio.Event()

        class OneChunk(SyntheticCapture):
            async def chunks(self):
                yield struct.pack("<320h", *([16000] * 320))
                await self.stopped.wait()

        async def send_pcm(chunk):
            uploading.set()
            await release.wait()

        self.daemon.core.toggle()
        self.daemon.core.take_effects()
        self.daemon.core.state = "listening"
        running = RunningSession(
            SimpleNamespace(ledger=SimpleNamespace(terminal=False), send_pcm=send_pcm),
            capture=OneChunk(),
        )
        task = asyncio.create_task(self.daemon.pump(self.daemon.core.generation, running))
        sender = asyncio.create_task(self.daemon.upload(self.daemon.core.generation, running))
        try:
            await asyncio.wait_for(uploading.wait(), 1)
            self.assertIn("▆", self.host.cursor_frame.waveform)
            self.assertEqual(self.host.commits, [])
        finally:
            release.set()
            running.stop_requested = True
            await running.capture.stop()
            await task
            # Match production stop_capture: Python 3.10's wait_for may consume
            # cancellation when its child completes in the same event-loop turn.
            running.discard_audio = True
            running.wake.set()
            sender.cancel()
            await asyncio.wait_for(asyncio.gather(sender, return_exceptions=True), 2)

    async def test_buffered_prefix_and_live_tail_are_uploaded_exactly_once_in_order(self):
        self.ready_gate = asyncio.Event()
        live = asyncio.Event()
        chunks = [i.to_bytes(2, "little") * 320 for i in range(30)]

        class SequenceCapture(SyntheticCapture):
            async def chunks(self):
                for chunk in chunks[:20]:
                    yield chunk
                await live.wait()
                for chunk in chunks[20:]:
                    yield chunk
                await self.stopped.wait()

        capture = SequenceCapture()
        self.daemon.capture_factory = lambda: capture
        await self.daemon.action("toggle")
        await self.until(
            lambda: self.daemon.sessions.get(1) and self.daemon.sessions[1].queued_bytes == 12800
        )
        self.assertTrue(capture.started)
        self.assertEqual(self.pcm, [])
        self.ready_gate.set()
        live.set()
        await self.until(lambda: len(self.pcm) == 30)
        await self.daemon.action("pause")
        await self.until(lambda: not self.daemon.tasks)
        self.assertEqual(self.pcm, chunks)
        self.assertTrue(capture.closed)

    async def test_full_audio_buffer_fails_closed_instead_of_dropping_the_prefix(self):
        self.ready_gate = asyncio.Event()
        self.daemon.audio_buffer_limit = 639
        await self.daemon.action("toggle")
        await self.until(lambda: self.daemon.core.state == "failed")
        self.assertIn("缓存", self.daemon.core.error)
        self.assertTrue(self.captures[0].closed)
        self.assertEqual(self.pcm, [])
        self.ready_gate.set()
        await self.until(lambda: not self.daemon.tasks)

    async def test_backend_errors_before_and_after_ready_stop_capture(self):
        for before in (True, False):
            self.fail_before_ready = before
            self.fail_after_audio = not before
            await self.daemon.action("toggle")
            await self.until(lambda: self.daemon.core.state == "failed")
            self.assertIn("upstream", self.daemon.core.error)
            self.assertTrue(self.captures[-1].closed)
            await self.until(lambda: not self.daemon.tasks)
        self.assertEqual(self.host.commits, [])

    def use_editor(self, editor):
        @asynccontextmanager
        async def session():
            yield SessionSettings(self.client, self.daemon.capture_factory, editor=editor)

        self.daemon.session_factory = session

    async def test_command_collects_instruction_without_typing_it_then_replaces_once(self):
        calls = []

        class Editor:
            async def edit(self, text, instruction):
                calls.append((text, instruction))
                return "Hello world."

        self.use_editor(Editor())
        self.host.selected_text = "你好世界。"
        await self.daemon.action("command")
        await self.until(lambda: self.daemon.core.state == "listening")
        self.assertEqual(self.daemon.core.mode, "edit")
        self.assertEqual(self.host.commits, [])
        await self.daemon.action("pause")
        await self.until(lambda: not self.daemon.tasks)
        self.assertEqual(calls, [("你好世界。", "模拟定稿。")])
        self.assertEqual([c[2] for c in self.host.commits], ["Hello world."])
        self.assertEqual(self.daemon.core.state, "paused")

    async def test_command_without_selection_is_normal_dictation(self):
        await self.daemon.action("command")
        await self.until(lambda: self.daemon.core.state == "listening")
        self.assertEqual(self.daemon.core.mode, "dictation")
        await self.daemon.action("pause")
        await self.until(lambda: not self.daemon.tasks)
        self.assertEqual([c[2] for c in self.host.commits], ["模拟定稿。"])

    async def test_changed_selection_and_model_error_never_replace_original(self):
        host = self.host
        for failure in (False, True):

            class Editor:
                async def edit(self, text, instruction):
                    if failure:
                        raise ValueError("model unavailable")
                    host.selected_text = "用户的新选区"
                    return "must not insert"

            self.use_editor(Editor())
            self.host.selected_text = "旧选区"
            await self.daemon.action("command")
            await self.until(lambda: self.daemon.core.state == "listening")
            await self.daemon.action("pause")
            await self.until(lambda: not self.daemon.tasks)
            self.assertEqual(self.daemon.core.state, "failed")
            self.assertEqual(self.host.commits, [])

    async def test_escape_during_model_request_cancels_without_late_replacement(self):
        entered, cancelled = asyncio.Event(), asyncio.Event()

        class Editor:
            async def edit(self, text, instruction):
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()

        self.use_editor(Editor())
        self.host.selected_text = "原文"
        await self.daemon.action("command")
        await self.until(lambda: self.daemon.core.state == "listening")
        await self.daemon.action("pause")
        await asyncio.wait_for(entered.wait(), 2)
        self.assertTrue(self.captures[0].closed)
        await self.daemon.action("cancel")
        await asyncio.wait_for(cancelled.wait(), 2)
        await self.until(lambda: not self.daemon.tasks)
        self.assertEqual(self.host.commits, [])
        self.assertEqual(self.daemon.core.state, "idle")
