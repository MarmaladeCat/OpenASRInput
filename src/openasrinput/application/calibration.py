"""Bounded microphone calibration jobs; no browser audio or text-model rewriting."""

import asyncio
import copy
import time
from uuid import uuid4

from ..adapters.audio import capture_for_platform
from ..adapters.audio_devices import selected_device
from ..adapters.portal import PortalClient
from ..domain.audio_processing import (
    AudioProcessor,
    candidates,
    dbfs,
    level_improvement,
    measure,
    samples,
    score,
)
from ..infrastructure.audio_profiles import connection_key, matching_profile, recognition_context
from ..infrastructure.config import ConfigConflict

PASSAGES = {
    "calibration": (
        "今天早上，我打开窗户，发现外面的天气很晴朗。桌上放着书本、温水和需要整理的纸张。"
        "请先检查会议记录，再把修改后的文件发给同事。如果时间合适，我们下午一起讨论接下来的安排。"
    ),
    "validation": (
        "周末我准备去公园散步，听听风声，看看路边的花草。回家以后，"
        "我会整理照片，把有趣的事情记录下来。"
    ),
}
ACTIVE = {
    "preparing",
    "noise",
    "recording",
    "evaluating",
    "validation-noise",
    "validation-recording",
    "verifying",
}


async def recognize(client, pcm):
    """Replay at real-time pace, consume revisions concurrently, use stable finals."""
    creating = asyncio.create_task(client.create_session())
    try:
        descriptor = await asyncio.shield(creating)
    except asyncio.CancelledError:
        try:
            descriptor = await creating
            await client.cancel_session(descriptor["sessionId"])
        except Exception:
            pass
        raise
    async with client.stream(descriptor) as stream:

        async def send():
            started = asyncio.get_running_loop().time()
            for offset in range(0, len(pcm), 6400):
                await asyncio.sleep(
                    max(0, started + offset / 32000 - asyncio.get_running_loop().time())
                )
                await stream.send_pcm(pcm[offset : offset + 6400])
            # Do not signal end before the final frame's audio duration elapsed.
            await asyncio.sleep(
                max(0, started + len(pcm) / 32000 - asyncio.get_running_loop().time())
            )
            await stream.end_audio()

        async def receive():
            while not stream.ledger.terminal:
                event = await stream.receive()
                if event["type"] in {"session.error", "session.cancelled"}:
                    raise ValueError(event.get("message", "识别会话已取消"))
                if event["type"] == "session.finished" and not stream.ended:
                    raise ValueError("识别服务提前结束，未比较完整录音")
            return "".join(x.text for x in stream.ledger.utterances.values() if x.final)

        sender, receiver = asyncio.create_task(send()), asyncio.create_task(receive())

        async def exchange():
            done, _ = await asyncio.wait((sender, receiver), return_when=asyncio.FIRST_COMPLETED)
            if receiver in done:
                result = await receiver
                await sender
                return result
            await sender
            # A receive begun before audio.end has no PortalStream deadline yet.
            # Bound that pending read explicitly by the ready event's deadline.
            return await asyncio.wait_for(receiver, stream.finalize_timeout)

        try:
            return await asyncio.wait_for(
                exchange(),
                len(pcm) / 32000 + 60,
            )
        finally:
            sender.cancel()
            receiver.cancel()
            await asyncio.gather(sender, receiver, return_exceptions=True)


