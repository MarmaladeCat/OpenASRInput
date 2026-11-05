"""Own versioned configuration: explicit path, atomic writes and secret-safe views."""

import copy
import hashlib
import json
import math
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

from ..presentation.themes import THEMES
from .audio_profiles import validate_profiles
from .model_cards import fingerprint, merge_cards, normalize_editor, require_complete
from .platform_support import config_home, exclusive_lock, socket_default
from .portal_cards import fingerprint as portal_fingerprint
from .portal_cards import merge_cards as merge_portal_cards
from .portal_cards import normalize_portal
from .portal_cards import validate_card as validate_portal_card

ROOT = Path(__file__).resolve().parents[3]  # Development tools only; never a user data root.
PROFILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}")

DEFAULTS = {
    "schemaVersion": 1,
    "portal": {"url": "http://127.0.0.1:10087", "apiKey": "", "profileId": ""},
    "textEdit": {
        "provider": "deepseek",
        "url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "apiKey": "",
    },
    "audio": {
        "deviceId": None,
        "gain": 1,
        "calibrations": [],
        "sampleRate": 16000,
        "channels": 1,
        "encoding": "pcm_s16le",
    },
    "overlay": {
        "position": "cursor",
        "transparency": 0,
        "theme": "material",
        "colorMode": "light",
        "scale": 1,
        "width": 760,
        "fontSize": 15,
        "radius": 18,
        "previewBufferWords": 20,
    },
    "runtime": {
        "socketPath": os.environ.get(
            "OPENASRINPUT_DEFAULT_SOCKET",
            socket_default(),
        )
    },
    "input": {"keyboardInlinePreedit": True, "framework": "auto"},
    "settings": {"theme": "material", "colorMode": "light"},
}
EDITABLE = {
    "portal": {"url", "apiKey", "profileId", "clearApiKey", "cards", "activePortalCardId"},
    "textEdit": {"provider", "url", "model", "apiKey", "clearApiKey", "cards", "activeModelCardId"},
    "audio": {"deviceId", "gain", "calibrations"},
    "overlay": {
        "theme",
        "colorMode",
        "scale",
        "width",
        "fontSize",
        "radius",
        "position",
        "transparency",
    },
    "settings": {"theme", "colorMode"},
    "runtime": {"socketPath"},
    "input": {"keyboardInlinePreedit", "framework"},
}


class ConfigConflict(ValueError):
    pass


def default_path():
    configured = os.environ.get("OPENASRINPUT_CONFIG")
    return (Path(configured) if configured else config_home() / "input.json").expanduser()


def validate_origin(url):
    if not isinstance(url, str):
        raise ValueError("Portal 地址必须是 HTTP(S) 地址")
    parsed = urlsplit(url)
    try:
        parsed.port
    except ValueError as error:
        raise ValueError("Portal 端口无效") from error
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("Portal 地址请填写 HTTP(S) 根地址，例如 http://127.0.0.1:10087")
    return url.rstrip("/")


def _number(value, low, high, name, *, integer=False):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name}必须在 {low}–{high} 之间")
    if integer and type(value) is not int:
        raise ValueError(f"{name}必须是整数")


