"""Real GTK3 text entry using IBus on isolated X11 or headless Sway/Wayland."""

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from openasrinput.adapters.native import NativeBridge
from openasrinput.domain.bridge import CursorFrame

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wayland", action="store_true")
    parser.add_argument("--gtk4", action="store_true")
    parser.add_argument("--selection", action="store_true")
    parser.add_argument("--unsupported-selection", action="store_true")
    parser.add_argument("--require-panel", action="store_true")
    parser.add_argument("--package", type=Path)
    args = parser.parse_args()
    children = []
    bridge = None
    with tempfile.TemporaryDirectory(prefix="ig-", dir=ROOT / "test-results") as directory:
        home = Path(directory)
        runtime = home / "r"
        runtime.mkdir(mode=0o700)
        os.environ.update(
            HOME=directory,
            XDG_CONFIG_HOME=str(home / "config"),
            XDG_CACHE_HOME=str(home / "cache"),
            XDG_RUNTIME_DIR=str(runtime),
            GTK_IM_MODULE="ibus",
            GIO_USE_VFS="local",
            IBUS_USE_PORTAL="0",
        )
        os.environ.pop("IBUS_ADDRESS", None)
        os.environ.pop("WAYLAND_DISPLAY", None)
        log_path = (
            ROOT
            / "test-results"
            / ("ibus-gtk-wayland-host.log" if args.wayland else "ibus-gtk-x11-host.log")
        )
        with log_path.open("w") as log:
            try:
                if args.wayland:
                    os.environ.pop("DISPLAY", None)
                    os.environ.update(
                        WLR_BACKENDS="headless",
                        WLR_RENDERER="pixman",
                        WLR_LIBINPUT_NO_DEVICES="1",
                        GDK_BACKEND="wayland",
                    )
                    config = home / "sway.conf"
                    config.write_text(
                        "output * resolution 1200x900\nseat seat0 fallback true\nxwayland disable\n"
                    )
                    children.append(
                        subprocess.Popen(["sway", "-c", str(config)], stdout=log, stderr=log)
                    )
                    deadline = time.monotonic() + 15
                    display = None
                    while time.monotonic() < deadline:
                        display = next(
                            (path for path in runtime.glob("wayland-*") if path.is_socket()), None
                        )
                        if display:
                            break
                        assert children[-1].poll() is None, "Sway exited"
                        time.sleep(0.05)
                    assert display, "Sway did not publish a Wayland socket"
                    os.environ["WAYLAND_DISPLAY"] = display.name
                else:
                    os.environ["GDK_BACKEND"] = "x11"
                import gi

                gi.require_version("IBus", "1.0")
                gi.require_version("Gtk", "4.0" if args.gtk4 else "3.0")
                from gi.repository import GLib, Gtk, IBus

                def wait(predicate):
                    deadline = time.monotonic() + 15
                    while time.monotonic() < deadline:
                        while GLib.MainContext.default().iteration(False):
                            pass
                        value = predicate()
                        if value:
                            return value
                        time.sleep(0.02)
                    raise AssertionError("GTK/IBus state timeout; see " + str(log_path))

                children.append(
                    subprocess.Popen(
                        ["ibus-daemon", "--single", "--panel=disable", "--config=disable"],
                        stdout=log,
                        stderr=log,
                    )
                )
                IBus.init()
                bus = IBus.Bus.new()
                wait(bus.is_connected)
                path = home / "b.sock"
                engine = ROOT / "src/native/ibus/engine.py"
                if args.package:
                    payload = home / "package"
                    subprocess.run(
                        ["dpkg-deb", "-x", str(args.package.resolve()), str(payload)], check=True
                    )
                    engine = payload / "usr/lib/openasrinput/ibus/engine.py"
                children.append(
                    subprocess.Popen(
                        [
                            sys.executable,
                            str(engine),
                            "--socket",
                            str(path),
                        ],
                        stdout=log,
                        stderr=log,
                    )
                )
                wait(path.exists)
                bridge = NativeBridge(path)
                window = Gtk.Window(title="OpenASRInput IBus isolated test")
                widget = Gtk.TextView() if args.gtk4 or args.selection else Gtk.Entry()
                widget.set_property("im-module", "ibus")
                entry = widget
                if args.gtk4 or args.selection:

                    class TextEditor:
                        def set_text(self, text):
                            widget.get_buffer().set_text(text)

                        def get_text(self):
                            buffer = widget.get_buffer()
                            return buffer.get_text(*buffer.get_bounds(), True)

                        def select_region(self, start, end):
                            buffer = widget.get_buffer()
                            buffer.select_range(
                                buffer.get_iter_at_offset(end), buffer.get_iter_at_offset(start)
                            )

                        def get_selection_bounds(self):
                            return tuple(
                                item.get_offset()
                                for item in widget.get_buffer().get_selection_bounds()
                            )

                        def grab_focus(self):
                            widget.grab_focus()

                        def has_focus(self):
                            return widget.has_focus()

                    entry = TextEditor()
                if args.gtk4:
                    window.set_child(widget)
                    window.set_default_size(800, 200)
                else:
                    window.add(widget)
                    window.set_default_size(800, 200)
                    window.show_all()
                window.present()
                entry.grab_focus()
                if args.wayland:
                    # Headless wlroots has no physical keyboard. Keep a virtual
                    # keyboard alive so GTK receives actual keyboard-seat focus.
                    children.append(
                        subprocess.Popen(
                            ["wtype", "-k", "Shift_L", "-s", "60000"], stdout=log, stderr=log
                        )
                    )
                if not args.wayland:
                    if args.gtk4:
                        wait(window.get_mapped)
                        subprocess.run(
                            [
                                "xdotool",
                                "search",
                                "--name",
                                "OpenASRInput IBus isolated test",
                                "windowfocus",
                            ],
                            check=True,
                        )
                    else:
                        window.get_window().focus(0)
                        window.get_display().flush()
                assert bus.set_global_engine("openasrinput")
                wait(lambda: bridge.context_status()["focused"])
                wait(
                    lambda: (
                        window.is_active()
                        and (entry.has_focus() or (args.gtk4 and window.get_focus() is not None))
                    )
                )
                epoch, stable_since = None, time.monotonic()

                def settled():
                    nonlocal epoch, stable_since
                    current = bridge.context_status()["focusEpoch"]
                    if current != epoch:
                        epoch, stable_since = current, time.monotonic()
                    return time.monotonic() - stable_since > 0.3

                wait(settled)
                lease = bridge.begin_context()
                assert lease
                assert (
                    bridge.show_cursor(lease, 1, CursorFrame("listening", "尚未定稿", ""))
                    == "accepted"
                )
                for _ in range(20):
                    while GLib.MainContext.default().iteration(False):
                        pass
                    time.sleep(0.01)
                assert entry.get_text() == "", "preview must not become document text"
                if args.require_panel:
                    status = bridge.context_status()["panel"]
                    assert status["backend"] == (
                        "wayland-layer-shell" if args.wayland else "x11"
                    ), status
                    for position in ("top", "bottom-right", "hidden", "cursor"):
                        assert (
                            bridge.configure_panel(
                                {
                                    "theme": "nord",
                                    "colorMode": "dark",
                                    "scale": 1.2,
                                    "width": 640,
                                    "fontSize": 16,
                                    "radius": 20,
                                    "position": position,
                                    "transparency": 35,
                                }
                            )
                            == "accepted"
                        )
                        status = bridge.context_status()["panel"]
                        assert status["position"] == position and status["transparency"] == 35, (
                            status
                        )
                        assert window.is_active(), "custom panel stole keyboard focus"
                assert bridge.submit(lease, "gtk-commit", "真实输入框中文。") == "accepted", (
                    bridge.context_status()
                )
                wait(lambda: entry.get_text() == "真实输入框中文。")
                if args.gtk4 or args.selection:

                    def pump():
                        end = time.monotonic() + 0.4
                        wait(lambda: time.monotonic() > end)

                    def command_key():
                        command = (
                            ["wtype", "-M", "alt", "-k", "z", "-m", "alt"]
                            if args.wayland
                            else ["xdotool", "key", "alt+z"]
                        )
                        key = subprocess.Popen(command, stdout=log, stderr=log)
                        children.append(key)
                        wait(lambda: key.poll() is not None)
                        assert key.returncode == 0
                        events = []
                        wait(lambda: events.extend(bridge.poll_events()) or "command" in events)
                        pump()

                    bridge.clear_cursor(lease)
                    original = "前文 你好😀世界 后文"
                    if args.unsupported_selection:
                        entry.set_text(original)
                        entry.select_region(3, 8)
                        pump()
                        command_key()
                        lease = bridge.begin_context()
                        assert bridge.request("SELECTION", lease.lease_id) == "unsupported"
                        bridge.clear_cursor(lease)
                        assert entry.get_text() == original and entry.get_selection_bounds() == (
                            3,
                            8,
                        )
                        print(
                            "PASS unsupported GTK4 selection: explicitly rejected; document and selection preserved"
                        )
                    for index, replacement in enumerate(
                        () if args.unsupported_selection else ("Hello 😀", "", "替换中文")
                    ):
                        entry.set_text(original)
                        entry.select_region(3, 8) if index != 2 else entry.select_region(8, 3)
                        pump()
                        command_key()
                        lease = bridge.begin_context()
                        selected = bridge.selection(lease)
                        assert selected == "你好😀世界", (
                            selected,
                            entry.get_selection_bounds(),
                            bridge.context_status(),
                        )
                        assert (
                            bridge.show_cursor(
                                lease, 1, CursorFrame("edit-listening", "翻译成英文", "▁█")
                            )
                            == "accepted"
                        )
                        pump()
                        assert entry.get_text() == original
                        assert entry.get_selection_bounds() == (3, 8), entry.get_selection_bounds()
                        if index == 0 and not args.wayland and args.require_panel:
                            subprocess.run(
                                [
                                    "import",
                                    "-window",
                                    "root",
                                    str(ROOT / "test-results/ibus-selection-panel.png"),
                                ],
                                check=True,
                            )
                        assert bridge.submit(lease, f"edit-{index}", replacement) == "accepted"
                        wait(lambda: entry.get_text() == "前文 " + replacement + " 后文")
                        assert bridge.submit(lease, f"edit-{index}", replacement) == "accepted"
                        pump()
                        assert entry.get_text() == "前文 " + replacement + " 后文"
                        bridge.clear_cursor(lease)
                    if not args.unsupported_selection:
                        entry.set_text(original)
                        entry.select_region(3, 8)
                        pump()
                        command_key()
                        lease = bridge.begin_context()
                        assert bridge.selection(lease) == "你好😀世界"
                        # Exercise a real user selection change. Some GTK/IBus
                        # versions do not notify programmatic buffer selection.
                        command = (
                            ["wtype", "-M", "shift", "-k", "Home", "-m", "shift"]
                            if args.wayland
                            else ["xdotool", "key", "shift+Home"]
                        )
                        key = subprocess.Popen(command, stdout=log, stderr=log)
                        children.append(key)
                        wait(lambda: key.poll() is not None)
                        assert key.returncode == 0
                        pump()
                        entry.select_region(3, 8)
                        pump()
                        assert bridge.submit(lease, "changed", "禁止替换") == "stale"
                        assert entry.get_text() == original
                        print(
                            "PASS IBus selection: Unicode, reverse selection, empty replacement, deduplication, moved-away-and-back rejection"
                        )
                # Starting another preview then losing the real widget must not commit it.
                if not bridge.valid(lease):
                    lease = bridge.begin_context()
                assert lease
                bridge.show_cursor(lease, 2, CursorFrame("listening", "取消的预览", ""))
                window.destroy()
                wait(lambda: not bridge.valid(lease))
                assert bridge.submit(lease, "late", "迟到") == "stale"
                print(
                    "PASS real GTK4/IBus" if args.gtk4 else "PASS real GTK3/IBus",
                    "Wayland" if args.wayland else "X11",
                    "preedit isolation, Unicode commit and widget destruction",
                )
            finally:
                if bridge:
                    bridge.close()
                for child in reversed(children):
                    child.terminate()
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait()


if __name__ == "__main__":
    main()
