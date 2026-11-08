"""Run current-source Windows native rules with the product-owned .NET SDK."""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    tools = ROOT / ".cache/functional/windows"
    dotnet = tools / "dotnet/dotnet.exe"
    env = {
        **os.environ,
        "DOTNET_ROOT": str(tools / "dotnet"),
        "DOTNET_CLI_HOME": str(tools / "home"),
        "NUGET_PACKAGES": str(tools / "nuget"),
        "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
    }
    for project in ("tests/windows/NativeRules.csproj", "tests/windows_caret/CaretRules.csproj"):
        subprocess.run(
            [str(dotnet), "build", project, "--no-incremental", "-c", "Release"],
            cwd=ROOT,
            env=env,
            check=True,
            timeout=120,
        )
        subprocess.run(
            [str(dotnet), "run", "--no-build", "--project", project, "-c", "Release"],
            cwd=ROOT,
            env=env,
            check=True,
            timeout=120,
        )


if __name__ == "__main__":
    main()
