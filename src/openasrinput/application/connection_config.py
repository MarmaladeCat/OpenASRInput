"""Offline connection selection shared by preflight and the running daemon."""

import copy

from ..infrastructure.config import normalize, validate_origin


def effective_config(config, overrides):
    """Resolve explicit launch overrides without moving a saved Key to another origin."""
    config = copy.deepcopy(config)
    for name, fields in overrides.items():
        if name == "portal":
            portal = config[name]
            if "url" in fields and validate_origin(fields["url"]) != portal["url"]:
                url = validate_origin(fields["url"])
                matches = [card for card in portal["cards"] if card["url"] == url]
                if len(matches) == 1 and "apiKey" not in fields:
                    portal.update({key: matches[0][key] for key in ("url", "apiKey", "profileId")})
                else:
                    # Never inherit another endpoint's profile or choose ambiguous cards.
                    portal.update(url=url, apiKey="", profileId="")
            portal.pop("cards", None)
        config[name].update(fields)
    return normalize(config)


def require_connection(config):
    if not config["portal"]["apiKey"].strip():
        raise ValueError(
            "尚未配置当前 Portal 接入 Key。请打开 OpenASRInput 设置 → 语音识别，为该地址配置并选择 Portal 卡，或显式设置 OPENASRINPUT_PORTAL_KEY。"
        )
