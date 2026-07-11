"""FFT-based bass brightness envelope.

Brightness comes from bass-band FFT magnitude energy, mapped from a
fixed dB range onto 10-1000 and lightly smoothed (fast attack, fast
release) so bass hits stay punchy instead of fading slowly.

BASS_MIN_FREQ_HZ/BASS_MAX_FREQ_HZ and DB_FLOOR/DB_CEIL are calibrated
against a synthesized, realistically-mixed track (kick + bassline +
snare + hihat + pad at typical relative mix levels, 0.85 peak) played
and re-captured through real WASAPI loopback - not a single pure tone.

That mattered: an earlier calibration (20-200 Hz, floor 10 dB, ceil
40 dB) was tuned against isolated sine tones, which concentrate all
their energy into 1-2 FFT bins and read far louder than the same
frequency range does in a real mix. Against the realistic track, the
20-200 Hz band's loudest kick hits only reached ~16-18 dB - never
anywhere close to a 40 dB ceiling - so bass was, correctly, barely
visible. Measured percentiles for a narrower 40-150 Hz band (kick +
bass fundamental, avoiding sub-40 Hz content most systems barely
reproduce and 150-200 Hz content that's diluted by non-bass material):
quiet/background ~-60 to 4 dB, loud hits ~17-24 dB. DB_FLOOR/DB_CEIL
below are set from that.

Still just a calibration on one synthesized track, not a broad library
of real songs - tune by ear if it still feels off for a given genre.
"""
from __future__ import annotations

import numpy as np

# Bass band only (kick drum / bassline fundamental range).
BASS_MIN_FREQ_HZ = 40
BASS_MAX_FREQ_HZ = 150

BRIGHTNESS_MIN = 10
BRIGHTNESS_MAX = 1000

# Fixed loudness calibration (dB of mean bass-band magnitude).
DB_FLOOR = -5.0
DB_CEIL = 22.0
ENERGY_EPSILON = 1e-8

# Light smoothing: fast enough that individual bass hits still read as
# punchy hits rather than a slow fade. These need to stay comparable to
# (not much shorter than) music_mode.SEND_INTERVAL_SECONDS - the
# original 0.03s attack fully settled well within one ~0.15s send
# interval, so the value actually sent was close to a single raw,
# unsmoothed audio block each time. That's what read as jerky/flickery
# live, separately from any network-side dropouts.
BRIGHTNESS_ATTACK_SECONDS = 0.08
BRIGHTNESS_RELEASE_SECONDS = 0.25


class AudioEnvelope:
    """Turns a stream of audio blocks into a smoothed bass-brightness value."""

    def __init__(self, sample_rate: int, block_size: int):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self._block_seconds = block_size / sample_rate
        self._window = np.hanning(block_size)
        freqs = np.fft.rfftfreq(block_size, d=1 / sample_rate)
        self._bass_mask = (freqs >= BASS_MIN_FREQ_HZ) & (freqs <= BASS_MAX_FREQ_HZ)

        self._brightness = float(BRIGHTNESS_MIN)

    def process(self, block: np.ndarray) -> int:
        """Feed one audio block; return the current brightness (10-1000)."""
        spectrum = np.abs(np.fft.rfft(block * self._window))
        bass_energy = float(np.mean(spectrum[self._bass_mask])) if self._bass_mask.any() else 0.0

        db = 20.0 * np.log10(bass_energy + ENERGY_EPSILON)
        normalized = min(1.0, max(0.0, (db - DB_FLOOR) / (DB_CEIL - DB_FLOOR)))
        target_brightness = BRIGHTNESS_MIN + normalized * (BRIGHTNESS_MAX - BRIGHTNESS_MIN)

        tau = BRIGHTNESS_ATTACK_SECONDS if target_brightness > self._brightness else BRIGHTNESS_RELEASE_SECONDS
        alpha = 1.0 - np.exp(-self._block_seconds / tau)
        self._brightness += alpha * (target_brightness - self._brightness)

        return int(round(self._brightness))
