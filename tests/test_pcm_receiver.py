import math
import struct

import pytest

from qobuz_pi_control.pcm_receiver import HEADER, HEADER_V2, fft_bands


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


def test_version_2_timestamp_packet():
    samples = [0] * 1024
    payload = b"".join(struct.pack("<h", value) for value in samples)
    packet_v2 = HEADER_V2.pack(b"QPCM", 2, 1, 16, 48000, len(samples), 123.456) + payload
    levels = fft_bands(packet_v2)
    assert levels is not None
    assert len(levels) == 64
    assert max(levels) == 0
