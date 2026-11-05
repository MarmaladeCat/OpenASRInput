"""Configuration-driven daemon: live appearance, immutable recognition rounds."""

import copy
import os
import time
from contextlib import asynccontextmanager

from ..adapters.audio import capture_for_platform
from ..adapters.audio_devices import selected_device
from ..adapters.portal import PortalClient
from ..adapters.text_edit import TextEditor
from ..infrastructure.audio_profiles import effective_audio
from ..infrastructure.config import atomic_json
from .connection_config import effective_config, require_connection
from .daemon import SessionSettings


class ConfigRuntime:
    def __init__(
        self,
        store,
        bridge,
        *,
        overrides=None,
        portal_factory=PortalClient,
        capture_factory=capture_for_platform,
    ):
        self.store, self.bridge = store, bridge
        self.overrides = overrides or {}
        self.portal_factory, self.capture_factory = portal_factory, capture_factory
        self.appearance = None
        self.active_connection = None
        self.next_poll = 0.0
        self.error = ""
        self.keyboard_inline = None
        self.last_status = {}
        self.audio_status = ""
        self.framework = os.environ.get("OPENASRINPUT_ACTIVE_FRAMEWORK", "")
        self.framework_preference = store.read()[0]["input"]["framework"]

    def read(self):
        config, revision = self.store.read()
        return effective_config(config, self.overrides), revision

    def apply_appearance(self, config):
        options = config["overlay"]
        if options != self.appearance:
            result = self.bridge.configure_panel(options)
            if result != "accepted":
                raise RuntimeError("原生面板没有接受外观设置，请使用更新后的插件")
            self.appearance = copy.deepcopy(options)
        inline = config["input"]["keyboardInlinePreedit"]
        if inline != self.keyboard_inline:
            result = self.bridge.configure_keyboard(inline)
            if result != "accepted":
                raise RuntimeError("原生插件没有接受键盘兼容设置")
            self.keyboard_inline = inline

    @asynccontextmanager
    async def session(self):
        config, _ = self.read()
        self.apply_appearance(config)
        self.active_connection = {
            key: copy.deepcopy(config[key]) for key in ("portal", "audio", "textEdit")
        }
        portal, audio = config["portal"], config["audio"]
        require_connection(config)
        # Pin the actual input before capture, so a later system-default change
        # cannot apply another microphone's profile to this recording.
        device = None
        self.audio_status = ""
        if audio["calibrations"]:
            try:
                device = await selected_device(audio["deviceId"])
            except (OSError, ValueError, RuntimeError):
                self.audio_status = "无法确认麦克风身份，使用备用增益；请检查系统输入设备。"
        async with self.portal_factory(
            portal["url"], portal["apiKey"], portal["profileId"]
        ) as client:

            async def prepare_audio(client):
                options, self.audio_status = await effective_audio(
                    audio, portal, client, device=device
                )
                return options

            yield SessionSettings(
                client,
                lambda: self.capture_factory(device["id"] if device else audio["deviceId"]),
                audio["gain"],
                TextEditor(config["textEdit"]),
                prepare_audio=prepare_audio if device else None,
            )

    async def tick(self, daemon):
        if time.monotonic() < self.next_poll:
            return
        self.next_poll = time.monotonic() + 0.5
        revision = ""
        pending = False
        framework_pending = False
        try:
            config, revision = self.read()
            framework_pending = config["input"]["framework"] != self.framework_preference
            self.apply_appearance(config)
            self.error = ""
            current = {key: config[key] for key in ("portal", "audio", "textEdit")}
            pending = (
                daemon.core.state in {"connecting", "listening", "pausing", "processing"}
                and current != self.active_connection
            )
        except (ValueError, OSError, RuntimeError) as error:
            self.error = str(error)
        native_context = {}
        if hasattr(self.bridge, "context_status"):
            try:
                native_context = self.bridge.context_status()
            except (ValueError, OSError, RuntimeError):
                pass  # Optional diagnostics cannot terminate a recognition round.
        ledger = getattr(daemon.core, "ledger", None)
        generation = getattr(daemon.core, "generation", 0)
        submissions = [
            item
            for item in getattr(daemon.core, "submissions", [])
            if item.generation == generation
        ]
        recognition = {
            "generation": generation,
            "eventSequence": ledger.seq if ledger else 0,
            "finalCount": ledger.final_count if ledger else 0,
            "previewCharacters": len(ledger.preview) if ledger else 0,
            "submissions": {
                status: sum(item.status == status for item in submissions)
                for status in ("queued", "submitted", "retained", "cancelled")
            },
            "submittedCharacters": sum(
                len(item.text) for item in submissions if item.status == "submitted"
            ),
        }
        self.last_status = {
            "running": True,
            "state": daemon.core.state,
            "mode": getattr(daemon.core, "mode", "dictation"),
            "updatedAt": time.time(),
            "revision": revision,
            "pendingConnection": pending,
            "appearance": self.appearance,
            "error": self.error or daemon.core.error or getattr(self.bridge, "warning", ""),
            "stopReason": getattr(daemon.core, "stop_reason", ""),
            "transitions": list(getattr(daemon.core, "transitions", [])),
            "nativeContext": native_context,
            "recognition": recognition,
            "audioCalibration": self.audio_status,
            "inputFramework": self.framework or native_context.get("framework", ""),
            "frameworkRestartRequired": framework_pending,
            "overrides": [
                name + "." + key for name, fields in self.overrides.items() for key in fields
            ],
        }
        atomic_json(self.store.status_path, self.last_status)

    def stopped(self):
        atomic_json(
            self.store.status_path,
            {
                **self.last_status,
                "running": False,
                "state": "stopped",
                "error": self.error or self.last_status.get("error", ""),
                "updatedAt": time.time(),
            },
        )
