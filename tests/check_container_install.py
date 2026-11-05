"""Actual dpkg install/reinstall/remove, allowed only in a disposable container."""

import argparse
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.request import Request, urlopen


def installed(name):
    result = subprocess.run(
        ["dpkg-query", "-W", "-f=${db:Status-Status}", name], text=True, capture_output=True
    )
    return result.returncode == 0 and result.stdout == "installed"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--framework", choices=("ibus", "fcitx4", "fcitx5"), required=True)
    args = parser.parse_args()
    if (
        not Path("/.dockerenv").exists()
        or os.geteuid() != 0
        or os.environ.get("OPENASRINPUT_INSTALL_SANDBOX") != "1"
    ):
        raise RuntimeError("Requires an explicitly isolated root container")
    framework_packages = {"ibus": "ibus", "fcitx4": "fcitx-bin", "fcitx5": "fcitx5"}
    before = {key: installed(value) for key, value in framework_packages.items()}
    assert before[args.framework]
    assert not (before["fcitx4"] and before["fcitx5"])
    if args.framework == "ibus":
        assert not before["fcitx4"] and not before["fcitx5"], before
    architecture = subprocess.check_output(["dpkg", "--print-architecture"], text=True).strip()
    assert (
        subprocess.check_output(
            ["dpkg-deb", "-f", str(args.package), "Architecture"], text=True
        ).strip()
        == architecture
    )
    subprocess.run(["dpkg", "--install", str(args.package)], check=True)
    with tempfile.TemporaryDirectory(prefix="input-install-") as directory:
        home = Path(directory)
        config = home / "input.json"
        env = {**os.environ, "HOME": directory, "OPENASRINPUT_CONFIG": str(config)}
        for variable in (
            "PYTHONPATH",
            "OPENASRINPUT_APP_ROOT",
            "LD_LIBRARY_PATH",
            "LD_LIBRARY_PATH_ORIG",
        ):
            env.pop(variable, None)
        launcher = "/usr/bin/openasrinput"
        assert "OpenASRInput" in subprocess.check_output(
            [launcher, "--version"], env=env, text=True
        )
        assert json.loads(subprocess.check_output([launcher, "demo"], env=env, text=True))[
            "submitted"
        ] == ["语音与光标预编辑。"]
        ready = home / "ready.json"
        process = subprocess.Popen(
            [launcher, "settings-server", "--no-open", "--port", "0", "--ready-file", str(ready)],
            env=env,
        )
        try:
            deadline = time.monotonic() + 30
            while not ready.exists() and time.monotonic() < deadline:
                assert process.poll() is None, "installed settings process exited"
                time.sleep(0.1)
            url = json.loads(ready.read_text())["url"]
            origin, token = url.split("/#token=")
            with urlopen(
                Request(origin + "/api/config", headers={"Authorization": "Bearer " + token})
            ) as response:
                assert json.load(response)["config"]["input"]["framework"] == "auto"
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        config.write_text(
            json.dumps({"input": {"framework": args.framework}, "preserve": "user-data"})
        )
        subprocess.run(["dpkg", "--install", str(args.package)], check=True)
        assert json.loads(config.read_text())["preserve"] == "user-data"
        assert before == {key: installed(value) for key, value in framework_packages.items()}
        subprocess.run(["dpkg", "--remove", "openasrinput"], check=True)
        assert not Path(launcher).exists()
        assert json.loads(config.read_text())["preserve"] == "user-data"
    print(
        "PASS actual dpkg install/reinstall/remove; retained user config; no extra input framework installed"
    )


if __name__ == "__main__":
    main()
