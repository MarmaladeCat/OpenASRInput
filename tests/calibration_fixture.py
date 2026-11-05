"""Synthetic microphone/recognizer for isolated calibration tests and UI inspection."""

import asyncio
import math
import struct

from openasrinput.application.calibration import PASSAGES
from openasrinput.domain.audio_processing import samples

DEVICE = {
    "id": "synthetic-mic",
    "title": "模拟麦克风（测试）",
    "fingerprint": "synthetic-device",
    "calibratable": True,
}


def tone(amplitude=500, seconds=7, frequency=440):
    values = [
        round(amplitude * math.sin(i * 2 * math.pi * frequency / 16000))
        for i in range(round(seconds * 16000))
    ]
    return struct.pack(f"<{len(values)}h", *values)


async def device(identity):
    if identity not in (None, "", DEVICE["id"]):
        raise ValueError("模拟设备不存在")
    return dict(DEVICE)


class Capture:
    delay = 0

    def __init__(self, device=None):
        self.stopped = asyncio.Event()
        self.started = False

    async def start(self):
        self.started = True

    async def chunks(self):
        pcm = b"\0" * 96000 + tone()
        for offset in range(0, len(pcm), 6400):
            if self.stopped.is_set():
                return
            yield pcm[offset : offset + 6400]
            await asyncio.sleep(self.delay)
        await self.stopped.wait()

    async def stop(self):
        self.stopped.set()


class Portal:
    default = "cloud"
    auto_learn = False

    def __init__(self, url, key, profile_id):
        self.profile_id = profile_id

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def capabilities(self):
        return {}

    async def profiles(self):
        return {
            "defaultProfileId": self.default,
            "profiles": [
                {"id": "cloud", "provider": "test", "title": "模拟 Portal（测试）"},
                {"id": "other", "provider": "test", "title": "另一测试配置"},
            ],
        }

    async def hotwords(self):
        return {"settings": {"autoLearn": self.auto_learn}}


class Recognizer:
    def __init__(self):
        self.calls = []
        self.validation = False
        self.equal = False
        self.regress = False

    async def __call__(self, client, pcm):
        self.calls.append((client.profile_id, pcm))
        text = PASSAGES["validation" if self.validation else "calibration"]
        good = max(samples(pcm)) > 1000
        if self.equal:
            return text
        if self.validation and self.regress:
            good = not good
        return text if good else text[5:]
