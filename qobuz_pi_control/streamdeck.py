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


def _artwork_tiles(deck, artwork: bytes, playing: bool = False, metadata=("", "", "")):
    """Render 5x3 cover mosaic with transport glyphs over the first three keys."""
    from PIL import Image, ImageOps, ImageDraw, ImageFont
    from StreamDeck.ImageHelpers import PILHelper

    with Image.open(BytesIO(artwork)) as source:
        source.load()
        key_w, key_h = deck.key_image_format()["size"]
        canvas_w = 5 * key_w + 4 * ART_GAP_PX
        canvas_h = 3 * key_h + 2 * ART_GAP_PX
        cover = ImageOps.fit(source.convert("RGB"), (canvas_w, canvas_h))
        cover.load()

    tiles = []
    for row in range(3):
        for col in range(5):
            index = row * 5 + col
            x = col * (key_w + ART_GAP_PX)
            y = row * (key_h + ART_GAP_PX)
            tile = cover.crop((x, y, x + key_w, y + key_h)).copy()
            tile.load()
            if index in KEY_ACTIONS:
                # Dark translucent disc preserves the artwork behind the icon.
                rgba = tile.convert("RGBA")
                overlay = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
                draw = ImageDraw.Draw(overlay)
                cx, cy = key_w // 2, key_h // 2
                radius = min(key_w, key_h) * .34
                draw.ellipse((cx-radius, cy-radius, cx+radius, cy+radius),
                             fill=(0, 0, 0, 175))
                white = (255, 255, 255, 255)
                if index == 0:  # Previous
                    draw.rectangle((cx-17, cy-12, cx-13, cy+12), fill=white)
                    draw.polygon([(cx+12, cy-12), (cx-12, cy), (cx+12, cy+12)], fill=white)
                elif index == 2:  # Next
                    draw.rectangle((cx+13, cy-12, cx+17, cy+12), fill=white)
                    draw.polygon([(cx-12, cy-12), (cx+12, cy), (cx-12, cy+12)], fill=white)
                elif playing:  # Pause
                    draw.rounded_rectangle((cx-12, cy-13, cx-4, cy+13), radius=2, fill=white)
                    draw.rounded_rectangle((cx+4, cy-13, cx+12, cy+13), radius=2, fill=white)
                else:  # Play
                    draw.polygon([(cx-9, cy-14), (cx-9, cy+14), (cx+15, cy)], fill=white)
                tile = Image.alpha_composite(rgba, overlay).convert("RGB")
            if index in (5, 6, 7):
                from textwrap import wrap
                value = str(metadata[index - 5] or "")
                if value:
                    rgba = tile.convert("RGBA")
                    overlay = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
                    draw = ImageDraw.Draw(overlay)
                    draw.rounded_rectangle((3, 7, key_w - 3, key_h - 7),
                                           radius=8, fill=(0, 0, 0, 175))
                    font = ImageFont.load_default(size=12)
                    # Pixel-width-aware wrapping for variable-width text.
                    words = value.split()
                    lines = []
                    line = ""
                    for word in words:
                        candidate = (line + " " + word).strip()
                        if draw.textbbox((0, 0), candidate, font=font)[2] <= key_w - 12:
                            line = candidate
                        else:
                            if line:
                                lines.append(line)
                            line = word
                    if line:
                        lines.append(line)
                    lines = lines[:3]
                    if lines and draw.textbbox((0, 0), lines[-1], font=font)[2] > key_w - 12:
                        lines[-1] = lines[-1][:11] + "…"
                    line_h = 15
                    start_y = (key_h - len(lines) * line_h) // 2
                    for n, line in enumerate(lines):
                        bounds = draw.textbbox((0, 0), line, font=font)
                        draw.text(((key_w - (bounds[2] - bounds[0])) // 2,
                                   start_y + n * line_h), line, font=font,
                                  fill="white")
                    tile = Image.alpha_composite(rgba, overlay).convert("RGB")
            tiles.append(PILHelper.to_native_format(deck, tile))
    return tiles


