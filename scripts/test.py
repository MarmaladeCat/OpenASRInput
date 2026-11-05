"""Prepare and run product-owned, coarse functional scenarios (no unit-test discovery)."""

import argparse
import hashlib
import json
import locale
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
import venv
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCTS = {"OpenASRInput": ROOT}
TARGET = f"{sys.platform}-{platform.machine().lower()}"


def execute(command, directory, env=None, log=None, timeout=600):
    command = [shutil.which(str(command[0])) or str(command[0]), *map(str, command[1:])]
    print(f"[{directory.name}] {' '.join(command)}", flush=True)
    with subprocess.Popen(
        command,
        cwd=directory,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT if log else None,
        start_new_session=os.name != "nt",
    ) as process:
        try:
            code = process.wait(timeout=timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            # Reap only this scenario's process tree, including browser/service children.
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            else:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise
        if code:
            raise subprocess.CalledProcessError(code, command)


def environment(directory):
    base = directory / ".cache/functional" / TARGET
    python = base / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return base, python


def electron(directory):
    return (
        directory
        / "node_modules/electron/dist"
        / ("electron.exe" if os.name == "nt" else "electron")
    )


def npm_setup(directory, env):
    lock = directory / "package-lock.json"
    stamp = directory / "node_modules/.functional-environment"
    fingerprint = TARGET + ":" + hashlib.sha256(lock.read_bytes()).hexdigest()
    if stamp.exists() and stamp.read_text() == fingerprint and electron(directory).exists():
        return
    execute(["npm", "ci", "--no-audit", "--no-fund"], directory, env, timeout=1800)
    # Electron 44 exposes an explicit installer instead of a postinstall hook.
    if not electron(directory).exists():
        execute(["node", "node_modules/electron/install.js"], directory, env, timeout=1800)
    if not electron(directory).exists():
        raise RuntimeError(f"Electron executable missing after setup: {directory}")
    stamp.write_text(fingerprint)


def drawio(directory, resource):
    target = directory / "third_party/drawio/webapp"
    if (target / "index.html").exists():
        return
    archive = directory / ".cache/functional/drawio.war"
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.exists():
        temporary = archive.with_suffix(".download")
        if os.name == "nt":
            # Windows curl uses Schannel, including Windows' on-demand root updates.
            # Keep TLS verification enabled; verify the pinned archive hash below too.
            execute(
                [
                    "curl.exe",
                    "--fail",
                    "--location",
                    "--max-time",
                    "600",
                    "--output",
                    temporary,
                    resource["url"],
                ],
                directory,
                timeout=660,
            )
        else:
            with urllib.request.urlopen(resource["url"], timeout=120) as response:
                with temporary.open("wb") as output:
                    shutil.copyfileobj(response, output)
        temporary.replace(archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != resource["sha256"]:
        raise RuntimeError(f"draw.io checksum mismatch: {archive}")
    with zipfile.ZipFile(archive) as package:
        package.extractall(target)
    for name in ("WEB-INF", "META-INF"):
        shutil.rmtree(target / name, ignore_errors=True)
    archive.unlink()


def setup(directory, manifest, suite, env):
    base, python = environment(directory)
    base.mkdir(parents=True, exist_ok=True)
    if not python.exists():
        venv.create(base / "venv", with_pip=True)
    lock = directory / "tests/functional/requirements.txt"
    fingerprint = hashlib.sha256(lock.read_bytes()).hexdigest() if lock.exists() else "stdlib"
    stamp = base / "requirements.sha256"
    if not stamp.exists() or stamp.read_text() != fingerprint:
        if lock.exists():
            execute([python, "-m", "pip", "install", "-r", lock], directory, env, timeout=1800)
            execute([python, "-m", "pip", "check"], directory, env)
        stamp.write_text(fingerprint)
    if suite in ("unit", "ui"):
        if manifest.get("nodeProject"):
            npm_setup(directory, env)
        if suite == "ui" and manifest.get("drawio"):
            drawio(directory, manifest["drawio"])
        for command in manifest.get("prepareUI", []) if suite == "ui" else []:
            execute(command, directory, env)
    if suite == "windows-native":
        for command in manifest.get("prepareWindows", []):
            execute(command, directory, env, timeout=1800)
    print(f"Ready: {manifest['product']} ({TARGET})", flush=True)


def read_manifests(names):
    result = []
    for name in names:
        directory = PRODUCTS[name]
        document = directory / "tests/functional/manifest.json"
        manifest = json.loads(document.read_text(encoding="utf-8"))
        if manifest.get("schemaVersion") != 1 or manifest["product"] != name:
            raise ValueError(f"Invalid manifest: {document}")
        ids = [case["id"] for case in manifest["cases"]]
        if len(ids) != len(set(ids)):
            raise ValueError(f"Duplicate case IDs: {document}")
        result.append((directory, manifest))
    return result


def provenance(directory):
    try:
        commit = (
            subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=directory).decode().strip()
        )
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=directory))
        return {"commit": commit, "dirty": dirty}
    except (OSError, subprocess.CalledProcessError):
        snapshot = ROOT / "source-provenance.json"
        return json.loads(snapshot.read_text()).get(directory.name, {}) if snapshot.exists() else {}


