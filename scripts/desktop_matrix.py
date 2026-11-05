"""Test the delivered deb in actual isolated desktop sessions, reusing image layers.

Unsupported OS/session/framework cells are explicit, never counted as passed.
No full Linux VMs, desktop ISOs, host displays, or global Docker pruning.
"""

import argparse
import fcntl
import hashlib
import itertools
import json
import shutil
import subprocess
import time
from pathlib import Path

from container_matrix import ROOT, source_fingerprint, source_snapshot, write_json
from desktop_targets import (
    BASES,
    DEFAULT_PROFILE,
    DESKTOPS,
    FRAMEWORKS,
    PROFILES,
    exclusions,
    image,
    scope,
    unsupported,
)

RESULTS = ROOT / "test-results/desktop-matrix"


def check_profile(profile):
    """Do not silently replace an archived run's scope with a new definition."""
    manifest = RESULTS / "scope.json"
    summary = RESULTS / "summary.json"
    if manifest.exists():
        profiles = {json.loads(manifest.read_text())["profile"]}
    elif summary.exists():
        profiles = {row.get("profile") for row in json.loads(summary.read_text())} - {None}
    else:
        profiles = set()
    if profiles and profiles != {profile}:
        raise ValueError(
            f"Results belong to {sorted(profiles)}, not {profile}; use a new directory"
        )


def summarize(profile=DEFAULT_PROFILE):
    check_profile(profile)
    manifest = scope(profile)
    rows = []
    for target in manifest["targets"]:
        release, arch, desktop, protocol, framework = target.values()
        path = RESULTS / f"{release}-{arch}-{desktop}-{protocol}-{framework}" / "result.json"
        rows.append(
            json.loads(path.read_text())
            if path.exists()
            else dict(target, profile=profile, status="not-run")
        )
    write_json(RESULTS / "scope.json", manifest)
    write_json(RESULTS / "summary.json", rows)
    counts = {
        status: sum(row["status"] == status for row in rows)
        for status in sorted({row["status"] for row in rows})
    }
    print(json.dumps(counts), flush=True)
    return rows


def invoke(command, path, timeout=3600):
    print("RUN", path.stem, flush=True)
    with path.open("w") as log:
        log.write(json.dumps(list(map(str, command))) + "\n")
        log.flush()
        subprocess.run(
            list(map(str, command)),
            stdout=log,
            stderr=subprocess.STDOUT,
            check=True,
            timeout=timeout,
            cwd=ROOT,
        )


def build_images(release, arch, args):
    base = f"openasrinput-matrix:ubuntu22-{arch}-fcitx4" if release == "22.04" else BASES[release]
    command = [
        "docker",
        "build",
        "--platform",
        f"linux/{arch}",
        "--network",
        args.network,
        "-f",
        "packaging/docker/Dockerfile.desktop-matrix",
        "--build-arg",
        "BASE=" + base,
    ]
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
        command += ["--build-arg", name]
    for framework in args.frameworks:
        if not any(
            not exclusions(args.profile, release, desktop, protocol, framework)
            and not unsupported(release, desktop, protocol, framework)
            for desktop, protocol in itertools.product(args.desktops, args.protocols)
        ):
            continue
        for attempt in range(1, 4):
            log = RESULTS / f"image-{release}-{arch}-{framework}-{attempt}.log"
            try:
                invoke(
                    [
                        *command,
                        "--build-arg",
                        "FRAMEWORK=" + framework,
                        "-t",
                        image(release, arch, framework),
                        ".",
                    ],
                    log,
                    timeout=7200,
                )
                break
            except subprocess.CalledProcessError:
                if attempt == 3 or not any(
                    marker in log.read_text(errors="replace")
                    for marker in ("502", "503", "504", "EOF", "TLS handshake timeout")
                ):
                    raise


