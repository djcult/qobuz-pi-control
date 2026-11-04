from unittest.mock import AsyncMock

import pytest

from qobuz_pi_control.litra import Litra


@pytest.mark.parametrize('current,increase,expected,commands', [
    (200, True, 220, [('brightness', '--device-type', 'beam', '--value', '220'), ('on', '--device-type', 'beam')]),
    (200, False, 180, [('brightness', '--device-type', 'beam', '--value', '180'), ('on', '--device-type', 'beam')]),
    (390, True, 400, [('brightness', '--device-type', 'beam', '--value', '400'), ('on', '--device-type', 'beam')]),
    (30, False, 0, [('off', '--device-type', 'beam')]),
    (0, False, 0, []),
    (0, True, 30, [('brightness', '--device-type', 'beam', '--value', '30'), ('on', '--device-type', 'beam')]),
    (None, True, 30, [('brightness', '--device-type', 'beam', '--value', '30'), ('on', '--device-type', 'beam')]),
    (None, False, 0, [('off', '--device-type', 'beam')]),
])
async def test_adjust(current, increase, expected, commands):
    light = Litra()
    light.brightness = current
    light._run = AsyncMock(return_value=b'')
    await light.adjust(increase)
    assert [call.args for call in light._run.call_args_list] == commands
    assert light.brightness == expected


async def test_failed_write_does_not_advance_level():
    light = Litra()
    light.brightness = 200
    light._run = AsyncMock(side_effect=RuntimeError('USB error'))
    with pytest.raises(RuntimeError, match='USB error'):
        await light.adjust(True)
    assert light.brightness == 200
