"""Private GNOME compositor integration, invoked by check_gnome_panel.py only."""

import ast
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from openasrinput.adapters.native import NativeBridge
from openasrinput.domain.bridge import CursorFrame

ROOT = Path(__file__).resolve().parents[1]


def dbus(method="Describe"):
    output = subprocess.check_output(
        [
            "gdbus",
            "call",
            "--session",
            "--dest",
            "org.openasrinput.Panel",
            "--object-path",
            "/org/openasrinput/Panel",
            "--method",
            "org.openasrinput.Panel1." + method,
        ],
        text=True,
        stderr=subprocess.DEVNULL,
        timeout=10,
    )
    return json.loads(ast.literal_eval(output)[0])


def wait(predicate):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except (subprocess.SubprocessError, ValueError, ConnectionError):
            pass
        time.sleep(0.05)
    raise RuntimeError("GNOME panel did not reach the expected state")


def main():
    sandbox = Path(sys.argv[1])
    assert sandbox.parent == ROOT / "test-results", "private project-local sandbox required"
    if os.environ.get("OPENASRINPUT_PRIVATE_SYSTEM_BUS") == "1":
        # Supply a private bus for system-service proxies; never mount the host bus.
        os.environ["DBUS_SYSTEM_BUS_ADDRESS"] = os.environ["DBUS_SESSION_BUS_ADDRESS"]
    subprocess.run(
        ["gsettings", "set", "org.gnome.shell", "enabled-extensions", "['openasrinput@local']"],
        check=True,
    )
    subprocess.run(
        ["gsettings", "set", "org.gnome.shell", "disable-user-extensions", "false"], check=True
    )
    shell = host = bridge = None
    logfile = ROOT / "test-results/gnome-panel-test.log"
    with logfile.open("w") as log:
        try:
            shell = subprocess.Popen(
                [
                    "gnome-shell",
                    "--wayland",
                    "--no-x11",
                    "--headless",
                    "--virtual-monitor",
                    "1200x900",
                    "--virtual-monitor",
                    "800x600",
                    "--wayland-display",
                    "asr",
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            wait(lambda: dbus()["backend"] == "gnome-shell")
            # Extension export precedes Shell's startup animation/session setup.
            # Under QEMU that phase can take tens of seconds and hide early frames.
            wait(lambda: "GNOME Shell started" in logfile.read_text(errors="replace"))
            env = {
                **os.environ,
                "WAYLAND_DISPLAY": "asr",
                "FCITX_ADDON_DIRS": str(ROOT / "build/fcitx5/lib"),
                "XDG_DATA_DIRS": str(ROOT / "build/fcitx5/share") + ":/usr/share",
                "OPENASRINPUT_SOCKET": str(sandbox / "bridge.sock"),
            }
            host = subprocess.Popen(
                [
                    str(ROOT / "build/fcitx5/native_host"),
                    "-D",
                    "--disable=all",
                    "--enable=openasrinput",
                ],
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=log,
                text=True,
            )
            assert host.stdout.readline().strip() == "READY"
            bridge = NativeBridge(sandbox / "bridge.sock")
            lease = bridge.begin_context()
            assert lease is not None
            revision = 0

            def first_frame():
                nonlocal revision
                revision += 1
                bridge.show_cursor(
                    lease, revision, CursorFrame("listening", "原生 Wayland 图形面板。", "▁▂▄▆█▆▄▂")
                )
                return dbus()["visible"]

            wait(first_frame)
            assert bridge.request("PANEL_BACKEND") == "gnome-shell"
            status = dbus()
            assert not status["reactive"] and not status["canFocus"]
            bridge.show_cursor(
                lease, revision + 1, CursorFrame("listening", "原生 Wayland 图形面板。", "▁▁▃▅▇█▆▂")
            )
            wait(lambda: dbus()["frames"] >= 2)
            settings = {
                "theme": "nord",
                "colorMode": "dark",
                "scale": 1.25,
                "width": 640,
                "fontSize": 18,
                "radius": 20,
                "position": "top-right",
                "transparency": 50,
            }
            bridge.configure_panel(settings)
            wait(lambda: dbus().get("position") == "top-right" and dbus().get("opacity") == 128)
            top = dbus()["geometry"]
            assert "panel-layout-v2" in dbus()["capabilities"]
            # No new SHOW/audio: THEME must move/repaint the current surface itself.
            settings.update(position="bottom-left", transparency=25)
            bridge.configure_panel(settings)
            wait(lambda: dbus().get("position") == "bottom-left" and dbus().get("opacity") == 191)
            bottom = dbus()["geometry"]
            assert bottom["x"] < top["x"] and bottom["y"] > top["y"]
            monitors = dbus()["monitors"]
            assert len(monitors) == 2
            settings["position"] = "bottom"
            bridge.configure_panel(settings)
            for index in (1, 0, 1, 0):
                monitor = monitors[index]
                host.stdin.write(f"RECT_ONLY {monitor['x'] + 100} {monitor['y'] + 100} 2 24\n")
                host.stdin.flush()
                assert host.stdout.readline().strip() == "OK"
                wait(lambda: dbus()["monitorIndex"] == index)
                geometry = dbus()["geometry"]
                assert monitor["x"] <= geometry["x"]
                assert geometry["x"] + geometry["width"] <= monitor["x"] + monitor["width"]
                assert geometry["y"] > monitor["y"] + monitor["height"] / 2
                assert geometry["y"] + geometry["height"] <= monitor["y"] + monitor["height"]
            settings["position"] = "hidden"
            bridge.configure_panel(settings)
            wait(lambda: not dbus()["visible"])
            settings["position"] = "top"
            bridge.configure_panel(settings)
            wait(lambda: dbus()["visible"] and dbus().get("position") == "top")
            settings["transparency"] = 100
            bridge.configure_panel(settings)
            wait(lambda: not dbus()["visible"])
            settings["transparency"] = 0
            bridge.configure_panel(settings)
            wait(lambda: dbus()["visible"] and dbus().get("opacity") == 255)
            fixed = dbus()["geometry"]
            host.stdin.write("RECT_ONLY 300 400 2 24\n")
            host.stdin.flush()
            assert host.stdout.readline().strip() == "OK"
            assert dbus()["geometry"] == fixed  # Fixed mode ignores cursor movement.
            settings["position"] = "cursor"
            bridge.configure_panel(settings)
            wait(lambda: dbus()["geometry"]["x"] == 300)
            host.stdin.write("RECT_ONLY 100 200 2 24\n")
            host.stdin.flush()
            assert host.stdout.readline().strip() == "OK"
            wait(lambda: dbus()["geometry"]["x"] == 100 and dbus()["geometry"]["y"] == 232)
            host.stdin.write("SNAPSHOT\n")
            host.stdin.flush()
            snapshot = host.stdout.readline().strip().split("\t")
            assert bytes.fromhex(snapshot[1]).decode() == "原生 Wayland 图形面板。"
            assert len(snapshot) == 4 and snapshot[3] == "0"  # No commit or application deletion.
            bridge.clear_cursor(lease)
            wait(lambda: not dbus()["visible"])
            lease = bridge.begin_context()
            bridge.show_cursor(lease, 1, CursorFrame("listening", "焦点变化会隐藏面板", "▃▅█"))
            wait(lambda: dbus()["visible"])
            host.stdin.write("FOCUS2\n")
            host.stdin.flush()
            assert host.stdout.readline().strip() == "OK"
            wait(lambda: not dbus()["visible"])
            lease = bridge.begin_context()
            bridge.show_cursor(lease, 1, CursorFrame("listening", "进程退出会隐藏面板", "▁▅█"))
            wait(lambda: dbus()["visible"])
            host.kill()
            host.wait()
            wait(lambda: not dbus()["visible"])
            os.environ["WAYLAND_DISPLAY"] = "asr"
            subprocess.run(["dbus-update-activation-environment", "WAYLAND_DISPLAY"], check=True)
            errors = subprocess.check_output(
                [
                    "gdbus",
                    "call",
                    "--session",
                    "--dest",
                    "org.gnome.Shell.Extensions",
                    "--object-path",
                    "/org/gnome/Shell/Extensions",
                    "--method",
                    "org.gnome.Shell.Extensions.GetExtensionErrors",
                    "openasrinput@local",
                ],
                text=True,
            )
            assert "@as []" in errors or errors.strip() == "([],)", errors
            os.environ["WAYLAND_DISPLAY"] = "asr"
            spec = importlib.util.spec_from_file_location(
                "ibus_panel", ROOT / "src/native/ibus/panel_client.py"
            )
            adapter = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(adapter)
            panel = adapter.Panel()
            try:
                wait(lambda: panel.request("STATUS").get("backend") == "gnome-shell")
                panel.request("ANCHOR", 200, 300, 2, 24, 0)
                panel.show("IBus 复用原生面板", "▁▃█", "edit-listening")
                wait(lambda: dbus()["visible"])
                assert not dbus()["reactive"] and not dbus()["canFocus"]
                colors = (
                    "ffffff,f8fafc,dbe4ee,1e293b,64748b,475569,38b8ab,6366f1,eef2ff,ecfdf5,15803d"
                )
                panel.request("THEME", "material:light", 1, 640, 16, 18, colors, "top-right", 35)
                wait(lambda: dbus().get("position") == "top-right")
                panel.request("THEME", "material:light", 1, 640, 16, 18, colors, "hidden", 35)
                wait(lambda: not dbus()["visible"])
            finally:
                panel.close()
            print(
                "PASS IBus standalone renderer -> GNOME Shell: shared appearance, no focus, hot hide and child cleanup"
            )
            print(
                "PASS GNOME native Wayland (no X11): real addon -> Shell graphics, theme/scale, click-through, preedit isolation, focus loss, process disconnect"
            )
        finally:
            if bridge:
                bridge.close()
            for process in (host, shell):
                if process and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()


if __name__ == "__main__":
    main()
