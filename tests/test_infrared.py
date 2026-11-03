from qobuz_pi_control.infrared import PressFilter, FRAME, RX_ACTIONS


def test_rc5_hold_and_new_press():
    presses = PressFilter()
    assert presses.accept(0x1635, True, 1)
    assert not presses.accept(0x1635, True, 1.112)
    assert not presses.accept(0x1635, True, 1.224)
    assert presses.accept(0x1635, False, 1.3)
    assert presses.accept(0x1620, False, 1.4)
    assert presses.accept(0x1620, False, 2)


def test_captured_frame():
    match = FRAME.search('189229.468034: lirc protocol(rc5): scancode = 0x1635 toggle=1')
    assert RX_ACTIONS[int(match[1], 16)] == 'toggle'
    assert 'toggle=1' in match[2]
