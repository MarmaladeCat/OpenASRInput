"""Real GTK input/selection using installed adapters in an existing test desktop."""

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

from openasrinput.adapters.native import NativeBridge
from openasrinput.domain.bridge import CursorFrame


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--framework", required=True)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--desktop", required=True)
    args = parser.parse_args()
    assert Path("/.dockerenv").exists()
    os.environ.update(
        GTK_IM_MODULE="ibus" if args.framework == "ibus" else "fcitx",
        GDK_BACKEND=args.protocol,
        IBUS_USE_PORTAL="0",
    )
    os.environ.pop("IBUS_ADDRESS", None)
    import gi

    gi.require_version("Gtk", "3.0" if args.framework == "ibus" else "4.0")
    from gi.repository import GLib, Gtk

    def pump():
        while GLib.MainContext.default().iteration(False):
            pass

    def wait(predicate, timeout=30):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            pump()
            result = predicate()
            if result:
                return result
            time.sleep(0.02)
        raise AssertionError("Input state timeout")

    def settle():
        until = time.monotonic() + 0.5
        wait(lambda: time.monotonic() >= until)

    def key(value):
        env = {**os.environ, "DISPLAY": os.environ["OPENASRINPUT_OUTER_DISPLAY"]}
        child = subprocess.Popen(["xdotool", "key", "--clearmodifiers", value], env=env)
        wait(lambda: child.poll() is not None)
        assert child.returncode == 0
        settle()

    def capture(name):
        child = subprocess.Popen(
            ["import", "-window", "root", f"/results/{name}.png"],
            env={**os.environ, "DISPLAY": os.environ["OPENASRINPUT_OUTER_DISPLAY"]},
        )
        wait(lambda: child.poll() is not None)
        assert child.returncode == 0

    path = Path(os.environ["XDG_RUNTIME_DIR"]) / "input.sock"
    os.environ["OPENASRINPUT_SOCKET"] = str(path)
    children, bridge = [], None
    failures = []
    checks = []
    phase = "startup"

    def checkpoint(name):
        checks.append(name)
        Path("/results/input.json").write_text(
            json.dumps(
                {"checks": checks, "failures": failures, "phase": phase},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    with Path("/results/input-host.log").open("w") as log:

        def launch(command):
            child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
            children.append(child)
            return child

        try:
            if os.environ.get("OPENASRINPUT_TRACE_IPC") == "1":
                # Only the disposable fixture bus: synthetic editor contents,
                # never the user's desktop/session or application documents.
                launch(["dbus-monitor", "--session", "interface='org.fcitx.Fcitx.InputContext1'"])
            if args.framework == "ibus":
                gi.require_version("IBus", "1.0")
                from gi.repository import IBus

                IBus.init()
                bus = IBus.Bus.new()
                if not bus.is_connected():
                    launch(["ibus-daemon", "--single", "--panel=disable", "--config=disable"])
                wait(bus.is_connected)
                assert "openasrinput" in {engine.get_name() for engine in bus.list_engines()}, (
                    "installed IBus engine missing from desktop catalogue"
                )
                launch(
                    [
                        "/usr/bin/python3",
                        "/usr/lib/openasrinput/ibus/engine.py",
                        "--socket",
                        str(path),
                    ]
                )
            else:
                launch(
                    [
                        "fcitx5",
                        "-D",
                        "--disable=all",
                        "--enable=openasrinput,dbus,dbusfrontend,xcb,classicui,keyboard,wayland",
                    ]
                )
            wait(path.exists)
            bridge = NativeBridge(path, timeout=5)
            window = Gtk.Window(title="OpenASRInput desktop acceptance")
            if os.environ.get("OPENASRINPUT_TRACE_DESKTOP") == "1":
                window.connect(
                    "notify::is-active",
                    lambda *_: print(
                        "EDITOR_FOCUS", time.monotonic(), window.is_active(), flush=True
                    ),
                )
            widget = Gtk.TextView()
            widget.set_property("im-module", os.environ["GTK_IM_MODULE"])
            buffer = widget.get_buffer()
            window.set_default_size(720, 260)
            if args.framework == "ibus":
                window.add(widget)
            else:
                window.set_child(widget)
            if args.framework == "ibus":
                window.show_all()
            window.present()
            widget.grab_focus()
            settle()
            if args.protocol == "x11":
                gi.require_version("GdkX11", "3.0" if args.framework == "ibus" else "4.0")
                from gi.repository import GdkX11  # noqa: F401

                surface = window.get_window() if args.framework == "ibus" else window.get_surface()
                xid = str(surface.get_xid())
                wait(window.get_mapped)
                # Searching every desktop window races unrelated Plasma popup
                # destruction (BadWindow). GDK already owns the exact client XID.
                subprocess.run(
                    [
                        "xdotool",
                        "windowactivate",
                        "--sync",
                        xid,
                        "windowfocus",
                        "--sync",
                        xid,
                        "mousemove",
                        "--window",
                        xid,
                        "60",
                        "60",
                        "click",
                        "1",
                    ],
                    check=True,
                )
            elif args.desktop == "kde":
                # A fresh Wayland client has no activation token. Click the
                # centered fixture through the nested compositor's outer display,
                # as a user would, before asserting that it owns keyboard focus.
                subprocess.run(
                    ["xdotool", "mousemove", "--sync", "640", "400", "click", "1"],
                    env={**os.environ, "DISPLAY": os.environ["OPENASRINPUT_OUTER_DISPLAY"]},
                    check=True,
                )
            wait(lambda: window.is_active() and widget.has_focus())
            if args.framework == "ibus":
                if args.desktop == "gnome":
                    subprocess.run(
                        [
                            "gsettings",
                            "set",
                            "org.gnome.desktop.input-sources",
                            "sources",
                            "[('ibus', 'openasrinput')]",
                        ],
                        check=True,
                    )
                    settle()
                assert bus.set_global_engine("openasrinput")
            try:
                wait(lambda: window.is_active() and bridge.context_status().get("focused"))
            except AssertionError:
                print(
                    "FOCUS FAILURE",
                    window.is_active(),
                    widget.has_focus(),
                    bridge.context_status(),
                    flush=True,
                )
                if args.framework == "ibus":
                    engine = bus.get_global_engine()
                    print("IBUS ENGINE", engine.get_name() if engine else None, flush=True)
                raise
            if args.framework == "ibus" and args.desktop == "gnome":
                # GNOME applies its input-source setting asynchronously, and
                # under QEMU can still replace the engine after the first focus.
                # Require a stable active source before sending the test chord.
                previous = None
                stable_since = time.monotonic()

                def stable_source():
                    nonlocal previous, stable_since
                    status = bridge.context_status()
                    engine = bus.get_global_engine()
                    current = (
                        status.get("focusEpoch"),
                        status.get("focused"),
                        engine.get_name() if engine else None,
                        window.is_active(),
                    )
                    if current != previous:
                        if os.environ.get("OPENASRINPUT_TRACE_DESKTOP") == "1":
                            print("IBUS_SOURCE", time.monotonic(), current, flush=True)
                        previous, stable_since = current, time.monotonic()
                    return (
                        current[1:] == (True, "openasrinput", True)
                        and time.monotonic() - stable_since >= 1
                    )

                wait(stable_source)
            print("READY focused editor", flush=True)
            if args.desktop == "gnome":
                from desktop_diagnostics import gnome_state

                phase = "desktop-editor-ready"

                def editor_visible():
                    state = gnome_state()
                    return (
                        state.get("window") == "OpenASRInput desktop acceptance"
                        and state.get("overview") is False
                        and state.get("modalCount") == 0
                        and (args.framework != "ibus" or state.get("inputSource") == "openasrinput")
                        and any(
                            item["title"] == state["window"]
                            and item["mapped"]
                            and item["opacity"] == 255
                            for item in state.get("windows", [])
                        )
                    )

                wait(editor_visible)
                checkpoint(phase)

            def text():
                return buffer.get_text(*buffer.get_bounds(), True)

            phase = "ordinary-input"
            key("a")
            wait(lambda: text() == "a")
            key("BackSpace")
            wait(lambda: text() == "")
            checkpoint(phase)
            phase = "shortcut"
            settle()
            key("shift+space")
            events = []
            wait(lambda: events.extend(bridge.poll_events()) or "toggle" in events)
            checkpoint("shortcut")
            phase = "preedit-isolation"
            lease = bridge.begin_context()
            assert lease, bridge.context_status()
            assert (
                bridge.show_cursor(lease, 1, CursorFrame("listening", "中文预览", "▁▃█"))
                == "accepted"
            )
            settle()

            assert text() == "", "preview became document text"
            checkpoint("preedit-isolation")
            panel = bridge.context_status().get("panel", {})
            backend = bridge.request("PANEL_BACKEND")
            capture("panel-default")
            phase = "panel-no-focus"
            for position in ("top", "bottom-right", "hidden", "cursor"):
                assert (
                    bridge.configure_panel(
                        {
                            "theme": "nord",
                            "colorMode": "dark",
                            "position": position,
                            "transparency": 35,
                            "width": 640,
                            "fontSize": 16,
                            "radius": 18,
                            "scale": 1,
                        }
                    )
                    == "accepted"
                )
                settle()
                assert window.is_active(), "editor lost focus during panel check"
                if position in ("bottom-right", "hidden"):
                    capture("panel-" + position)
            checkpoint("panel-no-focus")
            phase = "Unicode-commit"
            assert bridge.submit(lease, "dictation", "中文😀定稿") == "accepted"
            wait(lambda: text() == "中文😀定稿")
            assert bridge.submit(lease, "dictation", "中文😀定稿") == "accepted"
            settle()
            assert text() == "中文😀定稿"
            checkpoint("Unicode-commit-and-deduplication")
            bridge.clear_cursor(lease)
            settle()
            original = "前文 你好😀世界 后文"
            for index, replacement in enumerate(("Hello 😀", "", "中文替换", "")):
                phase = (
                    "selection",
                    "empty-replacement",
                    "reverse-selection",
                    "reverse-empty-replacement",
                )[index]
                buffer.set_text(original)
                widget.set_overwrite(index == 3)
                start, end = (3, 8) if index < 2 else (8, 3)
                buffer.select_range(
                    buffer.get_iter_at_offset(end), buffer.get_iter_at_offset(start)
                )
                settle()
                key("alt+z")
                events = []
                wait(lambda: events.extend(bridge.poll_events()) or "command" in events)
                lease = bridge.begin_context()
                selected = bridge.selection(lease) if lease else None
                assert selected == "你好😀世界", (index, selected, bridge.context_status())
                assert (
                    bridge.show_cursor(lease, 1, CursorFrame("edit-listening", "翻译成英文", "▃█"))
                    == "accepted"
                )
                settle()
                assert text() == original
                assert tuple(i.get_offset() for i in buffer.get_selection_bounds()) == (3, 8)
                try:
                    result = bridge.submit(lease, f"edit-{index}", replacement)
                except RuntimeError as error:
                    if replacement:
                        raise
                    failures.append({"check": "empty-replacement", "error": str(error)})
                    assert text() == original, "rejected empty replacement changed the document"
                    bridge.clear_cursor(lease)
                    settle()
                    continue
                assert result == "accepted"
                expected = "前文 " + replacement + " 后文"
                try:
                    wait(lambda: text() == expected)
                except AssertionError:
                    # Only synthetic fixture text, never user documents.
                    print(
                        "REPLACEMENT FAILURE",
                        index,
                        repr(text()),
                        repr(expected),
                        bridge.context_status(),
                        flush=True,
                    )
                    raise
                assert bridge.submit(lease, f"edit-{index}", replacement) == "accepted"
                assert bridge.submit(lease, f"edit-again-{index}", "") == "stale"
                bridge.clear_cursor(lease)
                settle()
                checkpoint(phase)
            phase = "empty-dictation-keeps-selection"
            widget.set_overwrite(False)
            buffer.set_text(original)
            buffer.select_range(buffer.get_iter_at_offset(8), buffer.get_iter_at_offset(3))
            settle()
            lease = bridge.begin_context()
            assert lease
            assert bridge.submit(lease, "empty-dictation", "") == "accepted"
            settle()
            assert text() == original
            assert tuple(i.get_offset() for i in buffer.get_selection_bounds()) == (3, 8)
            bridge.clear_cursor(lease)
            settle()
            assert tuple(i.get_offset() for i in buffer.get_selection_bounds()) == (3, 8)
            checkpoint(phase)
            phase = "caret-change-rejection"
            buffer.set_text(original)
            # Replacing a buffer that owns X11 PRIMARY queues selection-clear.
            # Let GTK process that event before the next synthetic selection;
            # otherwise it clears the freshly selected range even without an IM.
            settle()
            buffer.select_range(buffer.get_iter_at_offset(8), buffer.get_iter_at_offset(3))
            settle()
            assert tuple(i.get_offset() for i in buffer.get_selection_bounds()) == (3, 8)
            key("alt+z")
            bridge.poll_events()
            lease = bridge.begin_context()
            selected = bridge.selection(lease)
            assert selected == "你好😀世界", (
                selected,
                tuple(i.get_offset() for i in buffer.get_selection_bounds()),
                bridge.context_status(),
            )
            if args.framework == "ibus":
                key("shift+Home")
            else:
                # Fcitx5's exclusive voice mode deliberately consumes ordinary
                # editing keys. Move the actual widget selection and verify it.
                buffer.select_range(buffer.get_iter_at_offset(2), buffer.get_iter_at_offset(0))
                settle()
                assert tuple(i.get_offset() for i in buffer.get_selection_bounds()) == (0, 2)
            assert bridge.submit(lease, "moved", "禁止写入") == "stale"
            assert text() == original
            checkpoint("caret-change-rejection")
            phase = "destroyed-target-rejection"
            lease = bridge.begin_context()
            window.destroy()
            settle()
            assert bridge.submit(lease, "destroyed", "禁止写入") == "stale"
            checkpoint("destroyed-target-rejection")
            evidence = dict(
                input="real GTK3 TextView" if args.framework == "ibus" else "real GTK4 TextView",
                panelBackend=backend,
                panelStatus=panel,
                checks=checks,
                customPanel=backend in ("x11", "wayland-layer-shell", "gnome-shell")
                and panel.get("active", False),
                failures=failures,
            )
            Path("/results/input.json").write_text(
                json.dumps(evidence, ensure_ascii=False, indent=2)
            )
            print("FAIL" if failures else "PASS", json.dumps(evidence, ensure_ascii=False))
        except Exception as error:
            failures.append({"check": phase, "error": str(error)})
            partial = {"checks": checks, "failures": failures, "phase": phase}
            if args.desktop == "gnome":
                from desktop_diagnostics import gnome_state

                try:
                    partial["desktop"] = gnome_state()
                except (ValueError, subprocess.SubprocessError):
                    pass
            if bridge:
                try:
                    partial["context"] = bridge.context_status()
                except RuntimeError:
                    pass
            Path("/results/input.json").write_text(
                json.dumps(partial, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            capture("input-failure")
            raise
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
