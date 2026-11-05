"""Build and verify Input in isolated, architecture-specific Docker environments."""

import argparse
import concurrent.futures
import hashlib
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENVIRONMENTS = {
    "ubuntu22": {"base": "ubuntu:22.04", "gnome": False},
    "debian12": {"base": "debian:bookworm-slim", "gnome": False},
    "debian13": {"base": "debian:trixie-slim", "gnome": True},
}
PROXIES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")


def source_paths():
    return sorted(
        set(
            subprocess.check_output(
                ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT
            ).split(b"\0")
        )
        - {b""}
    )


def source_fingerprint():
    digest = hashlib.sha256()
    for entry in source_paths():
        path = ROOT / os.fsdecode(entry)
        if path.is_file():
            digest.update(entry + b"\0" + path.read_bytes())
    return digest.hexdigest()


@contextmanager
def source_snapshot(parent):
    """Freeze only inventoried source; parallel edits cannot mix versions in a deb."""
    fingerprint = source_fingerprint()
    with tempfile.TemporaryDirectory(prefix="source-", dir=parent) as temporary:
        snapshot = Path(temporary)
        for entry in source_paths():
            relative = os.fsdecode(entry)
            source = ROOT / relative
            if source.is_file():
                target = snapshot / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        if source_fingerprint() != fingerprint:
            raise RuntimeError("Source changed while taking the build snapshot; retry")
        yield snapshot, fingerprint


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def run(command, log, *, timeout=3600):
    log.parent.mkdir(parents=True, exist_ok=True)
    print("RUN", log.stem, flush=True)
    with log.open("w") as output:
        output.write(json.dumps(command) + "\n")
        output.flush()
        process = subprocess.Popen(
            command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT, start_new_session=True
        )
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise
    if code:
        raise RuntimeError(f"Exit {code}; see {log}")


def image_name(environment, arch, framework):
    return f"openasrinput-matrix:{environment}-{arch}-{framework}"


def mounts(environment, arch):
    return {
        ROOT: ("/source", "ro"),
        ROOT / "build/matrix" / environment / arch: ("/source/build", "rw"),
        ROOT / "test-results/matrix" / environment / arch: ("/source/test-results", "rw"),
        ROOT / ".cache/build/artifacts/linux" / arch / "auto": ("/artifacts", "rw"),
    }


def task(args, environment, arch):
    import fcntl

    logs = ROOT / "test-results/matrix" / environment / arch
    logs.mkdir(parents=True, exist_ok=True)
    with (logs / "run.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {
                "environment": environment,
                "architecture": arch,
                "status": "failed",
                "error": "Another matrix run owns this environment",
            }
        return run_task(args, environment, arch)


