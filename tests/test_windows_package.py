"""Inspect the built MSI, registry/shortcut tables and the actual extracted PE payload."""

import argparse
import ctypes
import json
import os
import re
import struct
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
VERSION = re.search(r'^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(
    1
)
IMAGE = "openasrinput-build:windows"


def check_windows_runtime(root, stage):
    """Launch the real extracted app in a disposable profile, then stop its own event."""
    environment = {
        **os.environ,
        "APPDATA": str(stage / "appdata"),
        "OPENASR_DATA_ROOT": str(stage / "state"),
        "OPENASRINPUT_CONFIG": str(stage / "input.json"),
        "OPENASRINPUT_SETTINGS_PORT": "0",
    }
    command = [str(root / "python/python.exe"), str(root / "app/launch.py")]
    check = json.loads(
        subprocess.check_output(
            [*command, "--check"],
            env=environment,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    )
    assert check["ok"] and check["platform"] == "win32"
    runtime = json.loads(
        subprocess.check_output(
            [
                command[0],
                "-B",
                "-c",
                "import json, openasrinput; "
                "from openasrinput.infrastructure.platform_support import config_home; "
                "print(json.dumps({'home': str(config_home()), 'module': openasrinput.__file__}))",
            ],
            env=environment,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    )
    home = Path(runtime["home"])
    assert home.is_relative_to(stage / "state"), "runtime state must stay in the disposable profile"
    assert Path(runtime["module"]).is_relative_to(root), "use the packaged application"
    ready = home / "settings-ready.json"
    process = subprocess.Popen(
        [*command, "--background"],
        env=environment,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        deadline = time.monotonic() + 15
        while not ready.is_file():
            assert process.poll() is None and time.monotonic() < deadline, (
                f"packaged app startup: exit={process.poll()}, ready={ready}"
            )
            time.sleep(0.05)
        address = json.loads(ready.read_text(encoding="utf-8"))["url"]
        origin, token = address.split("/#token=")
        with urlopen(
            Request(origin + "/api/config", headers={"Authorization": "Bearer " + token}), timeout=3
        ) as response:
            config = json.load(response)["config"]
        assert config["textEdit"]["model"] == "deepseek-chat"
        with urlopen(origin, timeout=3) as response:
            assert b'id="tab-text-edit"' in response.read()
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenEventW.argtypes = [ctypes.c_uint, ctypes.c_bool, ctypes.c_wchar_p]
        kernel.OpenEventW.restype = ctypes.c_void_p
        kernel.SetEvent.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        event = kernel.OpenEventW(2, False, f"Local\\OpenASRInput-Stop-{process.pid}")
        assert event, "packaged shutdown event"
        try:
            assert kernel.SetEvent(event)
        finally:
            kernel.CloseHandle(event)
        assert process.wait(timeout=10) == 0
        assert not ready.exists(), "settings session removed on exit"
        assert not list(root.rglob("__pycache__"))
    finally:
        if process.poll() is None:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], check=True)
            process.wait(timeout=10)
    print(
        "PASS extracted Windows application: private Python, text editing settings, native bridge, clean shutdown"
    )


def windows_table(package, name):
    """Read MSI tables through Windows Installer, without installing the product."""
    installer = ctypes.WinDLL("msi", use_last_error=True)
    handle = ctypes.c_uint
    installer.MsiOpenDatabaseW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_void_p,
        ctypes.POINTER(handle),
    ]
    installer.MsiDatabaseOpenViewW.argtypes = [handle, ctypes.c_wchar_p, ctypes.POINTER(handle)]
    installer.MsiViewExecute.argtypes = [handle, handle]
    installer.MsiViewFetch.argtypes = [handle, ctypes.POINTER(handle)]
    installer.MsiRecordGetFieldCount.argtypes = [handle]
    installer.MsiRecordGetStringW.argtypes = [
        handle,
        ctypes.c_uint,
        ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.c_uint),
    ]
    installer.MsiCloseHandle.argtypes = [handle]
    database, view = handle(), handle()

    def check(result):
        if result:
            raise OSError(result, "Windows Installer table query failed")

    try:
        check(installer.MsiOpenDatabaseW(str(package), None, ctypes.byref(database)))
        check(
            installer.MsiDatabaseOpenViewW(database, f"SELECT * FROM `{name}`", ctypes.byref(view))
        )
        check(installer.MsiViewExecute(view, 0))
        rows = ["", "", ""]  # Match msiinfo export's three header lines.
        while True:
            record = handle()
            result = installer.MsiViewFetch(view, ctypes.byref(record))
            if result == 259:  # ERROR_NO_MORE_ITEMS
                break
            check(result)
            try:
                fields = []
                for column in range(1, installer.MsiRecordGetFieldCount(record) + 1):
                    length = ctypes.c_uint(65535)
                    text = ctypes.create_unicode_buffer(length.value + 1)
                    check(installer.MsiRecordGetStringW(record, column, text, ctypes.byref(length)))
                    fields.append(text.value)
                rows.append("\t".join(fields))
            finally:
                installer.MsiCloseHandle(record)
        return "\n".join(rows)
    finally:
        if view.value:
            installer.MsiCloseHandle(view)
        if database.value:
            installer.MsiCloseHandle(database)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="run extracted Windows app in a disposable profile"
    )
    parser.add_argument(
        "--electron",
        type=Path,
        help="also run real settings/model-card UI with the extracted Python",
    )
    parser.add_argument(
        "--package",
        type=Path,
        default=ROOT
        / f".cache/build/artifacts/windows/amd64/native/OpenASRInput_{VERSION}_win-x64.msi",
    )
    args = parser.parse_args()
    package = args.package.resolve()
    results = ROOT / "test-results"
    results.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="msi-check-", dir=results) as temporary:
        stage = Path(temporary).resolve()
        command = (
            []
            if os.name == "nt"
            else [
                "docker",
                "run",
                "--rm",
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "-v",
                f"{package}:/input.msi:ro",
                "-v",
                f"{stage}:/out",
                IMAGE,
            ]
        )

        def table(name):
            if os.name == "nt":
                return windows_table(package, name)
            return subprocess.check_output(
                [*command, "msiinfo", "export", "/input.msi", name], text=True
            )

        properties = table("Property")
        assert "OpenASRInput" in properties and "ALLUSERS\t1" not in properties
        assert f"ProductVersion\t{VERSION}" in properties
        assert "ARPNOMODIFY\t1" in properties and "ARPNOREMOVE\t1" not in properties
        secure = next(
            row.split("\t")[1]
            for row in properties.splitlines()
            if row.startswith("SecureCustomProperties\t")
        )
        assert "OPENASRINPUT_NO_LAUNCH" in secure.split(";")
        assert {
            "REMOVEUSERDATA",
            "INPUTDATADIR",
            "INSTALLDIR",
            "REPLACE_INPUT_PRODUCT",
            "REPLACE_PORTAL_PRODUCT",
            "REPLACE_BUNDLE_PRODUCT",
        } <= set(secure.split(";"))
        registry = table("Registry")
        searches = {
            row.split("\t")[0]: row.split("\t")[1]
            for row in table("AppSearch").splitlines()[3:]
            if row
        }
        locators = {
            row.split("\t")[0]: row.split("\t")[1:]
            for row in table("RegLocator").splitlines()[3:]
            if row
        }
        assert locators[searches["INSTALLDIR"]] == [
            "1",
            "Software\\OpenASRInput",
            "InstallDir",
            "18",
        ], "maintenance must resolve this user's actual 64-bit installation directory"
        assert "CurrentVersion\\Run" in registry and "--background" in registry
        assert all(line.split("\t")[1] == "1" for line in registry.splitlines()[3:] if line)
        shortcuts = table("Shortcut")
        assert "DesktopFolder" in shortcuts and "--settings" in shortcuts
        sequence = table("InstallExecuteSequence")
        assert "RemoveExistingProducts\tOLDVERSION\t1501" in sequence
        upgrade_rows = [row.split("\t") for row in table("Upgrade").splitlines()[3:] if row]
        upgrades = {row[6]: row for row in upgrade_rows}
        assert len(upgrades) == len(upgrade_rows) == 5
        assert {row[0].strip("{}").lower() for row in upgrade_rows} == {
            "d3a801cf-44d0-55e4-b813-f4f15fa12b7f",
            "64e55bb5-b8eb-40fa-bc40-089420d7c0a0",
            "638d1b81-3c59-49e1-9e8d-d0a68157c230",
        }
        for name in ("INPUT", "PORTAL", "BUNDLE"):
            assert (
                int(upgrades["REPLACE_" + name + "_PRODUCT"][4]) & 2
            )  # OnlyDetect; never remove without UI consent.
        assert upgrades["OLDVERSION"][2] == VERSION
        assert int(upgrades["OLDVERSION"][4]) & (512 | 2) == 512

        def affected(row, version):
            parsed = tuple(map(int, version.split(".")))
            attributes = int(row[4])
            lower = tuple(map(int, row[1].split("."))) if row[1] else None
            upper = tuple(map(int, row[2].split("."))) if row[2] else None
            return (lower is None or parsed > lower or (parsed == lower and attributes & 256)) and (
                upper is None or parsed < upper or (parsed == upper and attributes & 512)
            )

        # Check upgrading/rebuilding and downgrade protection from actual MSI rows.
        major, minor, patch = map(int, VERSION.split("."))
        for version, allowed in (
            ("0.0.0", True),
            (VERSION, True),
            (f"{major}.{minor}.{patch + 1}", False),
            (f"{major}.{minor + 1}.0", False),
            (f"{major + 1}.0.0", False),
        ):
            blockers = affected(upgrades["NEWERVERSION"], version)
            removable = affected(upgrades["OLDVERSION"], version)
            assert (not blockers) == allowed, version
            assert bool(removable) == allowed, version
        assert "Installed OR NOT NEWERVERSION" in table("LaunchCondition")
        steps = {row.split("\t")[0]: row.split("\t") for row in sequence.splitlines()[3:] if row}
        assert int(steps["AppSearch"][2]) < int(steps["CostFinalize"][2])
        assert int(steps["StopInput"][2]) < int(steps["InstallValidate"][2])
        assert int(steps["GuardReplacement"][2]) < int(steps["InstallInitialize"][2])
        assert "REPLACE_INPUT_PRODUCT" in steps["GuardReplacement"][1]
        assert 'REMOVE~="ALL"' in steps["StopInput"][1]
        assert "OPENASRINPUT_NO_LAUNCH" in steps["Launch"][1]
        assert "StopLauncher" in table("CustomAction") and "--shutdown" in table("CustomAction")
        actions = {
            row.split("\t")[0]: row.split("\t")
            for row in table("CustomAction").splitlines()[3:]
            if row
        }
        assert actions["GuardReplacement"][1] == "19", "replacement guard must block execution"
        cleanup = actions["RemoveInputData"]
        assert int(cleanup[1]) == 34 | 1024, "cleanup must be deferred and impersonate the user"
        assert cleanup[2] == "System64Folder" and "[INPUTDATADIR]" in cleanup[3]
        assert "REMOVEUSERDATA" in steps["RemoveInputData"][1]
        assert "INSTALLDIR" in table("RemoveFile")
        extract = (
            [
                "msiexec.exe",
                "/a",
                str(package),
                "/qn",
                "TARGETDIR=" + str(stage),
                "OPENASRINPUT_NO_LAUNCH=1",
                "/l*v",
                str(stage / "extract.log"),
            ]
            if os.name == "nt"
            else [*command, "msiextract", "-C", "/out", "/input.msi"]
        )
        subprocess.run(
            extract,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        launcher = next(stage.rglob("OpenASRInput.exe"))
        root = launcher.parent
        for executable in (
            launcher,
            root / "python/pythonw.exe",
            root / "native/OpenASRInputBridge.exe",
        ):
            data = executable.read_bytes()
            assert data[:2] == b"MZ"
            offset = struct.unpack_from("<I", data, 0x3C)[0]
            assert data[offset : offset + 4] == b"PE\0\0"
            assert struct.unpack_from("<H", data, offset + 4)[0] == 0x8664
        assert (root / "native/coreclr.dll").exists()
        assert (root / "native/UIAutomationClient.dll").exists()
        assert list((root / "python/Lib/site-packages/aiohttp").glob("*.pyd"))
        assert "../app" in next((root / "python").glob("python*._pth")).read_text()
        assert (root / "app/openasrinput/presentation/web/index.html").exists()
        assert (root / "app/openasrinput/presentation/branding/logo.svg").is_file()
        assert (root / "app/openasrinput/presentation/web/personal-hotwords.mjs").exists()
        assert (root / "app/openasrinput/presentation/web/audio-calibration.mjs").exists()
        assert (root / "app/openasrinput/application/calibration.py").exists()
        assert (
            f'class="version">v{(ROOT / "VERSION").read_text().strip()}'
            in (root / "app/openasrinput/presentation/web/index.html").read_text()
        )
        assert (
            'id="tab-hotwords"'
            in (root / "app/openasrinput/presentation/web/index.html").read_text()
        )
        assert (root / "app/openasrinput/entrypoints/windows.py").exists()
        assert not list(root.rglob("input.json")) and not list(root.rglob("credentials.json"))
        assert not list(root.rglob("__pycache__"))
        assert "sys.dont_write_bytecode = True" in (root / "app/launch.py").read_text()
        runtime = json.loads((root / "native/OpenASRInputBridge.runtimeconfig.json").read_text())
        assert runtime["runtimeOptions"]["tfm"].startswith("net8.0")
        if args.live:
            if os.name != "nt":
                raise RuntimeError("--live requires Windows")
            check_windows_runtime(root, stage)
        if args.electron:
            if os.name != "nt":
                raise RuntimeError("--electron requires Windows")
            environment = {
                **os.environ,
                "OPENASRINPUT_TEST_WINDOWS_PACKAGE_ROOT": str(root),
            }
            environment.pop("ELECTRON_RUN_AS_NODE", None)
            environment.pop("OPENASRINPUT_TEST_PACKAGE_ROOT", None)
            for test, filename in (
                ("test_settings_ui.cjs", "windows-package-ui.log"),
                ("test_calibration_ui.cjs", "windows-package-calibration-ui.log"),
            ):
                result = subprocess.run(
                    [str(args.electron.resolve()), str(ROOT / "tests" / test)],
                    env=environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=120,
                )
                log = results / filename
                log.write_bytes(result.stdout)
                if result.returncode:
                    raise RuntimeError(f"Packaged UI failed; see {log}")
        print(
            f"PASS Windows MSI {VERSION}: older-version upgrade/same-version rebuild/newer-version protection, per-user lifecycle, x64 private runtimes, no user credentials/caches"
        )


if __name__ == "__main__":
    main()
