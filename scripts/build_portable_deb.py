"""Build Input on Ubuntu 22.04 with private Python/ICU, for newer compatible deb systems."""

import argparse
import hashlib
import json
import os
import platform
import subprocess
from pathlib import Path

from container_matrix import source_snapshot, write_json

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--framework", choices=("auto", "fcitx4", "fcitx5"), default="auto")
    parser.add_argument(
        "--arch",
        choices=("amd64", "arm64"),
        default={"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine(), "amd64"),
    )
    parser.add_argument("--output", type=Path, help="product-owned candidate output directory")
    parser.add_argument("--image", help="explicit compatible baseline build image")
    parser.add_argument("--skip-image-build", action="store_true")
    parser.add_argument("--build-network", help="e.g. host when using a loopback proxy")
    args = parser.parse_args()
    image = args.image or "openasrinput-build:ubuntu22.04-" + args.arch
    if not args.skip_image_build:
        command = [
            "docker",
            "build",
            "--platform",
            "linux/" + args.arch,
            "-f",
            "packaging/docker/Dockerfile.portable",
            "-t",
            image,
        ]
        if args.build_network:
            command += ["--network", args.build_network]
        for variable in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
            command += ["--build-arg", variable]
        subprocess.run([*command, "."], cwd=ROOT, check=True)
    build = ROOT / ".cache/build/portable" / args.arch
    build.mkdir(parents=True, exist_ok=True)
    image_id = subprocess.check_output(
        ["docker", "image", "inspect", "--format", "{{.Id}}", image], text=True
    ).strip()
    output = (
        args.output.resolve()
        if args.output
        else ROOT / ".cache/build/artifacts/linux" / args.arch / args.framework
    )
    output.mkdir(parents=True, exist_ok=True)
    framework = args.framework
    commands = []
    for backend in ("fcitx4", "fcitx5") if framework == "auto" else (framework,):
        commands.extend(
            [
                [
                    "cmake",
                    "-S",
                    f"/source/src/native/{backend}",
                    "-B",
                    f"/build/{backend}",
                    "-DCMAKE_BUILD_TYPE=Release",
                ],
                ["cmake", "--build", f"/build/{backend}", "-j4"],
                ["ctest", "--test-dir", f"/build/{backend}", "--output-on-failure"],
            ]
        )
    commands.extend(
        [
            ["python", "/source/scripts/build_runtime.py"],
            [
                "python",
                "/source/scripts/build_deb.py",
                "--framework",
                framework,
                "--native-build",
                "/build" if framework == "auto" else f"/build/{framework}",
                "--runtime-dir",
                "/build/runtime/openasrinput-runtime",
                "--output",
                "/artifacts",
            ],
        ]
    )
    # All writable paths are product build caches; the source mount is read-only.
    code = "import subprocess; " + "; ".join(
        "subprocess.run(" + repr(command) + ", check=True)" for command in commands
    )
    with source_snapshot(build) as (source, fingerprint):
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--platform",
                "linux/" + args.arch,
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "-e",
                "HOME=/tmp",
                "-e",
                "OPENASRINPUT_BUILD_DIR=/build",
                "-e",
                "OPENASR_BUILD_IMAGE=" + image_id,
                "-v",
                f"{source}:/source:ro",
                "-v",
                f"{build}:/build",
                "-v",
                f"{output}:/artifacts",
                image_id,
                "python",
                "-c",
                code,
            ],
            check=True,
        )
    write_json(
        output / "build-receipt.json",
        {
            "architecture": args.arch,
            "sourceFingerprint": fingerprint,
            "image": subprocess.check_output(
                ["docker", "image", "inspect", "--format", "{{.Id}}", image], text=True
            ).strip(),
            "packages": {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in output.glob("*.deb")
            },
            "baseline": "Ubuntu 22.04 / glibc 2.35",
        },
    )
    print(
        json.dumps(
            {
                "framework": framework,
                "baseline": "Ubuntu 22.04 / glibc 2.35",
                "runtime": "private ASR Python and ICU; IBus uses system Python/GI",
            }
        )
    )


if __name__ == "__main__":
    main()
