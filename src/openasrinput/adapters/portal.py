"""Own thin client for OpenASRPortal v1. No imports from associated projects."""

import asyncio
import json
from urllib.parse import quote, urlencode, urlsplit
from uuid import uuid4

from ..domain.ledger import AUDIO, Ledger, ProtocolError


class PortalRequestError(RuntimeError):
    def __init__(self, code, message, status):
        super().__init__(message)
        self.code, self.status = code, status


class PortalClient:
    def __init__(self, url: str, api_key: str, profile_id: str | None = None):
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("Portal URL must be an HTTP(S) origin")
        if not api_key.strip():
            raise ValueError("Portal access key is required")
        if profile_id is not None and not isinstance(profile_id, str):
            raise ValueError("Portal profile id must be a string or omitted")
        self.url, self.api_key, self.profile_id = url.rstrip("/"), api_key, profile_id
        self.http = None

    async def __aenter__(self):
        # Optional dependency: offline core and demo need only Python's stdlib.
        from aiohttp import ClientSession, ClientTimeout, TraceConfig

        async def refuse_redirect(*args):
            raise ProtocolError("Portal redirects are unsupported")

        trace = TraceConfig()
        trace.on_request_redirect.append(refuse_redirect)
        self.http = ClientSession(
            timeout=ClientTimeout(total=15), trust_env=False, trace_configs=[trace]
        )
        return self

    async def __aexit__(self, *args):
        await self.http.close()
        self.http = None

    async def request(self, method, path, body=None):
        if self.http is None:
            raise RuntimeError("use PortalClient as an async context manager")
        async with self.http.request(
            method,
            self.url + path,
            json=body,
            headers={"Authorization": "Bearer " + self.api_key},
            allow_redirects=False,
        ) as response:
            if 300 <= response.status < 400:
                raise PortalRequestError(
                    "REDIRECT_REFUSED", "Portal redirect refused", response.status
                )
            data = await response.json()
            if response.status >= 400:
                error = data.get("error", {})
                raise PortalRequestError(
                    error.get("code", "HTTP_ERROR"),
                    error.get("message", "Portal request failed"),
                    response.status,
                )
            return data

    async def capabilities(self):
        data = await self.request("GET", "/v1/capabilities")
        if data.get("protocolVersion") != 1 or data.get("audio") != AUDIO:
            raise ProtocolError("unsupported Portal protocol/audio")
        return data

    async def profiles(self):
        return await self.request("GET", "/v1/profiles")

    async def hotwords(self, method="GET", body=None):
        path = "/v1/hotwords"
        if self.profile_id:
            path += "?" + urlencode({"profileId": self.profile_id})
        return await self.request(method, path, body)

    async def clear_hotword_statistics(self):
        return await self.request("DELETE", "/v1/hotwords/statistics")

    async def dictionary_catalog(self):
        return await self.request("GET", "/v1/hotwords/catalog")

    async def hotword_dictionary(self, method, body=None, identity=None):
        path = "/v1/hotwords/dictionaries"
        if identity:
            path += "/" + quote(identity, safe="")
        if self.profile_id:
            path += "?" + urlencode({"profileId": self.profile_id})
        return await self.request(method, path, body)

    async def create_session(self, *, request_id=None):
        result = await self.request(
            "POST",
            "/v1/sessions",
            {
                **({"profileId": self.profile_id} if self.profile_id else {}),
                "purpose": "dictation",
                "clientRequestId": request_id or str(uuid4()),
                "audio": dict(AUDIO),
            },
        )
        sid, ticket, path = (
            result.get("sessionId"),
            result.get("ticket"),
            result.get("streamPath"),
        )
        if not isinstance(sid, str) or not sid or not isinstance(ticket, str) or not ticket:
            raise ProtocolError("invalid session credentials")
        # Never follow an arbitrary streamPath with a one-time credential.
        if path != f"/v1/sessions/{quote(sid, safe='')}/stream":
            await self.cancel_session(sid)
            raise ProtocolError("streamPath must refer to this session on the same origin")
        return result

    async def cancel_session(self, session_id):
        return await self.request("DELETE", "/v1/sessions/" + quote(session_id, safe=""))

    def stream(self, session):
        return PortalStream(self, session)


