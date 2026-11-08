"""Run the existing native-input journeys only inside our disposable editor."""

import argparse
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from contextlib import ExitStack
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def capture_desktop(screenshot):
    try:
        subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
                "$r=[Windows.Forms.SystemInformation]::VirtualScreen; "
                "$b=New-Object Drawing.Bitmap($r.Width,$r.Height); "
                "$g=[Drawing.Graphics]::FromImage($b); "
                "$g.CopyFromScreen($r.Location,[Drawing.Point]::Empty,$r.Size); "
                f"$b.Save('{screenshot}',[Drawing.Imaging.ImageFormat]::Png); "
                "$g.Dispose(); $b.Dispose()",
            ],
            timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"Desktop capture failed: {error}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--microphone", action="store_true", help="Opt in to real microphone capture"
    )
    parser.add_argument("--portal-checkout", type=Path)
    parser.add_argument("--portal-python", type=Path)
    parser.add_argument("--bridge", type=Path, help="Bridge from an extracted current candidate")
    parser.add_argument(
        "--office-host",
        action="store_true",
        help="Run ordinary controls in a POWERPNT-named fixture (not real Office acceptance)",
    )
    args = parser.parse_args()
    if args.microphone and (not args.portal_checkout or not args.portal_python):
        parser.error("--microphone requires explicit --portal-checkout and --portal-python")
    if os.name != "nt":
        raise SystemExit("Requires an interactive Windows desktop")
    os.environ.pop("PSModulePath", None)
    # GetWindowRect, WindowFromPoint and SetCursorPos must share physical
    # coordinates. The 100%-DPI VM hid this mismatch on a 150% physical display.
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user.SetProcessDpiAwarenessContext.restype = ctypes.c_bool
    if not user.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
        raise ctypes.WinError(ctypes.get_last_error())
    tools = ROOT / ".cache/functional/windows"
    helper = (args.bridge or tools / "bridge/OpenASRInputBridge.exe").resolve()
    if not helper.is_file():
        raise RuntimeError("Windows bridge is missing; prepare the test tools or pass --bridge")
    os.environ["DOTNET_ROOT"] = str(tools / "dotnet")
    os.environ["OPENASRINPUT_WINDOWS_HELPER"] = str(helper)
    results = ROOT / "test-results"
    results.mkdir(exist_ok=True)
    prefix = "native-microphone" if args.microphone else "native-editor"
    if args.office_host:
        prefix += "-office-host"
    with (
        ExitStack() as cleanup,
        tempfile.TemporaryDirectory(
            prefix="functional-editor-", dir=results, ignore_cleanup_errors=True
        ) as temporary,
    ):
        directory = Path(temporary)
        if args.microphone:
            output = results / "native-microphone-portal.json"
            stdout = cleanup.enter_context(output.open("w", encoding="utf-8"))
            stderr = cleanup.enter_context(
                (results / "native-microphone-portal.log").open("w", encoding="utf-8")
            )
            portal = subprocess.Popen(
                [str(args.portal_python.resolve()), "tests/serve_windows_session.py"],
                cwd=args.portal_checkout.resolve(),
                env={**os.environ, "PYTHONPATH": str(args.portal_checkout.resolve() / "src")},
                stdout=stdout,
                stderr=stderr,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            cleanup.callback(stop_process, portal)
            deadline = time.monotonic() + 20
            while True:
                text = output.read_text(encoding="utf-8").strip()
                if text:
                    url = json.loads(text)["url"]
                    if not url.startswith("http://127.0.0.1:"):
                        raise RuntimeError("Microphone fixture must use loopback")
                    os.environ["OPENASRINPUT_TEST_PORTAL_URL"] = url
                    os.environ["OPENASRINPUT_TEST_MICROPHONE"] = "1"
                    break
                if portal.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError("Microphone Portal fixture failed to start")
                time.sleep(0.05)
        editor = tools / "editor/WindowsTestEditor.exe"
        if args.office_host:
            # The process name must never route ALL controls through Office's
            # slide-selection API. This fixture reproduces that routing failure
            # without installing Office or touching a user's presentation.
            editor = tools / "editor/POWERPNT.exe"
            shutil.copy2(tools / "editor/WindowsTestEditor.exe", editor)
        process = subprocess.Popen([str(editor), str(directory)])
        try:
            identity = directory / "editor-identity.json"
            deadline = time.monotonic() + 60
            while not identity.exists():
                if process.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError("Disposable editor did not start")
                time.sleep(0.1)
            information = json.loads(identity.read_text(encoding="utf-8"))
            assert information["processId"] == process.pid
            while not (directory / "browser-ready.json").exists():
                error = directory / "browser-error.txt"
                if error.exists():
                    raise RuntimeError(error.read_text(encoding="utf-8"))
                if process.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError("Disposable browser editor did not become ready")
                time.sleep(0.1)
            os.environ["OPENASRINPUT_TEST_EDITOR_DIR"] = str(directory)
            os.environ["OPENASRINPUT_TEST_TARGET_PROCESS_ID"] = str(process.pid)
            metadata = {
                "editor": information,
                "officeHostFixture": args.office_host,
                "bridgeSha256": hashlib.sha256(helper.with_suffix(".dll").read_bytes()).hexdigest(),
                "browser": json.loads(
                    (directory / "browser-ready.json").read_text(encoding="utf-8")
                ),
                "dotnet": subprocess.check_output(
                    [str(tools / "dotnet/dotnet.exe"), "--info"],
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=15,
                ),
            }
            (results / f"{prefix}-environment.json").write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-Command",
                    f"if (-not (New-Object -ComObject WScript.Shell).AppActivate({process.pid})) "
                    "{ throw 'Cannot activate test editor' }",
                ],
                check=True,
                timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            user.GetForegroundWindow.restype = ctypes.c_void_p
            user.GetWindowThreadProcessId.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_ulong),
            ]
            user.SetForegroundWindow.argtypes = [ctypes.c_void_p]
            user.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
            callback = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            user.EnumWindows.argtypes = [callback, ctypes.c_void_p]
            user.IsWindowVisible.argtypes = [ctypes.c_void_p]
            handles = []

            @callback
            def find_editor(handle, _):
                owner = ctypes.c_ulong()
                user.GetWindowThreadProcessId(handle, ctypes.byref(owner))
                if owner.value == process.pid and user.IsWindowVisible(handle):
                    handles.append(handle)
                return True

            user.EnumWindows(find_editor, None)
            if not handles:
                raise RuntimeError("Disposable editor has no visible window")
            # The unattended worker is not the foreground process. Attach only
            # while transferring focus to the verified disposable editor.
            thread = ctypes.windll.kernel32.GetCurrentThreadId()
            foreground_thread = user.GetWindowThreadProcessId(user.GetForegroundWindow(), None)
            # AttachThreadInput requires both threads to already own a message queue.
            user.PeekMessageW(ctypes.create_string_buffer(48), None, 0, 0, 0)
            attached = user.AttachThreadInput(thread, foreground_thread, True)
            try:
                user.ShowWindow(handles[0], 9)
                activated = user.SetForegroundWindow(handles[0])
                print(f"Editor activation: attached={attached}, activated={activated}", flush=True)
            finally:
                if attached:
                    user.AttachThreadInput(thread, foreground_thread, False)
            if not activated:
                # Windows may still reject a background worker's focus request.
                # Click only after hit-testing a point inside our disposable editor.
                from ctypes import wintypes

                user.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT)]
                user.WindowFromPoint.argtypes = [wintypes.POINT]
                user.WindowFromPoint.restype = ctypes.c_void_p
                bounds = wintypes.RECT()
                if not user.GetWindowRect(handles[0], ctypes.byref(bounds)):
                    raise ctypes.WinError()
                point = wintypes.POINT(bounds.left + 80, bounds.top + 90)
                hit_owner = ctypes.c_ulong()
                user.GetWindowThreadProcessId(user.WindowFromPoint(point), ctypes.byref(hit_owner))
                if hit_owner.value != process.pid:
                    raise RuntimeError(
                        f"Cannot click editor: point=({point.x},{point.y}), "
                        f"owner={hit_owner.value}, expected={process.pid}"
                    )
                if not user.SetCursorPos(point.x, point.y):
                    raise ctypes.WinError()
                user.mouse_event(2, 0, 0, 0, 0)
                time.sleep(0.05)
                user.mouse_event(4, 0, 0, 0, 0)
            foreground = ctypes.c_ulong()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                user.GetWindowThreadProcessId(user.GetForegroundWindow(), ctypes.byref(foreground))
                if foreground.value == process.pid:
                    break
                time.sleep(0.1)
            else:
                diagnostic = subprocess.run(
                    [
                        "powershell.exe",
                        "-NoProfile",
                        "-Command",
                        f"Get-Process -Id {foreground.value} | Format-List Id,ProcessName,MainWindowTitle,SessionId; query session",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=15,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                print(diagnostic.stdout, diagnostic.stderr, flush=True)
                raise RuntimeError(f"Editor activation failed; foreground PID: {foreground.value}")
            suite = unittest.defaultTestLoader.loadTestsFromName(
                "test_windows_session" if args.microphone else "test_windows_live"
            )
            result = unittest.TextTestRunner(verbosity=2).run(suite)
            (results / f"{prefix}-result.json").write_text(
                json.dumps(
                    {
                        "testsRun": result.testsRun,
                        "failures": [(str(test), detail) for test, detail in result.failures],
                        "errors": [(str(test), detail) for test, detail in result.errors],
                        "skipped": [(str(test), reason) for test, reason in result.skipped],
                        "successful": result.wasSuccessful() and not result.skipped,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            if result.skipped:
                raise RuntimeError(f"Native acceptance incomplete: {result.skipped}")
            if not result.wasSuccessful():
                raise SystemExit(1)
        finally:
            capture_desktop(results / f"{prefix}-desktop.png")
            stop_process(process)


def stop_process(process):
    if process.poll() is None:
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=True,
            stdout=subprocess.DEVNULL,
        )
    process.wait(timeout=15)


if __name__ == "__main__":
    main()