async def _download_artwork(http: aiohttp.ClientSession, deck, url: str, playing: bool = False, metadata=("", "", "")):
    """Fetch and validate artwork before changing any LCD buttons."""
    for attempt in range(2):
        try:
            async with http.get(url) as response:
                response.raise_for_status()
                if int(response.headers.get("Content-Length", 0)) > 4_000_000:
                    raise ValueError("Artwork exceeds 4 MB")
                data = await response.read()
                if len(data) > 4_000_000:
                    raise ValueError("Artwork exceeds 4 MB")
                logger.debug("Artwork HTTP %s: content-length=%s, received=%d, JPEG EOI=%s",
                             response.status, response.headers.get("Content-Length"),
                             len(data), data.endswith(b"\\xff\\xd9"))
            tiles = _artwork_tiles(deck, data, playing, metadata)
            _download_artwork._last_bytes = data
            logger.info("Artwork decoded and encoded: %s (%d bytes)", url, len(data))
            return tiles
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

    last_playing = None
    has_artwork = False
    artwork_bytes = None
    last_metadata = ("", "", "")
    last_art_url = None
    failed_art_retry_at = 0.0

    async def refresh_feedback() -> None:
        nonlocal last_playing, last_art_url, failed_art_retry_at, has_artwork, artwork_bytes, last_metadata
        timeout = aiohttp.ClientTimeout(total=6)
        async with aiohttp.ClientSession(timeout=timeout) as http:
            while True:
                try:
                    status = await get_status()
                    playback = status.get("status", "disconnected")
                    now_playing = status.get("now_playing") or {}
                    playing = playback == "playing"
                    metadata = tuple(str(now_playing.get(field) or "") for field in ("artist", "album", "title"))
                    if playing != last_playing:
                        if has_artwork and artwork_bytes is not None:
                            tiles = _artwork_tiles(deck, artwork_bytes, playing, metadata)
                            deck.set_key_image(1, tiles[1])
                        elif not has_artwork:
                            deck.set_key_image(1, _transport_image(deck, playing))
                        last_playing = playing
                    if has_artwork and artwork_bytes is not None and metadata != last_metadata:
                        tiles = _artwork_tiles(deck, artwork_bytes, playing, metadata)
                        for key in (5, 6, 7):
                            deck.set_key_image(key, tiles[key])
                        last_metadata = metadata
                    if not has_artwork:
                        show(5, playback.upper())
                        show(6, str(now_playing.get("title") or "")[:16])
                        show(7, str(now_playing.get("artist") or "")[:16])

                    art_url = now_playing.get("album_art_url") or ""
                    now = loop.time()
                    if art_url and (art_url != last_art_url or now >= failed_art_retry_at):
                        if all(key < deck.key_count() for key in ART_KEYS):
                            tiles = await _download_artwork(http, deck, art_url, playing, metadata)
                            if tiles is not None:
                                for key, tile in zip(ART_KEYS, tiles):
                                    deck.set_key_image(key, tile)
                                    rendered.pop(key, None)
                                last_art_url = art_url
                                has_artwork = True
                                last_metadata = metadata
                                # Cache the source bytes for dynamic Play/Pause overlays.
                                artwork_bytes = getattr(_download_artwork, "_last_bytes", None)
                                failed_art_retry_at = float("inf")
                            else:
                                logger.warning("Artwork unavailable; keeping previous cover")
                                last_art_url = art_url
                                failed_art_retry_at = now + 30.0
                    elif not art_url and last_art_url:
                        last_art_url = None
                        has_artwork = False
                        artwork_bytes = None
                        last_metadata = ("", "", "")
                        failed_art_retry_at = 0.0
                        for key in ART_KEYS:
                            show(key, "")
                        last_playing = None
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.warning("Could not refresh Stream Deck playback status",
                                   exc_info=True)
                    show(5, "OFFLINE")
                    if last_playing is not False and not has_artwork:
                        deck.set_key_image(1, _transport_image(deck, False))
                        last_playing = False
                await asyncio.sleep(1.0)

    feedback_task = asyncio.create_task(refresh_feedback())
    try:
        await asyncio.Event().wait()
    finally:
        feedback_task.cancel()
        await asyncio.gather(feedback_task, return_exceptions=True)
        deck.reset()
        deck.close()