def host_context(kind):
    """Record the environment without conflating a Windows guest with physical hardware."""
    result = {
        "kind": kind,
        "locale": locale.getlocale(),
        "preferredEncoding": locale.getpreferredencoding(False),
        "utf8Mode": sys.flags.utf8_mode,
    }
    if os.name == "nt":
        import ctypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        user = ctypes.WinDLL("user32", use_last_error=True)
        session = ctypes.c_ulong()
        if not kernel.ProcessIdToSessionId(os.getpid(), ctypes.byref(session)):
            raise ctypes.WinError(ctypes.get_last_error())
        result.update(
            sessionId=session.value,
            ansiCodePage=kernel.GetACP(),
            monitorCount=user.GetSystemMetrics(80),
            remoteSession=bool(user.GetSystemMetrics(0x1000)),
        )
    return result


def runtime_context(python, env, options=()):
    return json.loads(
        subprocess.check_output(
            [
                str(python),
                *options,
                "-c",
                "import json,sys; print(json.dumps({'executable':sys.executable,"
                "'version':sys.version,'utf8Mode':sys.flags.utf8_mode}))",
            ],
            text=True,
            env=env,
            timeout=15,
        )
    )


def run_case(directory, manifest, case, report_dir, env, ui_tool):
    base, python = environment(directory)
    replacements = {
        "python": str(python),
        "electron": str(electron(directory) if manifest.get("nodeProject") else electron(ui_tool)),
    }
    command = [part.format(**replacements) for part in case["command"]]
    if case["suite"] == "ui" and os.name != "nt":
        command = ["xvfb-run", "-a", *command]
    product_env = {
        **env,
        "PYTHONPATH": os.pathsep.join(str(directory / p) for p in manifest["pythonPath"]),
        "OPENASRINPUT_TEST_PYTHON": str(python),
        "OPENASRPORTAL_TEST_PYTHON": str(python),
    }
    log_path = report_dir / f"{manifest['product']}-{case['id']}.log"
    entry = {"product": manifest["product"], **case, "command": command, "log": log_path.name}
    started = time.monotonic()
    started_wall = time.time()
    try:
        if not python.exists():
            raise RuntimeError("Run setup for this target first")
        options = command[1:3] if command[:2] == [str(python), "-X"] else []
        entry["pythonRuntime"] = runtime_context(python, product_env, options)
        with log_path.open("w", encoding="utf-8") as log:
            execute(command, directory, product_env, log, case.get("timeout", 300))
        output = log_path.read_text(encoding="utf-8", errors="replace")
        skipped = sum(int(value) for value in re.findall(r"OK \(skipped=(\d+)\)", output))
        entry["skipped"] = skipped
        entry["status"] = "incomplete" if skipped else "passed"
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        entry.update(status="failed", error=str(error))
    entry["artifacts"] = []
    for name in case.get("artifacts", []):
        artifact = directory / name
        if artifact.is_file() and artifact.stat().st_mtime >= started_wall:
            target = report_dir / f"{manifest['product']}-{artifact.name}"
            shutil.copy2(artifact, target)
            entry["artifacts"].append(target.name)
    entry["seconds"] = round(time.monotonic() - started, 2)
    print(
        f"{entry['status']}: {manifest['product']}/{case['id']} ({entry['seconds']}s)", flush=True
    )
    if entry["status"] == "failed" and log_path.exists():
        print(log_path.read_text(encoding="utf-8", errors="replace")[-6000:])
    return entry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["list", "setup", "run"])
    parser.add_argument("--product", choices=["all", *PRODUCTS], default="all")
    parser.add_argument("--suite", choices=["unit", "core", "ui", "windows-native"], default="core")
    parser.add_argument("--case", help="Run one stable case ID")
    parser.add_argument(
        "--execution-host",
        choices=["physical", "virtual-machine", "unspecified"],
        default="unspecified",
        help="Explicit provenance; never inferred from the Windows OS name",
    )
    parser.add_argument(
        "--allow-skips",
        action="store_true",
        help="Allow an incomplete unit run; skipped cases remain incomplete in the report",
    )
    args = parser.parse_args()
    if args.suite == "windows-native" and os.name != "nt" and args.action != "list":
        parser.error("windows-native requires an interactive Windows desktop")
    manifests = read_manifests(PRODUCTS if args.product == "all" else [args.product])
    selected = [
        (directory, manifest, case)
        for directory, manifest in manifests
        for case in manifest["cases"]
        if case["suite"] == args.suite and (not args.case or case["id"] == args.case)
    ]
    if not selected:
        parser.error("No matching functional cases")
    if args.action == "list":
        for _, manifest, case in selected:
            print(f"{manifest['product']}/{case['id']}: {case['title']}\n  {case['expected']}")
        return
    cache = ROOT / ".cache/test-lab"
    cache.mkdir(parents=True, exist_ok=True)
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("OPENASR", "OPENNOTES", "OPENDRAFTS", "OPENLOCALASR"))
    }
    if os.name == "nt":
        # PowerShell 7 adjusts this when it launches powershell.exe directly,
        # but Python/Electron intermediaries inherit incompatible Core modules.
        # Let Windows PowerShell rebuild its own module search path in children.
        env = {key: value for key, value in env.items() if key.upper() != "PSMODULEPATH"}
    env.update(
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONUTF8="1",
        PIP_CACHE_DIR=str(cache / "pip"),
        npm_config_cache=str(cache / "npm"),
        ELECTRON_CACHE=str(cache / "electron"),
        electron_config_cache=str(cache / "electron"),
        ELECTRON_GET_USE_PROXY="1",
    )
    ui_tool = cache / "ui"
    if args.action == "setup":
        if args.suite == "ui" and any(not m.get("nodeProject") for _, m, _ in selected):
            ui_tool.mkdir(exist_ok=True)
            for filename in ("package.json", "package-lock.json"):
                shutil.copy2(ROOT / "tests/environments/ui" / filename, ui_tool / filename)
            npm_setup(ui_tool, env)
        for directory, manifest in manifests:
            if any(item[0] == directory for item in selected):
                setup(directory, manifest, args.suite, env)
        return
    report_dir = (
        ROOT
        / "test-results/functional"
        / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ-") + TARGET)
    )
    report_dir.mkdir(parents=True)
    report = {
        "schemaVersion": 1,
        "target": TARGET,
        "platform": platform.platform(),
        "python": sys.version,
        "node": subprocess.check_output(
            [shutil.which("node") or "node", "--version"], text=True
        ).strip()
        if shutil.which("node")
        else None,
        "suite": args.suite,
        "executionHost": host_context(args.execution_host),
        "productSource": provenance(ROOT),
        "source": {m["product"]: provenance(d) for d, m in manifests},
        "cases": [],
    }
    for directory, manifest, case in selected:
        report["cases"].append(run_case(directory, manifest, case, report_dir, env, ui_tool))
        (report_dir / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    lines = [f"# Functional tests: {TARGET}", "", f"Suite: {args.suite}", ""]
    for case in report["cases"]:
        lines.append(
            f"- **{case['status']}** {case['product']}/{case['id']} "
            f"({case['seconds']}s) — [{case['log']}]({case['log']})"
        )
    (report_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Report: {report_dir / 'report.json'}")
    raise SystemExit(
        any(
            case["status"] != "passed" and not (args.allow_skips and case["status"] == "incomplete")
            for case in report["cases"]
        )
    )


if __name__ == "__main__":
    main()
