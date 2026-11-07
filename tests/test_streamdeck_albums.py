"""Exercise USB callbacks through the controller without Stream Deck hardware."""

import asyncio
import sys
from types import ModuleType
from unittest.mock import AsyncMock, Mock

import pytest

from qobuz_pi_control import recents, streamdeck
from qobuz_pi_control.config import HomeAssistantConfig, StreamDeckConfig


@pytest.mark.asyncio
async def test_album_page_callbacks_support_tap_hold_and_page_change(tmp_path, monkeypatch):
    history = recents.RecentAlbums(tmp_path / "r.json")
    history.observe({"status": "playing", "now_playing": {"album_id": "a", "album": "Album"}})
    monkeypatch.setattr(recents, "RecentAlbums", lambda: history)

    deck = Mock()
    deck.key_count.return_value = 15
    deck.key_image_format.return_value = {"size": (72, 72)}
    manager = ModuleType("StreamDeck.DeviceManager")
    manager.DeviceManager = lambda: Mock(enumerate=lambda: [deck])
    monkeypatch.setitem(sys.modules, "StreamDeck.DeviceManager", manager)
    monkeypatch.setattr(streamdeck, "_label_image", lambda *_: b"")
    monkeypatch.setattr(streamdeck, "_transport_image", lambda *_: b"")
    monkeypatch.setattr(streamdeck, "receive_spectrum", AsyncMock())

    loop = asyncio.get_running_loop()
    frame_shown = asyncio.Event()
    display = Mock()
    display.show.side_effect = lambda _: loop.call_soon_threadsafe(frame_shown.set)
    monkeypatch.setattr(streamdeck, "TileDisplay", lambda _: display)
    play_album, dispatch = AsyncMock(), AsyncMock()
    task = asyncio.create_task(streamdeck.run_streamdeck(
        StreamDeckConfig(album_hold_seconds=0.01), dispatch,
        AsyncMock(return_value={"status": "stopped"}), play_album=play_album,
        home_assistant=HomeAssistantConfig(enabled=True, hold_seconds=0.01, repeat_seconds=0.01),
    ))
    try:
        await asyncio.sleep(0)
        callback = deck.set_key_callback.call_args.args[0]
        callback(deck, 13, True)
        callback(deck, 13, False)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        dispatch.assert_awaited_once_with("light_down")
        dispatch.reset_mock()
        callback(deck, 14, True)
        await asyncio.sleep(0.035)
        callback(deck, 14, False)
        await asyncio.sleep(0)
        assert dispatch.await_count >= 1
        assert all(call.args == ("office_light_up",) for call in dispatch.await_args_list)
        count = dispatch.await_count
        await asyncio.sleep(0.02)
        assert dispatch.await_count == count
        dispatch.reset_mock()
        callback(deck, 13, True)
        for _ in range(4):
            callback(deck, 4, True)
            callback(deck, 4, False)
        await asyncio.wait_for(frame_shown.wait(), timeout=1)

        callback(deck, 0, True)
        await asyncio.sleep(0)
        play_album.assert_not_awaited()
        callback(deck, 0, False)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        play_album.assert_awaited_once_with("a")

        callback(deck, 0, True)
        await asyncio.sleep(0.03)
        assert history.items[0]["pinned"]
        callback(deck, 0, False)
        await asyncio.sleep(0)
        assert play_album.await_count == 1

        callback(deck, 0, True)
        await asyncio.sleep(0.03)
        assert not history.items[0]["pinned"]
        callback(deck, 0, False)
        await asyncio.sleep(0)
        assert play_album.await_count == 1

        callback(deck, 0, True)
        callback(deck, 4, True)
        await asyncio.sleep(0.03)
        callback(deck, 0, False)
        await asyncio.sleep(0)
        assert not history.items[0]["pinned"]
        assert play_album.await_count == 1
        dispatch.assert_not_awaited()
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    deck.close.assert_called_once()
