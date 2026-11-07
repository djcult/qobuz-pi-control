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
    spectrum_fps: float = 15.0
    spectrum_delay_ms: float = 150.0
    spectrum_gain: float = 1.4
    spectrum_palette: str = "classic"
    spectrum_bands: int = 64
    album_hold_seconds: float = 0.7
    buttons: dict[int, str] = field(default_factory=lambda: {0: "previous", 1: "toggle", 2: "next", 4: "display", 10: "volume_down", 11: "volume_up", 13: "light_down", 14: "light_up"})


@dataclass(slots=True)
class IRConfig:
    enabled: bool = False
    device: str = "/dev/lirc0"
    rc_device: str = "rc2"
    receive: dict[int, str] = field(default_factory=lambda: {0x1635: "toggle", 0x1621: "previous", 0x1620: "next"})
    transmit: dict[str, int] = field(default_factory=lambda: {"volume_down": 0x1611, "volume_up": 0x1610})


@dataclass(slots=True)
class HomeAssistantConfig:
    enabled: bool = False
    base_url: str = "http://homeassistant.local:8123"
    entity_id: str = "light.shellydimmer2_a4e57cba3bdd"
    token: str = field(default="", repr=False)
    hold_seconds: float = 0.7
    repeat_seconds: float = 0.3
    step_pct: int = 5


@dataclass(slots=True)
class Config:
    proxy: ProxyConfig
    flirc: FlircConfig
    streamdeck: StreamDeckConfig
    ir: IRConfig = field(default_factory=IRConfig)
    home_assistant: HomeAssistantConfig = field(default_factory=HomeAssistantConfig)


def load_config(path: str | Path) -> Config:
    with Path(path).open("rb") as fh:
        raw = tomllib.load(fh)

    proxy_raw = raw.get("qobuz_proxy", {})
    flirc_raw = raw.get("flirc", {})
    deck_raw = raw.get("streamdeck", {})
    ir_raw = raw.get("ir", {})

    ha = HomeAssistantConfig(**raw.get("home_assistant", {}))
    if not 0.3 <= ha.hold_seconds <= 5:
        raise ValueError("home_assistant.hold_seconds must be between 0.3 and 5")
    if not 0.1 <= ha.repeat_seconds <= 5:
        raise ValueError("home_assistant.repeat_seconds must be between 0.1 and 5")
    if type(ha.step_pct) is not int or not 1 <= ha.step_pct <= 100:
        raise ValueError("home_assistant.step_pct must be an integer between 1 and 100")
    if ha.enabled and (not ha.entity_id.startswith("light.") or not ha.base_url.startswith(("http://", "https://"))):
        raise ValueError("home_assistant requires an HTTP(S) base_url and light entity_id")

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

    spectrum_fps = float(deck_raw.get("spectrum_fps", 15.0))
    if not 1 <= spectrum_fps <= 60:
        raise ValueError("streamdeck.spectrum_fps must be between 1 and 60")

    spectrum_delay_ms = float(deck_raw.get("spectrum_delay_ms", 150.0))
    if not 0 <= spectrum_delay_ms <= 2000:
        raise ValueError("streamdeck.spectrum_delay_ms must be between 0 and 2000")

    spectrum_gain = float(deck_raw.get("spectrum_gain", 1.4))
    if not 0.1 <= spectrum_gain <= 4.0:
        raise ValueError("streamdeck.spectrum_gain must be between 0.1 and 4.0")

    spectrum_bands = deck_raw.get("spectrum_bands", 64)
    if type(spectrum_bands) is not int or not 1 <= spectrum_bands <= 256:
        raise ValueError("streamdeck.spectrum_bands must be an integer between 1 and 256")

    spectrum_palette = deck_raw.get("spectrum_palette", "classic")
    if spectrum_palette not in ("classic", "retro_orange", "retro_green"):
        raise ValueError("streamdeck.spectrum_palette must be classic, retro_orange or retro_green")

    album_hold_seconds = float(deck_raw.get("album_hold_seconds", 0.7))
    if not 0.3 <= album_hold_seconds <= 5.0:
        raise ValueError("streamdeck.album_hold_seconds must be between 0.3 and 5.0")

    actions = {"play", "pause", "toggle", "next", "previous", "volume_down", "volume_up"}
    buttons = {int(k): v for k, v in deck_raw.get("buttons", StreamDeckConfig().buttons).items()}
    if any(not 0 <= k < 15 or v not in actions | {"display", "light_down", "light_up"} for k, v in buttons.items()):
        raise ValueError("streamdeck.buttons requires keys 0–14 and supported actions")
    receive = {int(k, 0) if isinstance(k, str) else k: v
               for k, v in ir_raw.get("receive", IRConfig().receive).items()}
    transmit = dict(ir_raw.get("transmit", IRConfig().transmit))
    if any(not 0 <= k <= 0x1f7f or v not in actions - {"volume_down", "volume_up"} for k, v in receive.items()):
        raise ValueError("ir.receive requires RC-5 codes and playback actions")
    if set(transmit) != {"volume_down", "volume_up"} or any(type(v) is not int or not 0 <= v <= 0x1f7f for v in transmit.values()):
        raise ValueError("ir.transmit requires volume_down and volume_up RC-5 codes")
    ir_raw = {**ir_raw, "receive": receive, "transmit": transmit}

    return Config(
        home_assistant=ha,
        ir=IRConfig(**ir_raw),
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
            spectrum_fps=spectrum_fps,
            spectrum_delay_ms=spectrum_delay_ms,
            spectrum_gain=spectrum_gain,
            spectrum_bands=spectrum_bands,
            spectrum_palette=spectrum_palette,
            album_hold_seconds=album_hold_seconds,
            buttons=buttons,
        ),
    )

