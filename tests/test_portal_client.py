import asyncio
import unittest

from openasrinput.adapters.portal import PortalClient, PortalRequestError
from openasrinput.application.controller import Controller
from openasrinput.domain.bridge import MemoryBridge
from openasrinput.domain.ledger import AUDIO, ProtocolError

try:
    from aiohttp import web
    from aiohttp.test_utils import TestServer
except ImportError:
    web = None


class PortalFixture:
    async def asyncSetUp(self):
        self.requests = []
        self.cancelled = []
        self.ws_headers = []
        self.pcm = []
        self.descriptor_override = None
        self.ws_redirect = False
        self.end_mode = "finish"
        self.timeout_ms = 1000
        self.sessions = 0
        self.ready_gate = None
        app = web.Application()
        app.router.add_get("/v1/capabilities", self.capabilities)
        app.router.add_post("/v1/sessions", self.create)
        app.router.add_delete("/v1/sessions/{sid}", self.cancel)
        app.router.add_get("/v1/sessions/{sid}/stream", self.stream)
        app.router.add_get("/redirect", self.redirect)
        self.server = TestServer(app)
        await self.server.start_server()
        self.client = PortalClient(str(self.server.make_url("/")).rstrip("/"), "input-key", "local")
        await self.client.__aenter__()

    async def asyncTearDown(self):
        await self.client.__aexit__()
        await self.server.close()

    async def capabilities(self, request):
        self.requests.append((request.headers.get("Authorization"), None))
        return web.json_response({"protocolVersion": 1, "audio": AUDIO})

    async def create(self, request):
        body = await request.json()
        self.requests.append((request.headers.get("Authorization"), body))
        self.sessions += 1
        sid = f"s{self.sessions}"
        return web.json_response(
            self.descriptor_override
            or {
                "sessionId": sid,
                "ticket": "one-time-ticket",
                "streamPath": f"/v1/sessions/{sid}/stream",
                "ticketExpiresInMs": 30000,
            },
            status=201,
        )

    async def cancel(self, request):
        self.cancelled.append(request.match_info["sid"])
        return web.json_response({"ok": True})

    async def redirect(self, request):
        raise web.HTTPFound("/v1/capabilities")

    async def stream(self, request):
        if self.ws_redirect:
            raise web.HTTPFound("/v1/capabilities")
        self.ws_headers.append(dict(request.headers))
        self.assertEqual(request.query["ticket"], "one-time-ticket")
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        sid = request.match_info["sid"]
        if self.ready_gate is not None:
            await self.ready_gate.wait()
        if getattr(self, "fail_before_ready", False):
            await socket.send_json(
                {
                    "type": "session.error",
                    "sessionId": sid,
                    "seq": 1,
                    "code": "UPSTREAM_ERROR",
                    "message": "upstream rejected",
                }
            )
            await socket.close()
            return socket
        await socket.send_json(
            {
                "type": "session.ready",
                "sessionId": sid,
                "seq": 1,
                "audio": AUDIO,
                "finalizeTimeoutMs": self.timeout_ms,
            }
        )
        from aiohttp import WSMsgType

        async for message in socket:
            if message.type == WSMsgType.BINARY:
                self.pcm.append(message.data)
                if getattr(self, "fail_after_audio", False):
                    await socket.send_json(
                        {
                            "type": "session.error",
                            "sessionId": sid,
                            "seq": 2,
                            "code": "UPSTREAM_ERROR",
                            "message": "upstream failed",
                        }
                    )
                    await socket.close()
                    return socket
            elif message.type == WSMsgType.TEXT:
                command = message.json()["type"]
                if command == "audio.end":
                    if self.end_mode == "stall":
                        continue
                    seq, revision = 2, 1
                    if self.end_mode == "stale-revision":
                        for rev, text in ((2, "新预览"), (1, "旧预览")):
                            await socket.send_json(
                                {
                                    "type": "transcript.partial",
                                    "sessionId": sid,
                                    "seq": seq,
                                    "utteranceId": f"{sid}:1",
                                    "revision": rev,
                                    "text": text,
                                }
                            )
                            seq += 1
                        revision = 3
                    await socket.send_json(
                        {
                            "type": "transcript.final",
                            "sessionId": sid,
                            "seq": seq,
                            "utteranceId": f"{sid}:1",
                            "revision": revision,
                            "text": "模拟定稿。",
                        }
                    )
                    await socket.send_json(
                        {
                            "type": "session.finished",
                            "sessionId": sid,
                            "seq": seq + 1,
                            "finalCount": 1,
                        }
                    )
                    await socket.close()
                elif command == "session.cancel":
                    await socket.send_json(
                        {"type": "session.cancelled", "sessionId": sid, "seq": 2}
                    )
                    await socket.close()
        return socket


