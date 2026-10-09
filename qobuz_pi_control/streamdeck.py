"""Stream Deck transport controls with live Qobuz playback feedback and artwork."""

from __future__ import annotations

import asyncio
from io import BytesIO
import logging

import aiohttp

from .config import StreamDeckConfig

logger = logging.getLogger(__name__)

# Stream Deck Original: 5 columns x 3 rows.
# Artwork occupies a 2x2 square at the right (keys 3, 4, 8, 9).
KEY_ACTIONS = {0: "previous", 1: "toggle", 2: "next"}
ART_KEYS = (3, 4, 8, 9)


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


def _artwork_tiles(deck, artwork: bytes):
    """Strictly decode and split one square cover into four LCD images."""
    from PIL import Image, ImageOps
    from StreamDeck.ImageHelpers import PILHelper

    with Image.open(BytesIO(artwork)) as source:
        source.load()  # Reject truncated/corrupt JPEGs before any LCD writes.
        size = deck.key_image_format()["size"]
        cover = ImageOps.fit(source.convert("RGB"), (2 * size[0], 2 * size[1]))
    width, height = cover.size
    return [
        PILHelper.to_native_format(
            deck,
            cover.crop((col * width // 2, row * height // 2,
                        (col + 1) * width // 2, (row + 1) * height // 2)),
        )
        for row in range(2) for col in range(2)
    ]


def _artwork_urls(url: str) -> list[str]:
    """Try the original URL, then a smaller Qobuz cover if applicable."""
    urls = [url]
    if "_600." in url:
        urls.append(url.replace("_600.", "_300."))
    return urls


async def _download_artwork(http: aiohttp.ClientSession, deck, url: str):
    """Retry each candidate, validating all four tiles before displaying any."""
    for candidate in _artwork_urls(url):
        for attempt in range(2):
            try:
                async with http.get(candidate) as response:
                    response.raise_for_status()
                    if int(response.headers.get("Content-Length", 0)) > 4_000_000:
                        raise ValueError("Artwork exceeds 4 MB")
                    data = await response.content.read(4_000_001)
                    if len(data) > 4_000_000:
                        raise ValueError("Artwork exceeds 4 MB")
                tiles = _artwork_tiles(deck, data)
                logger.info("Artwork decoded: %s (%d bytes)", candidate, len(data))
                return tiles
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Artwork attempt %d failed (%s): %s",
                               attempt + 1, candidate, exc)
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
    last_art_url = None
    failed_art_retry_at = 0.0

    async def refresh_feedback() -> None:
        nonlocal last_playing, last_art_url, failed_art_retry_at
        timeout = aiohttp.ClientTimeout(total=6)
        async with aiohttp.ClientSession(timeout=timeout) as http:
            while True:
                try:
                    status = await get_status()
                    playback = status.get("status", "disconnected")
                    now_playing = status.get("now_playing") or {}
                    playing = playback == "playing"
                    if playing != last_playing:
                        deck.set_key_image(1, _transport_image(deck, playing))
                        last_playing = playing
                    show(5, playback.upper())
                    show(6, str(now_playing.get("title") or "")[:16])
                    show(7, str(now_playing.get("artist") or "")[:16])

                    art_url = now_playing.get("album_art_url") or ""
                    now = loop.time()
                    if art_url and (art_url != last_art_url or now >= failed_art_retry_at):
                        if all(key < deck.key_count() for key in ART_KEYS):
                            tiles = await _download_artwork(http, deck, art_url)
                            if tiles is not None:
                                for key, tile in zip(ART_KEYS, tiles):
                                    deck.set_key_image(key, tile)
                                    rendered.pop(key, None)
                                last_art_url = art_url
                                failed_art_retry_at = float("inf")
                            else:
                                logger.warning("Artwork unavailable; keeping previous cover")
                                last_art_url = art_url
                                failed_art_retry_at = now + 30.0
                    elif not art_url and last_art_url:
                        last_art_url = None
                        failed_art_retry_at = 0.0
                        for key in ART_KEYS:
                            show(key, "")
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.warning("Could not refresh Stream Deck playback status",
                                   exc_info=True)
                    show(5, "OFFLINE")
                    if last_playing is not False:
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
