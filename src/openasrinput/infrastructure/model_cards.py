"""Local text-model cards, including lossless migration of the original connection."""

import copy
import hashlib
import json
from urllib.parse import urlsplit

DEEPSEEK_URLS = ("https://api.deepseek.com", "https://api.deepseek.com/v1")
FIELDS = {"id", "name", "provider", "url", "model", "apiKey"}


def fingerprint(card, *, catalog=False):
    fields = ("provider", "url", "apiKey") if catalog else ("provider", "url", "model", "apiKey")
    return hashlib.sha256(json.dumps([card.get(k, "") for k in fields]).encode()).hexdigest()


def validate_card(card):
    if not isinstance(card, dict) or card.keys() - FIELDS:
        raise ValueError("模型卡字段无效")
    card = {**dict.fromkeys(FIELDS, ""), **card}
    for field, value in card.items():
        if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 32 for c in value):
            raise ValueError("模型卡字段必须是有效文本")
    if not card["id"] or len(card["id"]) > 100 or not card["name"].strip():
        raise ValueError("请填写模型卡名称和 ID")
    if card["provider"] not in {"deepseek", "openai-compatible"}:
        raise ValueError("请选择支持的文本模型提供商")
    card["url"] = card["url"].strip().rstrip("/")
    if card["url"]:
        endpoint = urlsplit(card["url"])
        try:
            endpoint.port
        except ValueError:
            raise ValueError("文本模型端口无效") from None
        if (
            endpoint.scheme not in {"http", "https"}
            or not endpoint.hostname
            or endpoint.username
            or endpoint.password
            or endpoint.query
            or endpoint.fragment
        ):
            raise ValueError("文本模型地址需要是 HTTP(S) API 地址")
        if card["provider"] == "deepseek" and card["url"] not in DEEPSEEK_URLS:
            raise ValueError("DeepSeek 请选择官方地址；自定义网关请使用 OpenAI 兼容类型")
    card["model"] = card["model"].strip()
    if len(card["model"]) > 256 or any(c.isspace() for c in card["model"]):
        raise ValueError("文本模型名称无效")
    return card


def normalize_editor(editor):
    editor = copy.deepcopy(editor)
    if "cards" not in editor:
        legacy = {key: editor.get(key, "") for key in ("provider", "url", "model", "apiKey")}
        if legacy["provider"] not in {"deepseek", "openai-compatible"}:
            raise ValueError("请选择支持的文本模型提供商")
        if isinstance(legacy["url"], str) and legacy["url"].rstrip("/") not in DEEPSEEK_URLS:
            legacy["provider"] = "openai-compatible"
        migrated = validate_card(dict(legacy, id="legacy", name="原文本修改配置"))
        configured = (
            legacy["apiKey"]
            or legacy["url"] != DEEPSEEK_URLS[0]
            or legacy["model"] != "deepseek-chat"
        )
        editor["cards"] = [migrated] if configured else []
        editor["activeModelCardId"] = "legacy" if editor["cards"] else ""
    if not isinstance(editor["cards"], list) or len(editor["cards"]) > 100:
        raise ValueError("模型卡列表最多支持 100 张")
    cards = [validate_card(card) for card in editor["cards"]]
    ids = [card["id"] for card in cards]
    active = editor.get("activeModelCardId", "")
    if len(set(ids)) != len(ids) or not isinstance(active, str) or (active and active not in ids):
        raise ValueError("模型卡 ID 重复或当前模型卡不存在")
    editor.update(cards=cards, activeModelCardId=active, version=2)
    selected = next((card for card in cards if card["id"] == active), None)
    # Legacy projection keeps existing runtime readers compatible, without another secret owner.
    for field in ("provider", "url", "model", "apiKey"):
        editor[field] = (
            selected[field]
            if selected
            else {
                "provider": "deepseek",
                "url": DEEPSEEK_URLS[0],
                "model": "deepseek-chat",
                "apiKey": "",
            }[field]
        )
    return editor


def require_complete(card, *, model=True):
    required = {"name": "名称", "url": "API 地址", "apiKey": "API Key"}
    if model:
        required["model"] = "模型名称"
    missing = [label for field, label in required.items() if not card.get(field, "").strip()]
    if missing:
        raise ValueError("请先配置完整模型卡：缺少" + "、".join(missing))


def merge_cards(cards, previous, *, complete=False):
    if not isinstance(cards, list):
        raise ValueError("模型卡必须是列表")
    originals = {card["id"]: card for card in previous}
    result = []
    for value in cards:
        if not isinstance(value, dict):
            raise ValueError("模型卡必须是对象")
        card = dict(value)
        clear = card.pop("clearApiKey", False)
        if type(clear) is not bool:
            raise ValueError("清除密钥选项无效")
        if clear:
            card["apiKey"] = ""
        elif not card.get("apiKey"):
            card["apiKey"] = originals.get(card.get("id"), {}).get("apiKey", "")
        card = validate_card(card)
        # Older versions allowed incomplete drafts. Preserve unchanged old cards
        # so they can be repaired or deleted individually, but never add/edit one.
        if complete and card != originals.get(card["id"]):
            require_complete(card)
        result.append(card)
    return result