@unittest.skipIf(web is None, "install the optional portal dependency to run transport tests")
class PortalClientTests(PortalFixture, unittest.IsolatedAsyncioTestCase):
    async def test_default_selection_omits_profile_and_explicit_selection_is_preserved(self):
        for profile in (None, "", "local"):
            async with PortalClient(self.client.url, "input-key", profile) as client:
                await client.create_session()
            body = self.requests[-1][1]
            if profile:
                self.assertEqual(body["profileId"], profile)
            else:
                self.assertNotIn("profileId", body)

    async def test_dictation_contract_pcm_and_finished(self):
        await self.client.capabilities()
        session = await self.client.create_session()
        auth, body = self.requests[-1]
        self.assertEqual(auth, "Bearer input-key")
        self.assertEqual(body["purpose"], "dictation")
        self.assertEqual(body["audio"], AUDIO)
        async with self.client.stream(session) as stream:
            self.assertEqual(stream.ready_event["type"], "session.ready")
            await stream.send_pcm(bytes(640))
            await stream.end_audio()
            await stream.end_audio()  # End is idempotent on this client.
            self.assertEqual((await stream.receive())["type"], "transcript.final")
            self.assertEqual((await stream.receive())["finalCount"], 1)
            with self.assertRaises(RuntimeError):
                await stream.send_pcm(bytes(2))
        self.assertNotIn("Authorization", self.ws_headers[0])
        self.assertEqual(self.pcm, [bytes(640)])
        self.assertEqual(self.cancelled, [])

    async def test_resume_uses_a_new_session_and_request_id(self):
        first = await self.client.create_session()
        second = await self.client.create_session()
        self.assertNotEqual(first["sessionId"], second["sessionId"])
        self.assertNotEqual(
            self.requests[-1][1]["clientRequestId"], self.requests[-2][1]["clientRequestId"]
        )

    async def test_abandoned_stream_cancels_only_itself(self):
        session = await self.client.create_session()
        async with self.client.stream(session):
            pass
        self.assertEqual(self.cancelled, [session["sessionId"]])

    async def test_explicit_cancel_has_no_success_final(self):
        session = await self.client.create_session()
        async with self.client.stream(session) as stream:
            await stream.cancel()
            self.assertEqual((await stream.receive())["type"], "session.cancelled")
            self.assertEqual(stream.ledger.final_count, 0)

    async def test_invalid_pcm_is_rejected_before_transmission(self):
        session = await self.client.create_session()
        async with self.client.stream(session) as stream:
            for data in (b"x", b"", "text"):
                with self.assertRaises(ValueError):
                    await stream.send_pcm(data)
        self.assertEqual(self.pcm, [])

    async def test_http_redirect_is_not_followed(self):
        with self.assertRaises(PortalRequestError):
            await self.client.request("GET", "/redirect")
        self.assertEqual(self.requests, [])

    async def test_websocket_redirect_is_not_followed_and_session_is_cleaned(self):
        self.ws_redirect = True
        session = await self.client.create_session()
        with self.assertRaises(ProtocolError):
            async with self.client.stream(session):
                self.fail("must not follow a redirect")
        self.assertEqual(self.cancelled, [session["sessionId"]])
        self.assertEqual(len(self.requests), 1)

    async def test_stream_path_cannot_send_ticket_to_other_origin(self):
        self.descriptor_override = {
            "sessionId": "s1",
            "ticket": "secret",
            "streamPath": "https://other.invalid/stream",
        }
        with self.assertRaises(ProtocolError):
            await self.client.create_session()

    async def test_finalize_deadline_is_enforced_and_session_released(self):
        self.end_mode = "stall"
        self.timeout_ms = 20
        session = await self.client.create_session()
        with self.assertRaises((TimeoutError, asyncio.TimeoutError)):
            async with self.client.stream(session) as stream:
                await stream.end_audio()
                await stream.receive()
        self.assertEqual(self.cancelled, [session["sessionId"]])

    async def test_stale_revision_is_delivered_to_keep_controller_sequence_complete(self):
        self.end_mode = "stale-revision"
        host = MemoryBridge()
        host.focus("input")
        core = Controller(host)
        core.toggle()
        core.take_effects()
        session = await self.client.create_session()
        core.bind_session(core.generation, session["sessionId"])
        async with self.client.stream(session) as stream:
            core.on_event(core.generation, stream.ready_event)
            core.toggle()
            await stream.end_audio()
            sequences = []
            while not stream.ledger.terminal:
                event = await stream.receive()
                sequences.append(event["seq"])
                core.on_event(core.generation, event)
                core.drain()
        self.assertEqual(sequences, [2, 3, 4, 5])
        self.assertEqual(core.state, "paused")
        self.assertEqual([row[2] for row in host.commits], ["模拟定稿。"])


class PortalUrlTests(unittest.TestCase):
    def test_origin_validation(self):
        for url in (
            "file:///x",
            "http://user:pass@localhost",
            "http://localhost/admin",
            "http://localhost?key=x",
            "http://localhost#fragment",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                PortalClient(url, "key", "local")
