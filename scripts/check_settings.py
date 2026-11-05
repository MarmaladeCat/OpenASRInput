"""Run the settings browser check with all HOME/XDG data inside this checkout."""

import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    executable = os.environ.get("OPENASRINPUT_TEST_ELECTRON")
    if not executable:
        raise SystemExit("Set OPENASRINPUT_TEST_ELECTRON to an explicit Electron test executable")
    (ROOT / "test-results").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="settings-sandbox-", dir=ROOT / "test-results"
    ) as directory:
        temporary = Path(directory)
        env = dict(os.environ)
        for name in ("DBUS_SESSION_BUS_ADDRESS", "WAYLAND_DISPLAY", "XMODIFIERS"):
            env.pop(name, None)
        env["ELECTRON_OZONE_PLATFORM_HINT"] = "x11"
        env["XDG_SESSION_TYPE"] = "x11"
        # Deep submodule sandboxes exceed the Unix-domain socket path limit.
        env["OPENASRINPUT_DEFAULT_SOCKET"] = str(ROOT / "test-results/settings.sock")
        for name, part in (
            ("HOME", "home"),
            ("XDG_CONFIG_HOME", "config"),
            ("XDG_DATA_HOME", "data"),
            ("XDG_CACHE_HOME", "cache"),
            ("XDG_RUNTIME_DIR", "runtime"),
            ("TMPDIR", "tmp"),
        ):
            path = temporary / part
            path.mkdir(mode=0o700)
            env[name] = str(path)
        result = subprocess.run(
            [
                "xvfb-run",
                "-a",
                "-s",
                "-screen 0 1200x900x24",
                executable,
                "--ozone-platform=x11",
                os.environ.get(
                    "OPENASRINPUT_TEST_SCRIPT", str(ROOT / "tests/test_settings_ui.cjs")
                ),
            ],
            cwd=ROOT,
            env=env,
            timeout=120,
        )
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
