"""Explicit PulseAudio/PipeWire PCM16 capture subprocess, opened on activation."""

import asyncio
import os

from ..infrastructure.platform_support import config_home, exclusive_lock


def capture_for_platform(device=None):
    if os.name == "nt":
        from .windows import WindowsCapture

        return LockedCapture(WindowsCapture(device))
    return LockedCapture(AudioCapture(device))


class LockedCapture:
    """One microphone capture per user, including other settings processes."""

    def __init__(self, capture, lock_path=None):
        self.capture = capture
        self.lock_path = lock_path or config_home() / "microphone.lock"
        self.lock = None

    async def start(self):
        if self.lock is not None:
            raise RuntimeError("capture already started")
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock = exclusive_lock(self.lock_path, blocking=False)
        try:
            lock.__enter__()
        except OSError as error:
            raise RuntimeError("麦克风正在被语音输入或校准使用，请先结束当前录音。") from error
        self.lock = lock
        try:
            await self.capture.start()
        except BaseException:
            await self.stop()
            raise

    async def chunks(self):
        async for chunk in self.capture.chunks():
            yield chunk

    async def stop(self):
        try:
            await self.capture.stop()
        finally:
            if self.lock is not None:
                self.lock.__exit__(None, None, None)
                self.lock = None


class AudioCapture:
    def __init__(self, device=None):
        self.device = device
        self.process = None

    async def start(self):
        if self.process is not None:
            raise RuntimeError("capture already started")
        command = [
            "parec",
            "--raw",
            "--format=s16le",
            "--rate=16000",
            "--channels=1",
            "--latency-msec=20",
        ]
        if self.device:
            command.append("--device=" + self.device)
        self.process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )

    async def chunks(self):
        pending = bytearray()
        while True:
            data = await self.process.stdout.read(640)
            if not data:
                break
            pending.extend(data)
            while len(pending) >= 640:
                chunk = bytes(pending[:640])
                del pending[:640]
                yield chunk
        if len(pending) % 2:
            raise RuntimeError("capture ended with an incomplete PCM16 sample")
        if pending:
            yield bytes(pending)
        code = await self.process.wait()
        if code not in (0, -15):
            raise RuntimeError("microphone capture failed; check device and permissions")

    async def stop(self):
        if self.process is not None and self.process.returncode is None:
            try:
                self.process.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(self.process.wait(), 2)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
