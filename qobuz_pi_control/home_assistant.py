"""Office light brightness via Home Assistant's REST service API."""

import asyncio
import os

import aiohttp


class HomeAssistantLight:
    def __init__(self, config):
        self.config = config
        self.http = None
        self.lock = asyncio.Lock()

    async def __aenter__(self):
        if self.config.enabled:
            token = self.config.token or os.environ.get("HA_TOKEN", "")
            if not token.strip():
                raise ValueError("Set home_assistant.token in config.toml or HA_TOKEN")
            self.http = aiohttp.ClientSession(
                headers={"Authorization": f"Bearer {token.strip()}"},
                timeout=aiohttp.ClientTimeout(total=3),
            )
        return self

    async def __aexit__(self, *_):
        if self.http is not None:
            await self.http.close()

    async def adjust(self, increase):
        if self.http is None:
            raise RuntimeError("Home Assistant light control is disabled")
        # HA applies a relative step to its current light state, so wall-switch
        # and dashboard changes do not leave the controller's brightness stale.
        async with self.lock:
            async with self.http.post(
                f"{self.config.base_url.rstrip('/')}/api/services/light/turn_on",
                json={"entity_id": self.config.entity_id,
                      "brightness_step_pct": self.config.step_pct * (1 if increase else -1),
                      "transition": 0},
            ) as response:
                response.raise_for_status()
                await response.read()
