"""Consume the unified installer's recipient-only handoff, never the Portal DB."""

import json
from pathlib import Path

from .config import atomic_json
from .portal_cards import fingerprint, validate_card


def import_handoff(store, path):
    try:
        value = json.loads(Path(path).read_bytes())
    except FileNotFoundError:
        return False
    if (
        not isinstance(value, dict)
        or value.get("schemaVersion") != 1
        or not isinstance(value.get("generation"), str)
    ):
        raise ValueError("联合安装的 Portal 连接文件无效")
    card = validate_card(value["portal"], complete=True)
    config, revision = store.read()
    marker = config.get("installedPortalProvisioning", {})
    if isinstance(marker, dict) and marker.get("generation") == value["generation"]:
        return False
    cards = config["portal"]["cards"]
    existing = next((item for item in cards if item["id"] == card["id"]), None)
    if (
        existing
        and fingerprint(existing) != fingerprint(card)
        and (not isinstance(marker, dict) or marker.get("fingerprint") != fingerprint(existing))
    ):
        # Preserve a manually edited card; add the newly authorized local gateway.
        card["id"] = "local-input-" + value["generation"][:24]
    cards = [item for item in cards if item["id"] != card["id"]] + [card]
    store.save({"portal": {"cards": cards, "activePortalCardId": card["id"]}}, revision)
    # Reuse the same atomic/revision lock as settings writes. The marker is owned
    # by this installer consumer, not exposed as an editable API property.
    from .platform_support import exclusive_lock

    with exclusive_lock(store.path.with_suffix(".lock")):
        current, _ = store.read()
        current["installedPortalProvisioning"] = {
            "generation": value["generation"],
            "fingerprint": fingerprint(card),
        }
        atomic_json(store.path, current)
    return True