def run_task(args, environment, arch):
    label = f"{environment}-{arch}"
    container_name = "openasrinput-" + label + "-" + args.run_id
    logs = ROOT / "test-results/matrix" / environment / arch
    logs.mkdir(parents=True, exist_ok=True)
    result = {
        "environment": environment,
        "architecture": arch,
        "status": "running",
        "startedAt": time.time(),
        "images": {},
        "checks": [],
        "sourceFingerprint": args.source_fingerprint,
        "runId": args.run_id,
        "phase": "package-verification" if args.verify_only else "source-build-test",
    }
    if environment == "ubuntu22" and not args.verify_only:
        (logs / "artifact.json").unlink(missing_ok=True)
    try:
        spec = ENVIRONMENTS[environment]
        for framework in ("fcitx4", "fcitx5", "ibus"):
            image = image_name(environment, arch, framework)
            command = [
                "docker",
                "build",
                "--platform",
                f"linux/{arch}",
                "-f",
                "packaging/docker/Dockerfile.matrix",
                "-t",
                image,
                "--build-arg",
                "BASE=" + spec["base"],
                "--build-arg",
                "FRAMEWORK=" + framework,
                "--build-arg",
                "GNOME=" + str(int(spec["gnome"])),
            ]
            if args.network:
                command += ["--network", args.network]
            for variable in PROXIES:
                command += ["--build-arg", variable]
            if not args.skip_images:
                for attempt in range(1, 4):
                    image_log = logs / f"image-{framework}-{attempt}.log"
                    try:
                        run(command + ["."], image_log, timeout=args.timeout)
                        break
                    except RuntimeError:
                        text = image_log.read_text(errors="replace")
                        if attempt == 3 or not any(
                            marker in text
                            for marker in (
                                "EOF",
                                "502",
                                "503",
                                "504",
                                "TLS handshake timeout",
                                "Temporary failure resolving",
                            )
                        ):
                            raise
            result["images"][framework] = subprocess.check_output(
                ["docker", "image", "inspect", "--format", "{{.Id}}", image], text=True
            ).strip()
        command = [
            "docker",
            "run",
            "--rm",
            "--init",
            "--name",
            container_name,
            "--platform",
            f"linux/{arch}",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--shm-size",
            "512m",
            "--tmpfs",
            "/tmp:exec,mode=1777",
            "-e",
            "HOME=/tmp/home",
            "-e",
            "XDG_RUNTIME_DIR=/tmp/runtime",
            "-e",
            "OPENASRINPUT_BUILD_DIR=/source/build",
            "-e",
            "SOURCE_FINGERPRINT=" + args.source_fingerprint,
            "-e",
            "EXPECTED_ARCH=" + arch,
        ]
        for source, (target, mode) in mounts(environment, arch).items():
            source.mkdir(parents=True, exist_ok=True)
            command += [
                "--mount",
                f"type=bind,src={source},dst={target}" + (",readonly" if mode == "ro" else ""),
            ]
        failed = []
        for framework in () if args.verify_only else ("fcitx4", "fcitx5", "ibus"):
            invocation = [
                image_name(environment, arch, framework),
                "python",
                "scripts/container_matrix.py",
                "--inside",
                "--environment",
                environment,
                "--framework",
                framework,
                "--jobs",
                str(args.jobs),
            ]
            if (
                environment == "ubuntu22"
                and framework == "fcitx5"
                and not args.native_only
                and not failed
            ):
                invocation += ["--package"]
            try:
                (logs / (framework + "-checks.json")).unlink(missing_ok=True)
                run(
                    command + invocation, logs / ("run-" + framework + ".log"), timeout=args.timeout
                )
            except RuntimeError as error:
                failed.append(str(error))
            checks_file = logs / (framework + "-checks.json")
            if checks_file.exists():
                result["checks"] += json.loads(checks_file.read_text())
        artifact = ROOT / "test-results/matrix/ubuntu22" / arch / "artifact.json"
        if (environment == "ubuntu22" or args.verify_only) and not args.native_only:
            if not artifact.exists():
                raise RuntimeError("No successful baseline build receipt; refusing stale packages")
            receipt = json.loads(artifact.read_text())
            if receipt.get("sourceFingerprint") != args.source_fingerprint:
                raise RuntimeError(
                    "Baseline artifact was built from different source; rebuild before verifying"
                )
            result["artifact"] = receipt
            package_file = ROOT / ".cache/build/artifacts/linux" / arch / "auto" / receipt["package"]
            if hashlib.sha256(package_file.read_bytes()).hexdigest() != receipt["sha256"]:
                raise RuntimeError("Package differs from successful baseline build receipt")
            for framework in ("fcitx4", "fcitx5", "ibus"):
                invocation = [
                    image_name(environment, arch, framework),
                    "python",
                    "scripts/container_matrix.py",
                    "--inside",
                    "--environment",
                    environment,
                    "--framework",
                    framework,
                    "--verify-package",
                    "--artifact",
                    "/artifacts/" + receipt["package"],
                ]
                try:
                    (logs / (framework + "-checks.json")).unlink(missing_ok=True)
                    run(
                        command + invocation,
                        logs / ("package-" + framework + ".log"),
                        timeout=args.timeout,
                    )
                except RuntimeError as error:
                    failed.append(str(error))
                checks_file = logs / (framework + "-checks.json")
                if checks_file.exists():
                    result["checks"] += json.loads(checks_file.read_text())
                if package_file.exists():
                    install_command = list(command)
                    install_command[install_command.index("--user") + 1] = "0:0"
                    install_command += [
                        "-e",
                        "OPENASRINPUT_INSTALL_SANDBOX=1",
                        image_name(environment, arch, framework),
                        "python",
                        "tests/check_container_install.py",
                        "/artifacts/" + receipt["package"],
                        "--framework",
                        framework,
                    ]
                    try:
                        run(
                            install_command,
                            logs / ("install-" + framework + ".log"),
                            timeout=args.timeout,
                        )
                        result["checks"].append(
                            {"name": "install-" + framework, "status": "passed"}
                        )
                    except RuntimeError as error:
                        failed.append(str(error))
                        result["checks"].append(
                            {"name": "install-" + framework, "status": "failed"}
                        )
        if failed:
            raise RuntimeError("; ".join(failed))
        if source_fingerprint() != args.source_fingerprint:
            raise RuntimeError(
                "Source changed during the run; rerun before claiming a reproducible result"
            )
        result["status"] = "passed"
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        result.update(status="failed", error=str(error))
        # A timed-out docker CLI can leave its workload behind; only stop our named container.
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    finally:
        result["finishedAt"] = time.time()
        write_json(logs / ("verify-result.json" if args.verify_only else "result.json"), result)
        print(result["status"].upper(), label, flush=True)
    return result


