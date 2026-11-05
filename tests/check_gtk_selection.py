"""Real GTK4 selection replacement via Fcitx5 in an isolated desktop session."""

import argparse
import ctypes
import os
import subprocess
import sys
import sysconfig
import tempfile
import time
from pathlib import Path

from openasrinput.adapters.native import NativeBridge
from openasrinput.domain.bridge import CursorFrame

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", type=Path, default=ROOT / "build/fcitx5")
    parser.add_argument("--package", type=Path)
    args = parser.parse_args()
    if os.environ.get("OPENASRINPUT_SELECTION_TEST") != "1":
        with tempfile.TemporaryDirectory(prefix="gs-", dir=ROOT / "test-results") as folder:
            base = Path(folder)
            env = dict(os.environ)
            for name in ("DBUS_SESSION_BUS_ADDRESS", "DISPLAY", "WAYLAND_DISPLAY"):
                env.pop(name, None)
            for name in (
                "HOME",
                "XDG_CONFIG_HOME",
                "XDG_DATA_HOME",
                "XDG_CACHE_HOME",
                "XDG_RUNTIME_DIR",
            ):
                path = base / name
                path.mkdir(mode=0o700)
                env[name] = str(path)
            build = args.build.resolve()
            env.update(
                OPENASRINPUT_SELECTION_TEST="1",
                GDK_BACKEND="x11",
                GTK_IM_MODULE="fcitx",
                NO_AT_BRIDGE="1",
                GTK_A11Y="none",
                GIO_USE_VFS="local",
                OPENASRINPUT_SOCKET=str(base / "bridge.sock"),
                XDG_SESSION_TYPE="x11",
                FCITX_ADDON_DIRS=str(build / "lib")
                + ":/usr/lib/"
                + sysconfig.get_config_var("MULTIARCH")
                + "/fcitx5",
                XDG_DATA_DIRS=str(build / "share") + ":/usr/share",
            )
            if args.package:
                payload = base / "package"
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
            bus = base / "bus.conf"
            bus.write_text(
                "<busconfig><type>session</type><listen>unix:tmpdir=/tmp/opencode</listen>"
                '<policy context="default"><allow own="*"/><allow send_destination="*"/>'
                '<allow receive_sender="*"/></policy></busconfig>'
            )
            raise SystemExit(
                subprocess.call(
                    [
                        "dbus-run-session",
                        "--config-file=" + str(bus),
                        "--",
                        "xvfb-run",
                        "-a",
                        sys.executable,
                        __file__,
                        "--build",
                        str(build),
                    ],
                    env=env,
                )
            )
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("GdkX11", "4.0")
    from gi.repository import GLib, Gtk

    loop = GLib.MainContext.default()

    def pump(seconds=0.2):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            while loop.pending():
                loop.iteration(False)
            time.sleep(0.002)

    child = subprocess.Popen(
        [
            "fcitx5",
            "-D",
            "--disable=all",
            "--enable=openasrinput,dbus,dbusfrontend,xcb,classicui,keyboard",
        ],
        stdout=subprocess.DEVNULL,
    )
    window = Gtk.Window(title="OpenASRInput Selection Fixture")
    entry = Gtk.Entry()
    window.set_child(entry)
    window.set_default_size(640, 100)
    bridge = None
    try:
        for _ in range(100):
            if Path(os.environ["OPENASRINPUT_SOCKET"]).exists():
                break
            pump(0.05)
        window.present()
        entry.grab_focus()
        pump()
        xlib = ctypes.CDLL("libX11.so.6")
        xlib.XOpenDisplay.restype = ctypes.c_void_p
        xlib.XSetInputFocus.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_ulong,
        ]
        xlib.XFlush.argtypes = [ctypes.c_void_p]
        xlib.XCloseDisplay.argtypes = [ctypes.c_void_p]
        display = xlib.XOpenDisplay(None)
        xlib.XSetInputFocus(display, window.get_surface().get_xid(), 1, 0)
        xlib.XFlush(display)
        xlib.XCloseDisplay(display)
        pump()
        original = "前文 你好世界 后文"
        entry.set_text(original)
        entry.select_region(3, 7)
        pump()
        bridge = NativeBridge(os.environ["OPENASRINPUT_SOCKET"])
        xtest = ctypes.CDLL("libXtst.so.6")
        xtest.XTestFakeKeyEvent.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_int,
            ctypes.c_ulong,
        ]
        xlib.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]

        def command_key():
            display = xlib.XOpenDisplay(None)
            for sym, pressed in ((0xFFE9, 1), (0x7A, 1), (0x7A, 0), (0xFFE9, 0)):
                xtest.XTestFakeKeyEvent(display, xlib.XKeysymToKeycode(display, sym), pressed, 0)
                xlib.XFlush(display)
                pump(0.05)
            xlib.XCloseDisplay(display)

        command_key()
        assert bridge.poll_events() == ["command"], "Alt+Z did not reach GTK4 input context"
        lease = bridge.begin_context()
        assert lease, "GTK4 editable target unavailable"
        assert bridge.selection(lease) == "你好世界", "GTK4 did not expose selected text"
        bridge.show_cursor(lease, 1, CursorFrame("edit-listening", "翻译为英文", "▁█"))
        pump()
        assert entry.get_text() == original, "instruction preview modified original text"
        assert entry.get_selection_bounds() == (3, 7), "instruction preview changed selection"
        assert bridge.submit(lease, "translation", "Hello world") == "accepted"
        pump()
        assert entry.get_text() == "前文 Hello world 后文", repr(entry.get_text())
        assert bridge.submit(lease, "translation", "Hello world") == "accepted"
        pump()
        assert entry.get_text() == "前文 Hello world 后文"
        bridge.clear_cursor(lease)
        entry.set_text(original)
        entry.select_region(3, 7)
        pump()
        command_key()
        bridge.poll_events()
        lease = bridge.begin_context()
        assert bridge.selection(lease) == "你好世界"
        entry.select_region(0, 2)
        pump()
        assert bridge.submit(lease, "changed", "must not insert") == "stale"
        assert entry.get_text() == original
        bridge.clear_cursor(lease)
        # Real GTK deletion semantics, including reverse selections and a
        # non-BMP character: offsets must be code points, not UTF-8 bytes.
        original = "前文 你好😀世界 后文"
        for index, bounds in enumerate(((3, 8), (8, 3))):
            entry.set_text(original)
            entry.select_region(*bounds)
            pump()
            command_key()
            events = bridge.poll_events()
            lease = bridge.begin_context()
            selected = bridge.selection(lease)
            assert selected == "你好😀世界", (
                index,
                bounds,
                selected,
                entry.get_text(),
                entry.get_selection_bounds(),
                events,
            )
            assert bridge.submit(lease, f"delete-{index}", "") == "accepted"
            pump()
            assert entry.get_text() == "前文  后文", repr(entry.get_text())
            assert bridge.submit(lease, f"delete-{index}", "") == "accepted"
            assert bridge.submit(lease, f"delete-again-{index}", "") == "stale"
            pump()
            assert entry.get_text() == "前文  后文"
            bridge.clear_cursor(lease)
        entry.set_text(original)
        entry.select_region(3, 8)
        pump()
        lease = bridge.begin_context()
        # No SELECTION authorization: an empty dictation must not delete it.
        assert bridge.submit(lease, "empty-dictation", "") == "accepted"
        pump()
        assert entry.get_text() == original
        bridge.clear_cursor(lease)
        print(
            "PASS GTK4: selection snapshot, panel-only instruction, exact range replacement once, changed selection rejected"
        )
    finally:
        if bridge:
            bridge.close()
        window.destroy()
        child.terminate()
        child.wait(timeout=5)


if __name__ == "__main__":
    main()