def normalize(value):
    if not isinstance(value, dict):
        raise ValueError("配置必须是 JSON 对象")
    config = copy.deepcopy(DEFAULTS)
    # Existing installations used one theme for both surfaces.
    if "settings" not in value and isinstance(value.get("overlay"), dict):
        for field in ("theme", "colorMode"):
            if field in value["overlay"]:
                config["settings"][field] = value["overlay"][field]
    # Preserve existing draft/extension fields, while validating operational fields.
    for key, section in value.items():
        if key in DEFAULTS and isinstance(DEFAULTS[key], dict):
            if not isinstance(section, dict):
                raise ValueError(f"{key} 配置必须是对象")
            config[key].update(copy.deepcopy(section))
        else:
            config[key] = copy.deepcopy(section)
    if type(config["schemaVersion"]) is not int or config["schemaVersion"] != 1:
        raise ValueError("不支持的配置版本")
    portal, audio, overlay, runtime = (
        config[name] for name in ("portal", "audio", "overlay", "runtime")
    )
    config["portal"] = portal = normalize_portal(portal)
    config["textEdit"] = normalize_editor(config["textEdit"])
    if not isinstance(portal["apiKey"], str) or any(c in portal["apiKey"] for c in "\r\n"):
        raise ValueError("Portal 接入 Key 无效")
    if portal["profileId"] is None:
        portal["profileId"] = ""
    if not isinstance(portal["profileId"], str) or (
        portal["profileId"] and not PROFILE.fullmatch(portal["profileId"])
    ):
        raise ValueError("识别配置 ID 无效")
    if audio["deviceId"] is not None and (
        not isinstance(audio["deviceId"], str) or len(audio["deviceId"]) > 512
    ):
        raise ValueError("麦克风设备名称无效")
    _number(audio["gain"], 0.5, 3, "输入增益")
    validate_profiles(audio["calibrations"])
    if (audio["sampleRate"], audio["channels"], audio["encoding"]) != (16000, 1, "pcm_s16le"):
        raise ValueError("当前只支持 PCM16 / 16000 Hz / 单声道")
    if (
        not isinstance(overlay["theme"], str)
        or not isinstance(overlay["colorMode"], str)
        or overlay["theme"] not in THEMES
        or overlay["colorMode"] not in {"light", "dark"}
    ):
        raise ValueError("请选择支持的主题和亮暗模式")
    _number(overlay["scale"], 0.8, 1.5, "面板缩放")
    if not isinstance(overlay["position"], str) or overlay["position"] not in {
        "cursor",
        "top",
        "bottom",
        "top-left",
        "top-right",
        "bottom-left",
        "bottom-right",
        "hidden",
    }:
        raise ValueError("请选择支持的面板位置")
    _number(overlay["transparency"], 0, 100, "面板透明度", integer=True)
    settings = config["settings"]
    if (
        not isinstance(settings["theme"], str)
        or settings["theme"] not in THEMES
        or not isinstance(settings["colorMode"], str)
        or settings["colorMode"] not in {"light", "dark"}
    ):
        raise ValueError("请选择支持的设置页面主题和亮暗模式")
    _number(overlay["width"], 480, 960, "面板宽度", integer=True)
    _number(overlay["fontSize"], 12, 22, "预览字号", integer=True)
    _number(overlay["radius"], 8, 24, "面板圆角", integer=True)
    if type(overlay["previewBufferWords"]) is not int or overlay["previewBufferWords"] != 20:
        raise ValueError("当前语音缓冲固定为 20 词")
    if type(config["input"]["keyboardInlinePreedit"]) is not bool:
        raise ValueError("普通键盘内联预编辑选项无效")
    if config["input"]["framework"] not in ("auto", "ibus", "fcitx4", "fcitx5"):
        raise ValueError("输入框架必须是 auto、ibus、fcitx4 或 fcitx5")
    if (
        not isinstance(runtime["socketPath"], str)
        or not Path(runtime["socketPath"]).is_absolute()
        or (os.name != "nt" and len(os.fsencode(runtime["socketPath"])) >= 108)
        or "\x00" in runtime["socketPath"]
    ):
        raise ValueError("桥接 socket 需要填写长度小于 108 字节的绝对路径")
    return config


