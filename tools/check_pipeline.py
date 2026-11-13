"""Windows integration check: real screen + ONNX, simulated serial (no cursor moves).

Opens a temporary test window and closes it after sampling (default: 3 seconds)
or the sample duration plus 15 seconds if startup/recognition fails.
"""
from pathlib import Path
from dataclasses import replace
from contextlib import ExitStack
import argparse
import os
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["LOCALAPPDATA"] = tempfile.mkdtemp(prefix="aim-pipeline-check-")

import cv2
import numpy as np
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication, QLabel
from aim_assist.runtime import Runtime
from aim_assist.settings import ROOT, Settings
from aim_assist.windows import user32
from esp32_ble_mouse import decode_frame, encode_frame


class SimulatedBoard:
    """Exercise real XY framing and ACK handling without opening a COM port."""
    port = "SIMULATED"

    def __init__(self, protocol, writes):
        self.protocol = protocol
        self.writes = writes
        self.received = bytearray()

    @property
    def in_waiting(self):
        return len(self.received)

    def read(self, count):
        result = bytes(self.received[:count])
        del self.received[:count]
        return result

    def write(self, packet):
        if self.protocol == "legacy":
            if packet in (b"w", b"a", b"s", b"d"):
                self.writes.append(packet)
        else:
            fields = decode_frame(packet.splitlines()[-1])
            assert fields, "Invalid protocol frame"
            clock = int(time.monotonic() * 1000) & 0xffffffff
            if fields[0] == "H":
                response = f"R 1 {fields[1]} {clock} 1"
            else:
                if fields[0] == "M":
                    self.writes.append(packet)
                    remaining_ms = (int(fields[3]) - clock + 0x80000000) % 0x100000000 - 0x80000000
                    status = "OK" if 0 < remaining_ms <= 200 else "EXPIRED"
                else:
                    status = "STATUS"
                response = f"A {fields[1]} {fields[2]} {clock} 1 {status}"
            self.received.extend(encode_frame(response))
        return len(packet)

    def reset_output_buffer(self):
        pass

    def close(self):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--simulate-focus", action="store_true", help="Bypass foreground gating only in this check, for background automation sessions")
    parser.add_argument("--preview-only", action="store_true", help="Verify recognition without connecting even the simulated device")
    parser.add_argument("--protocol", choices=("xy1", "legacy"), default="xy1", help="Simulated device protocol (default: xy1)")
    parser.add_argument("--cpu-threads", type=int, default=0, help="ONNX Runtime intra-op CPU threads (0 uses the runtime default)")
    parser.add_argument("--rate", type=int, choices=(30, 60, 120), default=60, help="Recognition rate ceiling")
    parser.add_argument("--provider", choices=("CPUExecutionProvider", "DmlExecutionProvider", "CUDAExecutionProvider"),
                        default="CPUExecutionProvider", help="Backend to validate with real capture and simulated output")
    parser.add_argument("--seconds", type=float, default=3, help="Sample duration after the first preview")
    args = parser.parse_args()
    if args.seconds <= 0:
        parser.error("--seconds must be positive")
    settings = replace(Settings(), radius=155, cpu_threads=args.cpu_threads, rate=args.rate, provider=args.provider).validate()
    app = QApplication([])
    frame = cv2.imdecode(np.fromfile(str(ROOT / "tests/fixtures/rust-validation.jpg"), dtype=np.uint8), 1)
    # Existing repository fixture; no network or screenshot of unrelated apps.
    frame = cv2.cvtColor(frame[576:896, 1088:1408], cv2.COLOR_BGR2RGB).copy()
    image = QImage(frame.data, 320, 320, frame.strides[0], QImage.Format.Format_RGB888).copy()
    target = QLabel()
    target.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
    target.setWindowTitle("Aim Assist pipeline verification (simulated output)")
    target.setPixmap(QPixmap.fromImage(image))
    target.setScaledContents(True)
    target.resize(320, 320)
    target.show()
    scale = target.devicePixelRatioF()
    target.resize(round(320 / scale), round(320 / scale))
    target.raise_()
    target.activateWindow()
    writes = []
    board = SimulatedBoard(args.protocol, writes)
    with ExitStack() as resources:
        open_mock = resources.enter_context(patch("aim_assist.runtime.open_board", return_value=board))
        resources.enter_context(patch("serial.tools.list_ports.comports", return_value=[SimpleNamespace(device="SIMULATED")]))
        if args.simulate_focus:
            api = user32()

            class FocusProxy:
                def GetForegroundWindow(self):
                    return int(target.winId())

                def __getattr__(self, name):
                    return getattr(api, name)

            proxy = FocusProxy()
            resources.enter_context(patch("aim_assist.windows.user32", return_value=proxy))
            resources.enter_context(patch("aim_assist.runtime.user32", return_value=proxy))
        runtime = Runtime(settings)
        runtime.configure(settings, int(target.winId()))
        if not args.preview_only:
            runtime.connect("SIMULATED")
        started = time.monotonic()
        result = {}
        started_run = False
        first_preview_at = None

        def tick():
            nonlocal started_run, first_preview_at
            state = runtime.snapshot()
            if not started_run and (args.preview_only or state["connected"]):
                started_run = True
                if args.preview_only:
                    runtime.set_preview(True, "无设备预览联调")
                else:
                    runtime.set_active(True, "模拟串口联调")
            now = time.monotonic()
            if state["preview"] is not None and first_preview_at is None:
                first_preview_at = now
            if state["preview"] is not None and (writes or args.preview_only) and now - first_preview_at >= args.seconds:
                result.update(state["metrics"])
                output = ROOT / "artifacts"
                output.mkdir(exist_ok=True)
                filename = "pipeline-preview.png" if args.preview_only else f"pipeline-{args.protocol}.png"
                cv2.imencode(".png", cv2.cvtColor(state["preview"], cv2.COLOR_RGB2BGR))[1].tofile(str(output / filename))
                runtime.set_active(False)
                count = len(writes)

                def finish():
                    result["no_output_after_stop"] = count == len(writes)
                    app.quit()

                timer.stop()
                QTimer.singleShot(150, finish)
            elif now - started > args.seconds + 15:
                result["error"] = state["message"]
                app.quit()

        def activate():
            from ctypes import wintypes
            api = user32()
            api.SetForegroundWindow.argtypes = [wintypes.HWND]
            api.SetForegroundWindow(int(target.winId()))
            target.activateWindow()

        QTimer.singleShot(200, activate)

        timer = QTimer()
        timer.timeout.connect(tick)
        timer.start(30)
        try:
            app.exec()
        finally:
            runtime.shutdown()
            runtime.thread.join(5)
            target.close()
        print(result)
        if args.preview_only:
            open_mock.assert_not_called()
            assert not writes and result.get("moves") == 0, "Preview must never send movement"
            assert result.get("targets", 0) > 0, "No preview target detected"
        else:
            assert result.get("moves", 0) > 0, "No target movement produced; check test window focus"
            if args.protocol == "xy1":
                assert result.get("ack") is not None, "No XY movement ACK observed"
                assert result.get("accepted", 0) > 0, "No movement accepted by the simulated firmware"
        assert result["no_output_after_stop"], "Unexpected output after stop"
        assert not runtime.thread.is_alive()
        assert not runtime.io_thread.is_alive()
        print(f"PASS: capture + ONNX; provider={args.provider}; cpu_threads={args.cpu_threads}; rate={args.rate}; preview_only={args.preview_only}; protocol={args.protocol}; stop verified; simulated_focus={args.simulate_focus}")


if __name__ == "__main__":
    main()
