"""Linux input-framework selection; never changes the desktop input source."""

import os
import subprocess

FRAMEWORKS = ("ibus", "fcitx4", "fcitx5")


def running_frameworks():
    def output(*args):
        try:
            result = subprocess.run(args, capture_output=True, text=True, timeout=2)
            return result.stdout.strip() if result.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError):
            return ""

    names = output(
        "gdbus",
        "call",
        "--session",
        "--dest",
        "org.freedesktop.DBus",
        "--object-path",
        "/org/freedesktop/DBus",
        "--method",
        "org.freedesktop.DBus.ListNames",
    )
    result = []
    if output("ibus", "engine"):
        result.append("ibus")
    if "'org.fcitx.Fcitx5'" in names:
        result.append("fcitx5")
    if ("'org.fcitx.Fcitx'" in names or output("fcitx-remote") in {"1", "2"}) and os.environ.get(
        "XDG_SESSION_TYPE"
    ) != "wayland":
        result.append("fcitx4")
    return result


def select_framework(preference="auto", *, running=None, environ=None):
    env = os.environ if environ is None else environ
    if preference not in ("auto", *FRAMEWORKS):
        raise ValueError("输入框架必须是 auto、ibus、fcitx4 或 fcitx5")
    if preference != "auto":
        if preference == "fcitx4" and env.get("XDG_SESSION_TYPE") == "wayland":
            raise RuntimeError("Fcitx4 桥接仅支持 X11")
        return preference
    candidates = list(running_frameworks() if running is None else running)
    if env.get("XDG_SESSION_TYPE") == "wayland":
        candidates = [item for item in candidates if item != "fcitx4"]
    if len(candidates) == 1:
        return candidates[0]
    hints = {env.get(key, "") for key in ("GTK_IM_MODULE", "QT_IM_MODULE")} - {""}
    if hints == {"ibus"} and "ibus" in candidates:
        return "ibus"
    fcitx = [item for item in candidates if item.startswith("fcitx")]
    if hints <= {"fcitx", "fcitx5"} and hints and len(fcitx) == 1:
        return fcitx[0]
    raise RuntimeError("无法唯一识别活动输入框架；请在设置页手动选择，并执行 openasrinput start")
