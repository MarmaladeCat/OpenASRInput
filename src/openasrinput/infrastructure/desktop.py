"""Installed deb lifecycle: per-user activation, remote Portal, no repo dependency."""

import json
import os
import subprocess
import time
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .. import __version__
from .config import ConfigStore, atomic_json
from .files import FileTransaction, api, request_bytes
from .frameworks import select_framework


class PackageDesktop:
    def __init__(self):
        self.home = Path.home()
        self.config_dir = Path(os.environ.get("XDG_CONFIG_HOME", self.home / ".config"))
        self.state = (
            Path(os.environ.get("XDG_STATE_HOME", self.home / ".local/state"))
            / "openasrinput/package"
        )
        self.files = FileTransaction(self.state)
        self.store = ConfigStore()
        self.units = self.config_dir / "systemd/user"
        self.launcher = os.environ.get("OPENASRINPUT_PACKAGE_LAUNCHER", "/usr/bin/openasrinput")
        self.framework = os.environ.get("OPENASRINPUT_FRAMEWORK", "auto")
        if self.framework not in ("auto", "ibus", "fcitx4", "fcitx5"):
            raise ValueError("输入框架必须是 auto、ibus、fcitx4 或 fcitx5")
        self.unified = os.environ.get("OPENASRINPUT_PACKAGE_FRAMEWORK", "auto") == "auto"
        self.active_socket = None
        self.settings_port = int(os.environ.get("OPENASRINPUT_SETTINGS_PORT", "10088"))
        if not 1 <= self.settings_port <= 65535:
            raise ValueError("设置端口必须为 1–65535")

    def run(self, *args, check=True):
        return subprocess.run(args, check=check, capture_output=True, text=True, timeout=30)

    def ensure_config(self):
        config, _ = self.store.read()
        if not self.store.path.exists():
            atomic_json(self.store.path, config)
        return config

    def setup_units(self):
        config = self.ensure_config()

        def q(value):
            return json.dumps(str(value))

        for name, command in (
            ("openasrinput.service", f"run-daemon --config {q(self.store.path)}"),
            (
                "openasrinput-settings.service",
                f"settings-server --no-open --port {self.settings_port} --config {q(self.store.path)} --ready-file {q(self.state / 'settings-ready.json')}",
            ),
        ):
            if name == "openasrinput.service" and self.active_socket:
                command += f" --socket {q(self.active_socket)}"
            self.files.write(
                self.units / name,
                (
                    "[Unit]\nDescription=OpenASRInput user application\n"
                    "After=graphical-session.target\nPartOf=graphical-session.target\n"
                    + (
                        "Wants=openasrinput-ibus.service\nAfter=openasrinput-ibus.service\n"
                        if name == "openasrinput.service" and self.framework == "ibus"
                        else ""
                    )
                    + "[Service]\nType=simple\n"
                    f"ExecStart={q(self.launcher)} {command}\nEnvironment=PYTHONDONTWRITEBYTECODE=1\n"
                    + (
                        f"Environment=OPENASRINPUT_ACTIVE_FRAMEWORK={self.framework}\n"
                        if self.framework != "auto"
                        else ""
                    )
                    + "KillMode=control-group\nTimeoutStopSec=5\nRestart=on-failure\nRestartSec=3\n"
                    "[Install]\nWantedBy=graphical-session.target\n"
                ).encode(),
                0o644,
            )
        self.run("systemctl", "--user", "daemon-reload")
        return config

    def start(self):
        config, _ = self.store.read()
        if self.store.path.exists():
            raw = json.loads(self.store.path.read_bytes())
            previous = self.files.manifest.get("framework")
            if "framework" not in raw.get("input", {}) and previous in ("fcitx4", "fcitx5"):
                config["input"]["framework"] = previous
                atomic_json(self.store.path, config)
        preference = config["input"]["framework"]
        if preference == "auto":
            preference = os.environ.get("OPENASRINPUT_FRAMEWORK", "auto")
        # Keep a legacy installation's explicitly packaged framework on upgrade.
        if preference == "auto":
            preference = os.environ.get("OPENASRINPUT_PACKAGE_FRAMEWORK", "auto")
        try:
            self.framework = select_framework(preference)
        except RuntimeError:
            if preference == "auto":
                self.setup_units()
                self.run("systemctl", "--user", "enable", "--now", "openasrinput-settings.service")
            raise
        if self.unified and "OPENASRINPUT_FRAMEWORK" not in os.environ:
            self.active_socket = config["runtime"]["socketPath"] + "." + self.framework
            if len(os.fsencode(self.active_socket)) >= 108:
                raise ValueError("框架专用 socket 路径过长，请缩短 runtime.socketPath")
        if self.framework == "fcitx4" and os.environ.get("XDG_SESSION_TYPE") == "wayland":
            raise RuntimeError("Fcitx4 桥接仅支持 X11；请登录 X11 会话，或安装 Fcitx5 版本")
        config = self.setup_units()
        socket = Path(self.active_socket or config["runtime"]["socketPath"])
        if self.framework == "ibus":
            self.start_ibus(socket)
            return
        self.files.write(
            self.config_dir
            / (
                "fcitx/conf/openasrinput.conf"
                if self.framework == "fcitx4"
                else "fcitx5/conf/openasrinput.conf"
            ),
            ("[OpenASRInput]\nSocketPath=" + str(socket) + "\n").encode(),
            0o644,
        )
        # enable --now leaves an already running, pre-upgrade frozen process
        # untouched. Stop it before reloading the bridge and start a fresh one.
        self.stop()
        previous_socket = socket.stat() if socket.exists() else None
        # Refresh does not unload a mapped addon. Explicit activation must load
        # the installed Fcitx5 plugin, even when an old socket still exists.
        for method in ("Reload",) if self.framework == "fcitx4" else ("Restart",):
            if self.framework == "fcitx4":
                self.run("fcitx-remote", "-r")
            else:
                self.run(
                    "gdbus",
                    "call",
                    "--session",
                    "--dest",
                    "org.fcitx.Fcitx5",
                    "--object-path",
                    "/controller",
                    "--method",
                    "org.fcitx.Fcitx.Controller1." + method,
                )
            for _ in range(30):
                try:
                    current_socket = socket.stat()
                except FileNotFoundError:
                    current_socket = None
                replaced = previous_socket is None or (
                    current_socket is not None
                    and (current_socket.st_ino, current_socket.st_ctime_ns)
                    != (previous_socket.st_ino, previous_socket.st_ctime_ns)
                )
                if current_socket and (self.framework == "fcitx4" or replaced):
                    self.files.manifest["active"] = True
                    self.files.manifest["framework"] = self.framework
                    self.files.commit()
                    try:
                        self.run(
                            "systemctl",
                            "--user",
                            "enable",
                            "--now",
                            "openasrinput.service",
                            "openasrinput-settings.service",
                        )
                        self.wait_settings()
                    except (OSError, RuntimeError, subprocess.SubprocessError):
                        self.stop()
                        raise
                    return
                time.sleep(0.1)
        hint = (
            "首次安装后请注销重新登录，或执行 fcitx -r 后重试"
            if self.framework == "fcitx4"
            else "请检查 Fcitx5 是否运行"
        )
        raise RuntimeError("原生桥接未就绪，" + hint)

    def start_ibus(self, socket):
        helper = (
            Path(os.environ.get("OPENASRINPUT_APP_ROOT", "/usr/lib/openasrinput"))
            / "ibus/engine.py"
        )
        if not helper.is_file():
            raise RuntimeError("安装包缺少 IBus 桥接")
        self.run(
            "/usr/bin/python3",
            "-c",
            "import gi; gi.require_version('IBus', '1.0'); from gi.repository import IBus",
        )
        self.stop()
        self.run("systemctl", "--user", "stop", "openasrinput-ibus.service", check=False)
        self.files.write(
            self.units / "openasrinput-ibus.service",
            (
                "[Unit]\nDescription=OpenASRInput IBus bridge\nPartOf=openasrinput.service\n"
                "[Service]\nType=simple\nExecStart=/usr/bin/python3 "
                + json.dumps(str(helper))
                + " --socket "
                + json.dumps(str(socket))
                + "\nRestart=on-failure\nRestartSec=3\n"
            ).encode(),
            0o644,
        )
        self.run("systemctl", "--user", "daemon-reload")
        previous_socket = socket.stat() if socket.exists() else None
        self.run("systemctl", "--user", "start", "openasrinput-ibus.service")
        for _ in range(50):
            current_socket = socket.stat() if socket.exists() else None
            replaced = previous_socket is None or (
                current_socket is not None
                and (current_socket.st_ino, current_socket.st_ctime_ns)
                != (previous_socket.st_ino, previous_socket.st_ctime_ns)
            )
            if current_socket and replaced:
                self.files.manifest.update(active=True, framework="ibus")
                self.files.commit()
                try:
                    self.run(
                        "systemctl",
                        "--user",
                        "enable",
                        "--now",
                        "openasrinput.service",
                        "openasrinput-settings.service",
                    )
                    self.wait_settings()
                except (OSError, RuntimeError, subprocess.SubprocessError):
                    self.stop()
                    raise
                return
            time.sleep(0.1)
        self.run("systemctl", "--user", "stop", "openasrinput-ibus.service", check=False)
        raise RuntimeError("IBus 桥接未就绪，请检查 openasrinput-ibus.service 日志")

    def stop(self):
        self.run(
            "systemctl",
            "--user",
            "stop",
            "openasrinput.service",
            "openasrinput-settings.service",
        )
        (self.state / "settings-ready.json").unlink(missing_ok=True)
        if (self.units / "openasrinput-ibus.service").exists():
            self.run("systemctl", "--user", "stop", "openasrinput-ibus.service", check=False)

    def rollback(self):
        self.framework = self.files.manifest.get("framework", self.framework)
        self.stop()
        self.run(
            "systemctl",
            "--user",
            "disable",
            "openasrinput.service",
            "openasrinput-settings.service",
            check=False,
        )
        self.files.restore()
        self.run("systemctl", "--user", "daemon-reload")
        if self.framework == "fcitx4":
            self.run("fcitx-remote", "-r", check=False)
        elif self.framework == "fcitx5":
            self.run(
                "gdbus",
                "call",
                "--session",
                "--dest",
                "org.fcitx.Fcitx5",
                "--object-path",
                "/controller",
                "--method",
                "org.fcitx.Fcitx.Controller1.Restart",
                check=False,
            )

    def settings_url(self, ready):
        url = json.loads(ready.read_text())["url"]
        parsed = urlsplit(url)
        tokens = parse_qs(parsed.fragment)
        if (
            parsed.scheme != "http"
            or parsed.netloc != f"127.0.0.1:{self.settings_port}"
            or parsed.path != "/"
            or parsed.query
            or set(tokens) != {"token"}
            or len(tokens["token"]) != 1
        ):
            raise ValueError("设置就绪地址无效")
        origin = url.split("#", 1)[0]
        api(origin + "api/config", tokens["token"][0], timeout=0.5)
        health = api(origin + "api/health", tokens["token"][0], timeout=0.5)
        if (
            not isinstance(health, dict)
            or health.get("service") != "OpenASRInput.Settings"
            or health.get("version") != __version__
            or "dictionary-import" not in health.get("features", [])
            or "portal-cards" not in health.get("features", [])
            or "audio-calibration" not in health.get("features", [])
        ):
            raise ValueError("设置进程尚未支持当前界面")
        # A pre-upgrade process can still answer config requests while its old
        # package resource directory has disappeared. Check the actual UI too.
        for resource in (
            "",
            "settings.mjs",
            "settings.css",
            "personal-hotwords.mjs",
            "model-cards.mjs",
            "portal-cards.mjs",
            "audio-calibration.mjs",
        ):
            if not request_bytes(origin + resource, timeout=0.5):
                raise ValueError("设置页面资源为空")
        return url

    def wait_settings(self):
        ready = self.state / "settings-ready.json"
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if ready.exists():
                try:
                    return self.settings_url(ready)
                except (OSError, ValueError, TypeError, KeyError):
                    pass
            time.sleep(0.1)
        raise RuntimeError(
            f"设置界面未就绪，请检查 openasrinput-settings.service 日志及端口 {self.settings_port}"
        )

    def settings(self):
        # Opening settings must never start, restart or reconfigure services.
        active = self.run(
            "systemctl",
            "--user",
            "is-active",
            "--quiet",
            "openasrinput-settings.service",
            check=False,
        )
        try:
            if active.returncode:
                raise ValueError("设置服务未运行")
            url = self.settings_url(self.state / "settings-ready.json")
        except (OSError, ValueError, TypeError, KeyError) as error:
            raise RuntimeError(
                "设置服务未启动或与当前版本不兼容，请先执行 openasrinput start，再打开设置"
            ) from error
        if not webbrowser.open(url):
            raise RuntimeError("无法启动系统默认浏览器，请检查默认浏览器设置")


def dispatch(action):
    app = PackageDesktop()
    if action == "start":
        app.start()
    elif action == "stop":
        app.stop()
    elif action == "rollback":
        app.rollback()
    elif action == "settings":
        app.settings()
    elif action == "portal":
        webbrowser.open(app.store.read()[0]["portal"]["url"] + "/admin")
    else:
        print(json.dumps(app.store.status(), ensure_ascii=False, indent=2))
