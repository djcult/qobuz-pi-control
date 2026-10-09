"""Stream Deck transport controls with live Qobuz playback feedback and artwork."""

from __future__ import annotations

import asyncio
from io import BytesIO
import logging

import aiohttp

from .config import StreamDeckConfig

logger = logging.getLogger(__name__)

# Stream Deck Original: 5 columns x 3 rows.
# Experimental 5x3 full-deck artwork mosaic. Keys 0/1/2 still control playback.
KEY_ACTIONS = {0: "previous", 1: "toggle", 2: "next"}
ART_KEYS = tuple(range(15))
# Virtual pixels of physical space between adjacent LCDs; tune to your device.
ART_GAP_PX = 30


def _label_image(deck, label: str):
    from PIL import ImageDraw, ImageFont
    from StreamDeck.ImageHelpers import PILHelper

    image = PILHelper.create_image(deck)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=16)
    bounds = draw.textbbox((0, 0), label, font=font)
    x = (image.width - (bounds[2] - bounds[0])) // 2
    y = (image.height - (bounds[3] - bounds[1])) // 2
    draw.text((x, y), label, font=font, fill="white")
    return PILHelper.to_native_format(deck, image)


def _transport_image(deck, playing: bool):
    """Draw a proper play/pause symbol rather than a text label."""
    from PIL import ImageDraw
    from StreamDeck.ImageHelpers import PILHelper

    image = PILHelper.create_image(deck)
    draw = ImageDraw.Draw(image)
    w, h = image.size
    if playing:
        draw.rounded_rectangle((w * .30, h * .24, w * .43, h * .76),
                               radius=3, fill="white")
        draw.rounded_rectangle((w * .57, h * .24, w * .70, h * .76),
                               radius=3, fill="white")
    else:
        draw.polygon([(w * .34, h * .22), (w * .34, h * .78),
                      (w * .77, h * .50)], fill="white")
    return PILHelper.to_native_format(deck, image)


