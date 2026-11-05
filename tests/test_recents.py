import asyncio
import json

import pytest
from PIL import Image
from qobuz_pi_control.recents import AlbumKeyPresses, RecentAlbums, render_recents


def playing(album_id, title="Album"):
    return {
        "status": "playing",
        "now_playing": {
            "album_id": album_id,
            "album": title,
            "album_art_url": "https://example.com/a.jpg",
        },
    }


def test_history_deduplicates_and_survives_restart(tmp_path):
    path = tmp_path / "state" / "recents.json"
    history = RecentAlbums(path, limit=2)
    assert history.observe(playing("a"))
    assert not history.observe(playing("a"))
    assert history.observe(playing("b"))
    assert history.observe(playing("a"))
    assert [x["album_id"] for x in RecentAlbums(path).items] == ["a", "b"]
    history.observe(playing("c"))
    assert [x["album_id"] for x in history.items] == ["c", "a"]


def test_history_requires_active_playback_and_album_id(tmp_path):
    history = RecentAlbums(tmp_path / "r.json")
    assert not history.observe({"status": "paused", "now_playing": {"album_id": "a"}})
    assert not history.observe({"status": "playing", "now_playing": {"album": "No ID"}})
    assert not history.items


def test_bad_history_does_not_prevent_startup(tmp_path):
    path = tmp_path / "r.json"
    path.write_text("broken JSON")
    history = RecentAlbums(path)
    assert history.items == []
    history.observe(playing("a"))
    assert RecentAlbums(path).items[0]["album_id"] == "a"


def test_renderer_reserves_navigation_and_handles_missing_artwork():
    items = [
        {"album_id": str(i), "album": "An album with a long title"} for i in range(14)
    ]
    tiles = render_recents((72, 72), items, {}, {4: "display"})
    assert len(tiles) == 15
    assert all(tile.size == (72, 72) for tile in tiles)
    assert tiles[4].tobytes() != tiles[0].tobytes()
    empty = render_recents((72, 72), [], {}, {4: "display"})
    assert empty[4].tobytes() != Image.new("RGB", (72, 72), (12, 17, 23)).tobytes()


def test_pins_stay_visible_through_rotation_and_restart(tmp_path):
    path = tmp_path / "r.json"
    history = RecentAlbums(path)
    for album in ("a", "b", "c"):
        history.observe(playing(album))
    history.toggle_pin("a")
    history.toggle_pin("c")
    for i in range(60):
        history.observe(playing(str(i)))
    restored = RecentAlbums(path)
    assert [item["album_id"] for item in restored.items[:3]] == ["a", "c", "59"]
    assert all(item["pinned"] for item in restored.items[:2])
    assert len(restored.items) == 50
    restored.observe(playing("a", "Updated title"))
    assert restored.items[0]["album"] == "Updated title"
    assert restored.items[0]["pinned"]
    assert [item["album_id"] for item in restored.items[:2]] == ["a", "c"]


def test_unpin_returns_album_to_rotating_history(tmp_path):
    path = tmp_path / "r.json"
    history = RecentAlbums(path, limit=2)
    history.observe(playing("a"))
    history.toggle_pin("a")
    for album in ("b", "c"):
        history.observe(playing(album))
    history.toggle_pin("a")
    assert [item["album_id"] for item in history.items] == ["a", "c"]
    assert not RecentAlbums(path).items[0]["pinned"]
    for album in ("d", "e"):
        history.observe(playing(album))
    assert [item["album_id"] for item in history.items] == ["e", "d"]


def test_legacy_history_and_pin_protection_when_limit_changes(tmp_path):
    path = tmp_path / "r.json"
    path.write_text(json.dumps([{"album_id": "a"}, {"album_id": "b"}]))
    history = RecentAlbums(path, limit=2)
    assert not any(item["pinned"] for item in history.items)
    history.toggle_pin("a")
    history.toggle_pin("b")
    history.observe(playing("c"))
    assert [item["album_id"] for item in history.items] == ["a", "b"]
    assert [item["album_id"] for item in RecentAlbums(path, limit=1).items] == ["a", "b"]
    history.toggle_pin("missing")
    assert len(history.items) == 2


def test_pinned_cover_has_visible_badge_without_changing_navigation():
    item = {"album_id": "a", "album": "Album"}
    normal = render_recents((72, 72), [item], {}, {4: "display"})
    pinned = render_recents((72, 72), [item | {"pinned": True}], {}, {4: "display"})
    assert normal[0].crop((49, 2, 71, 25)).tobytes() != pinned[0].crop((49, 2, 71, 25)).tobytes()
    assert normal[0].crop((0, 43, 72, 72)).tobytes() == pinned[0].crop((0, 43, 72, 72)).tobytes()
    assert normal[4].tobytes() == pinned[4].tobytes()


@pytest.mark.asyncio
async def test_album_tap_plays_captured_album_only_on_release():
    taps, holds = [], []
    presses = AlbumKeyPresses(asyncio.get_running_loop(), taps.append, holds.append)
    presses.press(0, "a")
    assert taps == []
    # History can rotate while pressed: repeated down must not replace the album.
    presses.press(0, "b")
    presses.release(0)
    presses.release(0)
    assert taps == ["a"]
    assert holds == []
    assert presses.pending == {}


@pytest.mark.asyncio
async def test_album_hold_pins_once_and_never_launches_on_release():
    taps, holds = [], []
    presses = AlbumKeyPresses(asyncio.get_running_loop(), taps.append, holds.append, 0.01)
    presses.press(0, "a")
    await asyncio.sleep(0.03)
    assert holds == ["a"]
    assert taps == []
    presses.press(0, "b")
    await asyncio.sleep(0.03)
    presses.release(0)
    assert holds == ["a"]
    assert taps == []


@pytest.mark.asyncio
async def test_page_change_or_shutdown_cancels_pending_album_presses():
    taps, holds = [], []
    presses = AlbumKeyPresses(asyncio.get_running_loop(), taps.append, holds.append, 0.01)
    presses.press(0, "a")
    presses.press(1, "b")
    presses.cancel()
    await asyncio.sleep(0.03)
    presses.release(0)
    presses.release(1)
    assert holds == taps == []
    assert presses.pending == {}