class Calibration:
    def __init__(
        self,
        store,
        *,
        capture_factory=capture_for_platform,
        device_resolver=selected_device,
        portal_factory=PortalClient,
        recognizer=recognize,
    ):
        self.store = store
        self.capture_factory, self.device_resolver = capture_factory, device_resolver
        self.portal_factory, self.recognizer = portal_factory, recognizer
        self.task = None
        self.watchdog = None
        self.job = {"state": "idle"}
        self.stop_recording = asyncio.Event()
        self.audio = b""
        self.last_seen = time.monotonic()
        self.operation = asyncio.Lock()

    def view(self):
        self.last_seen = time.monotonic()
        return {**copy.deepcopy(self.job), "passages": PASSAGES}

    async def close(self):
        for task in (self.task, self.watchdog):
            if task:
                task.cancel()
        await asyncio.gather(*(x for x in (self.task, self.watchdog) if x), return_exceptions=True)
        self.audio = b""

    def check_id(self, identity):
        if identity != self.job.get("id"):
            raise ValueError("校准任务已变化，请重新载入")

    def check_revision(self):
        if self.store.read()[1] != self.revision:
            raise ConfigConflict("设置在校准期间已变化，请重新开始校准")

    async def start(self, revision):
        async with self.operation:
            if self.job["state"] in ACTIVE or self.job["state"] == "await-validation":
                raise ValueError("已有校准任务，请先取消")
            await self.close()
            self.config, self.revision = self.store.read()
            if revision != self.revision:
                raise ConfigConflict("设置已变化，请重新载入后校准")
            if not self.config["portal"]["apiKey"]:
                raise ValueError("请先配置并保存 Portal 接入 Key")
            self.job = {
                "id": str(uuid4()),
                "state": "preparing",
                "message": "正在检查设备与识别配置…",
                "results": [],
                "validation": [],
                "canApply": False,
            }
            self.last_seen = time.monotonic()
            self.stop_recording = asyncio.Event()
            self.task = asyncio.create_task(self.run(False))
            self.watchdog = asyncio.create_task(self.expire())
            return self.view()

    async def expire(self):
        while True:
            await asyncio.sleep(5)
            if time.monotonic() - self.last_seen > 30:
                if self.task:
                    self.task.cancel()
                    await asyncio.gather(self.task, return_exceptions=True)
                self.audio = b""
                self.job.update(
                    state="cancelled", message="设置页已离开，校准已结束。", canApply=False
                )
                return
            if self.job["state"] not in ACTIVE | {"await-validation"}:
                return

    async def action(self, identity, action):
        async with self.operation:
            self.check_id(identity)
            if action == "cancel":
                await self.close()
                self.job.update(state="cancelled", message="已取消校准。", canApply=False)
            elif action == "stop":
                if self.job["state"] not in {"recording", "validation-recording"}:
                    raise ValueError("请等待环境测量结束后朗读")
                if self.job.get("seconds", 0) < 8:
                    raise ValueError("请完整朗读，至少录制五秒语音")
                self.stop_recording.set()
            elif action == "validate":
                if self.job["state"] != "await-validation":
                    raise ValueError("请先完成候选比较")
                if self.task:
                    await self.task
                self.check_revision()
                self.stop_recording = asyncio.Event()
                self.job.update(state="preparing", message="准备独立验证录音…")
                self.task = asyncio.create_task(self.run(True))
            elif action == "apply":
                if self.job["state"] != "complete" or not self.job["canApply"]:
                    raise ValueError("此校准尚未通过独立验证")
                self.check_revision()
                device = await self.device_resolver(self.config["audio"]["deviceId"])
                if device["fingerprint"] != self.device["fingerprint"]:
                    raise ValueError("麦克风或系统音量已变化，请重新校准")
                async with self.client() as client:
                    await self.check_context(client)
                profiles = [
                    x
                    for x in self.config["audio"]["calibrations"]
                    if not (
                        x["deviceId"] == device["id"]
                        and x["connectionKey"] == connection_key(self.config["portal"])
                    )
                ]
                profiles.append(
                    {
                        "deviceId": device["id"],
                        "deviceTitle": device["title"],
                        "deviceFingerprint": device["fingerprint"],
                        "connectionKey": connection_key(self.config["portal"]),
                        "contextKey": self.context["key"],
                        "profileId": self.context["profileId"],
                        "gain": self.best["gain"],
                        "highpassHz": self.best["highpassHz"],
                        "manualGain": self.config["audio"]["gain"],
                        "verifiedAt": time.time(),
                        "cerBefore": self.job["validation"][0]["cer"],
                        "cerAfter": self.job["validation"][1]["cer"],
                    }
                )
                self.store.save({"audio": {"calibrations": profiles[-20:]}}, self.revision)
                self.job.update(
                    state="saved", message="校准已保存，下一轮语音输入生效。", canApply=False
                )
            else:
                raise ValueError("未知的校准操作")
            return self.view()

    def client(self):
        portal = self.config["portal"]
        return self.portal_factory(portal["url"], portal["apiKey"], portal["profileId"])

    async def check_context(self, client):
        # Reset to the configured selection so a changed default is detected.
        client.profile_id = self.config["portal"]["profileId"]
        context = await recognition_context(client)
        if context != self.context:
            raise ValueError("识别配置或热词在校准期间已变化，请重新开始")
        self.check_revision()

    async def record(self, validation):
        device = await self.device_resolver(self.config["audio"]["deviceId"])
        if device["fingerprint"] != self.device["fingerprint"]:
            raise ValueError("设备或系统输入音量已变化，请重新开始校准")
        capture = self.capture_factory(device["id"])
        pcm = bytearray()
        stopping = None
        prefix = "validation-" if validation else ""
        try:
            await asyncio.wait_for(capture.start(), 4)
            self.job.update(
                state=prefix + "noise", seconds=0, message="请保持安静三秒，测量背景噪声…"
            )

            async def stop():
                await self.stop_recording.wait()
                await capture.stop()

            stopping = asyncio.create_task(stop())
            iterator = capture.chunks().__aiter__()
            while True:
                try:
                    chunk = await asyncio.wait_for(iterator.__anext__(), 5)
                except StopAsyncIteration:
                    break
                room = max(0, 32000 * 45 - len(pcm))
                pcm.extend(chunk[:room])
                seconds = len(pcm) / 32000
                values = samples(chunk)
                self.job.update(
                    seconds=round(seconds, 1),
                    levelDbfs=dbfs(max((abs(x) for x in values), default=0)),
                )
                if seconds >= 3:
                    self.job.update(
                        state=prefix + "recording", message="请自然朗读下方文字，读完点击结束录音。"
                    )
                if seconds >= 45:
                    self.stop_recording.set()
            if not self.stop_recording.is_set():
                raise ValueError("麦克风意外停止，请检查设备后重试")
        finally:
            if stopping:
                stopping.cancel()
                await asyncio.gather(stopping, return_exceptions=True)
            await capture.stop()
        metrics = measure(bytes(pcm))
        self.job["metrics"] = metrics
        if metrics["errors"]:
            raise ValueError(" ".join(metrics["errors"]))
        device = await self.device_resolver(self.config["audio"]["deviceId"])
        if device["fingerprint"] != self.device["fingerprint"]:
            raise ValueError("录音期间设备或系统音量发生变化，请重录")
        # Keep 200 ms room tone; the rest was only for local noise measurement.
        return bytes(pcm[max(0, 96000 - 6400) :]), metrics

    async def evaluate(self, client, pcm, candidate, reference):
        await self.check_context(client)
        processor = AudioProcessor(candidate["gain"], candidate["highpassHz"])
        processed = b"".join(processor.process(pcm[i : i + 640]) for i in range(0, len(pcm), 640))
        transcript = await self.recognizer(client, processed)
        return {
            **candidate,
            **score(reference, transcript),
            "transcript": transcript,
            "clippedSamples": processor.clipped,
        }

    async def run(self, validation):
        try:
            async with self.client() as client:
                await client.capabilities()
                if not validation:
                    self.device = await self.device_resolver(self.config["audio"]["deviceId"])
                    self.context = await recognition_context(client)
                    previous = matching_profile(
                        self.config["audio"], self.config["portal"], self.device, self.context
                    )
                    self.current = {
                        "gain": previous["gain"] if previous else self.config["audio"]["gain"],
                        "highpassHz": previous["highpassHz"] if previous else 0,
                    }
                    self.job.update(device=self.device["title"], profile=self.context["title"])
                else:
                    await self.check_context(client)
                pcm, metrics = await self.record(validation)
                self.job.update(
                    state="verifying" if validation else "evaluating",
                    message="正在比较云端识别结果…",
                )
                if validation:
                    results = []
                    for item in ({"name": "当前配置", **self.current}, self.best):
                        self.job["message"] = "独立验证：" + item["name"]
                        results.append(
                            await self.evaluate(client, pcm, item, PASSAGES["validation"])
                        )
                        self.job["validation"] = copy.deepcopy(results)
                    before, after = results
                    improvement = self.training_improvement + before["errors"] - after["errors"]
                    accepted = (
                        not after["clippedSamples"]
                        and after["cer"] <= 0.2
                        and after["errors"] <= before["errors"]
                        and (
                            improvement >= 2
                            or (
                                self.level_adjustment
                                and level_improvement(self.current, self.best, metrics) >= 2
                            )
                        )
                    )
                    self.job.update(
                        state="complete" if accepted else "unchanged",
                        canApply=accepted,
                        message=(
                            "独立验证通过：自动增益使电平更合适，识别结果未退步，可应用推荐配置。"
                            if self.level_adjustment
                            else "独立验证通过，可应用推荐配置。"
                        )
                        if accepted
                        else "独立验证未显示可靠改善，保留当前配置。",
                    )
                    self.audio = b""
                    return
                self.audio = pcm
                results = []
                for item in candidates(self.current, metrics):
                    self.job["message"] = "比较候选：" + item["name"]
                    results.append(await self.evaluate(client, pcm, item, PASSAGES["calibration"]))
                    self.job["results"] = copy.deepcopy(results)
                baseline = results[0]
                eligible = [x for x in results[1:] if not x["clippedSamples"]]
                best = min(
                    eligible,
                    key=lambda x: (
                        x["errors"],
                        -level_improvement(baseline, x, metrics),
                        x["highpassHz"],
                    ),
                    default=baseline,
                )
                level_better = level_improvement(baseline, best, metrics) >= 3
                if best["errors"] > baseline["errors"] or (
                    best["errors"] == baseline["errors"] and not level_better
                ):
                    self.job.update(
                        state="unchanged",
                        message=(
                            "朗读与原文差异较大，请检查是否读错、漏读或选错识别语言后重试。"
                            if baseline["cer"] > 0.35
                            else "没有可靠改善，保留当前配置。"
                        ),
                    )
                    self.audio = b""
                    return
                self.job["message"] = "复测当前配置与推荐候选，排除偶然差异…"
                repeated = [
                    await self.evaluate(client, pcm, item, PASSAGES["calibration"])
                    for item in (baseline, best)
                ]
                self.job["repeated"] = repeated
                self.training_improvement = min(baseline["errors"], repeated[0]["errors"]) - max(
                    best["errors"], repeated[1]["errors"]
                )
                self.level_adjustment = level_better and self.training_improvement >= 0
                if (
                    (self.training_improvement < 1 and not self.level_adjustment)
                    or repeated[1]["clippedSamples"]
                    or max(best["cer"], repeated[1]["cer"]) > 0.35
                ):
                    self.job.update(
                        state="unchanged",
                        message="复测差异不稳定或朗读匹配度不足，请检查朗读后重试。",
                    )
                    self.audio = b""
                    return
                self.best = {key: best[key] for key in ("name", "gain", "highpassHz")}
                self.job.update(
                    state="await-validation",
                    recommendation=self.best,
                    message="已自动选择增益并完成复测，请再读另一段短文验证效果。",
                )
                self.audio = b""
        except asyncio.CancelledError:
            self.audio = b""
            raise
        except Exception as error:
            message = str(error) or "校准失败，请检查设备和连接后重试"
            key = self.config["portal"]["apiKey"]
            if key:
                message = message.replace(key, "[redacted]")
            self.job.update(state="failed", message=message[:600], canApply=False)
            self.audio = b""
