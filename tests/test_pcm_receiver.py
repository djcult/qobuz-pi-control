import math
import struct

import pytest

from qobuz_pi_control.pcm_receiver import HEADER, fft_bands


def packet(samples, *, rate=48000, bits=16, channels=1):
    payload = b"".join(struct.pack("<h", s) for s in samples)
    return HEADER.pack(b"QPCM", 1, channels, bits, rate, len(samples)) + payload


def test_silence():
    levels = fft_bands(packet([0] * 1024))
    assert levels is not None
    assert len(levels) == 64
    assert max(levels) == 0


def test_tone_has_visible_peak():
    samples = [int(24000 * math.sin(2 * math.pi * 1000 * i / 48000)) for i in range(1024)]
    levels = fft_bands(packet(samples))
    assert levels is not None
    assert max(levels) > 0.5


def test_invalid_header():
    assert fft_bands(b"invalid") is None
    assert fft_bands(HEADER.pack(b"WRNG", 1, 1, 16, 48000, 1) + b"\x00\x00") is None


def test_thirty_two_bands():
    levels = fft_bands(packet([0] * 1024), bands=32)
    assert levels is not None
    assert len(levels) == 32
    assert max(levels) == 0
