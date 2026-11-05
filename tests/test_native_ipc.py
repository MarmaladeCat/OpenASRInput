"""Load the real addon in a disposable native frontend and test its Unix IPC."""

import argparse
import asyncio
import os
import struct
import subprocess
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

from openasrinput.adapters.native import NativeBridge
from openasrinput.application.controller import Controller
from openasrinput.application.runtime import ConfigRuntime
from openasrinput.domain.bridge import CursorFrame
from openasrinput.domain.ledger import AUDIO
from openasrinput.infrastructure.config import DEFAULTS, EDITABLE, ConfigStore

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(
        description="Native addon IPC and optional cursor-panel screenshot"
    )
    parser.add_argument("--build", type=Path, default=ROOT / "build/fcitx5")
    parser.add_argument("--package", type=Path, help="load the plugin from an extracted Fcitx5 deb")
    parser.add_argument(
        "--direct-panel",
        action="store_true",
        help="expect a baseline-built plugin without custom panel callbacks (requires --visual)",
    )
    parser.add_argument(
        "--visual", action="store_true", help="use an isolated X11 DISPLAY (e.g. xvfb-run)"
    )
    parser.add_argument(
        "--wayland-fallback",
        action="store_true",
        help="check a relative-coordinate Wayland context through an isolated XWayland-style status surface",
    )
    parser.add_argument(
        "--installed-layout",
        action="store_true",
        help="test a user addon and socket config without environment overrides",
    )
    args = parser.parse_args()
    if args.direct_panel and not args.visual:
        parser.error("--direct-panel requires --visual")
    build = args.build.resolve()
    (ROOT / "test-results").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ipc-", dir=ROOT / "test-results") as directory:
        temporary = Path(directory)
        env = dict(os.environ)
        for name in ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "XMODIFIERS"):
            if name == "DISPLAY" and args.visual:
                continue
            env.pop(name, None)
        for name, part in (
            ("HOME", "home"),
            ("XDG_CONFIG_HOME", "config"),
            ("XDG_DATA_HOME", "data"),
            ("XDG_CACHE_HOME", "cache"),
            ("XDG_RUNTIME_DIR", "r"),
            ("TMPDIR", "tmp"),
        ):
            path = temporary / part
            path.mkdir(mode=0o700)
            env[name] = str(path)
        env.update(
            {
                "FCITX_ADDON_DIRS": str(build / "lib"),
                "XDG_DATA_DIRS": str(build / "share") + ":/usr/share",
                "OPENASRINPUT_SOCKET": str(temporary / "bridge.sock"),
            }
        )
        if args.package:
            payload = temporary / "package"
            subprocess.run(
                ["dpkg-deb", "-x", str(args.package.resolve()), str(payload)], check=True
            )
            library = next((payload / "usr/lib").glob("*/fcitx5/libopenasrinput.so"))
            env["FCITX_ADDON_DIRS"] = str(library.parent)
            env["XDG_DATA_DIRS"] = str(payload / "usr/share") + ":/usr/share"
        if args.wayland_fallback:
            if not args.visual:
                parser.error("--wayland-fallback requires --visual")
            env["WAYLAND_DISPLAY"] = "asr-test"
        if args.installed_layout:
            metadata = temporary / "data/fcitx5/addon/openasrinput.conf"
            metadata.parent.mkdir(parents=True)
            content = (build / "share/fcitx5/addon/openasrinput.conf").read_text()
            content = content.replace(
                "Library=libopenasrinput", "Library=" + str(build / "lib/libopenasrinput")
            )
            metadata.write_text(content)
            native_config = temporary / "config/fcitx5/conf/openasrinput.conf"
            native_config.parent.mkdir(parents=True)
            native_config.write_text(
                "[OpenASRInput]\nSocketPath=" + env["OPENASRINPUT_SOCKET"] + "\n"
            )
            env.pop("OPENASRINPUT_SOCKET")
            env["FCITX_ADDON_DIRS"] = str(temporary / "no-addons")
        if args.visual:
            runtime_addons = subprocess.check_output(
                [str(build / "native_host"), "--addon-dir"],
                env=env,
                text=True,
            ).strip()
            env["FCITX_ADDON_DIRS"] += ":" + runtime_addons
        enabled = "openasrinput,xcb,classicui" if args.visual else "openasrinput"
        process = subprocess.Popen(
            [str(build / "native_host"), "-D", "--disable=all", "--enable=" + enabled],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            env=env,
            cwd=ROOT,
        )
        bridge = None
        root = None
        try:
            assert process.stdout.readline().strip() == "READY", "native host startup failed"
            socket_path = str(temporary / "bridge.sock")
            bridge = NativeBridge(socket_path)
            # Older cores defer their initial focus/IM-information update. READY
            # only means the test frontend was constructed, not that it flushed.
            time.sleep(0.2)
            if args.wayland_fallback:
                process.stdin.write("RELATIVE\n")
                process.stdin.flush()
                assert process.stdout.readline().strip() == "OK"
            if args.visual:
                import tkinter as tk

                # Tk is only the disposable test frontend's text widget. The
                # floating three-row card is rendered by the real native addon.
                os.environ.clear()
                os.environ.update(env)
                root = tk.Tk()
                root.title("OpenASRInput · 隔离原生测试")
                root.geometry("940x390+32+32")
                root.configure(background="#f3f6fb")
                tk.Label(
                    root,
                    text="OpenASRInput",
                    background="#f3f6fb",
                    foreground="#1e293b",
                    font=("sans", 20, "bold"),
                ).pack(anchor="w", padx=28, pady=(20, 4))
                tk.Label(
                    root,
                    text="光标预编辑 · 原位修订 · 定稿上屏",
                    background="#f3f6fb",
                    foreground="#64748b",
                    font=("sans", 12),
                ).pack(anchor="w", padx=28)
                text_widget = tk.Text(
                    root,
                    height=4,
                    font=("sans", 20),
                    padx=18,
                    pady=16,
                    background="white",
                    foreground="#1e293b",
                    borderwidth=0,
                    highlightthickness=1,
                    highlightbackground="#dbe4ee",
                    highlightcolor="#c7d2fe",
                    insertbackground="#6366f1",
                )
                text_widget.pack(fill="both", expand=True, padx=28, pady=20)
                text_widget.tag_configure("preedit", underline=True, foreground="#4f46e5")
                text_widget.focus_set()
                root.update()

            def command(text):
                process.stdin.write(text + "\n")
                process.stdin.flush()
                return process.stdout.readline().strip("\n").split("\t")

            def snapshot():
                fields = command("SNAPSHOT")
                assert fields[0] == "S"
                result = {
                    "text": bytes.fromhex(fields[1]).decode(),
                    "wave": bytes.fromhex(fields[2]).decode(),
                    "deletions": int(fields[3]),
                    "commits": [bytes.fromhex(value).decode() for value in fields[4:]],
                }
                if args.direct_panel:
                    assert result["wave"] == "", (
                        "direct graphics leaked into the system candidate panel"
                    )
                if root is not None:
                    text_widget.delete("1.0", "end")
                    text_widget.insert("1.0", "".join(result["commits"]))
                    text_widget.insert("end", result["text"], "preedit")
                    text_widget.mark_set("insert", "end-1c")
                    root.update()
                    x, y, width, height = text_widget.bbox("insert")
                    command(
                        f"RECT {text_widget.winfo_rootx() + x} {text_widget.winfo_rooty() + y} {width} {height}"
                    )
                return result

            def screenshot(name):
                if root is None:
                    return
                root.update()
                picture = (
                    ROOT
                    / "test-results"
                    / ("wayland-fallback-" + name if args.wayland_fallback else name)
                )
                subprocess.run(
                    ["import", "-window", "root", str(picture)],
                    env=env,
                    cwd=ROOT,
                    check=True,
                    timeout=10,
                )
                print("Native cursor-panel screenshot:", picture)

            core = Controller(bridge)
            core.toggle()
            command("CAP_REPEAT")
            assert bridge.valid(core.lease), (
                "benign client capability update invalidated the voice target"
            )
            core.take_effects()
            assert core.bind_session(core.generation, "native-demo")
            core.drain()
            snapshot()
            expected_backend = (
                "xwayland-status" if args.wayland_fallback else "x11" if args.visual else "text"
            )
            assert bridge.request("PANEL_BACKEND") == expected_backend
            screenshot("cursor-panel-empty.png")
            core.on_event(
                core.generation,
                {
                    "type": "session.ready",
                    "sessionId": "native-demo",
                    "seq": 1,
                    "audio": AUDIO,
                    "finalizeTimeoutMs": 1000,
                },
            )
            for level in (
                0,
                512,
                2048,
                4096,
                8192,
                16384,
                24576,
                32767,
                24576,
                16384,
                8192,
                4096,
                2048,
                512,
                0,
                16000,
            ):
                core.on_audio(core.generation, struct.pack("<320h", *([level] * 320)))
            core.on_event(
                core.generation,
                {
                    "type": "transcript.partial",
                    "sessionId": "native-demo",
                    "seq": 2,
                    "utteranceId": "u1",
                    "revision": 1,
                    "text": "工圆",
                },
            )
            core.drain()
            first = snapshot()
            assert (
                first["text"] == "工圆"
                and (args.direct_panel or "▆" in first["wave"])
                and first["commits"] == []
            ), first
            command("RESET")
            assert snapshot()["text"] == "工圆", "same-target reset lost the voice preview"
            # Ordinary typing is consumed in exclusive voice mode; RIME is not invoked.
            command("DOWN n")
            command("UP n")
            assert snapshot()["text"] == "工圆"
            command("DOWN Alt_L")
            command("DOWN Alt+z")
            command("UP Alt+z")
            command("UP Alt_L")
            assert bridge.poll_events() == ["command"], "Alt+Z failed in exclusive voice mode"
            core.on_event(
                core.generation,
                {
                    "type": "transcript.partial",
                    "sessionId": "native-demo",
                    "seq": 3,
                    "utteranceId": "u1",
                    "revision": 2,
                    "text": "公园。",
                },
            )
            core.drain()
            assert snapshot()["text"] == "公园。"
            screenshot("cursor-waveform.png")
            # The settings palette reaches the real addon and repaints the
            # active panel without changing its preedit, lease or committed text.
            dark = {
                **DEFAULTS["overlay"],
                "theme": "nord",
                "colorMode": "dark",
                "scale": 1.1,
                "fontSize": 18,
                "radius": 20,
            }
            settings_store = ConfigStore(temporary / "input.json")
            settings_store.save(
                {
                    "overlay": {
                        key: value for key, value in dark.items() if key in EDITABLE["overlay"]
                    }
                },
                "defaults",
            )
            config_runtime = ConfigRuntime(settings_store, bridge)
            asyncio.run(config_runtime.tick(SimpleNamespace(core=core)))
            assert settings_store.status()["appearance"]["theme"] == "nord"
            themed = snapshot()
            assert themed["text"] == "公园。" and themed["commits"] == []
            assert bridge.configure_panel({**dark, "position": "hidden"}) == "accepted"
            hidden = snapshot()
            assert hidden["text"] == "公园。" and hidden["commits"] == []
            assert hidden["wave"] == "", "hidden panel leaked Classic UI fallback"
            assert (
                bridge.configure_panel({**dark, "position": "top", "transparency": 50})
                == "accepted"
            )
            assert snapshot()["text"] == "公园。"
            panel = bridge.context_status()["panel"]
            assert panel["position"] == "top" and panel["transparency"] == 50
            screenshot("settings-native-nord.png")
            assert bridge.configure_panel(DEFAULTS["overlay"]) == "accepted"
            if root is not None:
                command("SCALE 2")
                screenshot("cursor-panel-scaled.png")
                command("SCALE 1")
            core.on_event(
                core.generation,
                {
                    "type": "transcript.final",
                    "sessionId": "native-demo",
                    "seq": 4,
                    "utteranceId": "u1",
                    "revision": 3,
                    "text": "公园。",
                },
            )
            core.drain()
            assert snapshot()["commits"] == ["公园。"]
            core.cancel()
            core.drain()
            assert snapshot()["text"] == "" and snapshot()["wave"] == ""
            assert snapshot()["deletions"] == 0

            # Failure information is an eight-second UI notice, NOT preedit,
            # and must release keyboard ownership immediately.
            lease = bridge.begin_context()
            message = "Portal 尚未配置识别档案「doubao」。请在管理页添加并保存配置。"
            assert bridge.show_notice(lease, message) == "accepted"
            notice = snapshot()
            assert notice["text"] == "" and notice["commits"] == ["公园。"]
            assert args.direct_panel or message in notice["wave"]
            assert not bridge.valid(lease)
            screenshot("portal-missing-notice.png")
            time.sleep(0.2)
            assert args.direct_panel or message in snapshot()["wave"], (
                "failure notice disappeared immediately"
            )
            command("DOWN n")
            assert command("KEYRESULT") == ["0"], "failure information blocked normal typing"
            command("UP n")
            assert snapshot()["wave"] == ""
            lease = bridge.begin_context()
            assert bridge.show_notice(lease, message) == "accepted"
            time.sleep(8.3)
            assert snapshot()["wave"] == "", "expired notice left a stale panel"

            # Display window scrolls, but all words stay in the client preedit.
            lease = bridge.begin_context()
            words = ["a" + chr(ord("a") + index) for index in range(25)]
            complete = " ".join(words)
            bridge.show_cursor(lease, 1, CursorFrame("listening", " ".join(words[:21]), "▁▃▆█▆▃▁"))
            rolling = snapshot()
            assert args.direct_panel or rolling["wave"].split("\n")[1] == " ".join(words[1:21])
            bridge.show_cursor(lease, 2, CursorFrame("listening", complete, "▁▃▆█▆▃▁"))
            rolling = snapshot()
            assert rolling["text"] == complete
            assert args.direct_panel or rolling["wave"].split("\n")[1] == " ".join(words[5:])
            chinese = "今天我们准备一起测试新的语音输入面板观察波形变化确认文本缓冲能够持续更新然后检查定稿内容正确保持稳定"
            bridge.show_cursor(lease, 3, CursorFrame("listening", chinese, "▁▃▆█▆▃▁"))
            rolling = snapshot()
            assert rolling["text"] == chinese
            assert args.direct_panel or rolling["wave"].split("\n")[1] != chinese
            assert args.direct_panel or rolling["wave"].split("\n")[1].endswith("正确保持稳定")
            screenshot("cursor-buffer-20.png")
            bridge.clear_cursor(lease)

            lease = bridge.begin_context()
            bridge.show_cursor(lease, 1, CursorFrame("listening", "不可误上屏", "▁▆▁"))
            command("FOCUS2")
            assert not bridge.valid(lease)
            assert bridge.submit(lease, "late", "迟到结果") == "stale"
            assert snapshot()["text"] == "" and snapshot()["commits"] == []
            command("FOCUS1")
            first_returned = snapshot()
            assert first_returned["commits"] == ["公园。"], first_returned
            assert snapshot()["text"] == ""
            command("DOWN Shift_L")
            command("DOWN Shift+space")
            command("UP Shift+space")
            command("UP Shift_L")
            assert "toggle" in bridge.poll_events()
            # A lost daemon clears its preedit and restores keyboard availability.
            lease = bridge.begin_context()
            bridge.show_cursor(lease, 1, CursorFrame("listening", "连接断开即清除", "▁▆▁"))
            bridge.close()
            bridge = None
            command("DOWN n")
            assert command("KEYRESULT") == ["0"], "disconnected addon consumed a normal key"
            command("UP n")
            command("DOWN Shift_L")
            assert command("KEYRESULT") == ["0"], "disconnected addon delayed Shift"
            command("UP Shift_L")
            # A new peer/VALID request is a barrier after the disconnect callback.
            bridge = NativeBridge(socket_path)
            assert not bridge.valid(lease)
            assert snapshot()["text"] == ""
            print(
                "PASS native addon IPC: preedit revisions, PCM waveform, exclusive keys, final commit, focus, disconnect"
            )
            command("QUIT")
            assert process.wait(timeout=5) == 0
        finally:
            if root is not None:
                root.destroy()
            if bridge is not None:
                bridge.close()
            if process.poll() is None:
                process.kill()
                process.wait()


if __name__ == "__main__":
    main()
