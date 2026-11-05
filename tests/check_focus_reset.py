"""Real native addon focus/click-reset reproduction, isolated from the host desktop."""

import argparse
import os
import subprocess
import tempfile
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
    build = args.build.resolve()
    with tempfile.TemporaryDirectory(prefix="fr-", dir=ROOT / "test-results") as directory:
        stage = Path(directory)
        env = {
            **os.environ,
            "HOME": str(stage / "home"),
            "XDG_CONFIG_HOME": str(stage / "config"),
            "XDG_DATA_HOME": str(stage / "data"),
            "XDG_CACHE_HOME": str(stage / "cache"),
            "XDG_RUNTIME_DIR": str(stage / "run"),
            "TMPDIR": str(stage / "tmp"),
            "FCITX_ADDON_DIRS": str(build / "lib"),
            "XDG_DATA_DIRS": str(build / "share") + ":/usr/share",
            "OPENASRINPUT_SOCKET": str(stage / "bridge.sock"),
        }
        for name in ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "XMODIFIERS"):
            env.pop(name, None)
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
            env["FCITX_ADDON_DIRS"] = str(library.parent)
            env["XDG_DATA_DIRS"] = str(payload / "usr/share") + ":/usr/share"
        child = subprocess.Popen(
            [str(build / "native_host"), "-D", "--disable=all", "--enable=openasrinput"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            env=env,
            cwd=ROOT,
        )
        bridge = None
        try:
            assert child.stdout.readline().strip() == "READY"
            bridge = NativeBridge(env["OPENASRINPUT_SOCKET"])

            def command(value):
                child.stdin.write(value + "\n")
                child.stdin.flush()
                assert child.stdout.readline().strip() == "OK"

            core = Controller(bridge)
            # Return from another application, click, and immediately start speech.
            command("FOCUS2")
            command("FOCUS1")
            command("RESET")
            for event in ("DOWN Shift_L", "DOWN Shift+space", "UP Shift+space", "UP Shift_L"):
                command(event)
            assert bridge.poll_events() == ["toggle"]
            core.toggle()
            core.take_effects()
            assert core.bind_session(core.generation, "synthetic")
            core.on_event(
                core.generation,
                {
                    "type": "session.ready",
                    "sessionId": "synthetic",
                    "seq": 1,
                    "audio": AUDIO,
                    "finalizeTimeoutMs": 1000,
                },
            )
            core.drain()
            assert core.state == "listening"
            # GTK's click/focus synchronization may reset composition after acquisition.
            command("RESET")
            core.tick()
            core.drain()
            assert core.state == "listening", (
                f"reproduced immediate stop: {core.state}, {core.stop_reason}"
            )
            lease = core.lease
            assert (
                bridge.show_cursor(lease, 20, CursorFrame("listening", "只作预览", "▁█"))
                == "accepted"
            )
            command("RESET")
            assert bridge.valid(lease), "same-target composition reset revoked a live voice lease"
            assert bridge.submit(lease, "one", "稳定定稿") == "accepted"
            # Genuine target changes remain irrevocable; no old result may enter another app.
            command("FOCUS2")
            assert not bridge.valid(lease)
            command("FOCUS1")
            assert not bridge.valid(lease)
            assert bridge.submit(lease, "late", "不得误输入") == "stale"
            for round_ in range(20):
                command("FOCUS2")
                command("FOCUS1")
                command("RESET")
                bridge.poll_events()
                modifier, key = ("Alt_L", "Alt+z") if round_ % 2 else ("Shift_L", "Shift+space")
                command("DOWN " + modifier)
                command("DOWN " + key)
                command("RESET")  # Late reset while the activation modifier is still held.
                command("UP " + key)
                command("UP " + modifier)
                assert bridge.poll_events() == ["command" if modifier == "Alt_L" else "toggle"], (
                    "composition reset duplicated or swallowed the shortcut"
                )
                active = bridge.begin_context()
                assert active
                bridge.show_cursor(active, 1, CursorFrame("listening", "", "▁"))
                command("RESET")
                assert bridge.valid(active), "rapid app return stopped recording"
                bridge.clear_cursor(active)
            active = bridge.begin_context()
            command("PASSWORD")
            assert not bridge.valid(active), "password-field capability change retained a lease"
            assert bridge.submit(active, "password-late", "不得输入") == "stale"
            command("EDITABLE")
            assert not bridge.valid(active), "capability recovery resurrected an old lease"
            state = bridge.context_status()
            assert state["preservedResets"] >= 20 and state["lastInvalidation"] == "not-editable"
            # Alt+Tab / desktop shortcuts can send focus-out without delivering
            # the modifier release to this frontend. The next chord must recover.
            for lost, modifier, key in (
                ("Alt_L", "Shift_L", "Shift+space"),
                ("Shift_L", "Alt_L", "Alt+z"),
                ("Shift_L", "Shift_L", "Shift+space"),
                ("Alt_L", "Alt_L", "Alt+z"),
            ):
                bridge.poll_events()
                command("DOWN " + lost)
                command("FOCUS2")
                command("FOCUS1")
                # Intentionally omit UP: it happened outside the input frontend.
                assert bridge.context_status()["chord"]["blocked"]
                command("DOWN " + modifier)
                command("DOWN " + key)
                command("UP " + key)
                command("UP " + modifier)
                assert bridge.poll_events() == ["command" if modifier == "Alt_L" else "toggle"], (
                    f"lost {lost} release permanently blocked {key}"
                )
                assert not bridge.context_status()["chord"]["blocked"]
            # A genuinely held modifier across focus changes is still blocked:
            # returning to an editor must not turn a continued chord into speech.
            command("DOWN Shift_L")
            command("FOCUS2")
            command("FOCUS1")
            command("DOWN Shift+space")
            command("UP Shift+space")
            command("UP Shift_L")
            assert bridge.poll_events() == []
            # The chord's key release can also be lost after activation.
            for modifier, key in (("Shift_L", "Shift+space"), ("Alt_L", "Alt+z")):
                command("DOWN " + modifier)
                command("DOWN " + key)
                assert bridge.poll_events() == ["command" if modifier == "Alt_L" else "toggle"]
                command("FOCUS2")
                command("FOCUS1")
                command("DOWN " + modifier)
                command("DOWN " + key)
                command("UP " + key)
                command("UP " + modifier)
                assert bridge.poll_events() == ["command" if modifier == "Alt_L" else "toggle"], (
                    "lost chord release blocked reactivation"
                )
            assert bridge.context_status()["chord"]["recovered"] >= 6
            # Esc must release voice ownership without requiring a daemon or
            # Fcitx restart. Include cancellation while a shortcut modifier is held.
            for round_ in range(20):
                modifier, key = ("Alt_L", "Alt+z") if round_ % 2 else ("Shift_L", "Shift+space")
                core = Controller(bridge)
                core.toggle()
                core.take_effects()
                assert core.bind_session(core.generation, "escape-restart")
                core.on_event(
                    core.generation,
                    {
                        "type": "session.ready",
                        "sessionId": "escape-restart",
                        "seq": 1,
                        "audio": AUDIO,
                        "finalizeTimeoutMs": 1000,
                    },
                )
                core.drain()
                assert core.state == "listening"
                if round_ % 4 < 2:
                    command("DOWN " + modifier)
                command("DOWN Escape")
                command("UP Escape")
                assert bridge.poll_events() == ["cancel"]
                core.cancel()
                core.drain()
                if round_ % 4 < 2:
                    command("UP " + modifier)
                command("DOWN " + modifier)
                command("DOWN " + key)
                command("UP " + key)
                command("UP " + modifier)
                assert bridge.poll_events() == ["command" if modifier == "Alt_L" else "toggle"], (
                    "Esc blocked next activation"
                )
                core.toggle()
                core.drain()
                assert core.state == "connecting" and bridge.valid(core.lease)
                core.cancel()
                core.drain()
            original = "前文 你好世界 后文"
            command(f"SURROUNDING {original.encode().hex()} 7 3")
            selection_lease = bridge.begin_context()
            assert bridge.selection(selection_lease) == "你好世界"
            bridge.show_cursor(selection_lease, 1, CursorFrame("edit-listening", "翻译为英文", "▁"))
            assert bridge.submit(selection_lease, "edit-1", "Hello world") == "accepted"
            assert bridge.submit(selection_lease, "edit-1", "Hello world") == "accepted"
            bridge.clear_cursor(selection_lease)
            command(f"SURROUNDING {original.encode().hex()} 7 3")
            selection_lease = bridge.begin_context()
            assert bridge.selection(selection_lease) == "你好世界"
            command(f"SURROUNDING {original.encode().hex()} 7 7")
            assert bridge.submit(selection_lease, "changed-selection", "must not insert") == "stale"
            bridge.clear_cursor(selection_lease)
            command(f"SURROUNDING {original.encode().hex()} 0 0")
            selection_lease = bridge.begin_context()
            assert bridge.selection(selection_lease) == ""
            bridge.clear_cursor(selection_lease)
            print(
                "PASS native focus reset: app return/click/start, same-target resets, stable final, genuine focus loss and stale result isolation"
            )
        finally:
            if bridge:
                bridge.close()
            child.terminate()
            child.wait(timeout=5)


if __name__ == "__main__":
    main()
