"""Standalone, simulated full-deck spectrum renderer.

No ALSA access, no USB writes, no changes to the running controller.
Preview: python -m qobuz_pi_control.spectrum --output /tmp/spectrum.png
"""
from __future__ import annotations

import argparse
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw

BANDS = 64
COLUMNS = 5
ROWS = 3
GAP = 30


class Spectrum:
    """Smoothed logarithmic-band levels and slowly falling peak markers."""

    def __init__(self, bands: int = BANDS):
        self.levels = [0.0] * bands
        self.peaks = [0.0] * bands
        self.hold = [0] * bands

    def update(self, targets: list[float]) -> None:
        if len(targets) != len(self.levels):
            raise ValueError("Expected one level per band")
        for i, target in enumerate(targets):
            target = max(0.0, min(1.0, float(target)))
            old = self.levels[i]
            self.levels[i] = old + (0.72 if target > old else 0.15) * (target - old)
            if self.levels[i] >= self.peaks[i]:
                self.peaks[i] = self.levels[i]
                self.hold[i] = 5
            elif self.hold[i]:
                self.hold[i] -= 1
            else:
                self.peaks[i] = max(self.levels[i], self.peaks[i] - 0.025)


def simulated_bands(t: float, bands: int = BANDS) -> list[float]:
    """A deliberately artificial demo signal, not audio-derived FFT data."""
    rng = random.Random(int(t * 12))
    values = []
    for i in range(bands):
        x = i / max(1, bands - 1)
        envelope = 0.12 + 0.68 * math.exp(-((x - 0.37) / 0.32) ** 2)
        pulse = 0.55 + 0.45 * math.sin(t * 5.3 - i * 0.24) ** 2
        values.append(min(1.0, envelope * pulse * (0.65 + rng.random() * 0.55)))
    return values


def render_canvas(spectrum: Spectrum, key_size: tuple[int, int] = (72, 72),
                  gap: int = GAP) -> Image.Image:
    """Render one logical canvas; tile gaps are excluded when sliced."""
    kw, kh = key_size
    width = COLUMNS * kw + (COLUMNS - 1) * gap
    height = ROWS * kh + (ROWS - 1) * gap
    image = Image.new("RGB", (width, height), (3, 3, 5))
    draw = ImageDraw.Draw(image)
    margin = 9
    usable_height = height - 2 * margin
    spacing = (width - 2 * margin) / len(spectrum.levels)
    bar_width = max(2, int(spacing * 0.62))
    for i, (level, peak) in enumerate(zip(spectrum.levels, spectrum.peaks)):
        x = round(margin + (i + 0.5) * spacing)
        top = height - margin - round(level * usable_height)
        bottom = height - margin
        if bottom > top:
            draw.rectangle((x - bar_width // 2, top, x + bar_width // 2, bottom),
                           fill=(235, 159, 54))
        peak_y = height - margin - round(peak * usable_height)
        draw.line((x - bar_width // 2, peak_y, x + bar_width // 2, peak_y),
                  fill=(255, 224, 154), width=2)
    return image


def slice_tiles(canvas: Image.Image, key_size: tuple[int, int],
                gap: int = GAP) -> list[Image.Image]:
    kw, kh = key_size
    return [
        canvas.crop((col * (kw + gap), row * (kh + gap),
                     col * (kw + gap) + kw, row * (kh + gap) + kh))
        for row in range(ROWS) for col in range(COLUMNS)
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview simulated spectrum (no hardware access)")
    parser.add_argument("--output", type=Path, default=Path("/tmp/spectrum.png"))
    parser.add_argument("--key-size", type=int, default=72)
    args = parser.parse_args()
    spectrum = Spectrum()
    for frame in range(30):
        spectrum.update(simulated_bands(frame / 8))
    canvas = render_canvas(spectrum, (args.key_size, args.key_size))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(args.output)
    print(f"Saved simulated spectrum preview to {args.output}")


if __name__ == "__main__":
    main()
