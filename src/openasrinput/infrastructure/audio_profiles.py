"""Validated, device-bound calibration records and public Portal snapshots."""

import math

from ..adapters.audio_devices import digest, selected_device


def connection_key(portal):
    return digest([portal["url"], portal["apiKey"], portal["profileId"]])


def validate_profiles(profiles):
    if not isinstance(profiles, list) or len(profiles) > 20:
        raise ValueError("最多保存 20 个麦克风校准档案")
    for item in profiles:
        if not isinstance(item, dict) or set(item) != {
            "deviceId",
            "deviceTitle",
            "deviceFingerprint",
            "connectionKey",
            "contextKey",
            "profileId",
            "gain",
            "highpassHz",
            "manualGain",
            "verifiedAt",
            "cerBefore",
            "cerAfter",
        }:
            raise ValueError("麦克风校准档案格式无效")
        for key in (
            "deviceId",
            "deviceTitle",
            "deviceFingerprint",
            "connectionKey",
            "contextKey",
            "profileId",
        ):
            if not isinstance(item[key], str) or not 1 <= len(item[key]) <= 512:
                raise ValueError("麦克风校准标识无效")
        for key, low, high in (
            ("gain", 0.5, 3),
            ("manualGain", 0.5, 3),
            ("verifiedAt", 0, 1e12),
            ("cerBefore", 0, 100),
            ("cerAfter", 0, 100),
        ):
            value = item[key]
            if (
                type(value) not in (int, float)
                or not math.isfinite(value)
                or not low <= value <= high
            ):
                raise ValueError("麦克风校准数值无效")
        if type(item["highpassHz"]) is not int or item["highpassHz"] not in (0, 70):
            raise ValueError("麦克风高通参数无效")


async def recognition_context(client):
    listing = await client.profiles()
    identity = client.profile_id or listing.get("defaultProfileId")
    profile = next((x for x in listing.get("profiles", []) if x["id"] == identity), None)
    if not profile:
        raise ValueError("请先在 Portal 设置有效的识别配置")
    # Pin a default selection for this round; never let individual candidates
    # silently follow a newly selected server default.
    client.profile_id = identity
    hotwords = await client.hotwords()
    if hotwords.get("settings", {}).get("autoLearn"):
        raise ValueError("请先在个人热词页保存设置以关闭自动词频统计，再运行麦克风校准。")
    signature = digest(
        {
            "profile": {
                key: profile.get(key) for key in ("id", "provider", "configuration", "capabilities")
            },
            "hotwords": hotwords.get("settings", {}),
        }
    )
    return {"profileId": identity, "title": profile.get("title", identity), "key": signature}


def matching_profile(audio, portal, device, context):
    return next(
        (
            item
            for item in reversed(audio["calibrations"])
            if item["deviceId"] == device["id"]
            and item["deviceFingerprint"] == device["fingerprint"]
            and item["connectionKey"] == connection_key(portal)
            and item["contextKey"] == context["key"]
            and item["manualGain"] == audio["gain"]
        ),
        None,
    )


async def effective_audio(audio, portal, client, *, device=None):
    from aiohttp import ClientError

    baseline = {"gain": audio["gain"], "highpassHz": 0}
    if not audio["calibrations"]:
        return baseline, ""
    try:
        current = await selected_device(device["id"] if device else audio["deviceId"])
        if device and current["fingerprint"] != device["fingerprint"]:
            raise ValueError("录音设备状态已变化")
        device = current
        context = await recognition_context(client)
        profile = matching_profile(audio, portal, device, context)
    except (OSError, ValueError, RuntimeError, ClientError):
        profile = None
    if profile:
        return {key: profile[key] for key in baseline}, "已应用此麦克风的验证校准"
    return baseline, "设备、音量或识别配置已变化，使用手动增益；请重新校准。"
