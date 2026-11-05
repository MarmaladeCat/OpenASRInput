"""Run ONLY inside dbus-run-session -- xvfb-run -a; no host input configuration."""

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import gi

from openasrinput.adapters.native import NativeBridge
from openasrinput.domain.bridge import CursorFrame

gi.require_version("IBus", "1.0")
from gi.repository import GLib, IBus  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def wait(predicate):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        while GLib.MainContext.default().iteration(False):
            pass
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError("IBus integration timed out")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path)
    args = parser.parse_args()
    if os.environ.get("OPENASRINPUT_ISOLATED_IBUS") != "1":
        raise RuntimeError("Use an isolated D-Bus/Xvfb and OPENASRINPUT_ISOLATED_IBUS=1")
    (ROOT / "test-results").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT / "test-results") as directory:
        root = Path(directory)
        os.environ.update(
            HOME=str(root),
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_CACHE_HOME=str(root / "cache"),
            XDG_DATA_HOME=str(root / "data"),
            XDG_RUNTIME_DIR=str(root / "run"),
            GIO_USE_VFS="local",
            IBUS_USE_PORTAL="0",
        )
        (root / "run").mkdir(mode=0o700)
        os.environ.pop("WAYLAND_DISPLAY", None)
        os.environ.pop("IBUS_ADDRESS", None)
        engine = ROOT / "src/native/ibus/engine.py"
        registry = engine.parent
        if args.package:
            payload = root / "package"
            subprocess.run(
                ["dpkg-deb", "-x", str(args.package.resolve()), str(payload)], check=True
            )
            engine = payload / "usr/lib/openasrinput/ibus/engine.py"
            registry = payload / "usr/share/ibus/component"
        os.environ["IBUS_COMPONENT_PATH"] = str(registry) + ":/usr/share/ibus/component"
        daemon = subprocess.Popen(
            ["ibus-daemon", "--single", "--panel=disable", "--config=disable"]
        )
        helper = None
        bridge = None
        try:
            IBus.init()
            bus = IBus.Bus.new()
            wait(bus.is_connected)
            assert "openasrinput" in {item.get_name() for item in bus.list_engines()}, (
                "GNOME must discover the installed source before the bridge is running"
            )
            path = root / "bridge.sock"
            helper = subprocess.Popen([sys.executable, str(engine), "--socket", str(path)])
            wait(path.exists)
            bridge = NativeBridge(path)
            context = bus.create_input_context("openasrinput-integration")
            context.set_capabilities(IBus.Capabilite.PREEDIT_TEXT | IBus.Capabilite.FOCUS)
            committed = []
            previews = []
            context.connect("commit-text", lambda _, text: committed.append(text.get_text()))
            context.connect(
                "update-preedit-text", lambda _, text, *args: previews.append(text.get_text())
            )
            context.focus_in()
            assert bus.set_global_engine("openasrinput")
            context.focus_in()
            wait(lambda: bridge.context_status()["focused"])
            assert context.process_key_event(IBus.KEY_space, 65, IBus.ModifierType.SHIFT_MASK)
            assert context.process_key_event(IBus.KEY_space, 65, IBus.ModifierType.SHIFT_MASK)
            context.process_key_event(
                IBus.KEY_space, 65, IBus.ModifierType.SHIFT_MASK | IBus.ModifierType.RELEASE_MASK
            )
            assert wait(bridge.poll_events) == ["toggle"]
            lease = bridge.begin_context()
            assert lease
            bridge.show_cursor(lease, 1, CursorFrame("listening", "临时预览", ""))
            wait(lambda: "临时预览" in previews)
            assert bridge.submit(lease, "one", "你好世界") == "accepted"
            wait(lambda: committed == ["你好世界"])
            assert bridge.submit(lease, "one", "你好世界") == "accepted"
            context.focus_out()
            wait(lambda: not bridge.valid(lease))
            assert bridge.submit(lease, "late", "禁止迟到提交") == "stale"
            assert committed == ["你好世界"]
            context.focus_in()
            # The daemon may briefly focus its fallback context before routing
            # this context again; drain that transition before acquiring a lease.
            until = time.monotonic() + 0.3
            wait(lambda: time.monotonic() >= until and bridge.context_status()["focused"])
            lease = bridge.begin_context()
            bridge.show_cursor(lease, 1, CursorFrame("listening", "不应自动提交", ""))
            wait(lambda: "不应自动提交" in previews)
            context.reset()
            wait(lambda: not bridge.valid(lease))
            assert committed == ["你好世界"]
            context.set_content_type(IBus.InputPurpose.PASSWORD, IBus.InputHints.NONE)
            wait(lambda: bridge.begin_context() is None)
            print("PASS: real IBus preedit, Unicode commit, deduplication and focus isolation")
        finally:
            if bridge:
                bridge.close()
            for process in (helper, daemon):
                if process:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()


if __name__ == "__main__":
    main()
