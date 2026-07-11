"""System-audio loopback capture (Windows WASAPI via the `soundcard` package)."""
from __future__ import annotations

import warnings

import numpy as np
import soundcard as sc

# Benign and frequent under normal real-time capture load; not worth surfacing to the user.
warnings.filterwarnings("ignore", category=sc.SoundcardRuntimeWarning, message="data discontinuity")

SAMPLE_RATE = 44100
BLOCK_SIZE = 1024


class LoopbackStream:
    """Captures the default output device's audio (loopback) as mono float32 blocks."""

    def __init__(self, sample_rate: int = SAMPLE_RATE, block_size: int = BLOCK_SIZE):
        self.sample_rate = sample_rate
        self.block_size = block_size
        speaker = sc.default_speaker()
        self._microphone = sc.get_microphone(speaker.id, include_loopback=True)
        self._recorder = None

    def __enter__(self) -> "LoopbackStream":
        self._recorder = self._microphone.recorder(
            samplerate=self.sample_rate, channels=1, blocksize=self.block_size
        )
        self._recorder.__enter__()
        return self

    def __exit__(self, *exc_info) -> None:
        if self._recorder is not None:
            self._recorder.__exit__(*exc_info)
            self._recorder = None

    def read_block(self) -> np.ndarray:
        """Block until one mono float32 block of shape (block_size,) has been captured."""
        block = self._recorder.record(numframes=self.block_size)
        return block[:, 0]
