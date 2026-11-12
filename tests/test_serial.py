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


@pytest.mark.parametrize("max_rate,delta,gap", [(30, 40, 1 / 30), (60, 40, 1 / 60), (60, 10, 1 / 30)])
def test_adaptive_speed_and_no_catchup_burst(monkeypatch, max_rate, delta, gap):
    board = Mock()
    board.write.return_value = 1
    now = [0.]
    monkeypatch.setattr(protocol.time, "monotonic", lambda: now[0])
    mouse = protocol.Esp32Mouse(board, flush=False, max_rate=max_rate)
    assert mouse.move_relative(delta, 0)
    now[0] = gap - .0001
    assert not mouse.move_relative(delta, 0)
    now[0] = gap + .0001
    assert mouse.move_relative(-delta, 0)
    assert board.write.call_args.args == (b'a',)
    now[0] = 10
    assert mouse.move_relative(delta, 0)
    assert not mouse.move_relative(delta, 0)
    assert board.write.call_count == 3


class XYBoard:
    def __init__(self):
        self.buffer = bytearray()
        self.frames = []
        self.connected = True
        self.respond = True

    @property
    def in_waiting(self):
        return len(self.buffer)

    def read(self, count):
        data = bytes(self.buffer[:count])
        del self.buffer[:count]
        return data

    def write(self, packet):
        fields = protocol.decode_frame(packet)
        self.frames.append(fields)
        if self.respond:
            if fields[0] == "H":
                response = f"R 1 {fields[1]} 1000 {int(self.connected)}"
            else:
                response = f"A {fields[1]} {fields[2]} 1005 {int(self.connected)} OK"
            self.buffer.extend(protocol.encode_frame(response))
        return len(packet)

    def reset_output_buffer(self):
        pass


def test_xy_negotiation_small_diagonal_and_ack(monkeypatch):
    board = XYBoard()
    mouse = protocol.Esp32Mouse(board, flush=False)
    assert mouse.negotiate() == "xy1"
    assert mouse.ble_connected
    assert mouse.move_relative(1, -2)
    assert board.frames[-1][0] == "M"
    assert board.frames[-1][-2:] == ["1", "-2"]
    mouse.poll()
    assert mouse.pending is None
    assert mouse.last_status == "OK"
    mouse.next_move_at = 0
    assert mouse.move_relative(200, -200)
    assert board.frames[-1][-2:] == ["127", "-127"]


def test_xy_inflight_timeout_does_not_replay(monkeypatch):
    board = XYBoard()
    mouse = protocol.Esp32Mouse(board, flush=False)
    mouse.negotiate()
    board.respond = False
    assert mouse.move_relative(20, -5)
    count = len(board.frames)
    assert not mouse.move_relative(30, -10)
    assert len(board.frames) == count
    monkeypatch.setattr(protocol.time, "monotonic", lambda: mouse.pending[1] + .3)
    with pytest.raises(serial.SerialTimeoutException, match="回执超时"):
        mouse.poll()
    assert len(board.frames) == count


def test_xy_cancel_ignores_old_response_and_reports_disconnect():
    board = XYBoard()
    mouse = protocol.Esp32Mouse(board, flush=False)
    mouse.negotiate()
    mouse.move_relative(10, 10)
    mouse.cancel()
    assert board.frames[-1][0] == "S"
    mouse.poll()
    assert mouse.pending is None
    board.connected = False
    mouse.cancel()
    mouse.poll()
    assert mouse.ble_connected is False
    with pytest.raises(serial.SerialException, match="蓝牙未连接"):
        mouse.move_relative(10, 10)


def test_protocol_crc_rejects_corruption_and_partial_frames():
    packet = protocol.encode_frame("M 1 2 1080 25 -8")
    assert protocol.decode_frame(packet) == ["M", "1", "2", "1080", "25", "-8"]
    assert protocol.decode_frame(packet.replace(b"25", b"26")) is None
    assert protocol.decode_frame(packet[:-4]) is None
    assert protocol.decode_frame(b"boot log") is None
