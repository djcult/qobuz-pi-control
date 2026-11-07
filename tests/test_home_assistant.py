import asyncio
from unittest.mock import AsyncMock

import aiohttp
from aiohttp import web
import pytest

from qobuz_pi_control.config import HomeAssistantConfig, load_config
from qobuz_pi_control.home_assistant import HomeAssistantLight
from qobuz_pi_control.light_presses import LightKeyPresses


@pytest.mark.asyncio
async def test_tap_hold_release_and_cancel():
    dispatch = AsyncMock()
    presses = LightKeyPresses(dispatch, hold_seconds=0.02, repeat_seconds=0.01)
    try:
        presses.press(13, "light_down")
        presses.release(13)
        await asyncio.sleep(0)
        dispatch.assert_awaited_once_with("light_down")
        dispatch.reset_mock()
        presses.press(14, "light_up")
        presses.press(14, "light_up")  # Duplicate USB state must not start a second loop.
        await asyncio.sleep(0.055)
        presses.release(14)
        count = dispatch.await_count
        assert count >= 2
        assert all(call.args == ("office_light_up",) for call in dispatch.await_args_list)
        await asyncio.sleep(0.03)
        assert dispatch.await_count == count
        dispatch.reset_mock()
        presses.press(13, "light_down")
        presses.cancel()  # Page switch must not produce a tap or later hold.
        presses.release(13)
        await asyncio.sleep(0.03)
        dispatch.assert_not_awaited()
    finally:
        await presses.close()


@pytest.mark.asyncio
async def test_slow_request_cancelled_on_release_without_queueing():
    started = asyncio.Event()
    stopped = asyncio.Event()
    calls = []

    async def dispatch(action):
        calls.append(action)
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    presses = LightKeyPresses(dispatch, hold_seconds=0.01, repeat_seconds=0.01)
    try:
        presses.press(13, "light_down")
        await asyncio.wait_for(started.wait(), 1)
        presses.release(13)
        await asyncio.wait_for(stopped.wait(), 1)
        assert calls == ["office_light_down"]
    finally:
        await presses.close()


@pytest.mark.asyncio
async def test_rest_auth_payload_error_and_session_cleanup():
    calls = []

    async def service(request):
        calls.append((request.headers.get("Authorization"), await request.json()))
        return web.json_response([], status=401 if len(calls) == 3 else 200)

    app = web.Application()
    app.router.add_post("/api/services/light/turn_on", service)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    config = HomeAssistantConfig(enabled=True, base_url=f"http://127.0.0.1:{port}/", token="secret")
    try:
        async with HomeAssistantLight(config) as light:
            session = light.http
            await light.adjust(True)
            await light.adjust(False)
            with pytest.raises(aiohttp.ClientResponseError):
                await light.adjust(True)
        assert session.closed
        assert calls[0] == ("Bearer secret", {"entity_id": config.entity_id,
                          "brightness_step_pct": 5, "transition": 0})
        assert calls[1][1]["brightness_step_pct"] == -5
        assert "secret" not in repr(config)
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_missing_token_and_environment_fallback(monkeypatch):
    monkeypatch.delenv("HA_TOKEN", raising=False)
    with pytest.raises(ValueError, match="token"):
        async with HomeAssistantLight(HomeAssistantConfig(enabled=True)):
            pass
    monkeypatch.setenv("HA_TOKEN", "environment-token")
    async with HomeAssistantLight(HomeAssistantConfig(enabled=True)) as light:
        assert light.http.headers["Authorization"] == "Bearer environment-token"
    async with HomeAssistantLight(HomeAssistantConfig()) as light:
        assert light.http is None


def test_home_assistant_config_defaults_and_validation(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("")
    assert not load_config(path).home_assistant.enabled
    path.write_text('[home_assistant]\nenabled = true\ntoken = "local-token"\n')
    assert load_config(path).home_assistant.entity_id == "light.shellydimmer2_a4e57cba3bdd"
    for setting in ("hold_seconds = nan", "repeat_seconds = 0", "step_pct = 0", "step_pct = true"):
        path.write_text("[home_assistant]\n" + setting)
        with pytest.raises(ValueError, match="home_assistant"):
            load_config(path)
