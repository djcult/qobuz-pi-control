"""Persistent, album-ID-based listening history and launcher rendering."""

from __future__ import annotations

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
                        }
                    )
                    seen.add(item["album_id"])
            self.items = self.items[:limit]
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError):
            logger.warning("Could not load recent albums", exc_info=True)

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
        self.items = [item] + [
            entry for entry in self.items if entry["album_id"] != album_id
        ]
        self.items = self.items[: self.limit]
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self.items, ensure_ascii=False))
            temporary.replace(self.path)
        except OSError:
            logger.warning("Could not save recent albums", exc_info=True)
        self.last_album = album_id
        return True


def render_recents(key_size, items, artwork, key_actions, message=""):
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
    # The navigation key identifies the page and gives launch feedback.
    for key, action in key_actions.items():
        if action == "display":
            draw = ImageDraw.Draw(canvas)
            x, y = (key % 5) * (kw + GAP), (key // 5) * (kh + GAP)
            text = message or ("RECENT\nALBUMS" if items else "NO RECENT\nALBUMS YET")
            draw.multiline_text(
                (x + 4, y + 27),
                text,
                fill="white",
                font=ImageFont.load_default(size=10),
                spacing=3,
            )
    return slice_tiles(_page_indicator(canvas, key_size, key_actions), key_size)
