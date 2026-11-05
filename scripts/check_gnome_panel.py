"""Run real GNOME Wayland and Fcitx on a private bus with project-local data."""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    (ROOT / "test-results").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="g-", dir=ROOT / "test-results") as directory:
        sandbox = Path(directory)
        env = dict(os.environ)
        for name in (
            "DISPLAY",
            "WAYLAND_DISPLAY",
            "WAYLAND_SOCKET",
            "DBUS_SESSION_BUS_ADDRESS",
            "XMODIFIERS",
        ):
            env.pop(name, None)
        for name, folder in (
            ("HOME", "home"),
            ("XDG_CONFIG_HOME", "config"),
            ("XDG_DATA_HOME", "data"),
            ("XDG_CACHE_HOME", "cache"),
            ("XDG_RUNTIME_DIR", "r"),
            ("TMPDIR", "tmp"),
        ):
            path = sandbox / folder
            path.mkdir(mode=0o700)
            env[name] = str(path)
        extension = Path(env["XDG_DATA_HOME"]) / "gnome-shell/extensions/openasrinput@local"
        shutil.copytree(ROOT / "src/native/gnome/openasrinput@local", extension)
        env.update(
            PYTHONDONTWRITEBYTECODE="1",
            PYTHONPATH=str(ROOT / "src"),
            XDG_SESSION_TYPE="wayland",
            GSETTINGS_BACKEND="keyfile",
            LIBGL_ALWAYS_SOFTWARE="1",
        )
        subprocess.run(
            [
                "dbus-run-session",
                "--",
                sys.executable,
                str(ROOT / "tests/test_gnome_panel.py"),
                str(sandbox),
            ],
            cwd=ROOT,
            env=env,
            check=True,
            timeout=300,
        )


if __name__ == "__main__":
    main()
