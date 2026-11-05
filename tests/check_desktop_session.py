"""Disposable-container desktop session. No host bus/display or real user HOME."""

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

RESULTS = Path("/results")


def wait(predicate, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = predicate()
        except subprocess.TimeoutExpired:
            value = None
        if value:
            return value
        time.sleep(0.1)
    raise RuntimeError("Desktop readiness timeout")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--desktop", choices=("gnome", "kde", "xfce"), required=True)
    parser.add_argument("--protocol", choices=("x11", "wayland"), required=True)
    parser.add_argument("--framework", choices=("ibus", "fcitx4", "fcitx5"), required=True)
    parser.add_argument("--session", action="store_true")
    args = parser.parse_args()
    if not args.session:
        assert os.getuid() == 0 and Path("/.dockerenv").exists(), "Disposable container required"
        subprocess.run(["dpkg", "--install", "/input.deb"], check=True)
        # Distro KWin requests CAP_SYS_NICE via a file capability. Docker omits
        # that capability, so exec itself fails with EPERM. Nested testing needs
        # no realtime scheduling; remove only this container copy's capability.
        kwin = shutil.which("kwin_wayland")
        if kwin and "security.capability" in os.listxattr(kwin):
            os.removexattr(kwin, "security.capability")
        home = Path("/tmp/desktop-home")
        home.mkdir()
        os.chown(home, 1000, 1000)
        os.chown(RESULTS, 1000, 1000)
        for name, suffix in (
            ("HOME", ""),
            ("XDG_CONFIG_HOME", "config"),
            ("XDG_DATA_HOME", "data"),
            ("XDG_CACHE_HOME", "cache"),
            ("XDG_RUNTIME_DIR", "runtime"),
        ):
            path = home / suffix
            path.mkdir(exist_ok=True, mode=0o700)
            os.chown(path, 1000, 1000)
            os.environ[name] = str(path)
        Path("/tmp/opencode").mkdir(mode=0o1777, exist_ok=True)
        os.chmod("/tmp/opencode", 0o1777)
        os.environ.update(
            GSETTINGS_BACKEND="keyfile",
            GIO_USE_VFS="local",
            GTK_A11Y="none",
            NO_AT_BRIDGE="1",
            QT_ACCESSIBILITY="0",
            QT_QUICK_BACKEND="software",
            GTK_IM_MODULE="ibus" if args.framework == "ibus" else "fcitx",
            QT_IM_MODULE="ibus" if args.framework == "ibus" else "fcitx",
            XMODIFIERS="@im=ibus" if args.framework == "ibus" else "@im=fcitx",
            XDG_SESSION_TYPE=args.protocol,
            XDG_CURRENT_DESKTOP={"gnome": "GNOME", "kde": "KDE", "xfce": "XFCE"}[args.desktop],
            XDG_SESSION_DESKTOP=args.desktop,
            LANG="C.UTF-8",
            LC_ALL="C.UTF-8",
        )
        os.setgroups([])
        os.setgid(1000)
        os.setuid(1000)
        os.execvp(
            "dbus-run-session",
            [
                "dbus-run-session",
                "--",
                "xvfb-run",
                "-a",
                "-s",
                "-screen 0 1280x900x24",
                sys.executable,
                __file__,
                *sys.argv[1:],
                "--session",
            ],
        )
    os.environ["DBUS_SYSTEM_BUS_ADDRESS"] = os.environ["DBUS_SESSION_BUS_ADDRESS"]
    os.environ["OPENASRINPUT_OUTER_DISPLAY"] = os.environ["DISPLAY"]
    subprocess.run(["dbus-update-activation-environment", "--all"], check=True)
    children = []
    with (RESULTS / "desktop.log").open("w") as log:

        def launch(command):
            child = subprocess.Popen(
                command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True
            )
            children.append(child)
            return child

        try:
            if args.desktop == "gnome":
                shell_help = subprocess.check_output(["gnome-shell", "--help"], text=True)
                if args.protocol == "x11" and "--x11" not in shell_help:
                    version = subprocess.check_output(["gnome-shell", "--version"], text=True)
                    (RESULTS / "evidence.json").write_text(
                        json.dumps(
                            {
                                "status": "session-unavailable",
                                "reason": version.strip() + " does not provide an X11 session.",
                                "gnomeShellHelp": shell_help,
                            },
                            indent=2,
                        )
                    )
                    return
                nested = "--nested" if "--nested" in shell_help else "--devkit"
                if nested == "--devkit" and args.protocol == "wayland":
                    # Its GTK viewer must connect to the outer Xvfb, not the
                    # compositor's newly advertised (still output-less) Wayland socket.
                    os.environ["GDK_BACKEND"] = "x11"
                    os.environ["GSK_RENDERER"] = "cairo"
                    # New Mutter devkit presents its virtual output via PipeWire.
                    # Start only a private daemon using this container's runtime dir.
                    launch(["pipewire"])
                    wait(lambda: (Path(os.environ["XDG_RUNTIME_DIR"]) / "pipewire-0").is_socket())
                    launch(["wireplumber"])
                subprocess.run(
                    [
                        "gsettings",
                        "set",
                        "org.gnome.desktop.interface",
                        "enable-animations",
                        "false",
                    ],
                    check=True,
                )
                extensions = ["openasrinput@local", "openasrinput-legacy@local"]
                from desktop_diagnostics import gnome_state, install_gnome_probe

                version = subprocess.check_output(["gnome-shell", "--version"], text=True)
                extensions.append(install_gnome_probe(version.split()[-1].split(".")[0]))
                subprocess.run(
                    [
                        "gsettings",
                        "set",
                        "org.gnome.shell",
                        "enabled-extensions",
                        repr(extensions),
                    ],
                    check=True,
                )
                subprocess.run(
                    ["gsettings", "set", "org.gnome.shell", "disable-user-extensions", "false"],
                    check=True,
                )
                desktop = launch(
                    [
                        "gnome-shell",
                        *(
                            ["--wayland", nested, "--wayland-display=asr", "--no-x11"]
                            if args.protocol == "wayland"
                            else ["--x11", "--replace"]
                        ),
                    ]
                )
                wait(
                    lambda: (
                        "GNOME Shell started"
                        in (RESULTS / "desktop.log").read_text(errors="replace")
                    )
                )
            elif args.desktop == "kde":
                if args.protocol == "wayland":
                    os.environ["KWIN_COMPOSE"] = "Q"
                desktop = launch(
                    [
                        "kwin_wayland",
                        "--x11-display",
                        os.environ["DISPLAY"],
                        "--socket",
                        "asr",
                        "--width",
                        "1280",
                        "--height",
                        "800",
                        "--no-lockscreen",
                    ]
                    if args.protocol == "wayland"
                    else ["kwin_x11", "--replace"]
                )
                if args.protocol == "x11":
                    wait(
                        lambda: (
                            subprocess.run(
                                ["xprop", "-root", "_NET_SUPPORTING_WM_CHECK"],
                                capture_output=True,
                                text=True,
                            ).stdout.find("window id")
                            >= 0
                        )
                    )
            else:
                desktop = launch(["xfce4-session"])
                wait(
                    lambda: (
                        subprocess.run(
                            ["xprop", "-root", "_NET_SUPPORTING_WM_CHECK"],
                            capture_output=True,
                            text=True,
                        ).stdout.find("window id")
                        >= 0
                    )
                )
            if args.protocol == "wayland":
                socket = Path(os.environ["XDG_RUNTIME_DIR"]) / "asr"
                wait(socket.is_socket)
                os.environ["WAYLAND_DISPLAY"] = "asr"
                os.environ.pop("GDK_BACKEND", None)
                if args.desktop == "kde":
                    os.environ["QT_QPA_PLATFORM"] = "wayland"
                # The outer Xvfb only feeds keyboard events into the nested desktop.
                # Do not let an X11 panel accidentally render outside that desktop.
                os.environ.pop("DISPLAY", None)
                subprocess.run(
                    ["dbus-update-activation-environment", "--all"],
                    env={**os.environ, "DISPLAY": ""},
                    check=True,
                )
            if args.desktop == "kde":
                subprocess.run(
                    [
                        "gdbus",
                        "call",
                        "--session",
                        "--dest",
                        "org.freedesktop.DBus",
                        "--object-path",
                        "/org/freedesktop/DBus",
                        "--method",
                        "org.freedesktop.DBus.StartServiceByName",
                        "org.kde.ActivityManager",
                        "0",
                    ],
                    check=True,
                )
                plasma = launch(["plasmashell", "--no-respawn"])
                wait(
                    lambda: (
                        "desktop-ready:1"
                        in subprocess.run(
                            [
                                "gdbus",
                                "call",
                                "--session",
                                "--dest",
                                "org.kde.plasmashell",
                                "--object-path",
                                "/PlasmaShell",
                                "--method",
                                "org.kde.PlasmaShell.evaluateScript",
                                'print("desktop-ready:" + desktops().length)',
                            ],
                            capture_output=True,
                            text=True,
                            timeout=10,
                        ).stdout
                    )
                )
            if args.desktop == "gnome":
                wait(lambda: gnome_state().get("startingUp") is False)
                subprocess.run(
                    [
                        "xdotool",
                        "mousemove",
                        "--sync",
                        "640",
                        "400",
                        "click",
                        "1",
                        "key",
                        "--delay",
                        "100",
                        "Escape",
                    ],
                    env={**os.environ, "DISPLAY": os.environ["OPENASRINPUT_OUTER_DISPLAY"]},
                    check=True,
                )
                wait(lambda: gnome_state().get("overview") is False)
            assert desktop.poll() is None, "desktop exited"
            if args.framework == "fcitx4":
                os.environ["OPENASRINPUT_DESKTOP_TEST"] = "1"
                subprocess.run(
                    [
                        sys.executable,
                        "tests/test_fcitx4_x11.py",
                        "--build",
                        "/probes/fcitx4",
                        "--package",
                        "/input.deb",
                        "--results",
                        str(RESULTS),
                    ],
                    check=True,
                    timeout=180,
                )
                evidence = {
                    "input": "real XIM",
                    "selection": "unsupported by Fcitx4 adapter",
                    "panel": "x11",
                }
            else:
                subprocess.run(
                    [
                        sys.executable,
                        "tests/check_desktop_input.py",
                        "--framework",
                        args.framework,
                        "--protocol",
                        args.protocol,
                        "--desktop",
                        args.desktop,
                    ],
                    check=True,
                    timeout=180,
                )
                evidence = json.loads((RESULTS / "input.json").read_text())
            assert desktop.poll() is None, "desktop exited during input test"
            if args.desktop == "kde":
                assert plasma.poll() is None, "Plasma shell exited during input test"
            evidence.update(
                desktop=args.desktop,
                protocol=args.protocol,
                desktopPid=desktop.pid,
                architecture=subprocess.check_output(
                    ["dpkg", "--print-architecture"], text=True
                ).strip(),
                osRelease=Path("/etc/os-release").read_text(),
                packages=subprocess.check_output(
                    [
                        "dpkg-query",
                        "-W",
                        "gnome-shell",
                        "plasma-workspace",
                        "xfce4-session",
                        "ibus",
                    ],
                    text=True,
                ),
            )
            (RESULTS / "evidence.json").write_text(
                json.dumps(evidence, ensure_ascii=False, indent=2)
            )
        except Exception:
            env = {**os.environ, "DISPLAY": os.environ["OPENASRINPUT_OUTER_DISPLAY"]}
            try:
                subprocess.run(["xwininfo", "-root", "-tree"], env=env, timeout=10)
                subprocess.run(
                    ["import", "-window", "root", str(RESULTS / "failure.png")], env=env, timeout=20
                )
            except subprocess.SubprocessError:
                pass
            raise
        finally:
            for child in reversed(children):
                if child.poll() is None:
                    os.killpg(child.pid, signal.SIGTERM)
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL)
                        child.wait()


if __name__ == "__main__":
    main()
