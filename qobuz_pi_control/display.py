"""Shared virtual 5x3 Stream Deck canvas, slicing and changed-key transfers."""
from __future__ import annotations

from PIL import Image

COLUMNS = 5
ROWS = 3
GAP = 30


def canvas_size(key_size: tuple[int, int], gap: int = GAP) -> tuple[int, int]:
    kw, kh = key_size
    return (COLUMNS * kw + (COLUMNS - 1) * gap,
            ROWS * kh + (ROWS - 1) * gap)


def slice_tiles(canvas: Image.Image, key_size: tuple[int, int],
                gap: int = GAP) -> list[Image.Image]:
    kw, kh = key_size
    return [
        canvas.crop((col * (kw + gap), row * (kh + gap),
                     col * (kw + gap) + kw, row * (kh + gap) + kh))
        for row in range(ROWS) for col in range(COLUMNS)
    ]


class TileDisplay:
    """Send only changed native images; invalidate on mode transitions."""

    def __init__(self, deck):
        self.deck = deck
        self.previous: list[bytes | None] = [None] * (COLUMNS * ROWS)

    def invalidate(self) -> None:
        self.previous = [None] * (COLUMNS * ROWS)

    def show_native(self, tiles: list[bytes]) -> int:
        if len(tiles) != len(self.previous):
            raise ValueError("Expected 15 tiles")
        changed = 0
        for index, native in enumerate(tiles):
            if native != self.previous[index]:
                self.deck.set_key_image(index, native)
                self.previous[index] = native
                changed += 1
        return changed

    def show(self, tiles: list[Image.Image]) -> int:
        from StreamDeck.ImageHelpers import PILHelper
        if len(tiles) != len(self.previous):
            raise ValueError("Expected 15 tiles")
        changed = 0
        for index, tile in enumerate(tiles):
            native = PILHelper.to_native_format(self.deck, tile.convert("RGB"))
            if native != self.previous[index]:
                self.deck.set_key_image(index, native)
                self.previous[index] = native
                changed += 1
        return changed
