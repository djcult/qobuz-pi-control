"""TOML configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import tomllib


@dataclass(slots=True)
class ProxyConfig:
    base_url: str = "http://127.0.0.1:8689"
    speaker_id: str = "cdq2"
    timeout_seconds: float = 2.0


@dataclass(slots=True)
class FlircConfig:
    enabled: bool = True
    device: str = "auto"
    grab: bool = False
    mappings: dict[str, str] = field(default_factory=lambda: {
        "KEY_F13": "toggle",
        "KEY_F14": "next",
        "KEY_F15": "previous",
        "KEY_F16": "play",
        "KEY_F17": "pause",
    })


@dataclass(slots=True)
class StreamDeckConfig:
    enabled: bool = True
    device: str = "auto"
    brightness: int = 35


@dataclass(slots=True)
class Config:
    proxy: ProxyConfig
    flirc: FlircConfig
    streamdeck: StreamDeckConfig


def load_config(path: str | Path) -> Config:
    with Path(path).open("rb") as fh:
        raw = tomllib.load(fh)

    proxy_raw = raw.get("qobuz_proxy", {})
    flirc_raw = raw.get("flirc", {})
    deck_raw = raw.get("streamdeck", {})

    reserved = {"enabled", "device", "grab"}
    mappings = {
        value: {
            "play_pause": "toggle",
            "next": "next",
            "previous": "previous",
            "play": "play",
            "pause": "pause",
        }[name]
        for name, value in flirc_raw.items()
        if name not in reserved and name in {"play_pause", "next", "previous", "play", "pause"}
    }

    return Config(
        proxy=ProxyConfig(
            base_url=proxy_raw.get("base_url", "http://127.0.0.1:8689"),
            speaker_id=proxy_raw.get("speaker_id", "cdq2"),
            timeout_seconds=float(proxy_raw.get("timeout_seconds", 2.0)),
        ),
        flirc=FlircConfig(
            enabled=bool(flirc_raw.get("enabled", True)),
            device=flirc_raw.get("device", "auto"),
            grab=bool(flirc_raw.get("grab", False)),
            mappings=mappings or FlircConfig().mappings,
        ),
        streamdeck=StreamDeckConfig(
            enabled=bool(deck_raw.get("enabled", True)),
            device=deck_raw.get("device", "auto"),
            brightness=int(deck_raw.get("brightness", 35)),
        ),
    )
