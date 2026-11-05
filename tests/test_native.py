"""Run native checks with HOME/XDG/runtime and a copied RIME fixture in this repo."""

import argparse
import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fingerprint(source):
    names = ("default.custom.yaml", "rime_ice.custom.yaml", "user.yaml", "build/default.yaml")
    return {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in names}


def main():
    parser = argparse.ArgumentParser(description="Isolated Fcitx5 native preedit / waveform checks")
    parser.add_argument("--build", type=Path, default=ROOT / "build/fcitx5")
    parser.add_argument("--rime-source", type=Path)
    args = parser.parse_args()
    build = args.build.resolve()
    before = fingerprint(args.rime_source) if args.rime_source else None
    (ROOT / "test-results").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="native-", dir=ROOT / "test-results") as directory:
        temporary = Path(directory)
        env = dict(os.environ)
        for name in ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "XMODIFIERS"):
            env.pop(name, None)
        env.update(
            {
                "HOME": str(temporary / "home"),
                "XDG_CONFIG_HOME": str(temporary / "config"),
                "XDG_DATA_HOME": str(temporary / "data"),
                "XDG_CACHE_HOME": str(temporary / "cache"),
                "XDG_RUNTIME_DIR": str(temporary / "runtime"),
                "TMPDIR": str(temporary / "tmp"),
            }
        )
        for name in (
            "HOME",
            "XDG_CONFIG_HOME",
            "XDG_DATA_HOME",
            "XDG_CACHE_HOME",
            "XDG_RUNTIME_DIR",
            "TMPDIR",
        ):
            Path(env[name]).mkdir(mode=0o700)
        command = [str(build / "native_check")]
        if args.rime_source:
            source = args.rime_source.resolve()
            destination = temporary / "data/fcitx5/rime"
            destination.mkdir(parents=True)
            # No userdb, sync history, .git, or original build outputs. RIME deploys
            # only this copy; it cannot write through to the original directory.
            for entry in source.iterdir():
                if entry.is_file() and entry.suffix in {".yaml", ".txt"}:
                    shutil.copy2(entry, destination / entry.name)
            for name in ("cn_dicts", "en_dicts", "lua", "opencc"):
                shutil.copytree(source / name, destination / name, symlinks=False)
            profile = temporary / "config/fcitx5/profile"
            profile.parent.mkdir(parents=True)
            profile.write_text(
                "[Groups/0]\nName=Isolated\nDefault Layout=us\nDefaultIM=rime\n\n"
                "[Groups/0/Items/0]\nName=keyboard-us\nLayout=\n\n"
                "[Groups/0/Items/1]\nName=rime\nLayout=\n\n[GroupOrder]\n0=Isolated\n",
                encoding="utf-8",
            )
            command.append("--rime")
        try:
            result = subprocess.run(command, env=env, cwd=ROOT, timeout=180)
        finally:
            if before is not None and before != fingerprint(args.rime_source):
                raise RuntimeError("original RIME configuration changed during test")
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