def _artwork_tiles(deck, artwork: bytes, playing: bool = False,
                   metadata=("", "", ""), remaining=None, progress=None, quality=""):
    """Compose one continuous 5x3 canvas, then omit the physical button gaps."""
    from PIL import Image, ImageOps, ImageDraw, ImageFont
    from StreamDeck.ImageHelpers import PILHelper

    key_w, key_h = deck.key_image_format()["size"]
    canvas_w = 5 * key_w + 4 * ART_GAP_PX
    canvas_h = 3 * key_h + 2 * ART_GAP_PX
    with Image.open(BytesIO(artwork)) as source:
        source.load()
        cover = ImageOps.fit(source.convert("RGB"), (canvas_w, canvas_h)).convert("RGBA")
    overlay = Image.new("RGBA", cover.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    def font_at(size):
        try:
            return ImageFont.truetype("DejaVuSans.ttf", size)
        except OSError:
            return ImageFont.load_default(size=size)

    def centered(text, box, size, max_lines=2):
        """Fit text inside a canvas rectangle, shrinking or wrapping as needed."""
        text = str(text or "").strip()
        if not text:
            return
        x0, y0, x1, y1 = box
        width = x1 - x0 - 10
        height = y1 - y0 - 8
        for point_size in range(size, 9, -1):
            font = font_at(point_size)
            words = text.split()
            lines = []
            current = ""
            for word in words:
                candidate = (current + " " + word).strip()
                if draw.textbbox((0, 0), candidate, font=font)[2] <= width:
                    current = candidate
                else:
                    if current:
                        lines.append(current)
                    current = word
            if current:
                lines.append(current)
            line_h = point_size + 4
            if len(lines) <= max_lines and len(lines) * line_h <= height and all(
                draw.textbbox((0, 0), line, font=font)[2] <= width for line in lines
            ):
                break
        else:
            font = font_at(10)
            lines = [text]
            while lines[0] and draw.textbbox((0, 0), lines[0] + "…", font=font)[2] > width:
                lines[0] = lines[0][:-1]
            lines[0] += "…"
            line_h = 14
        top = (y0 + y1 - len(lines) * line_h) // 2
        for i, line in enumerate(lines):
            bounds = draw.textbbox((0, 0), line, font=font)
            draw.text(((x0 + x1 - (bounds[2] - bounds[0])) // 2,
                       top + i * line_h - bounds[1]), line, font=font,
                      fill=(255, 255, 255, 255))

    # Previous / Play-Pause / Next stay on keys 0, 1 and 2.
    for index in KEY_ACTIONS:
        cx = index * (key_w + ART_GAP_PX) + key_w // 2
        cy = key_h // 2
        radius = min(key_w, key_h) * .34
        draw.ellipse((cx-radius, cy-radius, cx+radius, cy+radius),
                     fill=(0, 0, 0, 175))
        white = (255, 255, 255, 255)
        if index == 0:
            draw.rectangle((cx-17, cy-12, cx-13, cy+12), fill=white)
            draw.polygon([(cx+12, cy-12), (cx-12, cy), (cx+12, cy+12)], fill=white)
        elif index == 2:
            draw.rectangle((cx+13, cy-12, cx+17, cy+12), fill=white)
            draw.polygon([(cx-12, cy-12), (cx+12, cy), (cx-12, cy+12)], fill=white)
        elif playing:
            draw.rounded_rectangle((cx-12, cy-13, cx-4, cy+13), radius=2, fill=white)
            draw.rounded_rectangle((cx+4, cy-13, cx+12, cy+13), radius=2, fill=white)
        else:
            draw.polygon([(cx-9, cy-14), (cx-9, cy+14), (cx+15, cy)], fill=white)

    # The middle row is a *single* title banner across all five LCDs.
    middle_top = key_h + ART_GAP_PX
    draw.rounded_rectangle((0, middle_top + 12, canvas_w, middle_top + key_h - 8),
                           radius=10, fill=(0, 0, 0, 155))
    centered(metadata[2], (12, middle_top + 14, canvas_w - 12,
                            middle_top + key_h - 28), 28, max_lines=2)

    # Bottom row: legible, bold, single-line labels rendered at 4x resolution.
    # Text is deliberately truncated rather than reduced to tiny point sizes.
    bottom_top = 2 * (key_h + ART_GAP_PX)
    for index, value in (
        (10, metadata[0]),
        (11, metadata[1]),
        (13, quality),
        (14, remaining),
    ):
        if not value:
            continue
        x = (index - 10) * (key_w + ART_GAP_PX)
        draw.rounded_rectangle((x + 2, bottom_top + 7, x + key_w - 2,
                                bottom_top + key_h - 7), radius=8,
                               fill=(0, 0, 0, 175))
        scale = 4
        from PIL import Image as PILImage
        text_layer = PILImage.new("RGBA", (key_w * scale, key_h * scale),
                                  (0, 0, 0, 0))
        td = ImageDraw.Draw(text_layer)
        try:
            font = ImageFont.truetype("DejaVuSans-Bold.ttf", 12 * scale)
        except OSError:
            font = ImageFont.load_default(size=12 * scale)
        value = str(value).strip()
        available = (key_w - 10) * scale
        def text_width(candidate):
            bb = td.textbbox((0, 0), candidate, font=font)
            return bb[2] - bb[0]
        if text_width(value) > available:
            while value and text_width(value + "…") > available:
                value = value[:-1]
            value += "…"
        bounds = td.textbbox((0, 0), value, font=font)
        td.text(((key_w * scale - (bounds[2] - bounds[0])) // 2,
                 (key_h * scale - (bounds[3] - bounds[1])) // 2 - bounds[1]),
                value, font=font, fill=(255, 255, 255, 255))
        text_layer = text_layer.resize((key_w, key_h), PILImage.Resampling.LANCZOS)
        overlay.alpha_composite(text_layer, (x, bottom_top))

    composite = Image.alpha_composite(cover, overlay).convert("RGB")
    tiles = []
    for row in range(3):
        for col in range(5):
            x = col * (key_w + ART_GAP_PX)
            y = row * (key_h + ART_GAP_PX)
            tile = composite.crop((x, y, x + key_w, y + key_h)).copy()
            tile.load()
            tiles.append(PILHelper.to_native_format(deck, tile))
    return tiles


async def _download_artwork(http: aiohttp.ClientSession, url: str):
    """Download a complete cover; leave the current image intact on failure."""
    for attempt in range(2):
        try:
            async with http.get(url) as response:
                response.raise_for_status()
                if int(response.headers.get("Content-Length", 0)) > 4_000_000:
                    raise ValueError("Artwork exceeds 4 MB")
                data = await response.read()
                if len(data) > 4_000_000:
                    raise ValueError("Artwork exceeds 4 MB")
            from PIL import Image
            with Image.open(BytesIO(data)) as source:
                source.load()
            return data
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("Artwork attempt %d failed: %s", attempt + 1, url, exc_info=True)
    return None

async def run_streamdeck(config: StreamDeckConfig, dispatch, get_status) -> None:
    try:
        from StreamDeck.DeviceManager import DeviceManager
    except ImportError as exc:
        raise RuntimeError(
            "Stream Deck support is not installed; run: uv sync --extra streamdeck"
        ) from exc

    decks = DeviceManager().enumerate()
    if not decks:
        raise RuntimeError("No Stream Deck found")

    deck = decks[0]
    deck.open()
    deck.reset()
    deck.set_brightness(max(0, min(config.brightness, 100)))
    logger.info("Stream Deck: %s", deck.get_serial_number())

    rendered: dict[int, str] = {}

    def show(key: int, label: str) -> None:
        if key >= deck.key_count() or rendered.get(key) == label:
            return
        deck.set_key_image(key, _label_image(deck, label))
        rendered[key] = label

    for key, label in {0: "PREV", 2: "NEXT", 5: "IDLE"}.items():
        show(key, label)

    loop = asyncio.get_running_loop()

    def on_key_change(_deck, key: int, state: bool) -> None:
        if state and (action := KEY_ACTIONS.get(key)):
            loop.call_soon_threadsafe(
                lambda: asyncio.create_task(dispatch(action))
            )

    deck.set_key_callback(on_key_change)

    artwork_bytes = None
    last_art_url = None
    failed_art_retry_at = 0.0
    last_render_state = None

    async def refresh_feedback() -> None:
        nonlocal artwork_bytes, last_art_url, failed_art_retry_at, last_render_state
        timeout = aiohttp.ClientTimeout(total=6)
        async with aiohttp.ClientSession(timeout=timeout) as http:
            while True:
                try:
                    status = await get_status()
                    playback = status.get("status", "disconnected")
                    now_playing = status.get("now_playing") or {}
                    playing = playback == "playing"
                    metadata = tuple(str(now_playing.get(field) or "")
                                     for field in ("artist", "album", "title"))
                    duration = now_playing.get("duration_seconds")
                    position = now_playing.get("position_seconds")
                    remaining = None
                    if duration is not None and position is not None and float(duration) > 0:
                        duration = float(duration)
                        position = max(0.0, min(float(position), duration))
                        seconds = max(0, int(duration - position + 0.999))
                        remaining = (f"{seconds // 3600:02d}:"
                                     f"{(seconds // 60) % 60:02d}:{seconds % 60:02d}")
                    # Qobuz metadata quality, not an ALSA-confirmed output format.
                    quality = str(now_playing.get("quality") or "")
                    # Display only the numeric bit-depth/sample-rate portion.
                    # Examples: "FLAC 24/96" -> "24/96", "24/96 FLAC" -> "24/96".
                    import re
                    match = re.search(r"\\b(\\d{1,2})\\s*/\\s*(\\d+(?:\\.\\d+)?)\\b", quality)
                    if match:
                        quality = f"{match.group(1)}/{match.group(2)}"
                    else:
                        quality = re.sub(r"\\bFLAC\\b", "", quality, flags=re.IGNORECASE).strip()
                    art_url = now_playing.get("album_art_url") or ""
                    now = loop.time()
                    if art_url and (art_url != last_art_url or now >= failed_art_retry_at):
                        data = await _download_artwork(http, art_url)
                        if data is not None:
                            artwork_bytes = data
                            last_art_url = art_url
                            failed_art_retry_at = float("inf")
                            last_render_state = None
                        else:
                            last_art_url = art_url
                            failed_art_retry_at = now + 30.0
                    elif not art_url and last_art_url:
                        artwork_bytes = None
                        last_art_url = None
                        failed_art_retry_at = 0.0
                        last_render_state = None
                        rendered.clear()
                        for key in ART_KEYS:
                            show(key, "")

                    if artwork_bytes is not None:
                        state = (last_art_url, playing, metadata, remaining, quality)
                        if state != last_render_state:
                            tiles = _artwork_tiles(deck, artwork_bytes, playing, metadata,
                                                   remaining, None, quality)
                            if last_render_state is None or state[0] != last_render_state[0]:
                                keys = ART_KEYS
                            else:
                                keys = set()
                                if state[1] != last_render_state[1]:
                                    keys.add(1)
                                if state[2] != last_render_state[2]:
                                    keys.update((5, 6, 7, 8, 9, 10, 11))
                                if state[3] != last_render_state[3]:
                                    keys.add(14)
                                if state[4] != last_render_state[4]:
                                    keys.add(13)
                            for key in keys:
                                deck.set_key_image(key, tiles[key])
                            last_render_state = state
                    else:
                        show(0, "PREV")
                        show(2, "NEXT")
                        show(5, playback.upper())
                        show(6, str(now_playing.get("title") or "")[:16])
                        show(7, str(now_playing.get("artist") or "")[:16])
                        deck.set_key_image(1, _transport_image(deck, playing))
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.warning("Could not refresh Stream Deck playback status",
                                   exc_info=True)
                    if artwork_bytes is None:
                        show(5, "OFFLINE")
                await asyncio.sleep(1.0)

    feedback_task = asyncio.create_task(refresh_feedback())
    try:
        await asyncio.Event().wait()
    finally:
        feedback_task.cancel()
        await asyncio.gather(feedback_task, return_exceptions=True)
        deck.reset()
        deck.close()
