"""Exclusive dictation coordinator: native cursor, microphone and public Portal v1."""

import asyncio
import sys
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from ..adapters.audio import capture_for_platform
from ..adapters.portal import PortalRequestError
from ..domain.audio_processing import AudioProcessor
from .controller import Controller


@dataclass
class RunningSession:
    stream: object = None
    capture: object = None
    pump: object = None
    discard_audio: bool = False
    capture_factory: object = capture_for_platform
    gain: float = 1
    queue: deque = field(default_factory=deque)
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    queued_bytes: int = 0
    stop_requested: bool = False
    capture_started: bool = False
    capture_done: bool = False
    end_requested: bool = False
    sender: object = None
    edit_requested: bool = False
    processor: object = None
    wave_processor: object = None


@dataclass
class SessionSettings:
    portal: object
    capture_factory: object
    gain: float = 1
    editor: object = None
    highpass_hz: int = 0
    prepare_audio: object = None


def recognition_error(error, profile=None):
    if isinstance(error, PortalRequestError):
        if error.code == "PROFILE_NOT_FOUND":
            if not profile:
                return "Portal 尚未设置有效的默认识别配置。请在 Portal 管理页添加配置并设为默认。"
            name = f"「{profile}」" if profile else ""
            return f"Portal 尚未配置识别档案{name}。请在 Portal 管理页添加并保存配置。"
        if error.code == "AUTH_FAILED":
            return "Portal 接入 Key 无效。请打开 OpenASRInput 设置检查连接信息。"
        if error.code == "UPSTREAM_BUSY":
            return "识别服务当前繁忙，请稍后按 Shift+Space 重试。"
    connection_types = (ConnectionError, TimeoutError, asyncio.TimeoutError)
    # Error reporting must not trigger another lazy import. A frozen runtime
    # replaced during an upgrade can fail to load aiohttp itself.
    connection_error = getattr(sys.modules.get("aiohttp"), "ClientConnectionError", None)
    if connection_error is not None:
        connection_types += (connection_error,)
    if isinstance(error, connection_types):
        return "无法连接 Portal。请确认服务已启动，并在设置中检查 Portal 地址。"
    return str(error) or "语音输入启动失败，请检查设置。"


