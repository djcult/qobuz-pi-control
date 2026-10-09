"""Small HTTP client for qobuz-proxy's semantic control API."""

from __future__ import annotations

from dataclasses import dataclass

import aiohttp

ACTIONS = frozenset({"play", "pause", "toggle", "next", "previous"})


@dataclass(slots=True)
class ControlResult:
    action: str
    accepted: bool
    speaker: dict


class QobuzProxyClient:
    def __init__(
        self,
        base_url: str,
        speaker_id: str,
        timeout_seconds: float = 2.0,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.speaker_id = speaker_id
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._session = session
        self._owns_session = session is None

    async def __aenter__(self) -> "QobuzProxyClient":
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=self.timeout)
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    async def action(self, action: str) -> ControlResult:
        if action not in ACTIONS:
            raise ValueError(f"Unsupported action: {action}")
        if self._session is None:
            raise RuntimeError("Client must be used as an async context manager")

        url = f"{self.base_url}/api/speakers/{self.speaker_id}/actions/{action}"
        async with self._session.post(url) as response:
            data = await response.json()
            if response.status not in (200, 202, 409):
                raise RuntimeError(
                    f"qobuz-proxy returned HTTP {response.status}: {data.get('error', data)}"
                )
            return ControlResult(
                action=action,
                accepted=bool(data.get("accepted", False)),
                speaker=data.get("speaker", {}),
            )

    async def status(self) -> dict:
        if self._session is None:
            raise RuntimeError("Client must be used as an async context manager")
        url = f"{self.base_url}/api/speakers"
        async with self._session.get(url) as response:
            response.raise_for_status()
            speakers = await response.json()
        return next(
            (speaker for speaker in speakers if speaker.get("id") == self.speaker_id),
            {},
        )
