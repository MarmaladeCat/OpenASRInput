"""Exercise the real deb's start/stop/settings lifecycle in a disposable home.

systemctl, the native framework and the browser are test doubles; the package's
settings server is real. No host services, microphone or installed files change.
"""

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    args = parser.parse_args()
    results = ROOT / "test-results"
    results.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ps-", dir=results) as directory:
        stage = Path(directory).resolve()
        payload = stage / "package"
        subprocess.run(["dpkg-deb", "-x", str(args.package.resolve()), str(payload)], check=True)
        home, tools = stage / "home", stage / "tools"
        home.mkdir()
        tools.mkdir()
        state = home / "state/openasrinput/package"
        state.mkdir(parents=True)
        ready = state / "settings-ready.json"
        launcher = payload / "usr/bin/openasrinput"
        config = home / "config/openasrinput/input.json"
        pidfile = stage / "settings.pid"
        browser_record = stage / "browser.json"
        commands = stage / "systemctl.jsonl"
        bridge = stage / "bridge.sock"
        bridge.touch()  # Native test double's replaceable readiness marker.
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        origin = f"http://127.0.0.1:{port}"
        systemctl = tools / "systemctl"
        systemctl.write_text(
            "#!"
            + sys.executable
            + "\n"
            + r"""
import json, os, select, signal, subprocess, sys
from pathlib import Path
args=sys.argv[1:]
with open(os.environ["TEST_COMMANDS"], "a") as log:
    log.write(json.dumps({"args":args,"ldLibraryPath":os.environ.get("LD_LIBRARY_PATH")})+"\n")
pidfile=Path(os.environ["TEST_PID"])
if "is-active" in args:
    sys.exit(0 if pidfile.exists() else 3)
if "stop" in args:
    assert args[-2:] == ["openasrinput.service", "openasrinput-settings.service"]
    if pidfile.exists():
        pid=int(pidfile.read_text())
        try:
            fd=os.pidfd_open(pid)
            try:
                os.kill(pid, signal.SIGTERM)
                if not select.select([fd], [], [], 5)[0]:
                    os.kill(pid, signal.SIGKILL)
                    assert select.select([fd], [], [], 5)[0]
            finally:
                os.close(fd)
        except ProcessLookupError:
            pass
        pidfile.unlink()
if "enable" in args:
    assert args[-2:] == ["openasrinput.service", "openasrinput-settings.service"]
    assert "--now" in args and not pidfile.exists()
    with open(os.environ["TEST_SETTINGS_LOG"], "w") as log:
        child=subprocess.Popen([os.environ["OPENASRINPUT_PACKAGE_LAUNCHER"], "settings-server", "--no-open",
            "--port", os.environ["OPENASRINPUT_SETTINGS_PORT"], "--config", os.environ["OPENASRINPUT_CONFIG"],
            "--ready-file", os.environ["TEST_READY"]], stdout=log, stderr=subprocess.STDOUT)
    pidfile.write_text(str(child.pid))
"""
        )
        systemctl.chmod(0o755)
        for command in ("gdbus", "fcitx-remote"):
            target = tools / command
            target.write_text(
                "#!" + sys.executable + "\n"
                "import os\nfrom pathlib import Path\n"
                "p=Path(os.environ['OPENASRINPUT_DEFAULT_SOCKET'])\n"
                "p.unlink(missing_ok=True)\np.touch()\n"
            )
            target.chmod(0o755)
        browser = tools / "xdg-open"
        browser.write_text(
            "#!" + sys.executable + "\n"
            "import json,os,sys\n"
            "with open(os.environ['TEST_BROWSER'], 'w') as output:\n"
            "    json.dump({'url':sys.argv[-1],'ldLibraryPath':os.environ.get('LD_LIBRARY_PATH')},output)\n"
        )
        browser.chmod(0o755)
        env = {
            **os.environ,
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / "config"),
            "XDG_STATE_HOME": str(home / "state"),
            "XDG_CACHE_HOME": str(home / "cache"),
            "XDG_SESSION_TYPE": "x11",
            "OPENASRINPUT_APP_ROOT": str(payload / "usr/lib/openasrinput"),
            "OPENASRINPUT_PACKAGE_LAUNCHER": str(launcher),
            "OPENASRINPUT_CONFIG": str(config),
            "OPENASRINPUT_DEFAULT_SOCKET": str(bridge),
            "OPENASRINPUT_SETTINGS_PORT": str(port),
            "PATH": str(tools) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
            "BROWSER": "xdg-open",
            "TEST_READY": str(ready),
            "TEST_PID": str(pidfile),
            "TEST_BROWSER": str(browser_record),
            "TEST_COMMANDS": str(commands),
            "TEST_SETTINGS_LOG": str(stage / "settings.log"),
        }
        for name in (
            "PYTHONPATH",
            "LD_LIBRARY_PATH",
            "LD_LIBRARY_PATH_ORIG",
            "OPENASRINPUT_FRAMEWORK",
        ):
            env.pop(name, None)
        packaged_framework = (payload / "usr/lib/openasrinput/framework").read_text().strip()
        if packaged_framework == "auto":
            # This fixture isolates service lifecycle, not desktop discovery.
            env["OPENASRINPUT_FRAMEWORK"] = "fcitx5"

        def run(action, check=True):
            result = subprocess.run(
                [str(launcher), action],
                cwd=stage,
                env=env,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if check and result.returncode:
                log = stage / "settings.log"
                raise RuntimeError(
                    f"{action}: {result.stdout}\n{result.stderr}\n"
                    + (log.read_text() if log.exists() else "")
                )
            return result

        def history():
            return [json.loads(line) for line in commands.read_text().splitlines()]

        try:
            result = run("settings", check=False)
            assert result.returncode and "openasrinput start" in result.stderr
            assert not browser_record.exists() and not config.exists()
            run("start")
            assert ready.exists() and pidfile.exists() and not browser_record.exists()
            original_config = config.read_bytes()
            actual = json.loads(ready.read_text())["url"]
            first_pid = pidfile.read_text()
            token = actual.split("token=", 1)[1]
            for resource in (
                "/api/config",
                "/api/health",
                "/api/audio/calibration",
                "/audio-calibration.mjs",
            ):
                with urlopen(
                    Request(origin + resource, headers={"Authorization": "Bearer " + token})
                ) as response:
                    assert response.status == 200 and response.read()
            for _ in range(2):
                before = len(history())
                browser_record.unlink(missing_ok=True)
                run("settings")
                deadline = time.monotonic() + 5
                while not browser_record.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                opened = json.loads(browser_record.read_text())
                assert opened["url"] == actual and opened["ldLibraryPath"] is None
                assert pidfile.read_text() == first_pid
                assert all("is-active" in row["args"] for row in history()[before:])
            # Explicit start refreshes both services and the settings token after upgrades.
            browser_record.unlink()
            run("start")
            assert pidfile.read_text() != first_pid
            assert json.loads(ready.read_text())["url"] != actual
            assert not browser_record.exists()
            run("stop")
            assert not pidfile.exists() and not ready.exists()
            result = run("settings", check=False)
            assert result.returncode and "openasrinput start" in result.stderr
            assert not browser_record.exists() and config.read_bytes() == original_config
            assert all(row["ldLibraryPath"] is None for row in history())
            print(
                "PASS packaged lifecycle: start both without browser, settings opens only, restart refreshes token, stop both, config preserved"
            )
        finally:
            if pidfile.exists():
                try:
                    run("stop")
                except (OSError, subprocess.SubprocessError):
                    try:
                        os.kill(int(pidfile.read_text()), signal.SIGKILL)
                    except ProcessLookupError:
                        pass


if __name__ == "__main__":
    main()