def inside(args):
    expected = {"amd64": "x86_64", "arm64": "aarch64"}[os.environ["EXPECTED_ARCH"]]
    if platform.machine() != expected:
        raise RuntimeError(f"Wrong CPU execution environment: {platform.machine()} != {expected}")
    for directory in (Path.home(), Path(os.environ["XDG_RUNTIME_DIR"])):
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.environ.update(GIO_USE_VFS="local", GSETTINGS_BACKEND="keyfile", LIBGL_ALWAYS_SOFTWARE="1")
    Path("/tmp/opencode").mkdir(exist_ok=True)
    os.environ["OPENASRINPUT_PRIVATE_SYSTEM_BUS"] = "1"
    versions = subprocess.run(
        [
            "dpkg-query",
            "-W",
            "-f=${Package} ${Version}\n",
            "libc6",
            "libibus-1.0-5",
            "libfcitx5core7",
            "fcitx-bin",
            "fcitx5",
            "gnome-shell",
            "sway",
        ],
        capture_output=True,
        text=True,
    )
    (ROOT / "test-results" / (args.framework + "-environment.json")).write_text(
        json.dumps(
            {
                "architecture": platform.machine(),
                "python": sys.version,
                "osRelease": Path("/etc/os-release").read_text(),
                "packages": versions.stdout,
            },
            indent=2,
        )
        + "\n"
    )
    checks = []
    failures = []

    def check(name, command, timeout=300):
        started = time.time()
        try:
            run(command, ROOT / "test-results" / (name + ".log"), timeout=timeout)
            checks.append({"name": name, "status": "passed", "seconds": time.time() - started})
            return True
        except (RuntimeError, subprocess.SubprocessError, OSError) as error:
            checks.append({"name": name, "status": "failed", "error": str(error)})
            failures.append(name)
            return False
        finally:
            (ROOT / "test-results" / (args.framework + "-checks.json")).write_text(
                json.dumps(checks, indent=2) + "\n"
            )

    py = sys.executable
    from build_deb import VERSION

    expected_package = (
        Path("/artifacts") / f"openasrinput_{VERSION}_{os.environ['EXPECTED_ARCH']}.deb"
    )
    if args.verify_package:
        package = Path(args.artifact) if args.artifact else expected_package
        if not package.is_file():
            raise RuntimeError("No built package to verify")
        if args.framework == "fcitx4":
            check(
                "package-fcitx4",
                [
                    "dbus-run-session",
                    "--",
                    "xvfb-run",
                    "-a",
                    py,
                    "tests/test_fcitx4_x11.py",
                    "--package",
                    str(package),
                ],
            )
        elif args.framework == "fcitx5":
            check("portable", [py, "tests/test_portable_deb.py", str(package)])
            check(
                "package-settings",
                [py, "tests/check_packaged_settings.py", "--package", str(package)],
            )
            check(
                "package-fcitx5",
                [
                    "xvfb-run",
                    "-a",
                    py,
                    "tests/test_native_ipc.py",
                    "--visual",
                    "--direct-panel",
                    "--package",
                    str(package),
                ],
            )
        else:
            os.environ["OPENASRINPUT_ISOLATED_IBUS"] = "1"
            check(
                "package-ibus",
                [
                    "dbus-run-session",
                    "--",
                    "xvfb-run",
                    "-a",
                    py,
                    "tests/check_ibus.py",
                    "--package",
                    str(package),
                ],
            )
            for wayland in (False, True):
                check(
                    "package-ibus-selection-" + ("wayland" if wayland else "x11"),
                    [
                        "dbus-run-session",
                        "--",
                        *([] if wayland else ["xvfb-run", "-a"]),
                        py,
                        "tests/check_ibus_gtk.py",
                        "--selection",
                        "--require-panel",
                        "--package",
                        str(package),
                        *(["--wayland"] if wayland else []),
                    ],
                )
        if failures:
            raise RuntimeError("Failed checks: " + ", ".join(failures))
        return
    for framework in (args.framework,) if args.framework != "ibus" else ():
        if not check(
            "configure-" + framework,
            [
                "cmake",
                "-S",
                f"src/native/{framework}",
                "-B",
                f"build/{framework}",
                "-DCMAKE_BUILD_TYPE=Release",
            ],
        ):
            continue
        check(
            "build-" + framework,
            ["cmake", "--build", f"build/{framework}", "-j", str(args.jobs)],
            1200,
        )
        check(
            "ctest-" + framework,
            ["ctest", "--test-dir", f"build/{framework}", "--output-on-failure"],
            600,
        )
    if args.framework == "ibus":
        check("python", [py, "-m", "unittest", "discover", "-s", "tests", "-q"], 600)
        os.environ["OPENASRINPUT_ISOLATED_IBUS"] = "1"
        check("ibus", ["dbus-run-session", "--", "xvfb-run", "-a", py, "tests/check_ibus.py"])
        check(
            "ibus-gtk-x11",
            [
                "dbus-run-session",
                "--",
                "xvfb-run",
                "-a",
                py,
                "tests/check_ibus_gtk.py",
                "--require-panel",
            ],
        )
        check(
            "ibus-gtk-wayland",
            [
                "dbus-run-session",
                "--",
                py,
                "tests/check_ibus_gtk.py",
                "--wayland",
                "--require-panel",
            ],
        )
        check(
            "ibus-selection-x11",
            [
                "dbus-run-session",
                "--",
                "xvfb-run",
                "-a",
                py,
                "tests/check_ibus_gtk.py",
                "--selection",
                "--require-panel",
            ],
        )
        check(
            "ibus-selection-wayland",
            [
                "dbus-run-session",
                "--",
                py,
                "tests/check_ibus_gtk.py",
                "--selection",
                "--wayland",
                "--require-panel",
            ],
        )
        check(
            "ibus-gtk4-selection-capability",
            [
                "dbus-run-session",
                "--",
                "xvfb-run",
                "-a",
                py,
                "tests/check_ibus_gtk.py",
                "--gtk4",
                *([] if args.environment == "debian13" else ["--unsupported-selection"]),
                "--require-panel",
            ],
        )
    elif args.framework == "fcitx4":
        check(
            "fcitx4-xim",
            ["dbus-run-session", "--", "xvfb-run", "-a", py, "tests/test_fcitx4_x11.py"],
            300,
        )
    else:
        check("fcitx5-native", [py, "tests/test_native.py"])
        # Every graphical backend suppresses Classic UI auxiliary text, even
        # when built against a core that supports custom panel callbacks.
        visual = ["--visual", "--direct-panel"]
        check("fcitx5-ipc", ["xvfb-run", "-a", py, "tests/test_native_ipc.py", *visual])
        check(
            "fcitx5-fallback",
            ["xvfb-run", "-a", py, "tests/test_native_ipc.py", *visual, "--wayland-fallback"],
        )
        check("fcitx5-gtk-reset", [py, "tests/check_gtk_focus_reset.py"])
        check("fcitx5-gtk-selection", [py, "tests/check_gtk_selection.py"])
        check("sway", ["dbus-run-session", "--", py, "tests/check_sway_panel.py"])
        if args.environment == "debian13":
            check("gnome", [py, "scripts/check_gnome_panel.py"])
    if args.package and not failures:
        built = check("freeze", [py, "scripts/build_runtime.py"], 1200)
        if built:
            built = check(
                "package",
                [
                    py,
                    "scripts/build_deb.py",
                    "--framework",
                    "auto",
                    "--runtime-dir",
                    "build/runtime/openasrinput-runtime",
                    "--output",
                    "/artifacts",
                ],
                600,
            )
        if built:
            package = expected_package
            (ROOT / "test-results/artifact.json").write_text(
                json.dumps(
                    {
                        "package": package.name,
                        "sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
                        "architecture": os.environ["EXPECTED_ARCH"],
                        "source": "ubuntu22",
                        "sourceFingerprint": os.environ.get("SOURCE_FINGERPRINT", ""),
                    },
                    indent=2,
                )
                + "\n"
            )
    if failures:
        raise RuntimeError("Failed checks: " + ", ".join(failures))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--environments", nargs="+", choices=ENVIRONMENTS, default=list(ENVIRONMENTS)
    )
    parser.add_argument(
        "--arches", nargs="+", choices=("amd64", "arm64"), default=["amd64", "arm64"]
    )
    parser.add_argument("--network", help="Docker image-build network; host for a localhost proxy")
    parser.add_argument("--skip-images", action="store_true")
    parser.add_argument("--native-only", action="store_true")
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Verify baseline deb in each selected environment without rebuilding source",
    )
    parser.add_argument("--parallel", type=int, default=2)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=7200)
    parser.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--environment", choices=ENVIRONMENTS, help=argparse.SUPPRESS)
    parser.add_argument("--package", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--framework", choices=("ibus", "fcitx4", "fcitx5"), help=argparse.SUPPRESS)
    parser.add_argument("--verify-package", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--artifact", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.inside:
        inside(args)
        return
    if min(args.parallel, args.jobs, args.timeout) < 1:
        parser.error("parallel, jobs and timeout must be positive")
    if args.verify_only and args.native_only:
        parser.error("verify-only and native-only are mutually exclusive")
    args.source_fingerprint = source_fingerprint()
    args.run_id = str(time.time_ns())
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as executor:
        futures = [
            executor.submit(task, args, env, arch)
            for env in args.environments
            for arch in args.arches
        ]
        results = [future.result() for future in futures]
    destination = ROOT / "test-results/matrix/summary.json"
    all_results = [
        json.loads(path.read_text()) for path in sorted(destination.parent.glob("*/*/*result.json"))
    ]
    for result in all_results:
        result["stale"] = result.get("sourceFingerprint") != args.source_fingerprint
    write_json(destination, all_results)
    print(destination)
    if any(item["status"] != "passed" for item in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
