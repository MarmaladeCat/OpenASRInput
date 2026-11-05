import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from calibration_fixture import DEVICE, Capture, Portal, Recognizer, device, tone
from test_portal_client import PortalFixture, web

from openasrinput.adapters.audio import LockedCapture
from openasrinput.adapters.audio_devices import selected_device
from openasrinput.adapters.windows import audio_device_interface, default_audio_device
from openasrinput.application.calibration import Calibration, recognize
from openasrinput.application.runtime import ConfigRuntime
from openasrinput.domain.audio_processing import (
    AudioProcessor,
    measure,
    normalized_text,
    samples,
    score,
)
from openasrinput.domain.bridge import MemoryBridge
from openasrinput.infrastructure.audio_profiles import effective_audio
from openasrinput.infrastructure.config import ROOT, ConfigConflict, ConfigStore


class ProcessingTests(unittest.TestCase):
    def test_causal_filter_is_identical_across_irregular_chunks(self):
        pcm = tone(amplitude=3000, seconds=0.2, frequency=30)
        whole = AudioProcessor(1.7, 70).process(pcm)
        streaming = AudioProcessor(1.7, 70)
        chunks = b"".join(streaming.process(pcm[i : i + 126]) for i in range(0, len(pcm), 126))
        self.assertEqual(whole, chunks)
        self.assertLess(max(samples(whole)[1000:]), 2500)
        self.assertEqual(AudioProcessor().process(pcm), pcm)

    def test_measure_rejects_silence_and_clipping_and_bounds_gain(self):
        self.assertTrue(measure(b"\0" * 32000 * 10)["warnings"])
        clipped = measure(b"\0" * 96000 + b"\xff\x7f" * 16000 * 5)
        self.assertTrue(any("削波" in x for x in clipped["warnings"]))
        clean = measure(b"\0" * 96000 + tone())
        self.assertFalse(clean["warnings"])
        self.assertEqual(clean["suggestedGain"], 3)
        processor = AudioProcessor(3)
        processor.process(tone(20000, 0.1))
        self.assertGreater(processor.clipped, 0)

    def test_character_errors_keep_real_word_and_number_differences(self):
        self.assertEqual(normalized_text("ＡＢＣ，下午。"), "abc下午")
        self.assertEqual(score("今天下午", "今天下午。 ")["errors"], 0)
        self.assertEqual(score("今天下午", "明天上午啊")["errors"], 3)
        self.assertGreater(score("三点", "四点")["errors"], 0)

    def test_noisy_energy_estimate_does_not_reject_a_full_reading(self):
        # Reproduce the reported ~25 s / -33 dBFS floor / 2.46 s loud syllables.
        pcm = tone(1040, 3) + tone(1400, 19.44) + tone(2950, 2.46)
        metrics = measure(pcm)
        self.assertAlmostEqual(metrics["recordingSeconds"], 21.9)
        self.assertLess(metrics["speechSeconds"], 3)
        self.assertTrue(metrics["warnings"])
        self.assertFalse(metrics["errors"])

    def test_noise_estimate_ignores_brief_startup_transient_and_allows_quiet_voice(self):
        normal = measure(tone(9000, 0.4) + tone(20, 2.6) + tone(500, 6))
        self.assertLess(normal["noiseDbfs"], -60)
        self.assertFalse(normal["errors"])
        quiet = measure(tone(1, 3) + tone(50, 6))
        self.assertGreater(quiet["speechSeconds"], 5)
        self.assertFalse(quiet["errors"])
        self.assertEqual(quiet["suggestedGain"], 3)
        self.assertTrue(measure(b"\0" * 32000 * 10)["errors"])


class DeviceTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_is_resolved_each_time_and_monitor_is_rejected(self):
        other = {**DEVICE, "id": "other", "fingerprint": "other-device"}
        monitor = {**DEVICE, "id": "output.monitor", "calibratable": False}
        with (
            patch(
                "openasrinput.adapters.audio_devices.default_device",
                AsyncMock(side_effect=[DEVICE["id"], "other", "output.monitor"]),
            ),
            patch(
                "openasrinput.adapters.audio_devices.devices",
                AsyncMock(return_value={"devices": [DEVICE, other, monitor]}),
            ),
        ):
            self.assertEqual((await selected_device(""))["id"], DEVICE["id"])
            self.assertEqual((await selected_device(""))["id"], "other")
            with self.assertRaisesRegex(ValueError, "监听源"):
                await selected_device("")

    def test_winmm_mapper_and_interface_use_the_documented_messages(self):
        import ctypes

        message = Mock()
        interface = "microphone-interface"

        def reply(identity, code, first, second):
            if code == 0x2015:
                self.assertEqual(identity, 0xFFFFFFFF)
                first._obj.value = 2
            elif code == 0x080D:
                first._obj.value = ctypes.sizeof(ctypes.create_unicode_buffer(interface))
            elif code == 0x080C:
                value = ctypes.create_unicode_buffer(interface)
                ctypes.memmove(first, value, ctypes.sizeof(value))
            else:
                self.fail(f"unexpected WinMM message {code}")
            return 0

        message.side_effect = reply
        with patch("ctypes.WinDLL", create=True) as library:
            library.return_value.waveInMessage = message
            self.assertEqual(default_audio_device(), "2")
            self.assertEqual(audio_device_interface("2"), interface)
        self.assertEqual(
            [call.args[1] for call in message.call_args_list], [0x2015, 0x080D, 0x080C]
        )


class CalibrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        (ROOT / "test-results").mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=ROOT / "test-results")
        self.store = ConfigStore(Path(self.directory.name) / "input.json")
        self.store.save(
            {"audio": {"deviceId": DEVICE["id"]}, "portal": {"apiKey": "test-secret"}}, "defaults"
        )
        self.recognizer = Recognizer()
        self.captures = []

        def capture(identity):
            value = Capture(identity)
            self.captures.append(value)
            return value

        self.manager = Calibration(
            self.store,
            capture_factory=capture,
            device_resolver=device,
            portal_factory=Portal,
            recognizer=self.recognizer,
        )

    async def asyncTearDown(self):
        await self.manager.close()
        self.directory.cleanup()

    async def record(self, validation=False):
        if validation:
            self.recognizer.validation = True
            await self.manager.action(self.manager.job["id"], "validate")
        else:
            await self.manager.start(self.store.read()[1])

        async def wait():
            while self.manager.job.get("seconds", 0) < 9 or not self.manager.job["state"].endswith(
                "recording"
            ):
                if self.manager.job["state"] == "failed":
                    self.fail(self.manager.job["message"])
                await asyncio.sleep(0.001)

        # Synthetic audio processing is CPU-bound under cross-architecture QEMU.
        await asyncio.wait_for(wait(), 15)
        await self.manager.action(self.manager.job["id"], "stop")
        await asyncio.wait_for(self.manager.task, 15)

    async def verified(self):
        await self.record()
        self.assertEqual(self.manager.job["state"], "await-validation", self.manager.job)
        await self.record(True)
        self.assertEqual(self.manager.job["state"], "complete", self.manager.job)

    async def test_record_compare_repeat_validate_save_and_runtime_binding(self):
        await self.verified()
        self.assertEqual(len(self.recognizer.calls), 6)
        await self.manager.action(self.manager.job["id"], "apply")
        config = self.store.read()[0]
        self.assertEqual(config["audio"]["gain"], 1)
        self.assertEqual(config["audio"]["calibrations"][0]["gain"], 3)
        for field, bad in (("gain", float("nan")), ("gain", True), ("highpassHz", 1000)):
            invalid = dict(config["audio"]["calibrations"][0])
            invalid[field] = bad
            with self.assertRaises(ValueError):
                self.store.patched({"audio": {"calibrations": [invalid]}})
        with patch("openasrinput.infrastructure.audio_profiles.selected_device", device):
            options, message = await effective_audio(
                config["audio"], config["portal"], Portal("", "", "")
            )
            self.assertEqual(options["gain"], 3)
            self.assertIn("已应用", message)
            config["audio"]["gain"] = 1.2
            options, message = await effective_audio(
                config["audio"], config["portal"], Portal("", "", "")
            )
            self.assertEqual(options["gain"], 1.2)
            self.assertIn("重新校准", message)
        self.assertTrue(all(x.stopped.is_set() for x in self.captures))
        self.assertEqual(self.manager.audio, b"")

    async def test_equal_recognition_still_calibrates_gain_after_independent_validation(self):
        self.recognizer.equal = True
        await self.verified()
        self.assertTrue(self.manager.level_adjustment)
        await self.manager.action(self.manager.job["id"], "apply")
        self.assertEqual(self.store.read()[0]["audio"]["calibrations"][0]["gain"], 3)

    async def test_equal_results_with_good_existing_gain_keep_original(self):
        self.recognizer.equal = True
        self.store.save({"audio": {"gain": 3}}, self.store.read()[1])
        before = self.store.path.read_bytes()
        await self.record()
        self.assertEqual(self.manager.job["state"], "unchanged")
        self.assertEqual(self.store.path.read_bytes(), before)

    async def test_default_device_calibrates_and_applies_without_changing_selection(self):
        self.store.save({"audio": {"deviceId": ""}}, self.store.read()[1])
        await self.verified()
        await self.manager.action(self.manager.job["id"], "apply")
        config = self.store.read()[0]
        self.assertEqual(config["audio"]["deviceId"], "")
        self.assertEqual(config["audio"]["gain"], 1)
        self.assertEqual(config["audio"]["calibrations"][0]["deviceId"], DEVICE["id"])
        with patch("openasrinput.infrastructure.audio_profiles.selected_device", device):
            options, _ = await effective_audio(
                config["audio"], config["portal"], Portal("", "", "")
            )
            self.assertEqual(options["gain"], 3)
        with patch(
            "openasrinput.infrastructure.audio_profiles.selected_device",
            AsyncMock(return_value={**DEVICE, "id": "other", "fingerprint": "other"}),
        ):
            options, _ = await effective_audio(
                config["audio"], config["portal"], Portal("", "", "")
            )
            self.assertEqual(options["gain"], 1)

    async def test_live_default_capture_is_pinned_to_profile_device(self):
        self.store.save({"audio": {"deviceId": ""}}, self.store.read()[1])
        await self.verified()
        await self.manager.action(self.manager.job["id"], "apply")
        capture = Mock()
        runtime = ConfigRuntime(
            self.store, MemoryBridge(), portal_factory=Portal, capture_factory=capture
        )
        with (
            patch(
                "openasrinput.application.runtime.selected_device", AsyncMock(return_value=DEVICE)
            ),
            patch("openasrinput.infrastructure.audio_profiles.selected_device", device),
        ):
            async with runtime.session() as settings:
                settings.capture_factory()
                capture.assert_called_once_with(DEVICE["id"])
                options = await settings.prepare_audio(settings.portal)
                self.assertEqual(options["gain"], 3)

    async def test_noisy_recording_reaches_recognition_instead_of_energy_gate(self):
        class NoisyCapture(Capture):
            async def chunks(self):
                pcm = tone(1040, 3) + tone(1400, 19.44) + tone(2950, 2.46)
                yield pcm
                await self.stopped.wait()

        self.manager.capture_factory = NoisyCapture
        self.recognizer.equal = True
        await self.record()
        self.assertTrue(self.recognizer.calls)
        self.assertNotEqual(self.manager.job["state"], "failed")
        self.assertTrue(self.manager.job["metrics"]["warnings"])

    async def test_default_switch_during_recording_rejects_before_cloud_upload(self):
        self.store.save({"audio": {"deviceId": ""}}, self.store.read()[1])
        calls = 0

        async def changing(identity):
            nonlocal calls
            self.assertEqual(identity, "")
            calls += 1
            return DEVICE if calls < 3 else {**DEVICE, "id": "other", "fingerprint": "other"}

        self.manager.device_resolver = changing
        await self.record()
        self.assertEqual(self.manager.job["state"], "failed")
        self.assertIn("录音期间", self.manager.job["message"])
        self.assertFalse(self.recognizer.calls)

    async def test_independent_regression_rejects_winner(self):
        await self.record()
        self.recognizer.regress = True
        await self.record(True)
        self.assertEqual(self.manager.job["state"], "unchanged")
        with self.assertRaises(ValueError):
            await self.manager.action(self.manager.job["id"], "apply")
        self.assertEqual(self.store.read()[0]["audio"]["calibrations"], [])

    async def test_stale_config_and_stale_job_cannot_apply(self):
        await self.verified()
        self.store.save({"audio": {"gain": 1.5}}, self.store.read()[1])
        with self.assertRaises(ConfigConflict):
            await self.manager.action(self.manager.job["id"], "apply")
        with self.assertRaises(ValueError):
            await self.manager.action("other-tab-job", "cancel")

    async def test_device_change_rejects_saved_result(self):
        await self.verified()

        async def changed(identity):
            return {**DEVICE, "fingerprint": "new-device"}

        self.manager.device_resolver = changed
        with self.assertRaisesRegex(ValueError, "麦克风"):
            await self.manager.action(self.manager.job["id"], "apply")

    async def test_changed_default_and_auto_learning_are_detected(self):
        await self.record()
        with patch.object(Portal, "default", "other"):
            await self.manager.action(self.manager.job["id"], "validate")
            await self.manager.task
        self.assertEqual(self.manager.job["state"], "failed")
        with patch.object(Portal, "auto_learn", True):
            await self.manager.start(self.store.read()[1])
            await self.manager.task
        self.assertIn("词频", self.manager.job["message"])
        self.assertEqual(len(self.captures), 1)

    async def test_cancel_releases_live_capture_without_cloud_upload(self):
        await self.manager.start(self.store.read()[1])
        while not self.captures or not self.captures[0].started:
            await asyncio.sleep(0)
        await self.manager.action(self.manager.job["id"], "cancel")
        self.assertTrue(self.captures[0].stopped.is_set())
        self.assertEqual(self.manager.job["state"], "cancelled")
        self.assertFalse(self.recognizer.calls)

    async def test_cloud_failure_does_not_save_or_leak_key(self):
        async def fail(client, pcm):
            raise ValueError("bad test-secret")

        self.manager.recognizer = fail
        await self.record()
        self.assertEqual(self.manager.job["state"], "failed")
        self.assertNotIn("test-secret", str(self.manager.view()))
        self.assertEqual(self.store.read()[0]["audio"]["calibrations"], [])

    async def test_cross_instance_microphone_lock_and_release(self):
        path = Path(self.directory.name) / "microphone.lock"
        first, second = LockedCapture(Capture(), path), LockedCapture(Capture(), path)
        await first.start()
        try:
            with self.assertRaisesRegex(RuntimeError, "正在被"):
                await second.start()
            self.assertFalse(second.capture.started)
        finally:
            await first.stop()
        await second.start()
        await second.stop()


