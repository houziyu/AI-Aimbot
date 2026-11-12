"""Windows integration check: real screen + ONNX, simulated serial (no cursor moves).

Opens a temporary test window for at most 10 seconds and closes it automatically.
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--simulate-focus", action="store_true", help="Bypass foreground gating only in this check, for background automation sessions")
    args = parser.parse_args()
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
    board = SimpleNamespace(port="SIMULATED", in_waiting=0, reset_output_buffer=lambda: None,
                            close=lambda: None, write=lambda data: writes.append(data) or len(data))
    with ExitStack() as resources:
        resources.enter_context(patch("aim_assist.runtime.open_board", return_value=board))
        resources.enter_context(patch("aim_assist.runtime.Esp32Mouse.negotiate", return_value="legacy"))
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
        settings = replace(Settings(), radius=155)
        runtime = Runtime(settings)
        runtime.configure(settings, int(target.winId()))
        runtime.connect("SIMULATED")
        started = time.monotonic()
        result = {}

        def tick():
            state = runtime.snapshot()
            if state["connected"] and not state["active"] and not result:
                runtime.set_active(True, "模拟串口联调")
            if state["preview"] is not None and writes and time.monotonic() - started > 1.5:
                result.update(state["metrics"])
                output = ROOT / "artifacts"
                output.mkdir(exist_ok=True)
                cv2.imencode(".png", cv2.cvtColor(state["preview"], cv2.COLOR_RGB2BGR))[1].tofile(str(output / "pipeline.png"))
                runtime.set_active(False)
                count = len(writes)

                def finish():
                    result["no_output_after_stop"] = count == len(writes)
                    app.quit()

                timer.stop()
                QTimer.singleShot(150, finish)
            elif time.monotonic() - started > 10:
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
        assert result.get("moves", 0) > 0, "No target movement produced; check test window focus"
        assert result["no_output_after_stop"], "Unexpected output after stop"
        assert not runtime.thread.is_alive()
        print(f"PASS: real window capture -> real ONNX -> target -> simulated serial; stop verified; simulated_focus={args.simulate_focus}")


if __name__ == "__main__":
    main()