class ConfigStore:
    def __init__(self, path=None, *, system_portal=None):
        self.path = Path(path or default_path()).expanduser().resolve()
        self.status_path = self.path.with_suffix(".runtime.json")
        # Explicit configurations (including test sandboxes and source workspaces)
        # must not silently inherit an installed desktop's credentials.
        self.system_portal = (
            Path(system_portal)
            if system_portal is not None
            else Path("/etc/openasrinput/portal.json")
            if path is None and os.name != "nt"
            else None
        )

    def installed_defaults(self):
        if self.system_portal is None:
            return {}
        try:
            return {"portal": json.loads(self.system_portal.read_bytes())}
        except FileNotFoundError:
            return {}

    def read(self):
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            return normalize(self.installed_defaults()), "defaults"
        try:
            value = json.loads(raw)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("配置文件不是有效的 UTF-8 JSON；原文件已保留") from error
        return normalize(value), hashlib.sha256(raw).hexdigest()

    def public(self):
        config, revision = self.read()
        value = {"schemaVersion": 1}
        for name, fields in EDITABLE.items():
            value[name] = {
                field: config[name][field]
                for field in fields
                if field not in {"apiKey", "clearApiKey"}
            }
        value["portal"]["hasApiKey"] = bool(config["portal"]["apiKey"])
        value["portal"]["cards"] = [
            {**{k: v for k, v in card.items() if k != "apiKey"}, "hasApiKey": bool(card["apiKey"])}
            for card in config["portal"]["cards"]
        ]
        value["textEdit"]["hasApiKey"] = bool(config["textEdit"]["apiKey"])
        value["textEdit"]["cards"] = [
            {**{k: v for k, v in card.items() if k != "apiKey"}, "hasApiKey": bool(card["apiKey"])}
            for card in config["textEdit"]["cards"]
        ]
        value["overlay"]["previewBufferWords"] = 20
        return {
            "config": value,
            "modelCardMetadata": self.model_metadata(config["textEdit"]["cards"]),
            "portalCardMetadata": self.portal_metadata(config["portal"]["cards"]),
            "revision": revision,
            "path": str(self.path),
            "platform": sys.platform,
        }

    def model_metadata(self, cards):
        try:
            saved = json.loads(self.path.with_suffix(".models.json").read_bytes())
            if not isinstance(saved, dict):
                return {}
        except (OSError, ValueError):
            return {}
        result = {}
        for card in cards:
            data = saved.get(card["id"], {})
            if not isinstance(data, dict):
                data = {}
            result[card["id"]] = {
                kind: {key: value for key, value in entry.items() if key != "fingerprint"}
                for kind, entry in data.items()
                if isinstance(entry, dict)
                and kind in {"test", "models"}
                and entry.get("fingerprint") == fingerprint(card, catalog=kind == "models")
            }
        return result

    def portal_metadata(self, cards):
        try:
            saved = json.loads(self.path.with_suffix(".portals.json").read_bytes())
        except (OSError, ValueError):
            return {}
        if not isinstance(saved, dict):
            return {}
        return {
            card["id"]: {k: v for k, v in entry.items() if k != "fingerprint"}
            for card in cards
            if isinstance(entry := saved.get(card["id"]), dict)
            and entry.get("fingerprint") == portal_fingerprint(card)
        }

    def record_portal_result(self, card, result):
        path = self.path.with_suffix(".portals.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        with exclusive_lock(path.with_suffix(".lock")):
            try:
                saved = json.loads(path.read_bytes())
            except (OSError, ValueError):
                saved = {}
            if not isinstance(saved, dict):
                saved = {}
            if len(saved) >= 200 and card["id"] not in saved:
                saved.pop(next(iter(saved)))
            saved[card["id"]] = {
                **result,
                "updatedAt": time.time(),
                "fingerprint": portal_fingerprint(card),
            }
            atomic_json(path, saved)

    def record_model_result(self, card, kind, result):
        path = self.path.with_suffix(".models.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        with exclusive_lock(path.with_suffix(".lock")):
            try:
                saved = json.loads(path.read_bytes())
            except (OSError, ValueError):
                saved = {}
            if not isinstance(saved, dict):
                saved = {}
            if card["id"] not in saved and len(saved) >= 200:
                saved.pop(next(iter(saved)))
            if not isinstance(saved.get(card["id"]), dict):
                saved[card["id"]] = {}
            saved.setdefault(card["id"], {})[kind] = {
                **result,
                "updatedAt": time.time(),
                "fingerprint": fingerprint(card, catalog=kind == "models"),
            }
            atomic_json(path, saved)

    def patched(self, patch, current=None):
        if not isinstance(patch, dict) or patch.keys() - EDITABLE.keys():
            raise ValueError("未知的设置分类")
        config = copy.deepcopy(current if current is not None else self.read()[0])
        for name, fields in patch.items():
            if not isinstance(fields, dict) or fields.keys() - EDITABLE[name]:
                raise ValueError(f"{name} 中存在未知设置")
            fields = copy.deepcopy(fields)
            if name == "portal":
                if "cards" in fields:
                    fields["cards"] = merge_portal_cards(
                        fields["cards"], config[name]["cards"], complete=True
                    )
                elif fields.keys() & {"url", "apiKey", "profileId", "clearApiKey"}:
                    # Legacy API edits only the selected connection, never another
                    # card's secret. Old clients remain usable after migration.
                    active = config[name]["activePortalCardId"]
                    original = next(
                        (card for card in config[name]["cards"] if card["id"] == active),
                        {
                            "id": "legacy",
                            "name": "原 Portal 连接",
                            "url": config[name]["url"],
                            "apiKey": "",
                            "profileId": "",
                        },
                    )
                    card = merge_portal_cards([{**original, **fields}], [original])[0]
                    fields = {
                        "cards": [
                            card if item["id"] == original["id"] else item
                            for item in config[name]["cards"]
                        ]
                        if active
                        else [*config[name]["cards"], card],
                        "activePortalCardId": card["id"],
                    }
            if name == "textEdit":
                if "cards" in fields:
                    fields["cards"] = merge_cards(
                        fields["cards"], config[name]["cards"], complete=True
                    )
                elif fields.keys() & {"provider", "url", "model", "apiKey", "clearApiKey"}:
                    existing = config[name]["cards"]
                    if len(existing) > 1 or any(card["id"] != "legacy" for card in existing):
                        raise ValueError("文本模型设置已升级为模型卡，请重新打开设置页面")
                    config[name].pop("cards", None)
            if name in {"portal", "textEdit"}:
                clear = fields.pop("clearApiKey", False)
                if type(clear) is not bool:
                    raise ValueError("清除密钥选项无效")
                if clear:
                    fields["apiKey"] = ""
                elif fields.get("apiKey") == "":
                    fields.pop("apiKey")  # Empty password field preserves the saved value.
            config[name].update(fields)
        result = normalize(config)
        selected_portal = result["portal"]["activePortalCardId"]
        if selected_portal and "activePortalCardId" in patch.get("portal", {}):
            validate_portal_card(
                next(card for card in result["portal"]["cards"] if card["id"] == selected_portal),
                complete=True,
            )
        selected = result["textEdit"]["activeModelCardId"]
        if selected and "activeModelCardId" in patch.get("textEdit", {}):
            before = current if current is not None else self.read()[0]
            if selected != before["textEdit"]["activeModelCardId"]:
                require_complete(
                    next(card for card in result["textEdit"]["cards"] if card["id"] == selected)
                )
        return result

    def save(self, patch, expected_revision):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with exclusive_lock(self.path.with_suffix(".lock")):
            current, revision = self.read()
            if expected_revision != revision:
                raise ConfigConflict("设置已在其他窗口修改，请重新载入后保存")
            config = self.patched(patch, current)
            if self.path.exists() and "cards" not in json.loads(self.path.read_bytes()).get(
                "portal", {}
            ):
                backup = self.path.with_suffix(".pre-portal-cards.json")
                if not backup.exists():
                    atomic_json(backup, json.loads(self.path.read_bytes()))
            if self.path.exists() and "cards" not in json.loads(self.path.read_bytes()).get(
                "textEdit", {}
            ):
                backup = self.path.with_suffix(".pre-model-cards.json")
                if not backup.exists():
                    atomic_json(backup, json.loads(self.path.read_bytes()))
            atomic_json(self.path, config)
        return self.public()

    def status(self):
        try:
            value = json.loads(self.status_path.read_text(encoding="utf-8"))
            if time.time() - value["updatedAt"] < 5:
                return value
            return {**value, "running": False, "state": "stopped", "stale": True}
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return {"running": False, "state": "stopped"}


def _replace_json(temporary, path):
    # Windows readers (including antivirus) can briefly deny DELETE sharing.
    # Retry the same flushed file; never truncate or rewrite the destination.
    for attempt in range(8):
        try:
            os.replace(temporary, path)
            return
        except PermissionError as error:
            if sys.platform != "win32" or getattr(error, "winerror", None) not in {5, 32, 33}:
                raise
            if attempt == 7:
                raise
            time.sleep(min(0.01 * 2**attempt, 0.1))


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            if hasattr(os, "fchmod"):
                os.fchmod(output.fileno(), 0o600)
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        _replace_json(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
