"""Per-user Windows background app: native tray/shortcuts, settings and dictation."""

import argparse
import asyncio
import ctypes
import hashlib
import json
import logging
import os
import sys
import threading
import webbrowser
from contextlib import contextmanager
from pathlib import Path
from urllib.request import Request, urlopen

from ..infrastructure.config import ConfigStore
from ..infrastructure.platform_support import config_home


def open_existing(ready, portal_settings_url=""):
    try:
        data = json.loads(ready.read_text(encoding="utf-8"))
        url = data["url"]
        origin, token = url.split("/#token=")
        if not origin.startswith("http://127.0.0.1:"):
            return False
        with urlopen(
            Request(origin + "/api/config", headers={"Authorization": "Bearer " + token}), timeout=2
        ):
            pass
        if portal_settings_url:
            with urlopen(
                Request(
                    origin + "/api/settings/open",
                    data=json.dumps({"portalUrl": portal_settings_url}).encode("utf-8"),
                    headers={
                        "Authorization": "Bearer " + token,
                        "Content-Type": "application/json",
                    },
                ),
                timeout=2,
            ):
                pass
        else:
            webbrowser.open(url)
        return True
    except (OSError, ValueError, KeyError):
        return False


@contextmanager
def stop_signal(kernel):
    kernel.CreateEventW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.CreateEventW.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    kernel.WaitForSingleObject.restype = ctypes.c_uint
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.CreateEventW(None, False, False, f"Local\\OpenASRInput-Stop-{os.getpid()}")
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield lambda: kernel.WaitForSingleObject(handle, 0) == 0
    finally:
        kernel.CloseHandle(handle)


async def application(store, ready, show_settings, stop_requested=None, portal_settings_url=""):
    from ..adapters.windows import WindowsBridge
    from ..application.daemon import Daemon
    from ..application.runtime import ConfigRuntime
    from ..presentation.settings_server import serve

    bridge = WindowsBridge()
    runtime = ConfigRuntime(store, bridge)
    server = asyncio.create_task(
        serve(
            store,
            port=int(os.environ.get("OPENASRINPUT_SETTINGS_PORT", "10088")),
            open_window=show_settings,
            ready_file=ready,
            announce=False,
            portal_settings_url=portal_settings_url,
        )
    )
    bridge.on_settings = lambda: threading.Thread(
        target=open_existing, args=(ready,), daemon=True
    ).start()

    async def tick(daemon):
        if server.done():
            await server
        if bridge.quit_requested or (stop_requested is not None and stop_requested()):
            raise asyncio.CancelledError()
        await runtime.tick(daemon)

    try:
        await Daemon(bridge, session_factory=runtime.session, on_tick=tick).run()
    except asyncio.CancelledError:
        pass
    except Exception as error:
        runtime.error = str(error)
        raise
    finally:
        server.cancel()
        await asyncio.gather(server, return_exceptions=True)
        try:
            runtime.stopped()
        except OSError:
            logging.exception("Could not save Windows input exit status")
        finally:
            try:
                bridge.close()
            finally:
                ready.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--settings", action="store_true")
    parser.add_argument("--background", action="store_true")
    parser.add_argument(
        "--portal-settings-handoff",
        type=Path,
        help="open the installed Portal management page after the Input settings tab loads",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify installed runtime/assets without starting input",
    )
    args = parser.parse_args()
    if args.check:
        import aiohttp

        from ..presentation.settings_server import ASSETS

        assert (ASSETS / "index.html").is_file()
        print(json.dumps({"ok": True, "aiohttp": aiohttp.__version__, "platform": sys.platform}))
        return
    if os.name != "nt":
        raise RuntimeError("此入口仅用于 Windows")
    portal_settings_url = ""
    if args.portal_settings_handoff:
        handoff = json.loads(args.portal_settings_handoff.read_text(encoding="utf-8"))
        if handoff.get("schemaVersion") != 1:
            parser.error("联合安装交接版本无效")
        if handoff.get("setupRequired", True):
            portal_settings_url = handoff["portal"]["url"].rstrip("/") + "/admin"
    directory = config_home()
    directory.mkdir(parents=True, exist_ok=True)
    ready = directory / "settings-ready.json"
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    name = "Local\\OpenASRInput-" + hashlib.sha256(str(directory).encode()).hexdigest()[:24]
    ctypes.set_last_error(0)
    handle = kernel.CreateMutexW(None, False, name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if ctypes.get_last_error() == 183:
            if not args.background:
                for _ in range(30):
                    if open_existing(ready, portal_settings_url):
                        return
                    import time

                    time.sleep(0.1)
            return
        logging.basicConfig(
            filename=directory / "application.log", level=logging.INFO, encoding="utf-8"
        )
        try:
            with stop_signal(kernel) as stop_requested:
                asyncio.run(
                    application(
                        ConfigStore(),
                        ready,
                        not args.background,
                        stop_requested,
                        portal_settings_url,
                    )
                )
        except Exception as error:
            logging.exception("Windows input application stopped")
            ctypes.windll.user32.MessageBoxW(None, str(error), "OpenASRInput 启动失败", 0x10)
    finally:
        kernel.CloseHandle(handle)


if __name__ == "__main__":
    main()
