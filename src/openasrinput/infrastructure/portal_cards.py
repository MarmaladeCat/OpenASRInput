"""Named Portal connections with a backwards-compatible active projection."""

import copy
import hashlib
import json
import re
from urllib.parse import urlsplit

DEFAULT_URL = "http://127.0.0.1:10087"
FIELDS = {"id", "name", "url", "apiKey", "profileId"}


def fingerprint(card):
    return hashlib.sha256(
        json.dumps([card.get(k, "") for k in ("url", "apiKey", "profileId")]).encode()
    ).hexdigest()


def validate_card(value, *, complete=False):
    if not isinstance(value, dict) or value.keys() - FIELDS:
        raise ValueError("Portal 卡字段无效")
    card = {**dict.fromkeys(FIELDS, ""), **value}
    if card["profileId"] is None:
        card["profileId"] = ""
    for field in FIELDS:
        if (
            not isinstance(card[field], str)
            or len(card[field]) > 4096
            or any(ord(c) < 32 for c in card[field])
        ):
            raise ValueError("Portal 卡字段必须是有效文本")
    if not card["id"] or len(card["id"]) > 100 or not card["name"].strip():
        raise ValueError("请填写 Portal 卡名称和 ID")
    card["name"] = card["name"].strip()
    card["url"] = card["url"].strip().rstrip("/")
    parsed = urlsplit(card["url"])
    try:
        parsed.port
    except ValueError:
        raise ValueError("Portal 端口无效") from None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("Portal 地址请填写 HTTP(S) 根地址")
    if card["profileId"] and not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", card["profileId"]
    ):
        raise ValueError("识别配置 ID 无效")
    if complete and not card["apiKey"].strip():
        raise ValueError("请填写此 Portal 卡的识别 Key")
    return card


def normalize_portal(value):
    portal = copy.deepcopy(value)
    if "cards" not in portal:
        legacy = {key: portal.get(key, "") for key in ("url", "apiKey", "profileId")}
        configured = legacy["apiKey"] or legacy["profileId"] or legacy["url"] != DEFAULT_URL
        portal["cards"] = (
            [validate_card({**legacy, "id": "legacy", "name": "原 Portal 连接"})]
            if configured
            else []
        )
        portal["activePortalCardId"] = "legacy" if configured else ""
    if not isinstance(portal["cards"], list) or len(portal["cards"]) > 100:
        raise ValueError("Portal 卡列表最多支持 100 张")
    cards = [validate_card(card) for card in portal["cards"]]
    ids = [card["id"] for card in cards]
    active = portal.get("activePortalCardId", "")
    if len(set(ids)) != len(ids) or not isinstance(active, str) or (active and active not in ids):
        raise ValueError("Portal 卡 ID 重复或当前卡不存在")
    selected = next((card for card in cards if card["id"] == active), None)
    portal.update(cards=cards, activePortalCardId=active, version=2)
    for field, default in (("url", DEFAULT_URL), ("apiKey", ""), ("profileId", "")):
        portal[field] = selected[field] if selected else default
    return portal


def merge_cards(values, previous, *, complete=False):
    if not isinstance(values, list):
        raise ValueError("Portal 卡必须是列表")
    originals = {card["id"]: card for card in previous}
    result = []
    for value in values:
        if not isinstance(value, dict):
            raise ValueError("Portal 卡必须是对象")
        card = dict(value)
        clear = card.pop("clearApiKey", False)
        if type(clear) is not bool:
            raise ValueError("清除密钥选项无效")
        if clear:
            card["apiKey"] = ""
        elif not card.get("apiKey"):
            card["apiKey"] = originals.get(card.get("id"), {}).get("apiKey", "")
        card = validate_card(card)
        if complete and card != originals.get(card["id"]):
            validate_card(card, complete=True)
        result.append(card)
    return result