@unittest.skipIf(web is None, "optional Portal dependency is unavailable")
class ReplayTests(PortalFixture, unittest.IsolatedAsyncioTestCase):
    async def test_replay_uses_revisions_and_real_time_frames(self):
        self.end_mode = "stale-revision"
        pcm = tone(seconds=0.22)
        started = time.monotonic()
        text = await recognize(self.client, pcm)
        self.assertGreaterEqual(time.monotonic() - started, 0.22)
        self.assertEqual(text, "模拟定稿。")
        self.assertEqual(self.pcm, [pcm[:6400], pcm[6400:]])

    async def test_server_error_cancels_sender_and_cleans_session(self):
        self.fail_after_audio = True
        with self.assertRaisesRegex(ValueError, "upstream failed"):
            await asyncio.wait_for(recognize(self.client, tone(seconds=2)), 1)

    async def test_pending_receiver_obeys_finalization_timeout(self):
        self.end_mode = "stall"
        self.timeout_ms = 30
        started = time.monotonic()
        with self.assertRaises(asyncio.TimeoutError):
            await recognize(self.client, tone(seconds=0.02))
        self.assertLess(time.monotonic() - started, 0.5)

    async def test_cancel_during_session_creation_cleans_remote_descriptor(self):
        original = self.client.create_session
        created, release = asyncio.Event(), asyncio.Event()

        async def creating():
            descriptor = await original()
            created.set()
            await release.wait()
            return descriptor

        with patch.object(self.client, "create_session", creating):
            task = asyncio.create_task(recognize(self.client, tone(seconds=0.02)))
            await created.wait()
            task.cancel()
            await asyncio.sleep(0)
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(self.cancelled, ["s1"])
        self.assertEqual(self.pcm, [])
