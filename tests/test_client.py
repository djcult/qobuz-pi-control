from unittest.mock import AsyncMock

import pytest

from qobuz_pi_control.client import QobuzProxyClient


class FakeResponse:
    def __init__(self, status, data):
        self.status = status
        self._data = data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        pass

    async def json(self):
        return self._data


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.post = lambda _url: self.response


@pytest.mark.asyncio
async def test_action_returns_semantic_result():
    session = FakeSession(
        FakeResponse(
            200,
            {
                "accepted": True,
                "speaker": {"id": "cdq2", "status": "playing"},
            },
        )
    )
    client = QobuzProxyClient("http://pi:8689", "cdq2", session=session)
    async with client:
        result = await client.action("toggle")
    assert result.accepted is True
    assert result.speaker["status"] == "playing"


@pytest.mark.asyncio
async def test_unknown_action_rejected_locally():
    client = QobuzProxyClient("http://pi:8689", "cdq2", session=AsyncMock())
    async with client:
        with pytest.raises(ValueError):
            await client.action("explode")


@pytest.mark.asyncio
@pytest.mark.parametrize('status,data,accepted', [
    (200, {'accepted': True}, True),
    (409, {'error': 'select this speaker in Qobuz first'}, False),
    (502, {'error': 'Qobuz did not acknowledge album launch'}, False),
])
async def test_album_launch_checks_server_result(status, data, accepted):
    from unittest.mock import Mock
    session = Mock()
    session.post.return_value = FakeResponse(status, data)
    async with QobuzProxyClient('http://pi:8689', 'cdq2', session=session) as client:
        if accepted:
            await client.play_album('abc123')
        else:
            with pytest.raises(RuntimeError, match=data['error']):
                await client.play_album('abc123')
    assert session.post.call_args.args[0] == 'http://pi:8689/api/speakers/cdq2/albums/abc123/play'
