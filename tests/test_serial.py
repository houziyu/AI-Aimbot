from unittest.mock import Mock
import pytest
import serial
import esp32_ble_mouse as protocol


def test_legacy_direction_and_rate_limit(monkeypatch):
    board = Mock()
    board.write.return_value = 1
    now = [0.]
    monkeypatch.setattr(protocol.time, "monotonic", lambda: now[0])
    mouse = protocol.Esp32Mouse(board, flush=False)
    assert not mouse.move_relative(4, 4)
    assert mouse.move_relative(30, -20)
    assert board.write.call_args.args == (b'd',)
    assert not mouse.move_relative(-30, 10)
    now[0] = .04
    assert mouse.move_relative(10, -40)
    assert board.write.call_args.args == (b'w',)
    board.flush.assert_not_called()


def test_short_write_fails():
    board = Mock()
    board.write.return_value = 0
    with pytest.raises(serial.SerialTimeoutException):
        protocol.move(board, "right")
