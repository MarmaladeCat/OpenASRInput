"""Qt5 selection regression; run inside an isolated D-Bus/Xvfb container."""

import argparse
import os
import subprocess
import tempfile
import time
from pathlib import Path

from PyQt5.QtWidgets import QApplication, QLineEdit, QTextEdit

from openasrinput.adapters.native import NativeBridge
from openasrinput.domain.bridge import CursorFrame


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--framework", choices=("fcitx5", "ibus"), default="fcitx5")
    parser.add_argument("--bmp", action="store_true", help="separate BMP-only control case")
    args = parser.parse_args()
    assert Path("/.dockerenv").is_file()
    selected_text = "你好汉世界" if args.bmp else "你好😀世界"
    selected_units = len(selected_text.encode("utf-16-le")) // 2
    original = "前文 " + selected_text + " 后文"
    with tempfile.TemporaryDirectory(prefix="qt-selection-") as directory:
        os.environ.update(
            HOME=directory,
            XDG_CONFIG_HOME=directory,
            XDG_RUNTIME_DIR=directory,
            QT_IM_MODULE="ibus" if args.framework == "ibus" else "fcitx",
            OPENASRINPUT_SOCKET=directory + "/input.sock",
        )
        app = None
        os.environ.pop("IBUS_ADDRESS", None)
        # Qt5 checks presence, not the value: even "0" enables the portal.
        os.environ.pop("IBUS_USE_PORTAL", None)
        children = []
        bridge = None
        bus = None
        glib = None

        def settle(seconds=0.3):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                if app:
                    app.processEvents()
                if glib:
                    while glib.MainContext.default().iteration(False):
                        pass
                time.sleep(0.01)

        try:
            if args.framework == "ibus":
                import gi

                gi.require_version("IBus", "1.0")
                from gi.repository import GLib, IBus

                glib = GLib
                children.append(
                    subprocess.Popen(
                        ["ibus-daemon", "--single", "--panel=disable", "--config=disable"]
                    )
                )
                IBus.init()
                bus = IBus.Bus.new()
                for _ in range(50):
                    if bus.is_connected():
                        break
                    settle()
                assert bus.is_connected(), "IBus did not start"
                children.append(
                    subprocess.Popen(
                        [
                            "/usr/bin/python3",
                            "/usr/lib/openasrinput/ibus/engine.py",
                            "--socket",
                            os.environ["OPENASRINPUT_SOCKET"],
                        ]
                    )
                )
            else:
                children.append(
                    subprocess.Popen(
                        [
                            "fcitx5",
                            "-D",
                            "--disable=all",
                            "--enable=openasrinput,dbus,dbusfrontend,xcb,classicui,keyboard",
                        ]
                    )
                )
            for _ in range(50):
                if Path(os.environ["OPENASRINPUT_SOCKET"]).exists():
                    break
                settle()
            bridge = NativeBridge(os.environ["OPENASRINPUT_SOCKET"], timeout=5)
            app = QApplication([])
            app.setQuitOnLastWindowClosed(False)
            for Widget in (QLineEdit, QTextEdit):
                widget = Widget()
                widget.setWindowTitle("Qt selection compatibility")
                widget.resize(600, 120)
                widget.show()
                settle()
                subprocess.run(
                    [
                        "xdotool",
                        "windowfocus",
                        "--sync",
                        str(int(widget.winId())),
                        "mousemove",
                        "--window",
                        str(int(widget.winId())),
                        "60",
                        "60",
                        "click",
                        "1",
                    ],
                    check=True,
                )
                widget.activateWindow()
                widget.setFocus()
                settle()
                if bus:
                    assert bus.set_global_engine("openasrinput")
                    settle()
                for index, replacement in enumerate(("Hello 😀", "", "")):
                    if Widget is QLineEdit:
                        widget.setText(original)
                        widget.setSelection(
                            3 if index < 2 else 3 + selected_units,
                            selected_units if index < 2 else -selected_units,
                        )
                        text = widget.text
                    else:
                        widget.setPlainText(original)
                        widget.setOverwriteMode(index == 2)
                        cursor = widget.textCursor()
                        cursor.setPosition(3 if index < 2 else 3 + selected_units)
                        cursor.setPosition(
                            3 + selected_units if index < 2 else 3, cursor.KeepAnchor
                        )
                        widget.setTextCursor(cursor)
                        text = widget.toPlainText
                    settle()
                    lease = bridge.begin_context()
                    assert lease, bridge.context_status()
                    selected = bridge.selection(lease)
                    assert selected == selected_text, repr(selected)
                    bridge.show_cursor(lease, 1, CursorFrame("edit-listening", "删除选区", "▂█"))
                    settle()
                    assert text() == original
                    assert (
                        bridge.submit(lease, f"{Widget.__name__}-{index}", replacement)
                        == "accepted"
                    )
                    settle()
                    expected = "前文 " + replacement + " 后文"
                    print(Widget.__name__, index, repr(text()), repr(expected), flush=True)
                    assert text() == expected
                    assert (
                        bridge.submit(lease, f"{Widget.__name__}-{index}", replacement)
                        == "accepted"
                    )
                    assert bridge.submit(lease, f"{Widget.__name__}-again-{index}", "") == "stale"
                    settle()
                    assert text() == expected
                    bridge.clear_cursor(lease)
                    settle()
                if Widget is QLineEdit:
                    widget.setText(original)
                    widget.setSelection(3, selected_units)
                else:
                    widget.setPlainText(original)
                    widget.setOverwriteMode(False)
                    cursor = widget.textCursor()
                    cursor.setPosition(3)
                    cursor.setPosition(3 + selected_units, cursor.KeepAnchor)
                    widget.setTextCursor(cursor)
                settle()

                def selection():
                    if Widget is QLineEdit:
                        return widget.selectionStart(), widget.selectedText()
                    cursor = widget.textCursor()
                    return cursor.selectionStart(), cursor.selectedText()

                lease = bridge.begin_context()
                assert bridge.submit(lease, f"{Widget.__name__}-empty-dictation", "") == "accepted"
                settle()
                assert text() == original
                assert selection() == (3, selected_text), selection()
                bridge.clear_cursor(lease)
                settle()
                assert selection() == (3, selected_text), selection()
                widget.close()
                settle()
            print(
                "PASS Qt5 line/text edit selections",
                args.framework,
                "BMP-only" if args.bmp else "including non-BMP",
            )
        finally:
            if bridge:
                bridge.close()
            for child in reversed(children):
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()


if __name__ == "__main__":
    main()
