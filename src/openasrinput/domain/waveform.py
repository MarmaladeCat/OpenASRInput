"""PCM16-derived waveform for the host input panel, never part of client text."""

import math
import struct
from collections import deque

BLOCKS = "▁▂▃▄▅▆▇█"


class Waveform:
    def __init__(self, columns=16, window_samples=320):
        if columns < 1 or window_samples < 1:
            raise ValueError("waveform dimensions must be positive")
        self.columns, self.window_samples = columns, window_samples
        self.history = deque([0.0] * columns, maxlen=columns)
        self.pending = bytearray()

    def feed(self, pcm: bytes):
        self.pending.extend(pcm)
        size = self.window_samples * 2
        while len(self.pending) >= size:
            samples = struct.unpack(f"<{self.window_samples}h", self.pending[:size])
            del self.pending[:size]
            rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples)) / 32768
            # Fixed reference, not AGC: silence stays silent; quiet speech is visible.
            self.history.append(min(1.0, math.sqrt(rms)))
        return self.bars

    @property
    def bars(self):
        return "".join(BLOCKS[min(7, int(level * 8))] for level in self.history)

    def reset(self):
        self.pending.clear()
        self.history = deque([0.0] * self.columns, maxlen=self.columns)
