"""Stream Deck adapter using the python-elgato-streamdeck library."""

from __future__ import annotations

import asyncio
import logging

from .config import StreamDeckConfig

logger = logging.getLogger(__name__)

# Simple first layout. Rendering/state feedback can evolve without changing
# the qobuz-proxy control contract.
KEY_ACTIONS = {
    0: "previous",
    1: "toggle",
    2: "next",
}


def _label_image(deck, label: str):
    from PIL import Image, ImageDraw, ImageFont
    from StreamDeck.ImageHelpers import PILHelper

    image = PILHelper.create_image(deck)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=18)
    box = draw.textbbox((0, 0), label, font=font)
    x = (image.width - (box[2] - box[0])) // 2
    y = (image.height - (box[3] - box[1])) // 2
    draw.text((x, y), label, font=font)
    return PILHelper.to_native_format(deck, image)


async def run_streamdeck(config: StreamDeckConfig, dispatch, get_status) -> None:
    try:
        from StreamDeck.DeviceManager import DeviceManager
    except ImportError as exc:
        raise RuntimeError(
            "Stream Deck support is not installed; run: pip install -e '.[streamdeck]'"
        ) from exc

    decks = DeviceManager().enumerate()
    if not decks:
        raise RuntimeError("No Stream Deck found")

    deck = decks[0]
    deck.open()
    deck.reset()
    deck.set_brightness(max(0, min(config.brightness, 100)))
    logger.info("Stream Deck: %s", deck.get_serial_number())

    labels = {0: "PREV", 1: "PLAY", 2: "NEXT"}
    for key, label in labels.items():
        if key < deck.key_count():
            deck.set_key_image(key, _label_image(deck, label))

    loop = asyncio.get_running_loop()

    def on_key_change(_deck, key: int, state: bool) -> None:
        if not state:
            return
        action = KEY_ACTIONS.get(key)
        if action:
            loop.call_soon_threadsafe(
                lambda: asyncio.create_task(dispatch(action))
            )

    deck.set_key_callback(on_key_change)

    # The proxy is authoritative: polling also catches Qobuz-app and FLIRC changes.
    # Only redraw changed labels to avoid unnecessary USB traffic.
    rendered = dict(labels)

    def show(key: int, label: str) -> None:
        if key >= deck.key_count() or rendered.get(key) == label:
            return
        deck.set_key_image(key, _label_image(deck, label))
        rendered[key] = label

    async def refresh_feedback() -> None:
        while True:
            try:
                status = await get_status()
                playback = status.get("status", "disconnected")
                now_playing = status.get("now_playing") or {}
                show(1, "PAUSE" if playback == "playing" else "PLAY")
                show(5, "PLAYING" if playback == "playing" else playback.upper())
                show(6, str(now_playing.get("title") or "")[:16])
                show(7, str(now_playing.get("artist") or "")[:16])
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Could not refresh Stream Deck playback status", exc_info=True)
                show(5, "OFFLINE")
                show(1, "PLAY")
            await asyncio.sleep(1.0)

    feedback_task = asyncio.create_task(refresh_feedback())
    try:
        await asyncio.Event().wait()
    finally:
        feedback_task.cancel()
        await asyncio.gather(feedback_task, return_exceptions=True)
        deck.reset()
        deck.close()
