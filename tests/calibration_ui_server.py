"""Local synthetic UI fixture: never accesses a real microphone or cloud account."""

import argparse
import asyncio
from pathlib import Path
from unittest.mock import patch

from aiohttp import web
from calibration_fixture import DEVICE, Capture, Portal, Recognizer, device

from openasrinput.application.calibration import Calibration
from openasrinput.infrastructure.config import ConfigStore, atomic_json
from openasrinput.presentation.settings_server import SettingsServer


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--port", type=int, default=0)
    options = parser.parse_args()
    store = ConfigStore(options.directory / "input.json")
    if not store.path.exists():
        store.save({"portal": {"apiKey": "synthetic-key"}}, "defaults")
    server = SettingsServer(store)
    recognizer = Recognizer()

    class SlowCapture(Capture):
        delay = 0.025

    class TestCalibration(Calibration):
        async def run(self, validation):
            recognizer.validation = validation
            await super().run(validation)

    server.calibration = TestCalibration(
        store,
        capture_factory=SlowCapture,
        device_resolver=device,
        portal_factory=Portal,
        recognizer=recognizer,
    )

    async def inventory():
        return {"devices": [DEVICE]}

    with patch("openasrinput.presentation.settings_server.audio_devices", inventory):
        runner = web.AppRunner(server.app())
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", options.port)
        try:
            await site.start()
            port = site._server.sockets[0].getsockname()[1]
            server.origin = f"http://127.0.0.1:{port}"
            url = server.origin + "/#token=" + server.token
            atomic_json(options.directory / "ready.json", {"url": url})
            print(url, flush=True)
            await asyncio.Event().wait()
        finally:
            await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
