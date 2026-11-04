from PIL import Image
from qobuz_pi_control.recents import RecentAlbums, render_recents


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
