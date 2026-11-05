"""Windows native process bridge. No global clipboard replacement or IME dependency."""

import asyncio
import json
import os
import queue
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

from ..domain.bridge import Lease
from ..presentation.themes import COLOR_FIELDS, palette


def helper_path():
    path = Path(os.environ.get("OPENASRINPUT_WINDOWS_HELPER", ""))
    if not path.is_file():
        raise RuntimeError(
            "Windows 原生组件不存在，请使用完整安装包或设置 OPENASRINPUT_WINDOWS_HELPER"
        )
    return str(path)


def process_flags():
    return {"creationflags": 0x08000000} if os.name == "nt" else {}


class WindowsBridge:
    def __init__(self, command=None):
        self.process = subprocess.Popen(
            command or [helper_path()],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **process_flags(),
        )
        self.lines = queue.Queue()
        self.events = deque()
        self.errors = deque(maxlen=20)
        self.serial = 0
        self.on_settings = None
        self.quit_requested = False
        self.warning = ""
        self.last_commit_error = ""
        self.context_status_supported = True
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.error_reader = threading.Thread(target=self._stderr, daemon=True)
        self.reader.start()
        self.error_reader.start()
        try:
            if self._line(15) != ["0", "HELLO", "OpenASRInput.Bridge", "1"]:
                raise RuntimeError("Windows 桥接协议不匹配")
            hotkeys = self.request("HOTKEYS").split(",")
            missing = [
                label
                for code, label in (("shift-space", "Shift+Space"), ("alt-x", "Alt+X"))
                if code not in hotkeys
            ]
            if missing:
                self.warning = "快捷键被其他应用占用：" + "、".join(missing)
        except BaseException:
            self.close()
            raise

    def _read(self):
        try:
            for line in self.process.stdout:
                if len(line) > 1024 * 1024:
                    break
                self.lines.put(line.decode("utf-8").rstrip("\r\n").split("\t"))
        finally:
            self.lines.put(None)

    def _stderr(self):
        for line in self.process.stderr:
            self.errors.append(line.decode("utf-8", errors="replace").strip())

    def _line(self, timeout=3):
        try:
            value = self.lines.get(timeout=timeout)
        except queue.Empty:
            raise RuntimeError("Windows 原生桥接响应超时") from None
        if value is None:
            raise RuntimeError("Windows 原生桥接已退出：" + " ".join(self.errors))
        return value

    def _event(self, value):
        if value[:2] != ["0", "EVENT"] or len(value) != 3:
            return False
        if value[2] == "settings":
            if self.on_settings:
                self.on_settings()
        elif value[2] == "quit":
            self.quit_requested = True
        else:
            self.events.append(value[2])
        return True

    def request(self, verb, *fields):
        self.serial += 1
        self.process.stdin.write(
            ("\t".join([str(self.serial), verb, *map(str, fields)]) + "\n").encode()
        )
        self.process.stdin.flush()
        deadline = time.monotonic() + 3
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("Windows 原生桥接响应超时")
            value = self._line(remaining)
            if self._event(value):
                continue
            if len(value) != 3 or value[:2] != [str(self.serial), "OK"]:
                raise RuntimeError("Windows 桥接拒绝请求")
            return value[2]

    def poll_events(self):
        while not self.lines.empty():
            value = self._line()
            if not self._event(value):
                raise RuntimeError("Windows 桥接返回了意外响应")
        result = list(self.events)
        self.events.clear()
        return result

    def begin_context(self):
        lease = self.request("BEGIN")
        return None if lease == "unavailable" else Lease(lease, "windows-" + lease, int(lease))

    def context_status(self):
        if not self.context_status_supported:
            return {}
        try:
            return json.loads(self.request("CONTEXT_STATUS"))
        except (RuntimeError, ValueError):
            self.context_status_supported = False
            return {}

    def valid(self, lease):
        return lease is not None and self.request("VALID", lease.lease_id) == "true"

    def selection(self, lease):
        value = self.request("SELECTION", lease.lease_id)
        if value in {"unsupported", "stale"}:
            raise ValueError("当前应用无法可靠读取选区，请换用支持选区的编辑器")
        return bytes.fromhex(value).decode("utf-8")

    def submit(self, lease, commit_id, text):
        result = self.request("COMMIT", lease.lease_id, commit_id, text.encode().hex())
        self.last_commit_error = (
            "Windows 未确认文字输入，请检查目标窗口权限；不会自动重复输入。"
            if result == "unknown"
            else ""
        )
        return result

    def show_cursor(self, lease, revision, frame):
        return self.request(
            "SHOW",
            lease.lease_id,
            revision,
            frame.text.encode().hex(),
            frame.waveform.encode().hex(),
            frame.state.encode().hex(),
        )

    def clear_cursor(self, lease):
        return self.request("CLEAR", lease.lease_id)

    def show_notice(self, lease, message):
        return self.request("NOTICE", lease.lease_id, message.encode().hex())

    def configure_keyboard(self, enabled):
        return self.request("KEYBOARD_PREEDIT", "1" if enabled else "0")

    def configure_panel(self, settings):
        colors = palette(settings["theme"], settings["colorMode"])
        return self.request(
            "THEME",
            settings["theme"] + ":" + settings["colorMode"],
            settings["scale"],
            settings["width"],
            settings["fontSize"],
            settings["radius"],
            ",".join(colors[field].lstrip("#") for field in COLOR_FIELDS),
            settings.get("position", "cursor"),
            settings.get("transparency", 0),
        )

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.reader.join(timeout=1)
        self.error_reader.join(timeout=1)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            stream.close()


