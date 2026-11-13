"""Serial adapter for XY1 firmware and the legacy Espressif mouse demo."""

import argparse
import binascii
import math
import secrets
import sys
import time

import serial


COMMANDS = {
    "up": b"w",
    "left": b"a",
    "down": b"s",
    "right": b"d",
}


class BleDisconnectedError(serial.SerialException):
    """Bluetooth is unavailable, but the serial session can stay open."""


class AckTimeoutError(serial.SerialTimeoutException):
    """A request was not acknowledged within the host timeout."""

    def __init__(self, kind):
        super().__init__("ESP32 回执超时，已停止发送")
        self.kind = kind


def encode_frame(body: str) -> bytes:
    data = body.encode("ascii")
    return data + f"*{binascii.crc_hqx(data, 0xffff):04X}\n".encode("ascii")


def decode_frame(line: bytes):
    try:
        data, checksum = line.strip().rsplit(b"*", 1)
        if len(checksum) != 4 or int(checksum, 16) != binascii.crc_hqx(data, 0xffff):
            return None
        return data.decode("ascii").split()
    except (ValueError, UnicodeError):
        return None


def open_board(port: str) -> serial.Serial:
    """Open the example's 115200-baud console with modem lines deasserted."""
    board = serial.Serial(baudrate=115200, timeout=1, write_timeout=1)
    board.port = port
    board.dtr = False
    board.rts = False
    board.open()
    return board


def move(board: serial.Serial, direction: str, *, flush: bool = True) -> None:
    """Send one direction byte. The official firmware chooses the distance."""
    command = COMMANDS.get(direction)
    if command is None:
        raise ValueError("Direction must be up, left, down, or right.")
    if board.write(command) != len(command):
        raise serial.SerialTimeoutException("The direction byte was not written.")
    if flush:
        board.flush()