def main():
    global RESULTS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=PROFILES, default=DEFAULT_PROFILE)
    parser.add_argument(
        "--list-targets",
        action="store_true",
        help="print scope/exclusions as JSON without writing or running",
    )
    parser.add_argument("--releases", nargs="+", choices=BASES)
    parser.add_argument(
        "--arches", nargs="+", choices=("amd64", "arm64"), default=["amd64", "arm64"]
    )
    parser.add_argument("--desktops", nargs="+", choices=DESKTOPS, default=list(DESKTOPS))
    parser.add_argument(
        "--protocols", nargs="+", choices=("x11", "wayland"), default=["x11", "wayland"]
    )
    parser.add_argument("--frameworks", nargs="+", choices=FRAMEWORKS, default=list(FRAMEWORKS))
    parser.add_argument("--network", default="default")
    parser.add_argument("--skip-images", action="store_true")
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument(
        "--summarize",
        action="store_true",
        help="aggregate the full profile without executing tests",
    )
    parser.add_argument(
        "--resume", action="store_true", help="reuse passing identical-source/image/package cells"
    )
    parser.add_argument("--minimum-free-gib", type=int, default=25)
    parser.add_argument(
        "--package-root",
        type=Path,
        default=ROOT / ".cache/build/artifacts/linux",
        help="candidate directory containing <arch>/auto/*.deb",
    )
    parser.add_argument(
        "--probe-root",
        type=Path,
        default=ROOT / "build/matrix/ubuntu22",
        help="native test fixtures under <arch>/fcitx4 (e.g. build/portable)",
    )
    parser.add_argument(
        "--results",
        type=Path,
        default=RESULTS,
        help="evidence directory; use a fresh directory for a versioned acceptance run",
    )
    args = parser.parse_args()
    profile_releases = PROFILES[args.profile]
    args.releases = args.releases or list(profile_releases)
    if not set(args.releases) <= set(profile_releases):
        parser.error("selected release is outside the requested profile")
    if args.list_targets:
        print(
            json.dumps(
                scope(
                    args.profile,
                    releases=args.releases,
                    arches=args.arches,
                    desktops=args.desktops,
                    protocols=args.protocols,
                    frameworks=args.frameworks,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    RESULTS = args.results.resolve()
    RESULTS.mkdir(parents=True, exist_ok=True)
    check_profile(args.profile)
    if args.summarize:
        summarize(args.profile)
        return
    if args.build_only:
        run_matrix(args, ROOT, source_fingerprint())
        return
    with source_snapshot(RESULTS) as (source, fingerprint):
        run_matrix(args, source, fingerprint)


def run_matrix(args, source, fingerprint):
    rows = []
    for release, arch in itertools.product(args.releases, args.arches):
        if not any(
            not exclusions(args.profile, release, desktop, protocol, framework)
            for desktop, protocol, framework in itertools.product(
                args.desktops, args.protocols, args.frameworks
            )
        ):
            continue
        if shutil.disk_usage(ROOT).free < args.minimum_free_gib * 1024**3:
            raise RuntimeError("Free-space reserve reached; refusing another environment")
        environment_error = None
        packages = list((args.package_root / arch / "auto").glob("*.deb"))
        package = packages[0].resolve() if len(packages) == 1 else None
        digest = hashlib.sha256(package.read_bytes()).hexdigest() if package else None
        receipt = {}
        if package and (package.parent / "build-receipt.json").is_file():
            receipt = json.loads((package.parent / "build-receipt.json").read_text())
            if receipt.get("packages", {}).get(package.name) != digest:
                environment_error = "Candidate does not match its build receipt"
        if release not in ("18.04", "20.04") and not args.skip_images:
            try:
                build_images(release, arch, args)
            except (OSError, subprocess.SubprocessError) as error:
                environment_error = str(error)
        if args.build_only:
            if environment_error:
                raise RuntimeError(environment_error)
            continue
        if release in ("18.04", "20.04") and package:
            # Only download the tiny base image; do not install unsupported desktops.
            command = [
                "docker",
                "run",
                "--rm",
                "--platform",
                f"linux/{arch}",
                "--mount",
                f"type=bind,src={package},dst=/input.deb,readonly",
                BASES[release],
                "sh",
                "-c",
                "getconf GNU_LIBC_VERSION; dpkg --print-architecture; dpkg --info /input.deb; "
                "dpkg --install /input.deb; code=$?; test $code -ne 0",
            ]
            try:
                invoke(command, RESULTS / f"unsupported-{release}-{arch}.log", timeout=300)
            except (OSError, subprocess.SubprocessError) as error:
                environment_error = str(error)
        for desktop, protocol, framework in itertools.product(
            args.desktops, args.protocols, args.frameworks
        ):
            if exclusions(args.profile, release, desktop, protocol, framework):
                continue
            key = f"{release}-{arch}-{desktop}-{protocol}-{framework}"
            directory = RESULTS / key
            directory.mkdir(exist_ok=True)
            # Prevent concurrent commands from overwriting the same cell/logs.
            lock = (directory / ".lock").open("w")
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            record = dict(
                release=release,
                architecture=arch,
                desktop=desktop,
                protocol=protocol,
                framework=framework,
                sourceFingerprint=fingerprint,
                sourceMode="read-only-snapshot",
                packageSha256=digest,
                package=str(package),
                buildSourceFingerprint=receipt.get("sourceFingerprint"),
                buildImage=receipt.get("image"),
                profile=args.profile,
                executionHost="container-native" if arch == "amd64" else "container-qemu-user",
                defaultInstallation=False,
                probeSha256=None,
                startedAt=time.time(),
            )
            exclusion = unsupported(release, desktop, protocol, framework)
            if not package or environment_error:
                record.update(
                    status="environment-blocked",
                    reason=environment_error or f"Expected one {arch} candidate deb",
                )
            elif exclusion:
                record.update(status=exclusion[0], reason=exclusion[1])
            else:
                tag = image(release, arch, framework)
                try:
                    record["image"] = subprocess.check_output(
                        ["docker", "image", "inspect", "--format", "{{.Id}}", tag],
                        text=True,
                        stderr=subprocess.PIPE,
                    ).strip()
                except subprocess.CalledProcessError:
                    record.update(
                        status="environment-blocked", reason="Missing desktop image: " + tag
                    )
                    record["finishedAt"] = time.time()
                    write_json(directory / "result.json", record)
                    rows.append(record)
                    lock.close()
                    print("ENVIRONMENT-BLOCKED", key, flush=True)
                    continue
                previous = directory / "result.json"
                probes = directory / "probes"
                probes.mkdir(exist_ok=True)
                if framework == "fcitx4":
                    try:
                        payload = (args.probe_root / arch / "fcitx4/fcitx4_xim_probe").read_bytes()
                    except OSError as error:
                        record.update(status="environment-blocked", reason=str(error))
                        write_json(previous, record)
                        rows.append(record)
                        lock.close()
                        continue
                    fixture = probes / "fcitx4/fcitx4_xim_probe"
                    fixture.parent.mkdir(exist_ok=True)
                    fixture.write_bytes(payload)
                    fixture.chmod(0o755)
                    record["probeSha256"] = hashlib.sha256(payload).hexdigest()
                if args.resume and previous.exists():
                    old = json.loads(previous.read_text())
                    if old.get("status") == "passed" and all(
                        old.get(k) == record[k]
                        for k in ("sourceFingerprint", "packageSha256", "image", "probeSha256")
                    ):
                        print("REUSE", key, flush=True)
                        rows.append(old)
                        lock.close()
                        continue
                batch = hashlib.sha256(str(RESULTS).encode()).hexdigest()[:8]
                container = "openasrinput-desktop-" + batch + "-" + key.replace(".", "-")
                try:
                    for name in ("evidence.json", "input.json", "xim.json"):
                        (directory / name).unlink(missing_ok=True)
                    invoke(
                        [
                            "docker",
                            "run",
                            "--rm",
                            "--init",
                            "--name",
                            container,
                            "--platform",
                            f"linux/{arch}",
                            "--network",
                            "none",
                            "--shm-size",
                            "512m",
                            "--env",
                            "OPENASRINPUT_TRACE_DESKTOP",
                            "--env",
                            "OPENASRINPUT_TRACE_IPC",
                            "--mount",
                            f"type=bind,src={source},dst=/source,readonly",
                            "--mount",
                            f"type=bind,src={directory},dst=/results",
                            "--mount",
                            f"type=bind,src={package},dst=/input.deb,readonly",
                            "--mount",
                            f"type=bind,src={probes},dst=/probes,readonly",
                            tag,
                            "/usr/bin/python3",
                            "tests/check_desktop_session.py",
                            "--desktop",
                            desktop,
                            "--protocol",
                            protocol,
                            "--framework",
                            framework,
                        ],
                        directory / "run.log",
                        timeout=600,
                    )
                    evidence = json.loads((directory / "evidence.json").read_text())
                    record.update(
                        status=(
                            "session-unavailable"
                            if evidence.get("status") == "session-unavailable"
                            else "failed"
                            if evidence.get("failures")
                            else "degraded"
                            if evidence.get("customPanel") is False
                            else "passed"
                        ),
                        evidence=evidence,
                    )
                    if record["status"] == "session-unavailable":
                        record["reason"] = evidence["reason"]
                    if record["status"] == "degraded":
                        record["reason"] = (
                            "Input tests passed, but custom panel unavailable; system/text fallback only."
                        )
                except (subprocess.SubprocessError, OSError, ValueError) as error:
                    record.update(status="failed", error=str(error))
                finally:
                    subprocess.run(
                        ["docker", "rm", "-f", container],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
            record["finishedAt"] = time.time()
            # The readonly snapshot, not the possibly edited checkout, ran the
            # test. Retain the live tree identity separately for diagnostics.
            record["workingSourceFingerprintEnd"] = source_fingerprint()
            write_json(directory / "result.json", record)
            lock.close()
            rows.append(record)
            print(record["status"].upper(), key, flush=True)
        write_json(
            RESULTS / f"summary-{release}-{arch}.json",
            [row for row in rows if row["release"] == release and row["architecture"] == arch],
        )
    if not args.build_only:
        summarize(args.profile)
        if any(row["status"] != "passed" for row in rows):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