class WindowsCapture:
    def __init__(self, device=None):
        self.device = device or "default"
        self.process = None
        self.stopping = False
        self.error_task = None
        self.ready_at = None
        self.first_pcm_at = None

    async def start(self):
        if self.device != "default" and not self.device.isdecimal():
            raise ValueError("请在设置页重新选择 Windows 麦克风")
        self.process = await asyncio.create_subprocess_exec(
            helper_path(),
            "--capture",
            self.device,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **process_flags(),
        )
        ready = await self.process.stderr.readline()
        if ready.rstrip(b"\r\n") != b"OpenASRInput.Capture\tREADY":
            raise RuntimeError(
                ready.decode("utf-8", errors="replace").strip() or "Windows 麦克风未确认开始采集"
            )
        self.ready_at = time.monotonic()
        self.error_task = asyncio.create_task(self.process.stderr.read(16384))

    async def chunks(self):
        pending = bytearray()
        while True:
            data = await self.process.stdout.read(640)
            if not data:
                break
            if self.first_pcm_at is None:
                self.first_pcm_at = time.monotonic()
            pending.extend(data)
            while len(pending) >= 640:
                yield bytes(pending[:640])
                del pending[:640]
        if len(pending) % 2:
            raise RuntimeError("Windows 麦克风返回了不完整的 PCM16 数据")
        if pending:
            yield bytes(pending)
        code = await self.process.wait()
        error = (await self.error_task).decode("utf-8", errors="replace").strip()
        if code != 0 or not self.stopping:
            raise RuntimeError(error or "Windows 麦克风采集提前结束，请检查设备和权限")

    async def stop(self):
        self.stopping = True
        if self.process and self.process.returncode is None:
            try:
                self.process.stdin.write(b"stop\n")
                await self.process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass
            try:
                await asyncio.wait_for(self.process.wait(), 3)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()


async def audio_devices():
    process = await asyncio.create_subprocess_exec(
        helper_path(),
        "--devices",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        **process_flags(),
    )
    try:
        output, error = await asyncio.wait_for(process.communicate(), 8)
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    if process.returncode:
        raise ValueError(error.decode("utf-8", errors="replace"))
    return json.loads(output)


def default_audio_device():
    """Resolve the WinMM WAVE_MAPPER to the same concrete input used for recording."""
    import ctypes

    message = ctypes.WinDLL("winmm").waveInMessage
    message.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
    message.restype = ctypes.c_uint
    identity, flags = ctypes.c_uint(0xFFFFFFFF), ctypes.c_uint()
    # DRVM_MAPPER + 21, intercepted by the mapper without opening a microphone.
    if (
        message(0xFFFFFFFF, 0x2015, ctypes.byref(identity), ctypes.byref(flags))
        or identity.value == 0xFFFFFFFF
    ):
        raise ValueError("系统默认麦克风不可用，请检查 Windows 输入设备设置")
    return str(identity.value)


def audio_device_interface(identity):
    """Ask WinMM for the persistent interface path, not its truncated display name."""
    import ctypes

    winmm = ctypes.WinDLL("winmm")
    message = winmm.waveInMessage
    message.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_size_t]
    message.restype = ctypes.c_uint
    size = ctypes.c_uint()
    # DRV_RESERVED + 13 queries size; + 12 queries the interface string.
    if message(int(identity), 0x080D, ctypes.byref(size), 0) or not 2 <= size.value <= 65536:
        return ""
    buffer = ctypes.create_unicode_buffer(size.value // 2)
    if message(int(identity), 0x080C, ctypes.cast(buffer, ctypes.c_void_p), size.value):
        return ""
    return buffer.value
