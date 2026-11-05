"""Build Input in its Ubuntu baseline container or isolated Windows environment."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

from release import collect, prepare_candidates, source_digest

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=("linux", "windows"), required=True)
    parser.add_argument("--arch", choices=("amd64", "arm64"), default="amd64")
    parser.add_argument("--build-network")
    parser.add_argument("--wix-bin", type=Path)
    args = parser.parse_args()
    before = prepare_candidates(args.platform, args.arch)
    if args.platform == "windows":
        if os.name != "nt" or args.arch != "amd64" or sys.version_info[:3] != (3, 12, 10):
            parser.error("Windows requires the native Python 3.12.10 amd64 build environment")
        command = [sys.executable, "scripts/build_windows.py", "--python-version", "3.12.10"]
        if args.wix_bin:
            command += ["--wix-bin", str(args.wix_bin)]
    else:
        command = [
            sys.executable,
            "scripts/build_portable_deb.py",
            "--framework",
            "auto",
            "--arch",
            args.arch,
        ]
        if args.build_network:
            command += ["--build-network", args.build_network]
    subprocess.run(command, cwd=ROOT, check=True)
    if source_digest() != before:
        raise RuntimeError("Product sources changed during build")
    collect(args.platform, args.arch)


if __name__ == "__main__":
    main()
