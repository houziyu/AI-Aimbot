"""Send directional commands to the Espressif BLE Mouse Mode example."""

import argparse
import sys
import time

import serial


COMMANDS = {
    "up": b"w",
    "left": b"a",
    "down": b"s",
    "right": b"d",
}


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
    """Translate a relative correction into one fixed step on the larger axis."""

    STEP_COUNTS = 10
    MOVE_INTERVAL = 1 / 30

    def __init__(self, board: serial.Serial, *, flush: bool = True):
        self.board = board
        self.flush = flush
        self.next_move_at = 0.0

    def move_relative(self, dx: int, dy: int) -> bool:
        """Return whether a direction byte was sent for this frame."""
        if max(abs(dx), abs(dy)) < self.STEP_COUNTS / 2:
            return False
        if time.monotonic() < self.next_move_at:
            return False

        if abs(dx) >= abs(dy):
            direction = "right" if dx > 0 else "left"
        else:
            direction = "down" if dy > 0 else "up"
        move(self.board, direction, flush=self.flush)
        self.next_move_at = time.monotonic() + self.MOVE_INTERVAL
        return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Test Espressif Mouse Mode from its USB serial console."
    )
    parser.add_argument("--port", required=True, help="Windows serial port, e.g. COM7")
    args = parser.parse_args()

    try:
        with open_board(args.port) as board:
            print("确认 Windows 已连接 ESP Mouse，再输入方向。")
            print("可用方向：up / left / down / right。输入 exit 退出。")
            while True:
                direction = input("> ").strip().lower()
                if direction == "exit":
                    return 0
                if not direction:
                    continue
                try:
                    move(board, direction)
                except ValueError as exc:
                    print(exc, file=sys.stderr)
    except (EOFError, KeyboardInterrupt):
        return 0
    except serial.SerialException as exc:
        print(f"串口访问失败：{exc}。请核对 COM 号并退出 IDF Monitor。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
