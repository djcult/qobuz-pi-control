"""FLIRC adapter.

FLIRC presents as a Linux input keyboard. We listen only for configured key
codes and dispatch semantic actions on key-down.
"""

from __future__ import annotations

import asyncio
import logging

from evdev import InputDevice, categorize, ecodes, list_devices

from .config import FlircConfig

logger = logging.getLogger(__name__)


def _find_device(config: FlircConfig) -> InputDevice:
    if config.device != "auto":
        return InputDevice(config.device)

    devices = [InputDevice(path) for path in list_devices()]
    for device in devices:
        name = device.name.lower()
        if "flirc" in name:
            return device
    raise RuntimeError("No FLIRC input device found")


async def run_flirc(config: FlircConfig, dispatch) -> None:
    device = _find_device(config)
    logger.info("FLIRC: %s (%s)", device.name, device.path)
    if config.grab:
        device.grab()

    try:
        async for event in device.async_read_loop():
            if event.type != ecodes.EV_KEY:
                continue
            key = categorize(event)
            if key.keystate != key.key_down:
                continue
            code = key.keycode
            if isinstance(code, list):
                code = code[0]
            action = config.mappings.get(code)
            if action:
                asyncio.create_task(dispatch(action))
    finally:
        if config.grab:
            device.ungrab()
        device.close()
