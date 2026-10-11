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
spectrum_delay_ms = 250
"""
    )
    config = load_config(path)
    assert config.proxy.base_url == "http://pi:8689"
    assert config.proxy.speaker_id == "living-room"
    assert config.flirc.mappings == {"KEY_F20": "toggle", "KEY_F21": "next"}
    assert config.streamdeck.enabled is False
    assert config.streamdeck.brightness == 42
    assert config.streamdeck.spectrum_delay_ms == 250


def test_spectrum_delay_defaults_and_validation(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text("[streamdeck]\n")
    assert load_config(path).streamdeck.spectrum_delay_ms == 150
    path.write_text("[streamdeck]\nspectrum_delay_ms = -1\n")
    import pytest
    with pytest.raises(ValueError, match="spectrum_delay_ms"):
        load_config(path)
