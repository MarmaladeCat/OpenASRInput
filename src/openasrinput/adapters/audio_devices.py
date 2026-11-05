"""Read-only device inventory and conservative calibration identities."""

import asyncio
import hashlib
import json
import os


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


async def pactl(*args):
    process = await asyncio.create_subprocess_exec(
        "pactl", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), 4)
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    if process.returncode:
        raise ValueError("无法读取音频设备，请检查 PulseAudio / PipeWire 连接")
    return output.decode("utf-8")


async def default_device():
    if os.name == "nt":
        from .windows import default_audio_device

        return default_audio_device()
    return (await pactl("get-default-source")).strip()


async def devices():
    if os.name == "nt":
        from .windows import audio_device_interface, audio_devices

        listing = await audio_devices()
        inventory = listing["devices"]
        for item in inventory:
            interface = audio_device_interface(item["id"])
            item["calibratable"] = bool(interface)
            item["fingerprint"] = digest(["winmm", interface])
        return listing
    output = await pactl("-f", "json", "list", "sources")
    result = []
    for item in json.loads(output):
        properties = item.get("properties", {})
        monitor = item.get("monitor_of_sink_name") or item["name"].endswith(".monitor")
        result.append(
            {
                "id": item["name"],
                "title": item.get("description", item["name"]),
                "calibratable": not bool(monitor),
                "fingerprint": digest(
                    [
                        item["name"],
                        {
                            key: properties.get(key)
                            for key in (
                                "device.serial",
                                "device.bus_path",
                                "alsa.card_name",
                                "device.product.name",
                            )
                        },
                        item.get("volume"),
                        item.get("mute"),
                        item.get("active_port"),
                    ]
                ),
            }
        )
    return {"devices": result}


async def selected_device(device_id):
    if not device_id:
        device_id = await default_device()
    listing = await devices()
    selected = next((x for x in listing["devices"] if x["id"] == device_id), None)
    if not selected or not selected["calibratable"]:
        raise ValueError(
            "麦克风不可用或无法确认身份，请检查系统默认输入设备；不能使用扬声器监听源。"
        )
    return selected
