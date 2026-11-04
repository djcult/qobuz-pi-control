import json
from unittest.mock import AsyncMock

import pytest

from qobuz_pi_control.litra import Litra


@pytest.mark.parametrize('on,current,increase,commands', [
    (True, 200, True, [('brightness', '--device-path', 'beam1', '--value', '220')]),
    (True, 200, False, [('brightness', '--device-path', 'beam1', '--value', '180')]),
    (True, 390, True, [('brightness', '--device-path', 'beam1', '--value', '400')]),
    (True, 30, False, [('off', '--device-path', 'beam1')]),
    (False, 200, False, []),
    (False, 200, True, [('brightness', '--device-path', 'beam1', '--value', '30'), ('on', '--device-path', 'beam1')]),
])
async def test_adjust(on, current, increase, commands):
    light = Litra()
    device = dict(device_type='beam', device_path='beam1', is_on=on,
                  brightness_in_lumen=current, minimum_brightness_in_lumen=30,
                  maximum_brightness_in_lumen=400)
    light._run = AsyncMock(side_effect=[json.dumps([device]).encode()] + [b''] * len(commands))
    await light.adjust(increase)
    assert [call.args for call in light._run.call_args_list] == [('devices', '--json'), *commands]


async def test_no_accessible_beam():
    light = Litra()
    light._run = AsyncMock(return_value=b'[]')
    with pytest.raises(RuntimeError, match='No accessible'):
        await light.adjust(True)
