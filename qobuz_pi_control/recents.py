"""Persistent, album-ID-based listening history and launcher rendering."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from io import BytesIO
from pathlib import Path

logger = logging.getLogger(__name__)


class RecentAlbums:
    def __init__(self, path: Path | None = None, limit: int = 50):
        root = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
        self.path = path or root / "qobuz-pi-control/recent-albums.json"
        self.limit = limit
        self.items: list[dict] = []
        self.last_album = None
        try:
            items = json.loads(self.path.read_text())
            if not isinstance(items, list):
                raise ValueError("Expected an album list")
            seen = set()
            for item in items:
                if (
                    isinstance(item, dict)
                    and isinstance(item.get("album_id"), str)
                    and item["album_id"]
                    and item["album_id"] not in seen
                ):
                    self.items.append(
                        {
                            k: str(item.get(k) or "")
                            for k in ("album_id", "album", "artist", "album_art_url")
                        } | {"pinned": item.get("pinned") is True}
                    )
                    seen.add(item["album_id"])
            self._trim()
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError):
            logger.warning("Could not load recent albums", exc_info=True)

    def _trim(self) -> None:
        pinned = [item for item in self.items if item.get("pinned")]
        recent = [item for item in self.items if not item.get("pinned")]
        self.items = pinned + recent[:max(0, self.limit - len(pinned))]

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self.items, ensure_ascii=False))
            temporary.replace(self.path)
        except OSError:
            logger.warning("Could not save recent albums", exc_info=True)

    def toggle_pin(self, album_id: str) -> None:
        for item in self.items:
            if item["album_id"] == album_id:
                self.items.remove(item)
                item["pinned"] = not item.get("pinned", False)
                # Keep pins in pinning order; put an unpinned album at the front
                # of the rotating recents so it remains easy to find.
                pinned = [entry for entry in self.items if entry.get("pinned")]
                recent = [entry for entry in self.items if not entry.get("pinned")]
                self.items = pinned + [item] + recent
                self._trim()
                self._save()
                return

    def observe(self, status: dict) -> bool:
        if status.get("status") != "playing":
            return False
        meta = status.get("now_playing") or {}
        album_id = str(meta.get("album_id") or "")
        if not album_id or album_id == self.last_album:
            return False
        item = {
            k: str(meta.get(k) or "")
            for k in ("album_id", "album", "artist", "album_art_url")
        }
        existing = next((entry for entry in self.items if entry["album_id"] == album_id), None)
        if existing is not None and existing.get("pinned"):
            # Playing a pin updates its metadata without changing pin order.
            existing.update(item)
        else:
            pinned = [entry for entry in self.items if entry.get("pinned")]
            recent = [entry for entry in self.items
                      if not entry.get("pinned") and entry["album_id"] != album_id]
            self.items = pinned + [item] + recent
        self._trim()
        self._save()
        self.last_album = album_id
        return True


class AlbumKeyPresses:
    """Resolve an album at key-down, then choose tap or hold on the event loop."""

    def __init__(self, loop, on_tap, on_hold, hold_seconds=0.7):
        self.loop = loop
        self.on_tap = on_tap
        self.on_hold = on_hold
        self.hold_seconds = hold_seconds
        self.pending: dict[int, tuple[str, asyncio.TimerHandle | None]] = {}

    def press(self, key: int, album_id: str) -> None:
        if key in self.pending:
            return
        timer = self.loop.call_later(self.hold_seconds, self._hold, key)
        self.pending[key] = (album_id, timer)

    def _hold(self, key: int) -> None:
        album_id, _ = self.pending[key]
        # Leave the consumed press until release, even if the album grid moves.
        self.pending[key] = (album_id, None)
        self.on_hold(album_id)

    def release(self, key: int) -> None:
        press = self.pending.pop(key, None)
        if press is not None:
            album_id, timer = press
            if timer is not None:
                timer.cancel()
                self.on_tap(album_id)

    def cancel(self) -> None:
        for _, timer in self.pending.values():
            if timer is not None:
                timer.cancel()
        self.pending.clear()


def render_recents(key_size, items, artwork, key_actions):
    """One album per key, reserving the configured page-switch keys."""
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    from .artwork import _page_indicator
    from .display import GAP, canvas_size, slice_tiles

    kw, kh = key_size
    canvas = Image.new("RGB", canvas_size(key_size), (12, 17, 23))
    available = [key for key in range(15) if key_actions.get(key) != "display"]
    for key, item in zip(available, items):
        tile = Image.new("RGB", key_size, (25, 37, 48))
        data = artwork.get(item.get("album_art_url"))
        if data:
            try:
                with Image.open(BytesIO(data)) as source:
                    tile = ImageOps.fit(source.convert("RGB"), key_size)
            except (OSError, ValueError):
                pass
        draw = ImageDraw.Draw(tile, "RGBA")
        if item.get("pinned"):
            # A small pushpin badge stays clear of the album title below.
            draw.rounded_rectangle((kw - 23, 2, kw - 2, 24), radius=4,
                                   fill=(0, 0, 0, 210))
            cx = kw - 12
            color = (255, 209, 92, 255)
            draw.rectangle((cx - 4, 6, cx + 4, 8), fill=color)
            draw.rectangle((cx - 2, 8, cx + 2, 13), fill=color)
            draw.polygon(((cx - 5, 16), (cx - 2, 12),
                          (cx + 2, 12), (cx + 5, 16)), fill=color)
            draw.line((cx, 16, cx, 21), fill=color, width=2)
        draw.rectangle((0, kh - 29, kw, kh), fill=(0, 0, 0, 200))
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", 10)
        except OSError:
            font = ImageFont.load_default(size=10)
        text = item.get("album") or "Album"
        words = text.split()
        lines = [""]
        for word in words:
            candidate = (lines[-1] + " " + word).strip()
            if draw.textlength(candidate, font=font) <= kw - 6:
                lines[-1] = candidate
            elif len(lines) < 2:
                lines.append(word)
            else:
                lines[-1] += " " + word
        for index, line in enumerate(lines[:2]):
            if draw.textlength(line, font=font) > kw - 6:
                while line and draw.textlength(line + "…", font=font) > kw - 6:
                    line = line[:-1]
                line += "…"
            draw.text((3, kh - 27 + index * 12), line, font=font, fill="white")
        canvas.paste(tile, ((key % 5) * (kw + GAP), (key // 5) * (kh + GAP)))
    return slice_tiles(_page_indicator(canvas, key_size, key_actions), key_size)
