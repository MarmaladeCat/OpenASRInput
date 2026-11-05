"""Run an explicit Electron check command in a project-local desktop sandbox."""

import argparse
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("provide the explicit test command after --")
    # Chromium creates TMPDIR/scoped_dir*/SingletonSocket (AF_UNIX limit: 108
    # bytes). Keep the project-local sandbox prefix short enough for it.
    with tempfile.TemporaryDirectory(prefix="e-", dir=ROOT / ".cache") as directory:
        temporary = Path(directory)
        environment = dict(os.environ)
        for name in ("DBUS_SESSION_BUS_ADDRESS", "WAYLAND_DISPLAY", "XMODIFIERS"):
            environment.pop(name, None)
        for name, part in (
            ("HOME", "home"),
            ("XDG_CONFIG_HOME", "config"),
            ("XDG_DATA_HOME", "data"),
            ("XDG_STATE_HOME", "state"),
            ("XDG_CACHE_HOME", "cache"),
            ("XDG_RUNTIME_DIR", "runtime"),
            ("TMPDIR", "tmp"),
        ):
            path = temporary / part
            path.mkdir(mode=0o700)
            environment[name] = str(path)
        environment["ELECTRON_OZONE_PLATFORM_HINT"] = "x11"
        environment["XDG_SESSION_TYPE"] = "x11"
        environment["GTK_THEME"] = "Adwaita"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["npm_config_cache"] = str(temporary / "npm")
        result = subprocess.run(
            ["dbus-run-session", "--", "xvfb-run", "-a", "-s", "-screen 0 1440x1000x24", *command],
            cwd=args.workdir.resolve(),
            env=environment,
            timeout=180,
        )
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
