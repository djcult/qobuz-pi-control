"""Stream Deck transport controls with live Qobuz playback feedback and artwork."""

from __future__ import annotations

import asyncio
from io import BytesIO
import logging
from pathlib import Path
import re

import aiohttp

from .config import StreamDeckConfig
from .artwork import _label_image, _artwork_tiles, _transport_image
from .spectrum import Spectrum, simulated_bands, render_canvas
from .display import TileDisplay, slice_tiles

logger = logging.getLogger(__name__)

# Stream Deck Original: 5 columns x 3 rows.
# Experimental 5x3 full-deck artwork mosaic. Keys 0/1/2 still control playback.
KEY_ACTIONS = {0: "previous", 1: "toggle", 2: "next"}
ART_KEYS = tuple(range(15))
# Virtual pixels of physical space between adjacent LCDs; tune to your device.


def _alsa_sample_rate_khz() -> str | None:
    """Read the active USB DAC playback rate from ALSA's negotiated hw_params."""
    # The DAC has appeared as card 3, but card numbers can change after reboot.
    for pcm in sorted(Path("/proc/asound").glob("card*/pcm*p/sub*/hw_params")):
        try:
            params = pcm.read_text()
            if "closed" in params:
                continue
            rate = re.search(r"^rate:\s*(\d+)", params, re.MULTILINE)
            if rate:
                hz = int(rate.group(1))
                if 8000 <= hz <= 384000:
                    return f"{hz / 1000:g}"
        except OSError:
            continue
    return None


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
    display = TileDisplay(deck)
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
    display_mode = 0
    display_revision = 0
    spectrum = Spectrum()
    spectrum_started = loop.time()

    def toggle_display() -> None:
        nonlocal display_mode, display_revision, last_render_state
        display_mode = (display_mode + 1) % 4
        display_revision += 1
        last_render_state = None
        display.invalidate()
        logger.info("Stream Deck display mode: %s",
                    ("artwork + all info", "artwork + title",
                     "spectrum + title", "spectrum only")[display_mode])

    def on_key_change(_deck, key: int, state: bool) -> None:
        if state and key == 4:
            loop.call_soon_threadsafe(toggle_display)
        elif state and (action := KEY_ACTIONS.get(key)):
            loop.call_soon_threadsafe(
                lambda: asyncio.create_task(dispatch(action))
            )

    deck.set_key_callback(on_key_change)

    artwork_bytes = None
    last_art_url = None
    failed_art_retry_at = 0.0
    last_render_state = None
    title_started_at = loop.time()
    last_title = None
    last_now_playing = {}

    # Network polling never waits on Stream Deck USB transfers. Rendering uses the
    # most recently published status, including while artwork is downloading.
    latest_status: dict = {}
    status_error = False
    last_render_state = None
    frame_count = 0
    frame_total_seconds = 0.0
    frame_max_seconds = 0.0
    frame_report_at = loop.time()

    async def poll_status() -> None:
        nonlocal artwork_bytes, last_art_url, failed_art_retry_at, last_now_playing, latest_status, status_error
        timeout = aiohttp.ClientTimeout(total=6)
        async with aiohttp.ClientSession(timeout=timeout) as http:
            while True:
                try:
                    status = await get_status()
                    latest_status = status
                    status_error = False
                    playback = status.get("status", "disconnected")
                    reported_now_playing = status.get("now_playing") or {}
                    # Keep complete metadata across transient track transitions.
                    if reported_now_playing.get("title"):
                        last_now_playing = reported_now_playing
                    now_playing = reported_now_playing or last_now_playing
                    playing = playback == "playing"
                    art_url = now_playing.get("album_art_url") or ""
                    now = loop.time()
                    if art_url and (art_url != last_art_url or now >= failed_art_retry_at):
                        data = await _download_artwork(http, art_url)
                        if data is not None:
                            artwork_bytes = data
                            last_art_url = art_url
                            failed_art_retry_at = float("inf")
                        else:
                            last_art_url = art_url
                            failed_art_retry_at = now + 30.0
                    # Missing artwork URLs are transient during track changes.
                    # Never clear the current cover while waiting for the next.

                except asyncio.CancelledError:
                    raise
                except Exception:
                    status_error = True
                    logger.warning("Could not poll Qobuz status", exc_info=True)
                await asyncio.sleep(0.3)

    async def render_feedback() -> None:
        nonlocal last_render_state, title_started_at, last_title
        nonlocal frame_count, frame_total_seconds, frame_max_seconds, frame_report_at
        # Yield between frames; status polling runs as a separate coroutine.
        while True:
            frame_started = loop.time()
            try:
                status = latest_status
                playback = status.get("status", "disconnected")
                now_playing = status.get("now_playing") or last_now_playing
                playing = playback == "playing"
                metadata = tuple(str(now_playing.get(field) or "")
                                 for field in ("artist", "album", "title"))
                marquee_text = " - ".join(part for part in
                                           (metadata[2], metadata[1]) if part)
                display_metadata = (metadata[0], metadata[1], marquee_text)
                if marquee_text != last_title:
                    last_title = marquee_text
                    title_started_at = loop.time()
                words = marquee_text.split()
                title_offset = 0
                if len(words) > 5:
                    # Hold the opening five words for 3 seconds before scrolling.
                    elapsed = max(0.0, loop.time() - title_started_at)
                    last_offset = len(words) - 5
                    step_seconds = 0.5
                    initial_hold_seconds = 3.0
                    end_hold_seconds = 0.5
                    cycle = (initial_hold_seconds
                             + last_offset * step_seconds
                             + end_hold_seconds)
                    phase = elapsed % cycle
                    if phase >= initial_hold_seconds:
                        title_offset = min(
                            last_offset,
                            1 + int((phase - initial_hold_seconds) / step_seconds),
                        )
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
                # Example: "FLAC Hi-Res (up to 24-bit/96kHz)" -> "24/96".
                # This is Qobuz's advertised quality, not verified ALSA PCM.
                bit_match = re.search(
                    r"(16|24|32)\s*(?:-?bit|bits?)?\s*/\s*"
                    r"(44\.1|48|88\.2|96|176\.4|192|352\.8|384)\s*(?:kHz)?",
                    quality, re.IGNORECASE,
                   if display_mode >= 2:
                    # Simulated spectrum until the non-blocking PCM tap is ready.
                    from PIL import Image, ImageDraw, ImageFont
                    from StreamDeck.ImageHelpers import PILHelper
                    spectrum.update(simulated_bands(loop.time() - spectrum_started))
                    canvas = render_canvas(spectrum, deck.key_image_format()["size"])
                    if display_mode == 2:
                        # Same five-key marquee positions as the artwork renderer.
                        kw, kh = deck.key_image_format()["size"]
                        gap = 30
                        band_y = kh + gap
                        overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
                        draw = ImageDraw.Draw(overlay)
                        draw.rounded_rectangle(
                            (0, band_y + 12, canvas.width, band_y + kh - 8),
                            radius=10, fill=(0, 0, 0, 155))
                        visible = words[title_offset:title_offset + 5]
                        start_col = (5 - len(visible)) // 2 if len(words) <= 5 else 0
                        for slot, word in enumerate(visible):
                            col = start_col + slot
                            x = col * (kw + gap)
                            font = None
                            for size in range(19, 5, -1):
                                candidate = ImageFont.truetype("DejaVuSans.ttf", size)
                                bounds = draw.textbbox((0, 0), word, font=candidate)
                                if bounds[2] - bounds[0] <= kw - 12:
                                    font = candidate
                                    break
                            if font is None:
                                font = ImageFont.truetype("DejaVuSans.ttf", 6)
                            # Truncate only extreme words that cannot fit at 6pt.
                            fitted = word
                            while fitted and draw.textbbox((0, 0), fitted, font=font)[2] > kw - 12:
                                fitted = fitted[:-1]
                            color = ((160, 220, 255, 255)
                                     if title_offset + slot >= len(metadata[2].split())
                                     else (255, 255, 255, 255))
                            draw.text((x + kw // 2, band_y + kh // 2),
                                      fitted, font=font, anchor="mm", fill=color)
                        canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
                    display.show(slice_tiles(canvas, deck.key_image_format()["size"]))
                    last_render_state = None
                elif artwork_bytes is not None:
                    show_overlays = display_mode == 0
                    state = (last_art_url, playing, display_metadata, remaining, quality, display_revision, title_offset)
                    if state != last_render_state:
                        tiles = _artwork_tiles(deck, artwork_bytes, playing, display_metadata,
                                               remaining, None, quality, show_overlays, title_offset, len(metadata[2].split()))
                        display.show_native(tiles)
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
                logger.warning("Could not render Stream Deck feedback", exc_info=True)
                if artwork_bytes is None and status_error:
                    show(5, "OFFLINE")
            elapsed = loop.time() - frame_started
            frame_count += 1
            frame_total_seconds += elapsed
            frame_max_seconds = max(frame_max_seconds, elapsed)
            if loop.time() - frame_report_at >= 10.0:
                window = loop.time() - frame_report_at
                logger.info("Stream Deck render: %.1f FPS, mean %.1f ms, max %.1f ms, %s mode",
                            frame_count / window, frame_total_seconds / frame_count * 1000,
                            frame_max_seconds * 1000, display_mode)
                frame_report_at = loop.time()
                frame_count = 0
                frame_total_seconds = 0.0
                frame_max_seconds = 0.0
            target = 1 / 15 if display_mode >= 2 else 0.2
            await asyncio.sleep(max(0, target - elapsed))

    poll_task = asyncio.create_task(poll_status())
    feedback_task = asyncio.create_task(render_feedback())
    try:
        await asyncio.Event().wait()
    finally:
        feedback_task.cancel()
        poll_task.cancel()
        await asyncio.gather(feedback_task, poll_task, return_exceptions=True)
        deck.reset()
        deck.close()
