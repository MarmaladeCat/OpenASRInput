"""Exercise the real layer-shell panel against an isolated headless Sway."""

import os
import select
import subprocess
import tempfile
import time
from pathlib import Path

from openasrinput.adapters.native import NativeBridge
from openasrinput.domain.bridge import CursorFrame

ROOT = Path(__file__).resolve().parents[1]


def wait(predicate):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise RuntimeError("Headless Sway/panel did not become ready")


def main():
    with tempfile.TemporaryDirectory(prefix="sway-", dir=ROOT / "test-results") as directory:
        sandbox = Path(directory)
        runtime = sandbox / "r"
        runtime.mkdir(mode=0o700)
        config = sandbox / "config"
        config.write_text(
            "output * resolution 1200x900\nseat seat0 fallback true\nxwayland disable\n"
        )
        env = {
            **os.environ,
            "HOME": str(sandbox),
            "XDG_RUNTIME_DIR": str(runtime),
            "WLR_BACKENDS": "headless",
            "WLR_LIBINPUT_NO_DEVICES": "1",
            "WLR_RENDERER": "pixman",
            "WLR_HEADLESS_OUTPUTS": "2",
            "XDG_SESSION_TYPE": "wayland",
        }
        env.pop("DISPLAY", None)
        env.pop("WAYLAND_DISPLAY", None)
        shell = host = bridge = None
        with (ROOT / "test-results/sway-panel.log").open("w") as log:
            try:
                shell = subprocess.Popen(
                    ["sway", "-c", str(config)], env=env, stdout=log, stderr=subprocess.STDOUT
                )
                display = wait(
                    lambda: next((p for p in runtime.glob("wayland-*") if p.is_socket()), None)
                )
                env.update(
                    WAYLAND_DISPLAY=display.name,
                    FCITX_ADDON_DIRS=str(ROOT / "build/fcitx5/lib"),
                    XDG_DATA_DIRS=str(ROOT / "build/fcitx5/share") + ":/usr/share",
                    OPENASRINPUT_SOCKET=str(sandbox / "b.sock"),
                )
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
                assert select.select([host.stdout], [], [], 15)[0], "native host timeout"
                assert host.stdout.readline().strip() == "READY"
                bridge = NativeBridge(env["OPENASRINPUT_SOCKET"])
                lease = bridge.begin_context()
                assert lease
                bridge.show_cursor(
                    lease, 1, CursorFrame("listening", "真实 Wayland 语音面板", "▁▂▄█")
                )
                wait(lambda: bridge.request("PANEL_BACKEND") == "wayland-layer-shell")
                for position in ("top", "bottom-left", "hidden", "cursor"):
                    assert (
                        bridge.configure_panel(
                            {
                                "theme": "nord",
                                "colorMode": "dark",
                                "scale": 1,
                                "width": 640,
                                "fontSize": 15,
                                "radius": 18,
                                "position": position,
                                "transparency": 25,
                            }
                        )
                        == "accepted"
                    )
                    time.sleep(0.1)
                    assert host.poll() is None and shell.poll() is None
                bridge.clear_cursor(lease)
                print("PASS real Sway layer-shell: show, appearance changes, hide and clear")
            finally:
                if bridge:
                    bridge.close()
                for child in (host, shell):
                    if child:
                        child.terminate()
                        try:
                            child.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            child.kill()
                            child.wait()


if __name__ == "__main__":
    main()
