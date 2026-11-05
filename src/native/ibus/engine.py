#!/usr/bin/python3
"""IBus engine and private Bridge v1 server (system Python + PyGObject).

All engine operations and socket callbacks run on the GLib thread. This process
has no ASR/network dependencies and can accompany the frozen application.
"""

import argparse
import json
import os
import socket
import stat
from pathlib import Path


class BridgeState:
    """Context epochs and idempotency, independent of GI for contract testing."""

    def __init__(self):
        self.engine = None
        self.epoch = 0
        self.lease = None
        self.revision = 0
        self.accepted = {}
        self.hidden = False
        self.connected = False
        self.event = lambda event: None
        self.selected = None
        self.selection_committed = False
        self.panel = None

    def focus(self, engine):
        had_lease = self.lease is not None
        if self.engine is not None:
            self.engine.preview("", "")
        self.engine = engine
        self.epoch += 1
        self.lease = None
        self.revision = 0
        self.selected = None
        self.selection_committed = False
        if self.panel:
            self.panel.hide()
        if had_lease:
            self.event("context-lost")

    def request(self, verb, *args):
        if verb == "CONTEXT_STATUS":
            return json.dumps(
                {
                    "framework": "ibus",
                    "focused": self.engine is not None and not self.engine.private,
                    "focusEpoch": self.epoch,
                    "capabilities": {"selection": self.snapshot() is not None, "preedit": True},
                    "panel": self.panel.request("STATUS")
                    if self.panel
                    else {"backend": "ibus", "customAppearance": False},
                }
            )
        if verb == "THEME":
            self.hidden = len(args) > 6 and args[6] == "hidden"
            if self.panel:
                self.panel.request("THEME", *args)
            return "accepted"
        if verb == "PANEL_BACKEND":
            return self.panel.request("STATUS")["backend"] if self.panel else "ibus"
        if verb == "KEYBOARD_PREEDIT":
            return "accepted"
        if verb == "BEGIN":
            if self.engine is None or self.engine.private:
                return "unavailable"
            self.epoch += 1
            self.lease = str(self.epoch)
            self.revision = 0
            self.selected = None
            self.selection_committed = False
            return self.lease
        if verb == "COMMIT" and len(args) == 3 and args[1] in self.accepted:
            return "accepted" if self.accepted[args[1]] == args else "failed"
        valid = bool(
            args and self.engine is not None and not self.engine.private and args[0] == self.lease
        )
        if verb == "VALID":
            return "true" if valid else "false"
        if not valid:
            return "stale"
        if verb == "SELECTION":
            snapshot = self.snapshot()
            if snapshot is None:
                return "unsupported"
            text, cursor, anchor, _ = snapshot
            selected = text[min(cursor, anchor) : max(cursor, anchor)]
            # IBus uses equal endpoints both for "no selection" and clients
            # that cannot expose one. Do not turn an unverified edit command
            # into dictation that could overwrite a hidden selection.
            if not selected:
                return "unsupported"
            if len(selected.encode()) > 64000:
                return "unsupported"
            self.selected = snapshot if selected else None
            return selected.encode().hex()
        if verb == "COMMIT" and len(args) == 3:
            if not args[1]:
                return "failed"
            if self.selected is not None and (
                self.selection_committed or self.snapshot() != self.selected
            ):
                return "stale"
            text = bytes.fromhex(args[2]).decode("utf-8")
            if self.selected is None:
                self.engine.preview("", "")
            if self.panel:
                self.panel.hide()
            # Nonempty CommitText replaces the verified selection in one operation.
            if self.selected is not None or text:
                self.selection_committed = self.selected is not None
                if self.selected is not None and not text:
                    self.engine.delete_selection()
                elif text:
                    self.engine.commit(text)
            self.accepted[args[1]] = args
            # A bounded process-lifetime deduplication cache.
            if len(self.accepted) > 4096:
                del self.accepted[next(iter(self.accepted))]
            return "accepted"
        if verb == "SHOW" and len(args) == 5:
            revision = int(args[1])
            if revision > self.revision:
                text, wave, state = [bytes.fromhex(value).decode("utf-8") for value in args[2:]]
                custom = self.panel and self.panel.show(text, wave, state).get("customAppearance")
                auxiliary = "" if custom or self.hidden else state + " " + wave + "\n" + text
                if self.selected is None:
                    self.engine.preview(text, auxiliary)
                else:
                    # Preedit can replace/collapse a selection in GTK. Instructions
                    # belong only in the panel until the final CommitText.
                    self.engine.auxiliary(auxiliary)
                self.revision = revision
            return "accepted"
        if verb == "CLEAR":
            self.engine.preview("", "")
            self.lease = None
            self.selected = None
            if self.panel:
                self.panel.hide()
            return "accepted"
        if verb == "NOTICE" and len(args) == 2:
            message = bytes.fromhex(args[1]).decode("utf-8")
            custom = self.panel and self.panel.show(message, "", "needs-config").get(
                "customAppearance"
            )
            self.engine.preview("", "" if custom or self.hidden else message)
            return "accepted"
        return "unsupported"

    def snapshot(self):
        if self.engine is None or self.engine.private:
            return None
        value = getattr(self.engine, "surrounding", None)
        if value is None:
            return None
        text, cursor, anchor = value
        if (
            not (0 <= cursor <= len(text) and 0 <= anchor <= len(text))
            or len(text.encode()) > 512 * 1024
        ):
            return None
        return text, cursor, anchor, getattr(self.engine, "cursor", None)