class PortalStream:
    """One-shot WS. No audio is accepted before ready or after audio.end."""

    def __init__(self, client, session):
        self.client, self.session = client, session
        self.ledger = Ledger(session["sessionId"])
        self.socket = None
        self.ended = False
        self.finalize_timeout = None
        self.deadline = None
        self.on_failure = None

    async def __aenter__(self):
        try:
            # Check again even if callers supplied a session descriptor themselves.
            sid = self.session["sessionId"]
            expected = f"/v1/sessions/{quote(sid, safe='')}/stream"
            if self.session["streamPath"] != expected:
                raise ProtocolError("invalid stream path")
            url = self.client.url + expected + "?" + urlencode({"ticket": self.session["ticket"]})
            # Deliberately no long-term Authorization header on WebSocket requests.
            self.socket = await self.client.http.ws_connect(url, max_msg_size=1024 * 1024)
            event = await self.receive(timeout=15)
            if event["type"] != "session.ready":
                if event["type"] == "session.error":
                    raise PortalRequestError(
                        event.get("code", "UPSTREAM_ERROR"),
                        event.get("message", "识别后端启动失败"),
                        502,
                    )
                raise ProtocolError("Portal did not become ready")
            self.ready_event = event
            return self
        except BaseException as error:
            if self.on_failure and isinstance(error, Exception):
                await self.on_failure(error)
            try:
                if self.socket is not None:
                    await self.socket.close()
                await self.client.cancel_session(self.session["sessionId"])
            except Exception:
                pass  # Preserve the original handshake/protocol error.
            raise

    async def __aexit__(self, *args):
        if self.on_failure and isinstance(args[1], Exception):
            await self.on_failure(args[1])
        try:
            await self.socket.close()
            if not self.ledger.terminal:
                await self.client.cancel_session(self.session["sessionId"])
        except Exception:
            if args[0] is None:
                raise

    async def receive(self, *, timeout=None):
        from aiohttp import WSMsgType

        if self.ledger.terminal:
            raise RuntimeError("session already reached its terminal event")
        while True:
            remaining = timeout
            if self.deadline is not None:
                budget = self.deadline - asyncio.get_running_loop().time()
                if budget <= 0:
                    raise TimeoutError("FINALIZATION_TIMEOUT")
                remaining = min(timeout, budget) if timeout is not None else budget
            message = await self.socket.receive(timeout=remaining)
            if message.type != WSMsgType.TEXT:
                raise ProtocolError("Portal stream disconnected before terminal event")
            event = json.loads(message.data)
            if not isinstance(event, dict):
                raise ProtocolError("invalid Portal event")
            previous_seq = self.ledger.seq
            changed = self.ledger.accept(event)
            if event.get("type") == "session.ready" and changed:
                self.finalize_timeout = event["finalizeTimeoutMs"] / 1000
            # Deliver stale revisions/duplicate finals with a NEW seq as well:
            # consumers must see every sequence number, even when text is unchanged.
            if self.ledger.seq > previous_seq:
                return event

    async def send_pcm(self, data: bytes):
        if not self.ledger.ready or self.ledger.terminal or self.ended:
            raise RuntimeError("audio may only be sent to a ready, active stream")
        if not isinstance(data, bytes) or not data or len(data) % 2:
            raise ValueError("PCM16 chunk must contain complete 16-bit samples")
        await self.socket.send_bytes(data)

    async def end_audio(self):
        if not self.ledger.ready or self.ledger.terminal:
            raise RuntimeError("stream is not active")
        if not self.ended:
            self.ended = True
            self.deadline = asyncio.get_running_loop().time() + self.finalize_timeout
            await self.socket.send_json({"type": "audio.end"})

    async def cancel(self):
        self.ended = True
        await self.socket.send_json({"type": "session.cancel"})
