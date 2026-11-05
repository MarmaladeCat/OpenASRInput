"""Actual GTK/Fcitx D-Bus reset reproduction in private D-Bus/Xvfb sessions."""

import argparse
import os
import subprocess
import sys
import sysconfig
import tempfile
import time
from pathlib import Path

from openasrinput.adapters.native import NativeBridge
from openasrinput.application.controller import Controller
from openasrinput.domain.bridge import CursorFrame
from openasrinput.domain.ledger import AUDIO

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build/fcitx5")
    parser.add_argument(
        "--package", type=Path, help="exercise the actual Fcitx5 plugin extracted from a deb"
    )
    args = parser.parse_args()
    if os.environ.get("OPENASRINPUT_GTK_ISOLATED") != "1":
        env = {**os.environ, "OPENASRINPUT_GTK_ISOLATED": "1"}
        env.update(GIO_USE_VFS="local", NO_AT_BRIDGE="1", GTK_IM_MODULE="fcitx", GDK_BACKEND="x11")
        for name in ("DBUS_SESSION_BUS_ADDRESS", "DISPLAY", "WAYLAND_DISPLAY"):
            env.pop(name, None)
        with tempfile.TemporaryDirectory(prefix="gb-", dir=ROOT / "test-results") as directory:
            for name, part in (
                ("HOME", "home"),
                ("XDG_CONFIG_HOME", "config"),
                ("XDG_DATA_HOME", "data"),
                ("XDG_CACHE_HOME", "cache"),
                ("XDG_RUNTIME_DIR", "run"),
            ):
                value = Path(directory) / part
                value.mkdir(mode=0o700)
                env[name] = str(value)
            config = Path(directory) / "bus.conf"
            config.write_text(
                f"<busconfig><type>session</type><listen>unix:abstract=openasrinput-gtk-{os.getpid()}</listen>"
                '<policy context="default"><allow own="*"/><allow send_destination="*"/><allow receive_sender="*"/></policy></busconfig>'
            )
            raise SystemExit(
                subprocess.call(
                    [
                        "dbus-run-session",
                        "--config-file=" + str(config),
                        "--",
                        "xvfb-run",
                        "-a",
                        sys.executable,
                        __file__,
                        *sys.argv[1:],
                    ],
                    env=env,
                )
            )
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, GLib, Gtk

    build = args.build.resolve()
    with tempfile.TemporaryDirectory(prefix="gr-", dir=ROOT / "test-results") as directory:
        stage = Path(directory)
        env = {
            **os.environ,
            "HOME": str(stage / "home"),
            "XDG_CONFIG_HOME": str(stage / "config"),
            "XDG_DATA_HOME": str(stage / "data"),
            "XDG_CACHE_HOME": str(stage / "cache"),
            "XDG_RUNTIME_DIR": str(stage / "run"),
            "TMPDIR": str(stage / "tmp"),
            "GTK_IM_MODULE": "fcitx",
            "XDG_SESSION_TYPE": "x11",
            "GDK_BACKEND": "x11",
            "GIO_USE_VFS": "local",
            "NO_AT_BRIDGE": "1",
            "FCITX_ADDON_DIRS": str(build / "lib")
            + ":/usr/lib/"
            + sysconfig.get_config_var("MULTIARCH")
            + "/fcitx5",
            "XDG_DATA_DIRS": str(build / "share") + ":/usr/share",
            "OPENASRINPUT_SOCKET": str(stage / "bridge.sock"),
        }
        for name in (
            "HOME",
            "XDG_CONFIG_HOME",
            "XDG_DATA_HOME",
            "XDG_CACHE_HOME",
            "XDG_RUNTIME_DIR",
            "TMPDIR",
        ):
            Path(env[name]).mkdir(mode=0o700)
        if args.package:
            payload = stage / "package"
            subprocess.run(
                ["dpkg-deb", "-x", str(args.package.resolve()), str(payload)], check=True
            )
            library = next((payload / "usr/lib").glob("*/fcitx5/libopenasrinput.so"))
            env["FCITX_ADDON_DIRS"] = (
                str(library.parent)
                + ":/usr/lib/"
                + sysconfig.get_config_var("MULTIARCH")
                + "/fcitx5"
            )
            env["XDG_DATA_DIRS"] = str(payload / "usr/share") + ":/usr/share"
        os.environ.update(env)
        child = subprocess.Popen(
            [
                "fcitx5",
                "-D",
                "--disable=all",
                "--enable=openasrinput,dbus,dbusfrontend,xcb,classicui,keyboard",
            ],
            env=env,
            cwd=stage,
            stdout=subprocess.DEVNULL,
        )
        bridge = None
        windows, contexts, commits = [], [], [[], []]
        loop = GLib.MainContext.default()

        def pump(seconds=0.03):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                while loop.pending():
                    loop.iteration(False)
                time.sleep(0.002)

        try:
            for i in range(2):
                window = Gtk.Window(title=f"Isolated app {i}")
                entry = Gtk.Entry()
                window.add(entry)
                window.show_all()
                pump()
                context = Gtk.IMMulticontext()
                context.set_client_window(entry.get_window())
                context.set_use_preedit(True)
                context.connect(
                    "commit", lambda _context, text, index=i: commits[index].append(text)
                )
                windows.append(window)
                contexts.append(context)
            for _ in range(300):
                if Path(env["OPENASRINPUT_SOCKET"]).exists():
                    break
                pump()
            bridge = NativeBridge(env["OPENASRINPUT_SOCKET"])
            first, second = contexts
            first.focus_in()
            pump(0.2)
            probe = bridge.begin_context()
            assert probe, "GTK did not create a focused Fcitx context"
            bridge.clear_cursor(probe)
            first.focus_out()
            second.focus_in()
            pump()
            second.focus_out()
            first.focus_in()
            first.reset()  # This is the real GTK Fcitx reset implementation.
            pump()
            for symbol, code, release, state in (
                (Gdk.KEY_Shift_L, 50, False, 0),
                (Gdk.KEY_space, 65, False, Gdk.ModifierType.SHIFT_MASK),
                (Gdk.KEY_space, 65, True, Gdk.ModifierType.SHIFT_MASK),
                (Gdk.KEY_Shift_L, 50, True, 0),
            ):
                event = Gdk.Event.new(
                    Gdk.EventType.KEY_RELEASE if release else Gdk.EventType.KEY_PRESS
                )
                event.key.window = windows[0].get_window()
                event.key.keyval, event.key.hardware_keycode, event.key.state, event.key.time = (
                    symbol,
                    code,
                    state,
                    100 + code,
                )
                first.filter_keypress(event.key)
                pump()
            assert "toggle" in bridge.poll_events(), "GTK shortcut did not reach the native addon"
            core = Controller(bridge)
            core.toggle()
            core.take_effects()
            assert core.bind_session(core.generation, "gtk-test")
            core.on_event(
                core.generation,
                {
                    "type": "session.ready",
                    "sessionId": "gtk-test",
                    "seq": 1,
                    "audio": AUDIO,
                    "finalizeTimeoutMs": 1000,
                },
            )
            core.drain()
            first.reset()  # Click/focus synchronization after the voice lease exists.
            pump()
            core.tick()
            core.drain()
            assert core.state == "listening", (
                f"GTK reproduced immediate stop: {core.state}, {core.stop_reason}"
            )
            lease = core.lease
            bridge.show_cursor(lease, 20, CursorFrame("listening", "尚未定稿的预览", "▁█"))
            pump()
            first.reset()
            pump()
            assert commits == [[], []], f"GTK client committed unconfirmed preedit: {commits}"
            assert bridge.valid(lease)
            assert bridge.submit(lease, "final-one", "稳定定稿") == "accepted"
            pump()
            assert commits == [["稳定定稿"], []]
            first.focus_out()
            second.focus_in()
            pump()
            assert not bridge.valid(lease)
            assert bridge.submit(lease, "late", "迟到结果") == "stale"
            pump()
            assert commits == [["稳定定稿"], []]
            print(
                "PASS actual GTK/Fcitx: app switch, click/reset, shortcut, reset while recording, non-committing preview and genuine target isolation"
            )
        finally:
            if bridge:
                bridge.close()
            for context in contexts:
                context.focus_out()
                context.set_client_window(None)
            for window in windows:
                window.destroy()
            pump()
            subprocess.run(
                ["fcitx5-remote", "-e"],
                env=env,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.terminate()
                child.wait(timeout=5)


if __name__ == "__main__":
    main()
