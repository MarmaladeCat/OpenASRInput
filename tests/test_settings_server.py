import asyncio
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from openasrinput.infrastructure.config import ROOT, ConfigStore

try:
    from aiohttp import ClientSession, web
    from aiohttp.test_utils import TestServer

    from openasrinput.presentation.settings_server import SettingsServer, serve
except ImportError:
    web = None


@unittest.skipIf(web is None, "optional settings dependency is not installed")
class SettingsServerTests(unittest.IsolatedAsyncioTestCase):
    async def test_occupied_port_fails_without_fallback_or_ready_record(self):
        ready = Path(self.directory.name) / "ready.json"
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            reservation.listen()
            with self.assertRaises(OSError):
                await serve(
                    self.store,
                    port=reservation.getsockname()[1],
                    open_window=False,
                    ready_file=ready,
                )
        self.assertFalse(ready.exists())

    async def asyncSetUp(self):
        (ROOT / "test-results").mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(prefix="settings-", dir=ROOT / "test-results")
        self.store = ConfigStore(Path(self.directory.name) / "input.json")
        self.settings = SettingsServer(self.store)
        self.server = TestServer(self.settings.app())
        await self.server.start_server()
        self.settings.origin = str(self.server.make_url("/")).rstrip("/")
        self.client = ClientSession(headers={"Authorization": "Bearer " + self.settings.token})

    async def asyncTearDown(self):
        await self.client.close()
        await self.server.close()
        self.directory.cleanup()

    async def test_config_requires_local_session_and_rejects_foreign_origin(self):
        async with self.client.get(
            self.server.make_url("/api/config"), headers={"Authorization": "Bearer wrong"}
        ) as response:
            self.assertEqual(response.status, 401)
        async with self.client.patch(
            self.server.make_url("/api/config"),
            headers={"Origin": "https://other.invalid"},
            json={},
        ) as response:
            self.assertEqual(response.status, 403)
        self.assertFalse(self.store.path.exists())

    async def test_save_reload_and_redaction(self):
        async with self.client.patch(
            self.server.make_url("/api/config"),
            json={
                "revision": "defaults",
                "patch": {
                    "portal": {"apiKey": "hidden-key"},
                    "overlay": {"theme": "rose-pine", "colorMode": "dark"},
                },
            },
        ) as response:
            self.assertEqual(response.status, 200)
            body = await response.json()
        self.assertNotIn("hidden-key", json.dumps(body))
        self.assertTrue(body["config"]["portal"]["hasApiKey"])
        async with self.client.patch(
            self.server.make_url("/api/config"), json={"revision": "defaults", "patch": {}}
        ) as response:
            self.assertEqual(response.status, 409)

    async def test_calibration_status_is_read_only_and_commands_require_settings_auth(self):
        async with self.client.get(self.server.make_url("/api/audio/calibration")) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.json())["state"], "idle")
        for action in ("start", "stop", "validate", "cancel", "apply", "reset"):
            async with self.client.post(
                self.server.make_url("/api/audio/calibration/" + action),
                headers={"Authorization": "Bearer wrong"},
                json={},
            ) as response:
                self.assertEqual(response.status, 401)
        async with self.client.post(
            self.server.make_url("/api/audio/calibration/start"),
            json={"revision": "defaults"},
        ) as response:
            self.assertEqual(response.status, 400)
        self.assertFalse(self.store.path.exists())
        self.assertIsNone(self.settings.calibration.task)

    async def test_portal_opens_last_after_the_requested_input_tab_navigates(self):
        opened = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def browser(url, **options):
            loop.call_soon_threadsafe(opened.put_nowait, (url, options))
            return True

        portal = "http://127.0.0.1:12345/admin"
        with patch("openasrinput.presentation.settings_server.webbrowser.open", browser):
            task = asyncio.create_task(self.settings.open_settings(portal, timeout=5))
            try:
                input_url, _ = await asyncio.wait_for(opened.get(), 2)
                self.assertEqual(urlsplit(input_url).fragment, "token=" + self.settings.token)
                # Other tabs and health/config probes cannot release this launch.
                for path in ("/", "/?launch=wrong", "/api/config"):
                    async with self.client.get(self.server.make_url(path)) as response:
                        await response.read()
                self.assertTrue(opened.empty())
                async with self.client.get(input_url.split("#")[0]) as response:
                    self.assertEqual(response.status, 200)
                    await response.read()
                await asyncio.wait_for(task, 2)
                self.assertEqual(await opened.get(), (portal, {"new": 2, "autoraise": True}))
                self.assertEqual(self.settings.browser_loads, {})
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def test_existing_instance_browser_launch_requires_session_and_http_url(self):
        with patch.object(self.settings, "open_settings") as open_settings:
            async with self.client.post(
                self.server.make_url("/api/settings/open"),
                headers={"Authorization": "Bearer wrong"},
                json={"portalUrl": "http://127.0.0.1:10087/admin"},
            ) as response:
                self.assertEqual(response.status, 401)
            for url in ("file:///C:/Windows/notepad.exe", "javascript:alert(1)"):
                async with self.client.post(
                    self.server.make_url("/api/settings/open"), json={"portalUrl": url}
                ) as response:
                    self.assertEqual(response.status, 400)
            open_settings.assert_not_called()
            async with self.client.post(
                self.server.make_url("/api/settings/open"),
                json={"portalUrl": "http://127.0.0.1:10087/admin"},
            ) as response:
                self.assertEqual(response.status, 200)
            await asyncio.gather(*self.settings.browser_tasks)
            open_settings.assert_awaited_once_with("http://127.0.0.1:10087/admin")

    async def test_unsaved_portal_test_reads_public_contract_without_starting_recognition(self):
        calls = []

        async def provider(request):
            calls.append(request.path)
            self.assertEqual(request.headers["Authorization"], "Bearer test-key")
            if request.path == "/v1/capabilities":
                return web.json_response(
                    {
                        "protocolVersion": 1,
                        "audio": {"encoding": "pcm_s16le", "sampleRate": 16000, "channels": 1},
                    }
                )
            return web.json_response(
                {
                    "profiles": [
                        {
                            "id": "local",
                            "title": "本地",
                            "provider": "openlocalasr",
                            "configuration": {"apiKey": "never-forward"},
                            "capabilities": {"latencyClass": "streaming"},
                        }
                    ]
                }
            )

        app = web.Application()
        app.router.add_get("/v1/{resource}", provider)
        async with TestServer(app) as remote:
            async with self.client.post(
                self.server.make_url("/api/portal/test"),
                json={
                    "portal": {
                        "url": str(remote.make_url("/")).rstrip("/"),
                        "apiKey": "test-key",
                        "profileId": "local",
                    }
                },
            ) as response:
                self.assertEqual(response.status, 200)
                body = await response.json()
        self.assertEqual(body["profiles"][0]["title"], "本地")
        self.assertNotIn("never-forward", json.dumps(body))
        self.assertEqual(calls, ["/v1/capabilities", "/v1/profiles"])
        self.assertFalse(self.store.path.exists())

    async def test_web_assets_and_theme_contract(self):
        for path in ("/", "/settings.css", "/settings.mjs", "/settings-session.mjs", "/personal-hotwords.mjs"):
            async with self.client.get(self.server.make_url(path)) as response:
                self.assertEqual(response.status, 200)
        async with self.client.get(self.server.make_url("/api/themes")) as response:
            value = await response.json()
            self.assertEqual(
                [item["id"] for item in value["themes"]],
                ["github", "material", "nord", "rose-pine"],
            )

    async def test_hotwords_use_saved_credentials_and_reject_connection_changes(self):
        calls = []

        async def provider(request):
            self.assertEqual(request.headers["Authorization"], "Bearer personal-key")
            if request.path == "/v1/capabilities":
                return web.json_response(
                    {
                        "protocolVersion": 1,
                        "audio": {"encoding": "pcm_s16le", "sampleRate": 16000, "channels": 1},
                        "hotwords": {"version": 1},
                    }
                )
            calls.append(
                (
                    request.method,
                    request.path,
                    request.query.get("profileId"),
                    await request.json() if request.can_read_body else None,
                )
            )
            return web.json_response(
                {
                    "version": 1,
                    "revision": 1,
                    "settings": {"autoLearn": True},
                    "learnedTerms": [],
                    "terms": [],
                }
            )

        app = web.Application()
        app.router.add_route("*", "/v1/{path:.*}", provider)
        async with TestServer(app) as remote:
            saved = self.store.save(
                {
                    "portal": {
                        "url": str(remote.make_url("/")).rstrip("/"),
                        "apiKey": "personal-key",
                        "profileId": "doubao",
                    }
                },
                "defaults",
            )
            async with self.client.get(self.server.make_url("/api/portal/hotwords")) as response:
                self.assertEqual(response.status, 200)
                listing = await response.json()
            self.assertEqual(listing["configRevision"], saved["revision"])
            self.assertNotIn("personal-key", json.dumps(listing))
            async with self.client.patch(
                self.server.make_url("/api/portal/hotwords"),
                json={
                    "configRevision": "old",
                    "revision": 1,
                    "settings": {"autoLearn": False},
                },
            ) as response:
                self.assertEqual(response.status, 409)
            self.assertEqual(len(calls), 1)
            async with self.client.patch(
                self.server.make_url("/api/portal/hotwords"),
                json={
                    "configRevision": saved["revision"],
                    "revision": 1,
                    "settings": {"autoLearn": False},
                },
            ) as response:
                self.assertEqual(response.status, 200)
            self.assertEqual(
                calls[-1],
                (
                    "PATCH",
                    "/v1/hotwords",
                    "doubao",
                    {"revision": 1, "settings": {"autoLearn": False}},
                ),
            )
            async with self.client.delete(
                self.server.make_url("/api/portal/hotwords"),
                json={
                    "configRevision": saved["revision"],
                },
            ) as response:
                self.assertEqual(response.status, 200)
            self.assertEqual(calls[-2][:2], ("DELETE", "/v1/hotwords/statistics"))
            self.assertEqual(self.store.read()[1], saved["revision"])

    async def test_hotwords_explain_unsupported_portal_and_require_saved_connection(self):
        async with self.client.get(self.server.make_url("/api/portal/hotwords")) as response:
            self.assertEqual(response.status, 400)

        async def old_portal(request):
            return web.json_response(
                {
                    "protocolVersion": 1,
                    "audio": {"encoding": "pcm_s16le", "sampleRate": 16000, "channels": 1},
                }
            )

        app = web.Application()
        app.router.add_get("/v1/capabilities", old_portal)
        async with TestServer(app) as remote:
            self.store.save(
                {"portal": {"url": str(remote.make_url("/")).rstrip("/"), "apiKey": "test-key"}},
                "defaults",
            )
            async with self.client.get(self.server.make_url("/api/portal/hotwords")) as response:
                self.assertEqual(response.status, 400)
                self.assertIn("升级 Portal", (await response.json())["error"])

    async def test_saved_recommendation_words_are_fetched_with_saved_key_and_profile(self):
        calls = []

        async def provider(request):
            self.assertEqual(request.headers["Authorization"], "Bearer personal-key")
            if request.path == "/v1/capabilities":
                return web.json_response(
                    {
                        "protocolVersion": 1,
                        "audio": {"encoding": "pcm_s16le", "sampleRate": 16000, "channels": 1},
                        "hotwords": {"version": 1, "dictionaries": True},
                    }
                )
            calls.append((request.method, request.path, request.query.get("profileId")))
            return web.json_response({"words": [{"text": "Python", "weight": 4}]})

        app = web.Application()
        app.router.add_get("/v1/{path:.*}", provider)
        async with TestServer(app) as remote:
            saved = self.store.save(
                {
                    "portal": {
                        "url": str(remote.make_url("/")).rstrip("/"),
                        "apiKey": "personal-key",
                        "profileId": "bailian",
                    }
                },
                "defaults",
            )
            async with self.client.get(
                self.server.make_url("/api/portal/hotwords/dictionaries/snapshot-id")
            ) as response:
                self.assertEqual(response.status, 200)
                body = await response.json()
            self.assertEqual(body["words"][0]["text"], "Python")
            self.assertEqual(body["configRevision"], saved["revision"])
            self.assertEqual(calls, [("GET", "/v1/hotwords/dictionaries/snapshot-id", "bailian")])

    async def new_page(self):
        async with self.client.post(self.server.make_url("/api/settings/session")) as response:
            self.assertEqual(response.status, 200)
            return await response.json()

    async def test_page_expires_after_twenty_minutes_without_renewing_on_reload(self):
        now = 1000
        self.settings.clock = lambda: now
        page = await self.new_page()
        self.assertEqual(page["settingsSession"], {"timeoutMinutes": 20, "expiresAt": 2200000})
        self.assertNotEqual(page["token"], self.settings.token)
        headers = {"Authorization": "Bearer " + page["token"]}
        now = 2199
        for path in ("settings/session", "config", "status"):
            async with self.client.get(self.server.make_url("/api/" + path), headers=headers) as response:
                self.assertEqual(response.status, 200)
                if path == "settings/session":
                    self.assertEqual((await response.json())["settingsSession"], page["settingsSession"])
        now = 2200
        for method, path, body in (
            ("GET", "config", None),
            ("GET", "settings/session", None),
            ("PATCH", "config", {"revision": "defaults", "patch": {"audio": {"gain": 2}}}),
            ("POST", "settings/session", None),
        ):
            async with self.client.request(
                method, self.server.make_url("/api/" + path), headers=headers, json=body
            ) as response:
                self.assertEqual(response.status, 401)
        self.assertFalse(self.store.path.exists())
        fresh = await self.new_page()
        self.assertNotEqual(fresh["token"], page["token"])
        self.assertEqual(fresh["settingsSession"]["expiresAt"], 3400000)

    async def test_duration_changes_zero_and_independent_pages(self):
        now = 1000
        self.settings.clock = lambda: now
        page, other = await self.new_page(), await self.new_page()
        headers = {"Authorization": "Bearer " + page["token"]}
        revision = "defaults"

        async def save(patch_body):
            nonlocal revision
            async with self.client.patch(
                self.server.make_url("/api/config"), headers=headers,
                json={"revision": revision, "patch": patch_body},
            ) as response:
                self.assertEqual(response.status, 200)
                result = await response.json()
                revision = result["revision"]
                return result["settingsSession"]

        self.assertEqual((await save({"settings": {"timeoutMinutes": 0}}))["expiresAt"], None)
        now = 1000000
        async with self.client.get(self.server.make_url("/api/config"), headers=headers) as response:
            self.assertEqual(response.status, 200)
        self.assertEqual((await self.new_page())["settingsSession"]["expiresAt"], None)
        other_headers = {"Authorization": "Bearer " + other["token"]}
        async with self.client.get(self.server.make_url("/api/config"), headers=other_headers) as response:
            self.assertEqual(response.status, 401)
        changed = await save({"settings": {"timeoutMinutes": 5}})
        self.assertEqual(changed["expiresAt"], (now + 300) * 1000)
        now += 60
        self.assertEqual(await save({"settings": {"timeoutMinutes": 5, "theme": "nord"}}), changed)
        for path in ("settings/session", "settings/open"):
            async with self.client.post(self.server.make_url("/api/" + path), headers=headers, json={}) as response:
                self.assertEqual(response.status, 403)

    async def test_invalid_duration_never_changes_saved_configuration(self):
        for minutes in (-1, 1.5, True, "20", None, 525601):
            async with self.client.patch(
                self.server.make_url("/api/config"),
                json={"revision": "defaults", "patch": {"settings": {"timeoutMinutes": minutes}}},
            ) as response:
                self.assertEqual(response.status, 400)
        self.assertFalse(self.store.path.exists())

    async def test_expiry_does_not_cancel_another_pages_calibration(self):
        now = 1000
        self.settings.clock = lambda: now
        await self.new_page()
        now = 1100
        other = await self.new_page()
        self.settings.calibration_owner = other["token"]
        with patch.object(self.settings.calibration, "close") as close:
            now = 2200
            await self.settings.prune_sessions()
            close.assert_not_called()

    async def test_expiry_cancels_the_owning_pages_calibration(self):
        now = 1000
        self.settings.clock = lambda: now
        page = await self.new_page()
        self.settings.calibration_owner = page["token"]
        self.settings.calibration.job = {"state": "await-validation", "canApply": True}
        with patch.object(self.settings.calibration, "close") as close:
            now = 2199
            await self.settings.prune_sessions()
            close.assert_not_called()
            now = 2200
            await self.settings.prune_sessions()
            close.assert_awaited_once()
            self.assertEqual(self.settings.calibration.job["state"], "cancelled")
            self.assertFalse(self.settings.calibration.job["canApply"])

    async def test_expiry_while_reading_request_body_prevents_save(self):
        now = 1000
        self.settings.clock = lambda: now
        page = await self.new_page()
        original = web.Request.read

        async def delayed_read(request):
            nonlocal now
            body = await original(request)
            now = 2200
            return body

        with patch.object(web.Request, "read", delayed_read):
            async with self.client.patch(
                self.server.make_url("/api/config"),
                headers={"Authorization": "Bearer " + page["token"]},
                json={"revision": "defaults", "patch": {"settings": {"timeoutMinutes": 0}}},
            ) as response:
                self.assertEqual(response.status, 401)
        self.assertFalse(self.store.path.exists())

    async def test_calibration_start_crossing_expiry_is_cancelled(self):
        now = 1000
        self.settings.clock = lambda: now
        page = await self.new_page()

        async def start(revision):
            nonlocal now
            now = 2200
            await self.settings.prune_sessions()
            self.settings.calibration.job = {"state": "preparing", "canApply": False}
            return self.settings.calibration.job.copy()

        with (
            patch.object(self.settings.calibration, "start", side_effect=start),
            patch.object(self.settings.calibration, "close") as close,
        ):
            async with self.client.post(
                self.server.make_url("/api/audio/calibration/start"),
                headers={"Authorization": "Bearer " + page["token"]},
                json={"revision": "defaults"},
            ) as response:
                self.assertEqual(response.status, 401)
            close.assert_awaited_once()
        self.assertEqual(self.settings.calibration.job["state"], "cancelled")
