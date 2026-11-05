import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from openasrinput.application.controller import Controller
from openasrinput.application.daemon import Daemon
from openasrinput.application.runtime import ConfigRuntime, require_connection
from openasrinput.domain.bridge import MemoryBridge
from openasrinput.domain.ledger import AUDIO
from openasrinput.infrastructure.config import ROOT, ConfigStore


class RuntimeConfigTests(unittest.IsolatedAsyncioTestCase):
    async def test_recognition_diagnostics_count_submissions_without_exposing_text(self):
        self.bridge.focus("diagnostic-editor")
        core = Controller(self.bridge)
        core.toggle()
        core.bind_session(core.generation, "diagnostic-round")
        core.on_event(
            core.generation,
            {
                "type": "session.ready",
                "sessionId": "diagnostic-round",
                "seq": 1,
                "audio": AUDIO,
                "finalizeTimeoutMs": 1000,
            },
        )
        text = "private transcript🙂"
        core.on_event(
            core.generation,
            {
                "type": "transcript.final",
                "sessionId": "diagnostic-round",
                "seq": 2,
                "utteranceId": "utterance",
                "revision": 1,
                "text": text,
            },
        )
        core.drain()
        await self.runtime.tick(SimpleNamespace(core=core))
        status = self.store.status()
        self.assertEqual(status["recognition"]["finalCount"], 1)
        self.assertEqual(status["recognition"]["submissions"]["submitted"], 1)
        self.assertEqual(status["recognition"]["submittedCharacters"], len(text))
        self.assertNotIn(text, str(status))

    async def asyncSetUp(self):
        (ROOT / "test-results").mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(
            prefix="runtime-config-", dir=ROOT / "test-results"
        )
        self.store = ConfigStore(Path(self.directory.name) / "input.json")
        self.store.save(
            {"portal": {"apiKey": "first-key"}, "audio": {"deviceId": "first-device"}}, "defaults"
        )
        self.bridge = MemoryBridge()
        self.clients = []

        class Client:
            def __init__(instance, *args):
                instance.connection = args
                instance.closed = False
                self.clients.append(instance)

            async def __aenter__(instance):
                return instance

            async def __aexit__(instance, *args):
                instance.closed = True

        self.runtime = ConfigRuntime(
            self.store,
            self.bridge,
            portal_factory=Client,
            capture_factory=lambda device: SimpleNamespace(device=device),
        )

    async def asyncTearDown(self):
        self.directory.cleanup()

    async def test_saved_theme_is_live_but_active_connection_and_capture_are_snapshots(self):
        async with self.runtime.session() as original:
            self.assertEqual(
                original.portal.connection, ("http://127.0.0.1:10087", "first-key", "")
            )
            self.store.save(
                {
                    "portal": {"apiKey": "next-key", "profileId": "cloud"},
                    "audio": {"deviceId": "next-device", "gain": 2},
                    "overlay": {"theme": "nord", "colorMode": "dark", "scale": 1.25},
                },
                self.store.read()[1],
            )
            await self.runtime.tick(
                SimpleNamespace(core=SimpleNamespace(state="listening", error=""))
            )
            self.assertEqual(self.bridge.panel_settings["theme"], "nord")
            self.assertEqual(self.bridge.panel_settings["colorMode"], "dark")
            self.assertTrue(self.store.status()["pendingConnection"])
            self.assertEqual(original.capture_factory().device, "first-device")
            self.assertEqual(original.gain, 1)
            self.assertEqual(original.portal.connection[1], "first-key")
        self.assertTrue(self.clients[0].closed)
        async with self.runtime.session() as updated:
            self.assertEqual(updated.portal.connection[1:], ("next-key", "cloud"))
            self.assertEqual(updated.capture_factory().device, "next-device")
            self.assertEqual(updated.gain, 2)

    async def test_invalid_external_edit_keeps_the_last_working_appearance(self):
        await self.runtime.tick(SimpleNamespace(core=SimpleNamespace(state="idle", error="")))
        self.store.path.write_text("broken")
        self.runtime.next_poll = 0
        await self.runtime.tick(SimpleNamespace(core=SimpleNamespace(state="idle", error="")))
        self.assertEqual(self.bridge.panel_settings["theme"], "material")
        self.assertIn("JSON", self.store.status()["error"])

    async def test_overrides_are_explicit_and_never_change_saved_credentials(self):
        self.runtime.overrides = {"portal": {"apiKey": "environment-key"}}
        async with self.runtime.session() as options:
            self.assertEqual(options.portal.connection[1], "environment-key")
        self.assertEqual(self.store.read()[0]["portal"]["apiKey"], "first-key")

    async def test_missing_key_reports_on_hotkey_without_creating_a_portal_client(self):
        self.store.save({"portal": {"clearApiKey": True}}, self.store.read()[1])
        self.bridge.focus("input")
        daemon = Daemon(self.bridge, session_factory=self.runtime.session)
        try:
            await daemon.action("toggle")
            await asyncio.gather(*list(daemon.tasks.values()))
            self.assertEqual(daemon.core.state, "failed")
            self.assertEqual(self.clients, [])
            self.assertIn("尚未配置当前 Portal 接入 Key", self.bridge.notices[0])
            self.assertEqual(self.bridge.commits, [])
        finally:
            await daemon.close()

    async def test_endpoint_override_never_reuses_another_cards_key_or_profile(self):
        original = self.store.path.read_bytes()
        self.runtime.overrides = {"portal": {"url": "http://127.0.0.1:19000"}}
        config, _ = self.runtime.read()
        self.assertEqual(config["portal"]["apiKey"], "")
        with self.assertRaisesRegex(ValueError, "当前 Portal"):
            require_connection(config)
        self.runtime.overrides["portal"]["apiKey"] = "explicit-key"
        async with self.runtime.session() as session:
            self.assertEqual(
                session.portal.connection, ("http://127.0.0.1:19000", "explicit-key", "")
            )
        self.assertEqual(self.store.path.read_bytes(), original)

    async def test_endpoint_override_selects_matching_saved_card_as_a_unit(self):
        self.store.save(
            {
                "portal": {
                    "cards": [
                        {
                            "id": "a",
                            "name": "A",
                            "url": "http://127.0.0.1:10087",
                            "apiKey": "a-key",
                            "profileId": "a",
                        },
                        {
                            "id": "b",
                            "name": "B",
                            "url": "http://127.0.0.1:19000",
                            "apiKey": "b-key",
                            "profileId": "b",
                        },
                    ],
                    "activePortalCardId": "a",
                }
            },
            self.store.read()[1],
        )
        self.runtime.overrides = {"portal": {"url": "http://127.0.0.1:19000/"}}
        async with self.runtime.session() as session:
            self.assertEqual(session.portal.connection, ("http://127.0.0.1:19000", "b-key", "b"))
        self.runtime.overrides["portal"]["profileId"] = "override"
        async with self.runtime.session() as session:
            self.assertEqual(session.portal.connection[1:], ("b-key", "override"))
        self.assertEqual(self.store.read()[0]["portal"]["activePortalCardId"], "a")
