"""Independent loopback settings UI; no Notes/Drafts implementation imports."""

import asyncio
import json
import logging
import secrets
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import ClientError, web

from .. import __version__
from ..adapters.audio_devices import devices as audio_devices
from ..adapters.portal import PortalClient, PortalRequestError
from ..adapters.text_edit import TextEditor
from ..application.calibration import ACTIVE, Calibration
from ..infrastructure.config import ConfigConflict, ConfigStore, atomic_json
from ..infrastructure.model_cards import merge_cards, require_complete
from ..infrastructure.portal_cards import merge_cards as merge_portal_cards
from ..infrastructure.portal_cards import validate_card as validate_portal_card
from .themes import public_themes

ASSETS = Path(__file__).with_name("web")
BRANDING = Path(__file__).with_name("branding")


class SettingsServer:
    def __init__(self, store=None):
        self.store = store or ConfigStore()
        self.token = secrets.token_urlsafe(32)
        self.origin = ""
        self.browser_loads = {}
        self.browser_tasks = set()
        self.calibration = Calibration(self.store)

    async def open_settings(self, portal_url="", timeout=20):
        # A fresh navigation nonce distinguishes this browser tab from health
        # probes and other settings windows. Open Portal only after Input loads.
        nonce = secrets.token_urlsafe(16)
        loaded = asyncio.Event()
        self.browser_loads[nonce] = loaded
        url = self.origin + "/?launch=" + nonce + "#token=" + self.token
        try:
            await asyncio.to_thread(webbrowser.open, url, new=2)
            if portal_url:
                try:
                    await asyncio.wait_for(loaded.wait(), timeout)
                except asyncio.TimeoutError:
                    logging.warning("Input settings browser did not load before Portal launch")
                await asyncio.to_thread(webbrowser.open, portal_url, new=2, autoraise=True)
        finally:
            self.browser_loads.pop(nonce, None)

    def queue_open(self, portal_url=""):
        if portal_url:
            parsed = urlsplit(portal_url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username:
                raise ValueError("Portal 设置地址必须为 HTTP/HTTPS 网页")
        task = asyncio.create_task(self.open_settings(portal_url))
        self.browser_tasks.add(task)
        task.add_done_callback(self.browser_tasks.discard)

    async def close_browsers(self, app):
        await self.calibration.close()
        tasks = list(self.browser_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def open_browser(self, request):
        body = await request.json()
        self.queue_open(body.get("portalUrl", ""))
        return web.json_response({"ok": True})

    @web.middleware
    async def boundary(self, request, handler):
        try:
            if request.path.startswith("/api/"):
                expected = "Bearer " + self.token
                if not secrets.compare_digest(request.headers.get("Authorization", ""), expected):
                    raise web.HTTPUnauthorized(text="设置会话已失效，请重新打开设置")
                if request.headers.get("Origin") not in (None, self.origin):
                    raise web.HTTPForbidden(text="设置请求来源无效")
            response = await handler(request)
        except ConfigConflict as error:
            response = web.json_response({"error": str(error)}, status=409)
        except (ValueError, KeyError, TypeError) as error:
            response = web.json_response({"error": str(error)}, status=400)
        except PortalRequestError as error:
            response = web.json_response({"error": str(error), "code": error.code}, status=502)
        except (OSError, asyncio.TimeoutError, ClientError) as error:
            response = web.json_response({"error": "连接或配置操作失败：" + str(error)}, status=502)
        except web.HTTPException as error:
            response = web.json_response({"error": error.text}, status=error.status)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        )
        return response

    def app(self):
        app = web.Application(middlewares=[self.boundary], client_max_size=8 * 1024 * 1024)
        app.router.add_get("/", self.asset)
        app.router.add_get("/branding/logo.svg", self.logo)
        app.router.add_get("/{name:settings\\.(?:css|mjs)}", self.asset)
        app.router.add_get("/{name:personal-hotwords\\.mjs}", self.asset)
        app.router.add_get("/{name:model-cards\\.mjs}", self.asset)
        app.router.add_get("/{name:portal-cards\\.mjs}", self.asset)
        app.router.add_get("/{name:audio-calibration\\.mjs}", self.asset)
        app.router.add_get("/api/config", self.config)
        app.router.add_get("/api/health", self.health)
        app.router.add_post("/api/settings/open", self.open_browser)
        app.on_cleanup.append(self.close_browsers)
        app.router.add_patch("/api/config", self.save)
        app.router.add_get("/api/themes", self.themes)
        app.router.add_get("/api/status", self.status)
        app.router.add_post("/api/portal/test", self.test_portal)
        app.router.add_post("/api/text-model/{action:test|models}", self.text_model)
        for method in ("GET", "PATCH", "DELETE"):
            app.router.add_route(method, "/api/portal/hotwords", self.hotwords)
        app.router.add_get("/api/portal/hotwords/catalog", self.hotwords)
        app.router.add_post("/api/portal/hotwords/dictionaries", self.hotwords)
        app.router.add_get("/api/portal/hotwords/dictionaries/{dictionary_id}", self.hotwords)
        for method in ("PATCH", "DELETE"):
            app.router.add_route(
                method, "/api/portal/hotwords/dictionaries/{dictionary_id}", self.hotwords
            )
        app.router.add_post("/api/audio/devices", self.devices)
        app.router.add_get("/api/audio/calibration", self.calibration_status)
        app.router.add_post("/api/audio/calibration/{action}", self.calibration_action)
        return app

    async def asset(self, request):
        if request.path == "/":
            loaded = self.browser_loads.get(request.query.get("launch", ""))
            if loaded is not None:
                loaded.set()
        return web.FileResponse(ASSETS / request.match_info.get("name", "index.html"))

    async def logo(self, request):
        return web.FileResponse(BRANDING / "logo.svg")

    async def config(self, request):
        return web.json_response(self.store.public())

    async def health(self, request):
        return web.json_response(
            {
                "service": "OpenASRInput.Settings",
                "version": __version__,
                "apiVersion": 1,
                "features": [
                    "personal-hotwords",
                    "dictionary-import",
                    "portal-cards",
                    "audio-calibration",
                ],
            }
        )

    async def save(self, request):
        body = await request.json()
        return web.json_response(self.store.save(body["patch"], body["revision"]))

    async def themes(self, request):
        return web.json_response({"themes": public_themes()})

    async def status(self, request):
        return web.json_response(self.store.status())

    async def test_portal(self, request):
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("Portal 测试请求必须是 JSON 对象")
        if "card" in body:
            config, revision = self.store.read()
            if body.get("revision") != revision:
                raise ConfigConflict("Portal 卡已更新，请重新载入后测试")
            portal = merge_portal_cards([body["card"]], config["portal"]["cards"])[0]
            validate_portal_card(portal, complete=True)
        else:
            portal = self.store.patched({"portal": body.get("portal", {})})["portal"]
        if not portal["apiKey"]:
            raise ValueError("请填写 Portal 接入 Key")
        started = time.monotonic()
        try:
            async with PortalClient(portal["url"], portal["apiKey"], portal["profileId"]) as client:
                capabilities = await client.capabilities()
                listing = await client.profiles()
        except (
            ValueError,
            OSError,
            asyncio.TimeoutError,
            ClientError,
            PortalRequestError,
        ) as error:
            if "card" not in body:
                raise
            message = (str(error) or "连接超时或请求失败").replace(portal["apiKey"], "[redacted]")
            result = {
                "ok": False,
                "error": message[:500],
                "elapsedMs": round((time.monotonic() - started) * 1000),
            }
            self.store.record_portal_result(portal, result)
            return web.json_response(result)
        profiles = []
        for profile in listing.get("profiles", []):
            profiles.append(
                {
                    "id": profile["id"],
                    "title": profile.get("title", profile["id"]),
                    "provider": profile.get("provider", ""),
                    "latencyClass": profile.get("capabilities", {}).get("latencyClass", "unknown"),
                    "textProcessing": profile.get("capabilities", {}).get(
                        "textProcessing", "unknown"
                    ),
                }
            )
        result = {
            "ok": True,
            "elapsedMs": round((time.monotonic() - started) * 1000),
            "profiles": profiles,
            "defaultProfileId": listing.get("defaultProfileId"),
            "maxRecordingMs": capabilities.get("maxRecordingMs", 300000),
        }
        if "card" in body:
            self.store.record_portal_result(portal, result)
        return web.json_response(result)

    async def devices(self, request):
        return web.json_response(await audio_devices())

    async def calibration_status(self, request):
        return web.json_response(self.calibration.view())

    async def calibration_action(self, request):
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("校准请求必须是 JSON 对象")
        action = request.match_info["action"]
        if action == "start":
            result = await self.calibration.start(body.get("revision"))
        elif action == "reset":
            if self.calibration.job["state"] in ACTIVE | {"await-validation"}:
                raise ValueError("请先取消校准任务")
            config, revision = self.store.read()
            if body.get("revision") != revision:
                raise ConfigConflict("设置已变化，请重新载入后恢复")
            device = await self.calibration.device_resolver(config["audio"]["deviceId"])
            profiles = [x for x in config["audio"]["calibrations"] if x["deviceId"] != device["id"]]
            value = self.store.save({"audio": {"calibrations": profiles}}, body.get("revision"))
            self.calibration.job.update(state="idle", canApply=False, message="已恢复手动增益。")
            return web.json_response({"job": self.calibration.view(), "settings": value})
        else:
            result = await self.calibration.action(body.get("id"), action)
        return web.json_response(
            {"job": result, **({"settings": self.store.public()} if action == "apply" else {})}
        )

    async def text_model(self, request):
        body = await request.json()
        current, revision = self.store.read()
        if body.get("revision") != revision:
            raise ConfigConflict("模型卡已更新，请重新载入后重试")
        card = merge_cards([body["card"]], current["textEdit"]["cards"])[0]
        require_complete(card, model=request.match_info["action"] != "models")
        editor = TextEditor(card)
        if request.match_info["action"] == "models":
            result = {"models": await editor.models(), "updatedAt": time.time()}
            self.store.record_model_result(card, "models", result)
            return web.json_response(result)
        started = time.monotonic()
        try:
            await editor.edit("这是一段测试文本。", "将这句话改为礼貌的问候，只返回一句简短中文。")
        except ValueError as error:
            self.store.record_model_result(card, "test", {"ok": False, "error": str(error)})
            raise
        result = {"ok": True, "elapsedMs": round((time.monotonic() - started) * 1000)}
        self.store.record_model_result(card, "test", result)
        return web.json_response(result)

    async def hotwords(self, request):
        config, revision = self.store.read()
        portal = config["portal"]
        if not portal["apiKey"]:
            raise ValueError("请先在语音识别中保存 Portal 地址和接入 Key")
        body = None
        if request.method != "GET":
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("热词请求必须为 JSON 对象")
            if body.get("configRevision") != revision:
                raise ConfigConflict("Portal 连接配置已更新，请刷新热词后重试")
        async with PortalClient(portal["url"], portal["apiKey"], portal["profileId"]) as client:
            capabilities = await client.capabilities()
            if capabilities.get("hotwords", {}).get("version") != 1:
                raise ValueError("此 Portal 尚不支持热词 API，请升级 Portal")
            dictionary_support = bool(capabilities.get("hotwords", {}).get("dictionaries"))
            is_dictionary = request.path != "/api/portal/hotwords"
            if is_dictionary:
                if not dictionary_support:
                    raise ValueError("此 Portal 尚不支持词库导入，请升级 Portal")
                if request.path.endswith("/catalog"):
                    result = await client.dictionary_catalog()
                else:
                    result = await client.hotword_dictionary(
                        request.method,
                        {key: value for key, value in body.items() if key != "configRevision"}
                        if body is not None
                        else None,
                        request.match_info.get("dictionary_id"),
                    )
            elif request.method == "DELETE":
                await client.clear_hotword_statistics()
                result = await client.hotwords()
            else:
                result = await client.hotwords(
                    request.method,
                    {"revision": body.get("revision"), "settings": body.get("settings")}
                    if body is not None
                    else None,
                )
        return web.json_response(
            {**result, "configRevision": revision, "dictionarySupport": dictionary_support}
        )


async def serve(
    store, *, port=10088, open_window=True, ready_file=None, announce=True, portal_settings_url=""
):
    server = SettingsServer(store)
    runner = web.AppRunner(server.app())
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    try:
        await site.start()
        actual_port = site._server.sockets[0].getsockname()[1]
        server.origin = f"http://127.0.0.1:{actual_port}"
        url = server.origin + "/#token=" + server.token
        if ready_file:
            atomic_json(ready_file, {"url": url})
        if announce:
            print(json.dumps({"settingsUrl": url, "configPath": str(store.path)}), flush=True)
        if open_window:
            server.queue_open(portal_settings_url)
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