class Daemon:
    def __init__(
        self,
        bridge,
        portal=None,
        *,
        capture_factory=capture_for_platform,
        session_factory=None,
        on_tick=None,
    ):
        self.bridge, self.portal = bridge, portal
        self.core = Controller(bridge)
        self.capture_factory = capture_factory
        self.sessions = {}
        self.tasks = {}
        self.last_wave_update = 0.0
        self.session_factory = session_factory or self.default_session
        self.on_tick = on_tick
        self.audio_buffer_limit = 16000 * 2 * 30  # At most 30 seconds of pending PCM.
        self.upload_timeout = 15

    @asynccontextmanager
    async def default_session(self):
        yield SessionSettings(self.portal, self.capture_factory)

    async def effects(self):
        for effect in self.core.take_effects():
            generation = effect.generation
            if effect.kind == "session.create":
                self.tasks[generation] = asyncio.create_task(self.session(generation))
                continue
            running = self.sessions.get(generation)
            if running is None:
                if effect.kind == "session.cancel":
                    task = self.tasks.get(generation)
                    if task and task is not asyncio.current_task():
                        task.cancel()
                continue
            if effect.kind == "audio.start":
                self.start_sender(generation, running)
            elif effect.kind in {"audio.stop", "audio.stop-flush"}:
                await self.stop_capture(running, flush=effect.kind == "audio.stop-flush")
            elif effect.kind == "audio.end":
                running.end_requested = True
                self.core.deadline = None  # Finalization starts AFTER buffered audio is sent.
                self.start_sender(generation, running)
                running.wake.set()
            elif effect.kind == "text.edit":
                running.edit_requested = True
            elif effect.kind == "session.cancel":
                task = self.tasks.get(generation)
                if task and task is not asyncio.current_task():
                    task.cancel()
                elif (
                    running.stream
                    and not running.stream.ledger.terminal
                    and not running.stream.socket.closed
                ):
                    await running.stream.cancel()

    def start_sender(self, generation, running):
        if running.stream is not None and running.sender is None:
            running.sender = asyncio.create_task(self.upload(generation, running))

    async def stop_capture(self, running, *, flush=False):
        running.stop_requested = True
        running.discard_audio = not flush
        if not flush:
            running.queue.clear()
            running.queued_bytes = 0
            if running.sender and running.sender is not asyncio.current_task():
                running.sender.cancel()
        if running.capture is not None and running.capture_started:
            await running.capture.stop()
        if (
            running.capture_started
            and running.pump is not None
            and running.pump is not asyncio.current_task()
        ):
            await running.pump
        running.wake.set()

    async def pump(self, generation, running):
        try:
            if running.stop_requested:
                return  # A stop that preceded session initialization must not open the device.
            await asyncio.wait_for(running.capture.start(), 3)
            running.capture_started = True
            if running.stop_requested:
                await running.capture.stop()
                # start() may have produced buffered PCM before stop/reset. Drain
                # it through the normal path for flush, discard only on cancellation.
            async for chunk in running.capture.chunks():
                if running.discard_audio:
                    continue
                if running.queued_bytes + len(chunk) > self.audio_buffer_limit:
                    raise RuntimeError("音频缓存已满（30 秒），已停止录音；请检查后端连接后重试")
                running.queue.append(chunk)
                running.queued_bytes += len(chunk)
                running.wake.set()
                # Present local energy before a potentially backpressured upload.
                if running.wave_processor is None:
                    running.wave_processor = AudioProcessor(running.gain)
                self.core.on_audio(generation, running.wave_processor.process(chunk))
                if time.monotonic() - self.last_wave_update >= 0.02:
                    self.core.drain()
                    self.last_wave_update = time.monotonic()
            if not running.stop_requested:
                raise RuntimeError("麦克风意外停止，已结束本轮录音")
        except Exception as error:
            if generation == self.core.generation:
                self.core.fail(str(error))
                self.core.drain()
                await self.effects()
        finally:
            if not running.capture_started:
                await running.capture.stop()
            running.capture_done = True
            running.wake.set()

    async def upload(self, generation, running):
        try:
            while not running.discard_audio and not running.stream.ledger.terminal:
                if running.queue:
                    chunk = running.queue.popleft()
                    running.queued_bytes -= len(chunk)
                    if running.processor is None:
                        running.processor = AudioProcessor(running.gain)
                    chunk = running.processor.process(chunk)
                    await asyncio.wait_for(running.stream.send_pcm(chunk), self.upload_timeout)
                elif running.capture_done and running.end_requested:
                    await asyncio.wait_for(running.stream.end_audio(), self.upload_timeout)
                    if generation == self.core.generation:
                        self.core.deadline = time.monotonic() + self.core.finalize_timeout
                    return
                else:
                    running.wake.clear()
                    await running.wake.wait()
        except Exception as error:
            if generation == self.core.generation:
                self.core.fail(recognition_error(error))
                self.core.drain()
                await self.effects()

    async def session(self, generation):
        settings = None
        try:
            async with self.session_factory() as settings:
                running = RunningSession(capture=settings.capture_factory(), gain=settings.gain)
                running.processor = AudioProcessor(settings.gain, settings.highpass_hz)
                running.wave_processor = AudioProcessor(settings.gain, settings.highpass_hz)
                running.stop_requested = self.core.pause_requested
                self.sessions[generation] = running
                running.pump = asyncio.create_task(self.pump(generation, running))
                try:
                    await self.serve_session(generation, settings, running)
                finally:
                    await self.stop_capture(running)
                    if running.pump:
                        await running.pump
                    if running.sender:
                        running.sender.cancel()
                        await asyncio.gather(running.sender, return_exceptions=True)
                    self.sessions.pop(generation, None)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if generation == self.core.generation:
                self.core.fail(
                    recognition_error(
                        error, getattr(settings.portal, "profile_id", None) if settings else None
                    )
                )
                self.core.drain()
                await self.effects()
        finally:
            self.tasks.pop(generation, None)

    async def serve_session(self, generation, settings, running):
        portal = settings.portal
        try:
            await portal.capabilities()
            if settings.prepare_audio:
                options = await settings.prepare_audio(portal)
                running.processor = AudioProcessor(options["gain"], options["highpassHz"])
                running.wave_processor = AudioProcessor(options["gain"], options["highpassHz"])
            if generation != self.core.generation or self.core.state != "connecting":
                return
            creating = asyncio.create_task(portal.create_session())
            try:
                descriptor = await asyncio.shield(creating)
            except asyncio.CancelledError:
                try:
                    descriptor = await creating
                    await portal.cancel_session(descriptor["sessionId"])
                finally:
                    raise
            if not self.core.bind_session(generation, descriptor["sessionId"]):
                await portal.cancel_session(descriptor["sessionId"])
                return
            channel = portal.stream(descriptor)

            async def connection_failed(error):
                if generation == self.core.generation:
                    self.core.fail(recognition_error(error, getattr(portal, "profile_id", None)))
                    self.core.drain()
                    await self.stop_capture(running)

            channel.on_failure = connection_failed
            async with channel as stream:
                if generation != self.core.generation or self.core.state not in {
                    "connecting",
                    "listening",
                    "pausing",
                }:
                    await stream.cancel()
                    return
                running.stream = stream
                self.core.on_event(generation, stream.ready_event)
                self.core.drain()
                await self.effects()
                while not stream.ledger.terminal:
                    event = await stream.receive()
                    self.core.on_event(generation, event)
                    self.core.drain()
                    await self.effects()
            if (
                running.edit_requested
                and generation == self.core.generation
                and self.core.state == "processing"
            ):
                if settings.editor is None:
                    raise ValueError("文本修改模型尚未配置")
                result = await settings.editor.edit(
                    self.core.selected_text, "".join(self.core.instruction_parts)
                )
                self.core.apply_edit(generation, result)
                self.core.drain()
                await self.effects()
        finally:
            await self.stop_capture(running)

    async def action(self, kind):
        if kind in {"toggle", "command"}:
            self.core.toggle(command=kind == "command")
        elif kind == "pause" and self.core.state in {"listening", "connecting"}:
            self.core.toggle("enter")
        elif kind == "cancel":
            self.core.cancel()
        elif kind == "context-lost":
            self.core.context_changed()
        await self.effects()
        if self.core.state != "connecting":
            self.core.drain()
            await self.effects()

    async def close(self):
        self.core.cancel()
        try:
            self.core.drain()
            await self.effects()
        finally:
            tasks = list(self.tasks.values())
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def run(self):
        try:
            while True:
                if self.on_tick is not None:
                    await self.on_tick(self)
                for event in self.bridge.poll_events():
                    await self.action(event)
                self.core.tick()
                running = self.sessions.get(self.core.generation)
                if self.core.state != "connecting" or (running and running.capture_started):
                    self.core.drain()
                await self.effects()
                await asyncio.sleep(0.02)
        finally:
            await self.close()
