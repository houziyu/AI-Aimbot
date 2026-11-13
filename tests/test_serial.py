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
        self.input = bytearray()
        self.move_status = "OK"

    @property
    def in_waiting(self):
        return len(self.buffer)

    def read(self, count):
        data = bytes(self.buffer[:count])
        del self.buffer[:count]
        return data

    def write(self, packet):
        self.input.extend(packet)
        lines = self.input.split(b"\n")
        self.input = bytearray(lines.pop())
        for line in lines:
            fields = protocol.decode_frame(line)
            if fields is None:
                continue
            self.frames.append(fields)
            if not self.respond:
                continue
            if fields[0] == "H":
                response = f"R 1 {fields[1]} 1000 {int(self.connected)}"
            else:
                status = self.move_status if fields[0] == "M" else "STATUS"
                response = f"A {fields[1]} {fields[2]} 1005 {int(self.connected)} {status}"
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
    assert mouse.ack_kind == "M" and mouse.ack_count == 1
    assert mouse.ack_ms >= 0
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


def test_xy_late_ack_already_buffered_is_rejected(monkeypatch):
    board = XYBoard()
    mouse = protocol.Esp32Mouse(board, flush=False)
    mouse.negotiate()
    assert mouse.move_relative(10, 0)
    assert board.in_waiting
    monkeypatch.setattr(protocol.time, "monotonic", lambda: mouse.pending[1] + mouse.ACK_TIMEOUT)
    with pytest.raises(serial.SerialTimeoutException, match="回执超时"):
        mouse.poll()
    assert mouse.ack_count == 0


@pytest.mark.parametrize(("board_clock", "expiry", "expected"), [
    (1000, 10.100, 1099),
    (1000, 10.600, 1174),
    (0xffffffc0, 10.100, 35),
])
def test_xy_deadline_uses_remaining_frame_age_and_wraps(monkeypatch, board_clock, expiry, expected):
    now = [10.]
    monkeypatch.setattr(protocol.time, "monotonic", lambda: now[0])
    board = XYBoard()
    mouse = protocol.Esp32Mouse(board, flush=False)
    assert mouse.negotiate() == "xy1"
    mouse.board_clock = board_clock
    now[0] = 10.095
    assert mouse.move_relative(1, -2, expires_at=expiry)
    deadline = int(board.frames[-1][3])
    assert deadline in (expected, expected + 1)  # Rounding down preserves the age limit.


@pytest.mark.parametrize("mode", ["xy1", "legacy"])
def test_send_rechecks_expiry_and_stop_after_preflight(monkeypatch, mode):
    now = [10.]
    monkeypatch.setattr(protocol.time, "monotonic", lambda: now[0])
    board = XYBoard() if mode == "xy1" else Mock()
    mouse = protocol.Esp32Mouse(board, flush=False)
    if mode == "xy1":
        mouse.negotiate()
        board.frames.clear()

    def delayed_preflight():
        now[0] = 10.1
        return True

    assert not mouse.move_relative(15, 0, expires_at=10.1, can_send=delayed_preflight)
    assert not mouse.move_relative(15, 0, can_send=lambda: False)
    if mode == "xy1":
        assert board.frames == []
    else:
        board.write.assert_not_called()


def test_xy_cancel_invalidates_partial_frame_before_stop():
    board = XYBoard()
    mouse = protocol.Esp32Mouse(board, flush=False)
    mouse.negotiate()
    # A purged write may have already transmitted everything but its newline.
    board.input.extend(protocol.encode_frame(f"M {mouse.token} 1 1080 10 10")[:-1])
    mouse.cancel()
    assert [fields[0] for fields in board.frames] == ["H", "S"]
    mouse.poll()
    assert mouse.pending is None and mouse.last_status == "STATUS"


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
