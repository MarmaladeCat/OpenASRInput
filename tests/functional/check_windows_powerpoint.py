"""Explicit real-PowerPoint acceptance on an isolated interactive Windows desktop."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bridge", type=Path, help="Use a bridge from the current extracted candidate"
    )
    args = parser.parse_args()
    tools = ROOT / ".cache/functional/windows"
    bridge = (args.bridge or tools / "bridge/OpenASRInputBridge.exe").resolve()
    output = ROOT / "test-results"
    output.mkdir(exist_ok=True)
    record = {"status": "blocked", "realPowerPoint": True, "bridge": str(bridge)}
    code = 2
    try:
        if os.name != "nt":
            raise RuntimeError("Requires an isolated interactive Windows desktop with PowerPoint")
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "PowerPoint.Application\\CLSID"):
                pass
        except FileNotFoundError:
            raise RuntimeError(
                "Microsoft PowerPoint is not installed; real Office acceptance blocked"
            ) from None
        if not bridge.is_file():
            raise RuntimeError(
                "Bridge is missing; run scripts/test.py setup --suite windows-office"
            )
        assembly = bridge.with_suffix(".dll")
        record["bridgeSha256"] = hashlib.sha256(bridge.read_bytes()).hexdigest()
        if assembly.is_file():
            record["assemblySha256"] = hashlib.sha256(assembly.read_bytes()).hexdigest()
        env = {
            **os.environ,
            "DOTNET_ROOT": str(tools / "dotnet"),
            "DOTNET_CLI_HOME": str(tools / "home"),
            "NUGET_PACKAGES": str(tools / "nuget"),
            "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
        }
        subprocess.run(
            [
                str(tools / "dotnet/dotnet.exe"),
                "build",
                "tests/windows_powerpoint/PowerPointTests.csproj",
                "--no-incremental",
                "-c",
                "Release",
                "-r",
                "win-x64",
                "--self-contained",
                "false",
            ],
            cwd=ROOT,
            env=env,
            check=True,
            timeout=180,
        )
        if (tools / "powerpoint").exists():
            shutil.rmtree(tools / "powerpoint")
        subprocess.run(
            [
                str(tools / "dotnet/dotnet.exe"),
                "publish",
                "--no-build",
                "tests/windows_powerpoint/PowerPointTests.csproj",
                "-c",
                "Release",
                "-r",
                "win-x64",
                "--self-contained",
                "false",
                "-o",
                str(tools / "powerpoint"),
            ],
            cwd=ROOT,
            env=env,
            check=True,
            timeout=180,
        )
        sandbox = output / ("powerpoint-" + uuid.uuid4().hex)
        record.update(status="failed", sandbox=str(sandbox))
        with subprocess.Popen(
            [str(tools / "powerpoint/PowerPointTests.exe"), str(bridge), str(sandbox)],
            cwd=ROOT,
            env=env,
        ) as process:
            try:
                code = process.wait(timeout=300)
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"], check=False, timeout=15
                )
                process.wait(timeout=15)
                raise
        record["status"] = "passed" if code == 0 else "failed"
        environment = sandbox / "environment.json"
        if environment.is_file():
            record["environment"] = json.loads(environment.read_text(encoding="utf-8"))
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        record["reason"] = str(error)
        print(str(error), flush=True)
    finally:
        record["exitCode"] = code
        (output / "native-powerpoint-result.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
