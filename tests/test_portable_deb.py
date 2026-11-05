"""Run an extracted Input deb without system Python modules or installed source."""

import argparse
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument(
        "--results", type=Path, default=Path(__file__).resolve().parents[1] / "test-results"
    )
    args = parser.parse_args()
    args.results.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="portable-", dir=args.results) as directory:
        stage = Path(directory).resolve()
        subprocess.run(["dpkg-deb", "-x", str(args.package.resolve()), str(stage)], check=True)
        application = stage / "usr/lib/openasrinput"
        assert (application / "runtime/openasrinput-runtime").is_file()
        depends = subprocess.check_output(
            ["dpkg-deb", "-f", str(args.package), "Depends"], text=True
        )
        framework = (application / "framework").read_text().strip()
        assert framework in ("auto", "fcitx4", "fcitx5")
        assert "libicu" not in depends and "python3-aiohttp" not in depends, depends
        if framework == "auto":
            assert "python3-gi" in depends and "gir1.2-ibus-1.0" in depends
            assert (application / "ibus/engine.py").is_file()
            panel = application / "ibus/voice-panel"
            assert panel.is_file()
            panel_linkage = subprocess.check_output(["ldd", str(panel)], text=True)
            assert "not found" not in panel_linkage, panel_linkage
            assert str(application / "ibus/panel-libs") in panel_linkage, panel_linkage
        else:
            assert "python3" not in depends
        libraries = list((stage / "usr/lib").glob("*/fcitx*/*openasrinput.so"))
        assert len(libraries) == (2 if framework == "auto" else 1)
        for library in libraries:
            linkage = subprocess.check_output(["ldd", str(library)], text=True)
            assert "not found" not in linkage, linkage
            assert str(library.parent / "openasrinput-libs") in linkage
        env = {
            **os.environ,
            "HOME": str(stage / "home"),
            "OPENASRINPUT_APP_ROOT": str(application),
            "OPENASRINPUT_CONFIG": str(stage / "input.json"),
            "PYTHONNOUSERSITE": "1",
        }
        env.pop("PYTHONPATH", None)
        env.pop("LD_LIBRARY_PATH", None)
        env.pop("LD_LIBRARY_PATH_ORIG", None)
        tools = stage / "tools"
        tools.mkdir()
        pactl = tools / "pactl"
        pactl.write_text('#!/bin/sh\n[ -z "${LD_LIBRARY_PATH:-}" ] || exit 9\nprintf "[]\\n"\n')
        pactl.chmod(0o755)
        env["PATH"] = str(tools) + os.pathsep + env.get("PATH", "/usr/bin:/bin")
        launcher = str(stage / "usr/bin/openasrinput")
        assert "OpenASRInput" in subprocess.check_output(
            [launcher, "--version"], env=env, text=True
        )
        demo = json.loads(
            subprocess.check_output([launcher, "demo"], env=env, cwd=stage, text=True)
        )
        assert demo["submitted"] == ["语音与光标预编辑。"]
        ready = stage / "ready.json"
        with (args.results / "portable-settings.log").open("w") as log:
            process = subprocess.Popen(
                [
                    launcher,
                    "settings-server",
                    "--config",
                    str(stage / "input.json"),
                    "--port",
                    "0",
                    "--no-open",
                    "--ready-file",
                    str(ready),
                ],
                env=env,
                cwd=stage,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError("frozen settings exited; see portable-settings.log")
                    if ready.exists():
                        break
                    time.sleep(0.1)
                data = json.loads(ready.read_text())
                origin, token = data["url"].split("/#token=")
                for resource in ("/", "/settings.mjs", "/settings.css", "/personal-hotwords.mjs"):
                    with urlopen(origin + resource) as response:
                        assert response.status == 200
                        if resource == "/":
                            assert b'id="tab-hotwords"' in response.read()
                with urlopen(
                    Request(origin + "/api/config", headers={"Authorization": "Bearer " + token})
                ) as response:
                    assert "config" in json.load(response)
                with urlopen(
                    Request(
                        origin + "/api/audio/devices",
                        data=b"{}",
                        method="POST",
                        headers={"Authorization": "Bearer " + token},
                    )
                ) as response:
                    assert json.load(response)["devices"] == []
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        print(
            "PASS portable Input deb: private runtime, native ICU resolution, offline demo and authenticated settings/assets"
        )


if __name__ == "__main__":
    main()
