"""Non-blocking Unix datagram PCM spectrum receiver.

Wire format shared with qobuz-proxy/backends/alsa/monitor.py.
The socket is owned by this process; no audio samples are changed.
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
from pathlib import Path
import socket
import struct

logger = logging.getLogger(__name__)
HEADER = struct.Struct("<4sBBBIH")  # legacy v1\nHEADER_V2 = struct.Struct("<4sBBBIHd")
SOCKET_PATH = "/tmp/qobuz-pcm.sock"


def fft_bands(packet: bytes, bands: int = 64) -> list[float] | None:
    """Calculate log-frequency magnitudes from source-format integer PCM."""
    import numpy as np

    if len(packet) < HEADER.size:
        return None
    magic, version, channels, bits, rate, frames = HEADER.unpack_from(packet)
    if magic != b"QPCM" or version != 1 or channels not in (1, 2) or bits not in (16, 24, 32):
        return None
    width = (bits + 7) // 8
    expected = header.size + frames * channels * width
    if not frames or len(packet) != expected or rate < 8000 or rate > 384000:
        return None
    payload = memoryview(packet)[header.size:]
    if bits == 16:
        samples = np.frombuffer(payload, dtype="<i2").reshape(-1, channels).astype(np.float64) / 32768
    elif bits == 32:
        samples = np.frombuffer(payload, dtype="<i4").reshape(-1, channels).astype(np.float64) / 2147483648
    else:
        raw = np.frombuffer(payload, dtype=np.uint8).reshape(-1, channels, 3)
        integers = (raw[:, :, 0].astype(np.int32) |
                    (raw[:, :, 1].astype(np.int32) << 8) |
                    (raw[:, :, 2].astype(np.int32) << 16))
        integers = (integers << 8) >> 8  # sign extend 24-bit
        samples = integers.astype(np.float64) / 8388608
    mono = samples.mean(axis=1)
    n = len(mono)
    if n < 64:
        return None
    # Hann window, no interpolation/resampling in the playback path.
    spectrum = np.abs(np.fft.rfft(mono * np.hanning(n))) * (2.0 / n)
    freqs = np.fft.rfftfreq(n, 1 / rate)
    edges = np.geomspace(35, min(20000, rate * 0.48), bands + 1)
    values = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        selected = spectrum[(freqs >= lo) & (freqs < hi)]
        # Narrow bass bands may have no bin centre even with a long window.
        # Use the nearest bin instead of displaying a permanently dead bar.
        if not selected.size:
            midpoint = math.sqrt(lo * hi)
            nearest = int(np.argmin(np.abs(freqs - midpoint)))
            selected = spectrum[nearest:nearest + 1]
        values.append(float(selected.max()))
    # Fixed logarithmic dB scale; silence stays at zero, no AGC pumping.
    return [max(0.0, min(1.0, (20 * math.log10(v + 1e-9) + 78) / 72)) for v in values]


async def receive_spectrum(latest: dict, path: str = SOCKET_PATH) -> None:
    """Publish latest bands and receive timestamp without blocking UI rendering."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.setblocking(False)
    try:
        Path(path).unlink(missing_ok=True)
        sock.bind(path)
        os.chmod(path, 0o600)
        logger.info("PCM spectrum receiver listening on %s", path)
        loop = asyncio.get_running_loop()
        while True:
            packet = await loop.sock_recv(sock, 65536)
            try:
                values = fft_bands(packet)
                if values is not None:
                    latest["bands"] = values
                    latest["at"] = loop.time()
            except Exception:
                logger.debug("Discarded invalid PCM monitor packet", exc_info=True)
    finally:
        sock.close()
        Path(path).unlink(missing_ok=True)
