from pathlib import Path

from qobuz_pi_control.config import load_config


def test_load_config(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        """
[qobuz_proxy]
base_url = "http://pi:8689"
speaker_id = "living-room"

[flirc]
enabled = true
play_pause = "KEY_F20"
next = "KEY_F21"

[streamdeck]
enabled = false
brightness = 42
"""
    )
    config = load_config(path)
    assert config.proxy.base_url == "http://pi:8689"
    assert config.proxy.speaker_id == "living-room"
    assert config.flirc.mappings == {"KEY_F20": "toggle", "KEY_F21": "next"}
    assert config.streamdeck.enabled is False
    assert config.streamdeck.brightness == 42