class Esp32Mouse:
    """Negotiate XY1, with a fixed-step fallback for the legacy demo."""

    STEP_COUNTS = 10
    ACK_TIMEOUT = .25
    MAX_COMMAND_AGE_MS = 80

    def __init__(self, board: serial.Serial, *, flush: bool = True, max_rate: int = 60):
        if type(max_rate) is not int or not 30 <= max_rate <= 60:
            raise ValueError("max_rate must be an integer between 30 and 60")
        self.board = board
        self.flush = flush
        self.max_rate = max_rate
        self.next_move_at = 0.0
        self.protocol = "legacy"
        self.ble_connected = None
        self.token = secrets.randbelow(0xffffffff) + 1
        self.sequence = 0
        self.pending = None
        self.received = bytearray()
        self.board_clock = 0
        self.reply_at = 0.
        self.last_status = ""
        self.ack_ms = 0.
        self.ack_count = 0
        self.ack_kind = ""
        self.pending_kind = ""

    def _write_frame(self, body, *, resync=False, expires_at=None, can_send=None):
        packet = (b"!\n" if resync else b"") + encode_frame(body)
        if can_send is not None and not can_send():
            return None
        started = time.monotonic()
        if expires_at is not None and started >= expires_at:
            return None
        if self.board.write(packet) != len(packet):
            raise serial.SerialTimeoutException("串口协议帧写入不完整")
        return started

    def _responses(self):
        if self.board.in_waiting:
            self.received.extend(self.board.read(min(self.board.in_waiting, 4096)))
        lines = self.received.split(b"\n")
        self.received = bytearray(lines.pop())
        if len(self.received) > 4096:
            self.received.clear()
        for line in lines:
            fields = decode_frame(line)
            if fields:
                yield fields

    def negotiate(self, timeout=1.):
        """Probe safely: uppercase framing is inert on the legacy demo."""
        deadline = time.monotonic() + timeout
        next_probe = 0.
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now >= next_probe:
                self._write_frame(f"H {self.token}")
                next_probe = now + .25
            for fields in self._responses():
                if len(fields) == 5 and fields[:3] == ["R", "1", str(self.token)]:
                    self.board_clock = int(fields[3])
                    self.ble_connected = bool(int(fields[4]))
                    self.reply_at = time.monotonic()
                    self.protocol = "xy1"
                    return self.protocol
            time.sleep(.005)
        return self.protocol

    def _request(self, kind, dx=0, dy=0, *, expires_at=None, can_send=None):
        now = time.monotonic()
        # The reported board clock precedes host receipt. Anchor the deadline
        # to that sample so reply transit and polling cannot extend freshness.
        wire_expiry = now + self.MAX_COMMAND_AGE_MS / 1000
        if expires_at is not None:
            wire_expiry = min(expires_at, wire_expiry)
        deadline = (self.board_clock + math.floor((wire_expiry - self.reply_at) * 1000)) & 0xffffffff
        sequence = (self.sequence + 1) & 0xffffffff
        started = self._write_frame(f"{kind} {self.token} {sequence} {deadline} {dx} {dy}",
                                    resync=kind == "S", expires_at=expires_at, can_send=can_send)
        if started is None:
            return False
        self.sequence = sequence
        self.pending = (sequence, started)
        self.pending_kind = kind
        return True

    def _check_ack_timeout(self, now):
        if self.pending and now >= self.pending[1] + self.ACK_TIMEOUT:
            raise AckTimeoutError(self.pending_kind)

    def poll(self):
        if self.protocol != "xy1":
            return
        self._check_ack_timeout(time.monotonic())
        for fields in self._responses():
            if len(fields) != 6 or fields[:2] != ["A", str(self.token)]:
                continue
            if self.pending is None or int(fields[2]) != self.pending[0]:
                continue
            now = time.monotonic()
            self._check_ack_timeout(now)
            self.ack_ms = (now - self.pending[1]) * 1000
            self.ack_count += 1
            self.ack_kind = self.pending_kind
            self.pending = None
            self.board_clock = int(fields[3])
            self.reply_at = now
            self.ble_connected = bool(int(fields[4]))
            self.last_status = fields[5]
            if self.last_status == "BLE":
                raise BleDisconnectedError("ESP Mouse 蓝牙未连接")
            if self.last_status in ("RANGE", "SEND", "DUP"):
                raise serial.SerialException(f"ESP32 拒绝位移：{self.last_status}")
        now = time.monotonic()
        self._check_ack_timeout(now)
        if self.pending is None and now - self.reply_at > .5:
            self._request("P")

    def cancel(self):
        self.board.reset_output_buffer()
        if self.protocol == "xy1":
            # Invalidate and terminate any partial frame left by purge.
            self._request("S")

    def move_relative(self, dx: int, dy: int, *, expires_at=None, can_send=None) -> bool:
        """Write a correction before its host deadline, with a final state check."""
        if self.protocol == "xy1":
            self.poll()
            if not self.ble_connected:
                raise BleDisconnectedError("ESP Mouse 蓝牙未连接")
        if self.pending or time.monotonic() < self.next_move_at or not (dx or dy):
            return False
        if self.protocol == "xy1":
            if not self._request("M", max(-127, min(127, int(dx))), max(-127, min(127, int(dy))),
                                 expires_at=expires_at, can_send=can_send):
                return False
            self.next_move_at = time.monotonic() + 1 / self.max_rate
            return True
        if can_send is not None and not can_send():
            return False
        if (expires_at is not None and time.monotonic() >= expires_at) or max(abs(dx), abs(dy)) < self.STEP_COUNTS / 2:
            return False
        if abs(dx) >= abs(dy):
            direction = "right" if dx > 0 else "left"
        else:
            direction = "down" if dy > 0 else "up"
        move(self.board, direction, flush=self.flush)
        # Large errors can use the configured ceiling; retain the slower pace
        # near the target where a fixed-size step can overshoot.
        rate = min(self.max_rate, max(30, max(abs(dx), abs(dy)) * 3))
        self.next_move_at = time.monotonic() + 1 / rate
        return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Test Espressif Mouse Mode from its USB serial console."
    )
    parser.add_argument("--port", required=True, help="Windows serial port, e.g. COM7")
    args = parser.parse_args()

    try:
        with open_board(args.port) as board:
            board.timeout = 0
            mouse = Esp32Mouse(board)
            print(f"固件协议：{mouse.negotiate()}")
            print("确认 Windows 已连接 ESP Mouse，再输入方向。")
            print("可用方向：up / left / down / right；XY 固件也可输入 dx dy，例如 5 -3。输入 exit 退出。")
            while True:
                direction = input("> ").strip().lower()
                if direction == "exit":
                    return 0
                if not direction:
                    continue
                try:
                    if mouse.protocol == "legacy":
                        move(board, direction)
                        continue
                    directions = {"up": (0, -10), "left": (-10, 0), "down": (0, 10), "right": (10, 0)}
                    delta = directions.get(direction)
                    if delta is None:
                        delta = tuple(map(int, direction.split()))
                        if len(delta) != 2 or max(map(abs, delta)) > 127:
                            raise ValueError("请输入两个 -127 到 127 的整数")
                    deadline = time.monotonic() + .5
                    while not mouse.move_relative(*delta) and time.monotonic() < deadline:
                        time.sleep(.005)
                    while mouse.pending:
                        mouse.poll()
                        time.sleep(.005)
                    print(f"固件回执：{mouse.last_status}")
                except ValueError as exc:
                    print(exc, file=sys.stderr)
    except (EOFError, KeyboardInterrupt):
        return 0
    except serial.SerialException as exc:
        print(f"串口访问失败：{exc}。请核对 COM 号并退出 IDF Monitor。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
