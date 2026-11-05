"""Frozen daemon + synthetic microphone/bridge/ASR/model; no desktop or live data."""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestServer
from test_portal_client import PortalFixture

ROOT = Path(__file__).resolve().parents[1]


class Fixture(PortalFixture, unittest.TestCase):
    pass


async def check(package):
    fixture = Fixture()
    await fixture.asyncSetUp()
    fixture.ready_gate = asyncio.Event()
    commits, model_calls, notices = [], [], []
    connected = asyncio.Event()
    writer = None

    async def bridge(reader, output):
        nonlocal writer
        writer = output
        output.write(b"0\tHELLO\tOpenASRInput.Bridge\t1\n")
        connected.set()
        try:
            while raw := await reader.readline():
                fields = raw.decode().rstrip("\n").split("\t")
                identity, verb = fields[:2]
                result = "accepted"
                if verb == "BEGIN":
                    result = "1"
                elif verb == "VALID":
                    result = "true"
                elif verb == "CONTEXT_STATUS":
                    result = "{}"
                elif verb == "SELECTION":
                    result = "你好世界。".encode().hex()
                elif verb == "COMMIT":
                    commits.append(bytes.fromhex(fields[4]).decode())
                elif verb == "NOTICE":
                    notices.append(bytes.fromhex(fields[3]).decode())
                output.write(f"{identity}\tOK\t{result}\n".encode())
                await output.drain()
        finally:
            output.close()

    async def model(request):
        assert request.headers["Authorization"] == "Bearer fixture-model-key"
        body = await request.json()
        model_calls.append(json.loads(body["messages"][1]["content"]))
        return web.json_response(
            {"choices": [{"finish_reason": "stop", "message": {"content": "Hello world."}}]}
        )

    model_app = web.Application()
    model_app.router.add_post("/chat/completions", model)
    model_server = TestServer(model_app)
    await model_server.start_server()
    try:
        with tempfile.TemporaryDirectory(prefix="pr-", dir=ROOT / "test-results") as directory:
            stage = Path(directory).resolve()
            subprocess.run(
                ["dpkg-deb", "-x", str(package.resolve()), str(stage / "package")], check=True
            )
            tools = stage / "tools"
            tools.mkdir()
            marker = stage / "microphone-started"
            capture = tools / "parec"
            capture.write_text(
                f"#!{sys.executable}\nimport os, signal, time\nfrom pathlib import Path\n"
                "signal.signal(signal.SIGTERM, lambda *_: exit(0))\n"
                "for i in range(20): os.write(1, i.to_bytes(2, 'little') * 320)\n"
                f"Path({str(marker)!r}).touch()\nwhile True: time.sleep(1)\n"
            )
            capture.chmod(0o755)
            socket_path = stage / "bridge.sock"
            config = stage / "input.json"
            config.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "portal": {
                            "url": fixture.client.url,
                            "apiKey": "input-key",
                            "profileId": "local",
                        },
                        "textEdit": {
                            "url": str(model_server.make_url("/")).rstrip("/"),
                            "apiKey": "fixture-model-key",
                        },
                        "runtime": {"socketPath": str(socket_path)},
                    }
                )
            )
            native = await asyncio.start_unix_server(bridge, path=socket_path)
            env = {
                **os.environ,
                "HOME": str(stage),
                "PATH": str(tools) + ":" + os.environ["PATH"],
                "PYTHONPATH": "/missing",
            }
            env.pop("PYTHONHOME", None)
            runtime = stage / "package/usr/lib/openasrinput/runtime/openasrinput-runtime"
            with (stage / "daemon.log").open("w") as log:
                child = await asyncio.create_subprocess_exec(
                    str(runtime), "daemon", "--config", str(config), env=env, stdout=log, stderr=log
                )

                async def until(predicate):
                    deadline = time.monotonic() + 30
                    while not predicate():
                        if child.returncode is not None or time.monotonic() >= deadline:
                            raise AssertionError(
                                (stage / "daemon.log").read_text() or "package fixture timeout"
                            )
                        await asyncio.sleep(0.02)

                try:
                    await asyncio.wait_for(connected.wait(), 30)
                    writer.write(b"0\tEVENT\tcommand\n")
                    await writer.drain()
                    await until(marker.exists)
                    await until(lambda: fixture.ws_headers)
                    assert fixture.pcm == [], "uploaded audio before session.ready"
                    writer.write(b"0\tEVENT\tpause\n")
                    await writer.drain()
                    fixture.ready_gate.set()
                    await until(lambda: commits or notices)
                    assert notices == [], notices
                    expected = b"".join(i.to_bytes(2, "little") * 320 for i in range(20))
                    assert b"".join(fixture.pcm) == expected, "lost/reordered/duplicated PCM"
                    assert model_calls == [
                        {"instruction": "模拟定稿。", "selectedText": "你好世界。"}
                    ]
                    assert commits == ["Hello world."], commits
                    print(
                        "PASS frozen daemon: capture before ready, ordered PCM, ASR instruction isolation, model result committed once"
                    )
                finally:
                    if child.returncode is None:
                        child.terminate()
                    await asyncio.wait_for(child.wait(), 10)
                    native.close()
                    await native.wait_closed()
    finally:
        fixture.ready_gate.set()
        await model_server.close()
        await fixture.asyncTearDown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, type=Path)
    asyncio.run(check(parser.parse_args().package))
