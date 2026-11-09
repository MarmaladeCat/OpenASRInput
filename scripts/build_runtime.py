"""Freeze the private application runtime on the oldest supported libc baseline."""

import os
import subprocess
import sys
from pathlib import Path

from runtime_cache import fingerprint, record, reusable
ROOT = Path(__file__).resolve().parents[1]


def main():
    build = Path(os.environ.get("OPENASRINPUT_BUILD_DIR", ROOT / "build"))
    marker = build / "runtime-cache.json"
    output = build / "runtime/openasrinput-runtime"
    key = fingerprint(ROOT)
    if reusable(marker, key, output):
        print("Reusing verified frozen Input runtime", flush=True)
        return
    marker.unlink(missing_ok=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onedir",
            "--name",
            "openasrinput-runtime",
            "--distpath",
            str(build / "runtime"),
            "--workpath",
            str(build / "pyinstaller"),
            "--specpath",
            str(build / "pyinstaller"),
            "--paths",
            str(ROOT / "src"),
            "--add-data",
            str(ROOT / "src/openasrinput/presentation/web") + ":openasrinput/presentation/web",
            "--add-data",
            str(ROOT / "src/openasrinput/presentation/branding")
            + ":openasrinput/presentation/branding",
            str(ROOT / "packaging/openasrinput"),
        ],
        cwd=ROOT,
        check=True,
    )
    record(marker, key, output)


if __name__ == "__main__":
    main()
