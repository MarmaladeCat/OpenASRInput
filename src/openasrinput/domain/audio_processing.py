"""Small causal PCM processor shared by calibration replay and live dictation."""

import math
import statistics
import struct
import unicodedata

RATE = 16000


def samples(pcm):
    if len(pcm) % 2:
        raise ValueError("PCM16 数据不完整")
    return struct.unpack(f"<{len(pcm) // 2}h", pcm)


class AudioProcessor:
    def __init__(self, gain=1, highpass_hz=0):
        self.gain = gain
        self.alpha = math.exp(-2 * math.pi * highpass_hz / RATE) if highpass_hz else 0
        self.previous_input = self.previous_output = 0.0
        self.clipped = 0

    def process(self, pcm):
        if self.gain == 1 and not self.alpha:
            return pcm
        output = []
        for value in samples(pcm):
            filtered = value
            if self.alpha:
                filtered = self.alpha * (self.previous_output + value - self.previous_input)
                self.previous_input, self.previous_output = value, filtered
            amplified = round(filtered * self.gain)
            self.clipped += int(amplified < -32768 or amplified > 32767)
            output.append(max(-32768, min(32767, amplified)))
        return struct.pack(f"<{len(output)}h", *output)


def dbfs(value):
    return round(20 * math.log10(max(value, 1) / 32768), 1)


def rms(values):
    return math.sqrt(sum(x * x for x in values) / max(1, len(values)))


def measure(pcm, noise_bytes=96000):
    """The first three seconds are explicitly recorded as room tone, not speech."""
    quiet, voice = samples(pcm[:noise_bytes]), samples(pcm[noise_bytes:])
    # A click, startup transient or an early syllable must not define the floor
    # for the entire recording. This is an energy estimate, not a speech VAD.
    quiet_levels = [rms(quiet[i : i + 320]) for i in range(0, len(quiet), 320)]
    noise = statistics.median(quiet_levels) if quiet_levels else 0
    frames = [voice[i : i + 320] for i in range(0, len(voice), 320)]
    active = [frame for frame in frames if rms(frame) > max(20, noise * 1.5)]
    voiced = [x for frame in active for x in frame]
    peak = max((abs(x) for x in voice), default=0)
    level = rms(voiced or voice)
    lowpass = 0.0
    low_energy = 0.0
    alpha = math.exp(-2 * math.pi * 80 / RATE)
    for value in quiet:
        lowpass = alpha * lowpass + (1 - alpha) * value
        low_energy += lowpass * lowpass
    clipped = sum(abs(x) >= 32760 for x in voice) / max(1, len(voice))
    warnings, errors = [], []
    if clipped > 0.001:
        errors.append("原始录音存在削波，数字增益无法修复；请降低系统麦克风音量或增加距离后重录。")
    if len(voice) < RATE * 5:
        errors.append("录音过短，请在环境测量结束后完整朗读至少五秒。")
    if rms(voice) < 8 and peak < 64:
        errors.append("几乎未收到声音，请检查麦克风静音、权限或系统默认输入设备。")
    if len(voiced) < RATE * 3:
        warnings.append(
            "能量估计中的明显声音片段较少，将继续用朗读识别结果核验，不据此判定没有语音。"
        )
    if level and level < noise * 3:
        warnings.append("估算人声与背景较接近，将继续比较识别结果；数字增益不能消除背景噪声。")
    # This is a conservative starting point, not a universal ASR optimum.
    gain = min(
        3,
        max(
            0.5,
            min(32768 * 10 ** (-22 / 20) / max(level, 1), 32768 * 10 ** (-6 / 20) / max(peak, 1)),
        ),
    )
    return {
        "noiseDbfs": dbfs(noise),
        "speechDbfs": dbfs(level),
        "peakDbfs": dbfs(peak),
        "clippingRatio": clipped,
        "speechSeconds": round(len(voiced) / RATE, 2),
        "recordingSeconds": round(len(voice) / RATE, 2),
        "suggestedGain": round(gain, 3),
        "lowFrequencyNoise": noise > 50 and low_energy > sum(x * x for x in quiet) * 0.45,
        "warnings": errors + warnings,
        "errors": errors,
    }


def level_improvement(before, after, metrics):
    """Gain-only distance to our level target, not a claim about ASR accuracy."""
    if before["highpassHz"] or after["highpassHz"]:
        return 0
    level = metrics["speechDbfs"]
    return abs(level + 20 * math.log10(before["gain"]) + 22) - abs(
        level + 20 * math.log10(after["gain"]) + 22
    )


def normalized_text(text):
    # The supplied passages deliberately avoid numbers/proper names; do not use
    # fuzzy semantic matching that could conceal real recognition errors.
    return "".join(
        c
        for c in unicodedata.normalize("NFKC", text).casefold()
        if unicodedata.category(c)[0] in "LN"
    )


def score(reference, transcript):
    expected, actual = normalized_text(reference), normalized_text(transcript)
    if not expected or len(actual) > 4000:
        raise ValueError("评分文本长度无效")
    row = list(range(len(actual) + 1))
    for i, left in enumerate(expected, 1):
        next_row = [i]
        for j, right in enumerate(actual, 1):
            next_row.append(min(row[j] + 1, next_row[-1] + 1, row[j - 1] + (left != right)))
        row = next_row
    return {"errors": row[-1], "characters": len(expected), "cer": row[-1] / len(expected)}


def candidates(current, metrics):
    choices = [
        {"name": "当前配置", **current},
        {"name": "原音对照", "gain": 1, "highpassHz": 0},
        {"name": "校准固定增益", "gain": metrics["suggestedGain"], "highpassHz": 0},
    ]
    if metrics["lowFrequencyNoise"]:
        choices.append(
            {"name": "固定增益与轻度高通", "gain": metrics["suggestedGain"], "highpassHz": 70}
        )
    result = []
    for item in choices:
        if not any(
            (x["gain"], x["highpassHz"]) == (item["gain"], item["highpassHz"]) for x in result
        ):
            result.append(item)
    return result
