"""Explicit local connection to the Fcitx5 addon; no auto-install or discovery."""

import json
import select
import socket
from collections import deque

from ..domain.bridge import Lease
from ..presentation.themes import COLOR_FIELDS, palette


def encode(text):
    return text.encode("utf-8").hex()


class NativeBridge:
    def __init__(self, path, *, timeout=2):
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.settimeout(timeout)
        self.timeout = timeout
        self.buffer = bytearray()
        self.events = deque()
        self.request_id = 0
        self._context_status_supported = True
        try:
            self.socket.connect(str(path))
            hello = self._line().split("\t")
            if hello != ["0", "HELLO", "OpenASRInput.Bridge", "1"]:
                raise RuntimeError("unsupported native bridge handshake")
        except BaseException:
            self.socket.close()
            raise

    def close(self):
        self.socket.close()

    def _line(self):
        while b"\n" not in self.buffer:
            data = self.socket.recv(8192)
            if not data:
                raise ConnectionError("native input bridge disconnected")
            self.buffer.extend(data)
            if len(self.buffer) > 1024 * 1024:
                raise RuntimeError("native bridge frame exceeds limit")
        line, _, remaining = self.buffer.partition(b"\n")
        self.buffer = bytearray(remaining)
        return line.decode("utf-8")

    def request(self, verb, *fields):
        self.request_id += 1
        request_id = str(self.request_id)
        self.socket.sendall(("\t".join([request_id, verb, *map(str, fields)]) + "\n").encode())
        while True:
            response = self._line().split("\t")
            if len(response) == 3 and response[:2] == ["0", "EVENT"]:
                self.events.append(response[2])
                continue
            if len(response) != 3 or response[0] != request_id or response[1] != "OK":
                raise RuntimeError("native bridge request rejected")
            return response[2]

    def poll_events(self):
        while b"\n" in self.buffer or select.select([self.socket], [], [], 0)[0]:
            fields = self._line().split("\t")
            if len(fields) != 3 or fields[:2] != ["0", "EVENT"]:
                raise RuntimeError("unexpected native bridge notification")
            self.events.append(fields[2])
        events = list(self.events)
        self.events.clear()
        return events

    def begin_context(self):
        lease = self.request("BEGIN")
        if lease == "unavailable":
            return None
        return Lease(lease, "native-" + lease, int(lease))

    def valid(self, lease):
        return self.request("VALID", lease.lease_id) == "true"

    def selection(self, lease):
        value = self.request("SELECTION", lease.lease_id)
        if value == "unsupported":
            raise ValueError(
                "当前应用不提供选区读取；请使用支持选区的编辑器，或用 Shift+Space 听写"
            )
        if value == "stale":
            raise ValueError("选区已变化，未开始文本修改")
        return bytes.fromhex(value).decode("utf-8")

    def submit(self, lease, commit_id, text):
        return self.request("COMMIT", lease.lease_id, commit_id, encode(text))

    def show_cursor(self, lease, revision, frame):
        return self.request(
            "SHOW",
            lease.lease_id,
            revision,
            encode(frame.text),
            encode(frame.waveform),
            encode(frame.state),
        )

    def clear_cursor(self, lease):
        self.request("CLEAR", lease.lease_id)

    def show_notice(self, lease, message):
        return self.request("NOTICE", lease.lease_id, encode(message))

    def configure_panel(self, settings):
        colors = palette(settings["theme"], settings["colorMode"])
        return self.request(
            "THEME",
            settings["theme"] + ":" + settings["colorMode"],
            settings["scale"],
            settings["width"],
            settings["fontSize"],
            settings["radius"],
            ",".join(colors[key][1:] for key in COLOR_FIELDS),
            settings.get("position", "cursor"),
            settings.get("transparency", 0),
        )

    def configure_keyboard(self, inline_preedit):
        return self.request("KEYBOARD_PREEDIT", "1" if inline_preedit else "0")

    def context_status(self):
        if not self._context_status_supported:
            return {}
        try:
            result = json.loads(self.request("CONTEXT_STATUS"))
        except (RuntimeError, ValueError):
            # Older v1 addons do not implement this optional diagnostic query.
            self._context_status_supported = False
            return {}
        return result if isinstance(result, dict) else {}
