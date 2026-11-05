"""Private child renderer; shares the exact Fcitx5 panel implementation."""

import json
import os
import socket
import subprocess
from pathlib import Path


class Panel:
    def __init__(self):
        self.process = self.socket = None
        self.status = {"backend": "ibus", "customAppearance": False}
        installed = Path(__file__).with_name("voice-panel")
        binary = Path(os.environ.get("OPENASRINPUT_PANEL_HELPER", installed))
        if not binary.is_file() and not os.environ.get("OPENASRINPUT_PANEL_HELPER"):
            binary = Path(__file__).resolve().parents[3] / "build/fcitx5/voice-panel"
        if not binary.is_file():
            return
        parent, child = socket.socketpair()
        # Loading fonts/GUI libraries can be slow on cold or emulated systems.
        # Finish startup before exposing the input bridge; ordinary frames still
        # have a short deadline so a stuck renderer cannot block typing.
        parent.settimeout(10)
        try:
            self.process = subprocess.Popen(
                [str(binary), "--fd", str(child.fileno())], pass_fds=(child.fileno(),)
            )
            self.socket = parent
        except OSError:
            parent.close()
        finally:
            child.close()
        if self.socket:
            self.request("STATUS")
            if self.socket:
                self.socket.settimeout(1)

    def request(self, *fields):
        if self.socket:
            try:
                self.socket.sendall(("\t".join(map(str, fields)) + "\n").encode())
                data = b""
                while not data.endswith(b"\n"):
                    part = self.socket.recv(4096)
                    if not part or len(data) > 16384:
                        raise OSError("panel disconnected")
                    data += part
                self.status = json.loads(data)
                self.status["customAppearance"] = self.status.get("backend", "text") != "text"
            except (OSError, ValueError):
                self.close()
        return self.status

    def show(self, text, wave, state):
        return self.request("SHOW", *(value.encode().hex() for value in (text, wave, state)))

    def hide(self):
        self.request("HIDE")

    def close(self):
        if self.socket:
            self.socket.close()
            self.socket = None
        if self.process:
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            self.process = None
        self.status = {"backend": "ibus", "customAppearance": False}
