"""Real Fcitx4/XIM regression. Run inside a private D-Bus/Xvfb session.

Uses only stdlib so the 4.2.9.8 native baseline can be tested on Debian bullseye.
Never talks to the host desktop or loads host user configuration.
"""

import argparse
import json
import os
import select
import shutil
import signal
import socket
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Lines:
    def __init__(self, fd):
        self.fd = fd
        self.buffer = b""

    def line(self, timeout=3):
        if os.environ.get("OPENASRINPUT_DESKTOP_TEST") == "1":
            timeout = max(timeout, 20)
        end = time.monotonic() + timeout
        while b"\n" not in self.buffer:
            if not select.select([self.fd], [], [], max(0, end - time.monotonic()))[0]:
                raise TimeoutError("native response timeout")
            data = os.read(self.fd, 65536)
            if not data:
                raise RuntimeError("native process disconnected")
            self.buffer += data
        line, self.buffer = self.buffer.split(b"\n", 1)
        return line.decode().split("\t")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build/fcitx4")
    parser.add_argument("--package", type=Path, help="exercise the exact native plugin from a deb")
    parser.add_argument("--results", type=Path, default=ROOT / "test-results")
    args = parser.parse_args()
    args.results.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="f4-", dir=args.results) as directory:
        home = Path(directory).resolve()
        env = {
            **os.environ,
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / "config"),
            "XDG_DATA_HOME": str(home / "data"),
            "XDG_CACHE_HOME": str(home / "cache"),
            "XDG_RUNTIME_DIR": str(home / "run"),
            "XDG_SESSION_TYPE": "x11",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "FCITXDIR": str(home / "prefix"),
            "OPENASRINPUT_SOCKET": str(home / "bridge.sock"),
        }
        env.pop("WAYLAND_DISPLAY", None)
        prefix = home / "prefix"
        addons = prefix / "lib/fcitx"
        addons.mkdir(parents=True)
        installed = (
            Path(
                subprocess.check_output(
                    ["pkg-config", "--variable=libdir", "fcitx"], text=True
                ).strip()
            )
            / "fcitx"
        )
        for library in installed.glob("*.so"):
            if library.name == "fcitx-openasrinput.so":
                continue  # The tested addon is copied below; never overwrite an installed symlink.
            (addons / library.name).symlink_to(library)
        library = args.build / "lib/fcitx-openasrinput.so"
        if args.package:
            payload = home / "package"
            subprocess.run(
                ["dpkg-deb", "-x", str(args.package.resolve()), str(payload)], check=True
            )
            library = next((payload / "usr/lib").glob("*/fcitx/fcitx-openasrinput.so"))
            shutil.copytree(library.parent / "openasrinput-libs", addons / "openasrinput-libs")
        shutil.copy2(library, addons)
        (prefix / "share").symlink_to("/usr/share", target_is_directory=True)
        config = home / "config/fcitx/addon"
        config.mkdir(parents=True)
        shutil.copy2(ROOT / "src/native/fcitx4/fcitx-openasrinput.conf", config)
        (home / "run").mkdir(mode=0o700)
        (home / "config/fcitx/profile").write_text(
            "[Profile]\nEnabledIMList=fcitx-keyboard-us:True\nCurrentIM=fcitx-keyboard-us\n"
        )
        children = []
        phase = "startup"
        events, committed = [], []
        with (args.results / "fcitx4-x11.log").open("w") as log:
            try:
                children.append(
                    subprocess.Popen(
                        [
                            "fcitx",
                            "-D",
                            "-s",
                            "0",
                            "--disable",
                            "all",
                            "--enable",
                            "fcitx-keyboard,fcitx-x11,fcitx-xim,fcitx-fullwidth-char,fcitx-openasrinput",
                        ],
                        env=env,
                        stdout=log,
                        stderr=log,
                    )
                )
                for _ in range(100):
                    if Path(env["OPENASRINPUT_SOCKET"]).exists():
                        break
                    if children[0].poll() is not None:
                        raise RuntimeError("Fcitx4 exited; see fcitx4-x11.log")
                    time.sleep(0.05)
                connection = socket.socket(socket.AF_UNIX)
                connection.connect(env["OPENASRINPUT_SOCKET"])
                native = Lines(connection.fileno())
                assert native.line() == ["0", "HELLO", "OpenASRInput.Bridge", "1"]
                events = []
                serial = 0

                def request(verb, *fields):
                    nonlocal serial
                    serial += 1
                    connection.sendall(("\t".join([str(serial), verb, *fields]) + "\n").encode())
                    while True:
                        fields = native.line()
                        if fields[:2] == ["0", "EVENT"]:
                            events.append(fields[2])
                            continue
                        assert fields[:2] == [str(serial), "OK"], fields
                        return fields[2]

                probe = subprocess.Popen(
                    [str(args.build / "fcitx4_xim_probe")],
                    env=env,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=log,
                )
                children.append(probe)
                output = Lines(probe.stdout.fileno())
                ready = output.line(timeout=30)
                assert ready[0] == "READY"
                if os.environ.get("OPENASRINPUT_DESKTOP_TEST") == "1":
                    subprocess.run(
                        [
                            "xdotool",
                            "windowactivate",
                            "--sync",
                            ready[1],
                            "windowfocus",
                            "--sync",
                            ready[1],
                        ],
                        env=env,
                        check=True,
                    )
                    subprocess.run(
                        ["xdotool", "mousemove", "--window", ready[1], "60", "60", "click", "1"],
                        env=env,
                        check=True,
                    )
                time.sleep(0.2)

                def keys(*command):
                    subprocess.run(["xdotool", *command], env=env, check=True)
                    time.sleep(0.1)

                def command(value):
                    probe.stdin.write((value + "\n").encode())
                    probe.stdin.flush()

                def expect(kind, value=None):
                    for _ in range(100):
                        line = output.line()
                        if os.environ.get("OPENASRINPUT_DESKTOP_TEST") == "1":
                            print("XIM", line, flush=True)
                        if line[0] == "TEXT":
                            committed.append(bytes.fromhex(line[1]).decode())
                        if line[0] == kind and (value is None or line[1] == value):
                            return line
                    raise AssertionError((kind, value))

                committed = []
                command("FOCUS?")
                expect("FOCUS", "yes")
                keys("key", "A")
                expect("TEXT", b"A".hex())
                for modifier, key, stalled in (
                    ("Alt_L", "z", False),
                    ("Shift_L", "space", False),
                    ("Alt_L", "z", True),
                    ("Shift_L", "space", True),
                ):
                    phase = f"shortcut-{modifier}-{key}-{'stalled' if stalled else 'normal'}"
                    if os.environ.get("OPENASRINPUT_TRACE_IPC") == "1":
                        print("SHORTCUT", time.monotonic(), modifier, key, flush=True)
                    keys("keydown", modifier, "keydown", key, "keydown", key)
                    if stalled:
                        request("PANEL_BACKEND")
                        os.kill(children[0].pid, signal.SIGSTOP)
                    try:
                        # Real X11 repeat release/press pairs. A stopped input
                        # framework must not reinterpret the queued pairs as
                        # fresh chords after the user has released both keys.
                        time.sleep(0.9)
                        keys("keyup", key, "keyup", modifier)
                    finally:
                        if stalled:
                            os.kill(children[0].pid, signal.SIGCONT)
                    # An IPC reply is not a barrier for the XIM frontend. The
                    # ordinary unmodified 'v' is a text-delivery marker, NOT a
                    # third shortcut. It traverses the same X11 event stream;
                    # count shortcut events only after the editor receives it.
                    keys("key", "v")
                    try:
                        expect("TEXT", b"v".hex())
                    except AssertionError as error:
                        raise AssertionError(
                            f"{phase}: ordinary text marker 'v' did not reach the editor "
                            "after shortcut release; 'v' is not a shortcut"
                        ) from error
                    request("PANEL_BACKEND")
                    assert events == ["command" if modifier == "Alt_L" else "toggle"], events
                    events.clear()
                phase = "notice"
                notice_lease = request("BEGIN")
                assert notice_lease != "unavailable"
                assert request("NOTICE", notice_lease, "请配置 Portal".encode().hex()) == "accepted"
                assert request("VALID", notice_lease) == "false"
                keys("key", "c")
                expect("TEXT", b"c".hex())
                phase = "preedit-reset"
                lease = request("BEGIN")
                assert lease != "unavailable", "XIM context not available"
                assert (
                    request(
                        "SHOW",
                        lease,
                        "1",
                        "工圆".encode().hex(),
                        "▁▃▆".encode().hex(),
                        b"listening".hex(),
                    )
                    == "accepted"
                )
                expect("PREEDIT", "工圆".encode().hex())
                command("RESET")
                expect("RESET")
                time.sleep(0.1)
                # Fcitx4's XIM_RESET_IC explicitly drops CurrentIC and emits
                # unfocus. Unlike Fcitx5 Reset, it must revoke the old target.
                assert request("VALID", lease) == "false", (
                    "XIM unfocus reset retained the old target"
                )
                command("FOCUS1")
                expect("FOCUSED")
                time.sleep(0.1)
                previous_lease = lease
                lease = request("BEGIN")
                assert lease not in ("unavailable", previous_lease)
                assert (
                    request("COMMIT", previous_lease, "reset-late", "不得输入".encode().hex())
                    == "stale"
                )
                assert (
                    request(
                        "SHOW",
                        lease,
                        "2",
                        "公园。".encode().hex(),
                        "▂▅█".encode().hex(),
                        b"listening".hex(),
                    )
                    == "accepted"
                )
                expect("PREEDIT", "公园。".encode().hex())
                command("FOCUS?")
                expect("FOCUS", "yes")
                keys("key", "n")
                phase = "commit"
                assert request("VALID", lease) == "true"
                assert request("COMMIT", lease, "first", "公园。".encode().hex()) == "accepted"
                expect("TEXT", "公园。".encode().hex())
                assert request("COMMIT", lease, "first", "公园。".encode().hex()) == "accepted"
                assert request("COMMIT", lease, "first", "不同".encode().hex()) == "failed"
                assert (
                    request(
                        "SHOW",
                        lease,
                        "3",
                        "未确认文字".encode().hex(),
                        "▁".encode().hex(),
                        b"listening".hex(),
                    )
                    == "accepted"
                )
                expect("PREEDIT", "未确认文字".encode().hex())
                phase = "focus-isolation"
                command("FOCUS2")
                expect("FOCUSED")
                time.sleep(0.2)
                assert request("VALID", lease) == "false"
                assert request("COMMIT", lease, "late", "迟到文字".encode().hex()) == "stale"
                keys("key", "a")
                expect("TEXT", b"a".hex())
                connection.close()
                phase = "disconnect"
                keys("key", "b")
                expect("TEXT", b"b".hex())
                assert committed == ["A", "v", "v", "v", "v", "c", "公园。", "a", "b"], committed
                command("QUIT")
                assert probe.wait(timeout=3) == 0
                print(
                    "PASS Fcitx4/X11: real XIM preedit revisions, dual shortcuts/repeat, final idempotency, focus isolation, normal typing"
                )
            except Exception as error:
                evidence = {
                    "phase": phase,
                    "failures": [{"check": phase, "error": str(error)}],
                    "events": list(events),
                    "committed": list(committed),
                }
                if "request" in locals():
                    try:
                        evidence["panelBackend"] = request("PANEL_BACKEND")
                        evidence["events"] = list(events)
                    except (OSError, ValueError, AssertionError, RuntimeError):
                        pass
                for label, diagnostic in (
                    ("focus", ["xdotool", "getwindowfocus", "getwindowname"]),
                    ("windows", ["xwininfo", "-root", "-tree"]),
                    (
                        "screenshot",
                        ["import", "-window", "root", str(args.results / "xim-failure.png")],
                    ),
                ):
                    try:
                        result = subprocess.run(
                            diagnostic, env=env, capture_output=True, text=True, timeout=5
                        )
                        evidence[label] = result.stdout + result.stderr
                    except (OSError, subprocess.SubprocessError):
                        pass
                (args.results / "xim.json").write_text(
                    json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                raise
            finally:
                for child in reversed(children):
                    if child.poll() is None:
                        child.terminate()
                        try:
                            child.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            child.kill()
                            child.wait()


if __name__ == "__main__":
    main()
