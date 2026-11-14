"""Remove ASR sentence-padding spaces after Chinese full-width terminators only."""

import re

TERMINATORS = "。！？"
PADDING = re.compile(r"(?<=[。！？]) +")


def dictation_text(text, previous=""):
    if previous and previous[-1] in TERMINATORS:
        text = text.lstrip(" ")
    return PADDING.sub("", text)