def run(path):
    import fcntl

    import gi

    gi.require_version("IBus", "1.0")
    from gi.repository import GLib, IBus

    IBus.init()
    state = BridgeState()
    from panel_client import Panel

    state.panel = Panel()
    loop = GLib.MainLoop()

    class Engine(IBus.Engine):
        __gtype_name__ = "OpenASRInputEngine"

        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.private = False
            self.down = set()
            self.surrounding = None
            self.cursor = (0, 0, 0, 0)
            self.preedit = ""
            self.connect("destroy", self.on_destroy)

        def on_destroy(self, *_):
            if state.engine is self:
                state.focus(None)

        def preview(self, text, auxiliary):
            if text != self.preedit:
                self.preedit = text
                self.update_preedit_text_with_mode(
                    IBus.Text.new_from_string(text),
                    len(text),
                    bool(text),
                    IBus.PreeditFocusMode.CLEAR,
                )
            self.auxiliary(auxiliary)

        def auxiliary(self, text):
            self.update_auxiliary_text(IBus.Text.new_from_string(text), bool(text))

        def do_set_surrounding_text(self, text, cursor, anchor):
            if self.private:
                self.surrounding = None
                return
            IBus.Engine.do_set_surrounding_text(self, text, cursor, anchor)
            self.surrounding = (text.get_text(), cursor, anchor)
            if (
                state.engine is self
                and state.selected is not None
                and state.snapshot() != state.selected
            ):
                state.focus(self)

        def do_set_cursor_location(self, x, y, width, height):
            self.cursor = (x, y, width, height)
            if state.engine is self:
                if state.selected is not None and state.snapshot() != state.selected:
                    state.focus(self)
                # IBus/Wayland cursor coordinates may be surface-relative. Let
                # GNOME or layer-shell position the panel instead of guessing.
                state.panel.request(
                    "ANCHOR", *self.cursor, int(not os.environ.get("WAYLAND_DISPLAY"))
                )

        def do_set_capabilities(self, capabilities):
            if not capabilities & IBus.Capabilite.SURROUNDING_TEXT:
                self.surrounding = None

        def do_enable(self):
            self.get_surrounding_text()  # Advertise RequireSurroundingText to clients.

        def commit(self, text):
            self.commit_text(IBus.Text.new_from_string(text))

        def delete_selection(self):
            # GTK deletes the still-selected range on CommitText, while Qt
            # ignores an empty commit and needs a preedit transition. This order
            # matters: committing AFTER preedit could delete GTK4's next character
            # in overwrite mode. The temporary preedit is never document text.
            self.commit("")
            self.preview(" ", "")
            self.preview("", "")

        def do_focus_in(self):
            self.down.clear()
            state.focus(self)
            self.get_surrounding_text()

        def do_focus_out(self):
            if state.engine is self:
                state.focus(None)
            self.down.clear()
            self.surrounding = None

        def do_disable(self):
            self.do_focus_out()

        def do_reset(self):
            # Conservative: a reset may indicate a changed caret/selection.
            if state.engine is self:
                state.focus(self)

        def do_set_content_type(self, purpose, hints):
            self.private = purpose in (IBus.InputPurpose.PASSWORD, IBus.InputPurpose.PIN)
            if self.private:
                self.surrounding = None
            if self.private and state.engine is self:
                state.focus(self)

        def do_process_key_event(self, keyval, keycode, modifiers):
            release = bool(modifiers & IBus.ModifierType.RELEASE_MASK)
            if keyval in self.down:
                if release:
                    self.down.remove(keyval)
                return True
            if release or self.private or state.engine is not self or not state.connected:
                return False
            mask = modifiers & (
                IBus.ModifierType.SHIFT_MASK
                | IBus.ModifierType.CONTROL_MASK
                | IBus.ModifierType.MOD1_MASK
                | IBus.ModifierType.SUPER_MASK
            )
            event = None
            if keyval == IBus.KEY_space and mask == IBus.ModifierType.SHIFT_MASK:
                event = "toggle"
            elif keyval in (IBus.KEY_z, IBus.KEY_Z) and mask == IBus.ModifierType.MOD1_MASK:
                event = "command"
            elif state.lease is not None and not mask:
                event = {IBus.KEY_Return: "pause", IBus.KEY_Escape: "cancel"}.get(keyval)
            if event:
                self.down.add(keyval)
                state.event(event)
                return True
            if state.selected is not None:
                state.focus(self)
            return False

    bus = IBus.Bus.new()
    if not bus.is_connected():
        raise RuntimeError("IBus 未运行")
    bus.connect("disconnected", lambda *_: loop.quit())
    factory = IBus.Factory.new(bus.get_connection())
    factory.add_engine("openasrinput", Engine.__gtype__)
    # Installed metadata exposes the source to GNOME's engine catalogue. Own
    # its factory name as well; RegisterComponent alone only creates an active
    # runtime engine, absent from ListEngines/GetEnginesByNames.
    bus.request_name("org.freedesktop.IBus.OpenASRInput", 0)
    component = IBus.Component.new(
        "org.freedesktop.IBus.OpenASRInput", "OpenASRInput", "1", "MIT", "OpenASRInput", "", "", ""
    )
    component.add_engine(
        IBus.EngineDesc.new(
            "openasrinput",
            "OpenASRInput 语音",
            "语音输入",
            "zh",
            "MIT",
            "OpenASRInput",
            "",
            "default",
        )
    )
    bus.register_component(component)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = open(str(path) + ".lock", "a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if path.exists():
        info = path.lstat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
            raise RuntimeError("IBus 桥接路径已被其他文件占用")
        path.unlink()
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    # The lifetime lock prevents a second helper replacing a live endpoint.
    server.bind(str(path))
    os.chmod(path, 0o600)
    server.listen(1)
    server.setblocking(False)
    clients = {}

    def close(client):
        clients.pop(client, None)
        state.connected = False
        client.close()
        state.focus(state.engine)

    def send(client, text):
        try:
            client.sendall(text.encode("utf-8"))
            return True
        except OSError:
            close(client)
            return False

    def event(value):
        for client in list(clients):
            send(client, "0\tEVENT\t" + value + "\n")

    state.event = event

    def receive(client, condition):
        if client not in clients:
            return False
        try:
            data = client.recv(8192)
            if not data:
                close(client)
                return False
            clients[client] += data
            if len(clients[client]) > 1024 * 1024:
                close(client)
                return False
            while b"\n" in clients[client]:
                line, clients[client] = clients[client].split(b"\n", 1)
                fields = line.decode("utf-8").split("\t")
                result = state.request(*fields[1:])
                if not send(client, fields[0] + "\tOK\t" + result + "\n"):
                    return False
        except (OSError, ValueError, TypeError, IndexError):
            close(client)
            return False
        return True

    def accept(*_):
        client, _ = server.accept()
        if clients:
            client.close()
            return True
        client.settimeout(0.2)
        clients[client] = b""
        state.connected = True
        if send(client, "0\tHELLO\tOpenASRInput.Bridge\t1\n"):
            GLib.io_add_watch(client, GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, receive)
        return True

    GLib.io_add_watch(server, GLib.IO_IN, accept)
    import signal

    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: (loop.quit(), False)[1])
    try:
        loop.run()
    finally:
        for client in list(clients):
            close(client)
        server.close()
        path.unlink(missing_ok=True)
        lock.close()
        state.panel.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", required=True)
    run(parser.parse_args().socket)
