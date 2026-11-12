"""One worker owns capture, inference and serial I/O. UI reads a bounded mailbox."""
from collections import deque
from dataclasses import replace
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler
import queue
import threading
import time

import cv2
import numpy as np
import serial.tools.list_ports

from esp32_ble_mouse import Esp32Mouse, open_board
from .settings import CONFIG_PATH
from .vision import Detector, TargetTracker
from .windows import capture_region, user32


class Runtime:
    def __init__(self, settings):
        self.settings = settings
        self.lock = threading.RLock()
        self.commands = queue.Queue()
        self.quit = threading.Event()
        self.connected = False
        self.ble_connected = None
        self.protocol = ""
        self.active = False
        self.busy = False
        self.epoch = 0
        self.hwnd = 0
        self.preview = None
        self.metrics = dict(fps=0., inference=0., serial=0., targets=0, moves=0)
        self.message = "连接设备后，选择目标窗口并开启辅助。"
        self.logs = deque(maxlen=200)
        self.logger = logging.getLogger(f"aim_assist.{id(self)}")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(CONFIG_PATH.parent / "runtime.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        self.logger.addHandler(handler)
        self.thread = threading.Thread(target=self._run, name="aim-worker", daemon=True)
        self.thread.start()
        self.log("程序已就绪；串口连接不代表蓝牙 HID 已配对。")

    def log(self, text):
        with self.lock:
            self.logs.appendleft(f"{datetime.now():%H:%M:%S}   {text}")
            self.logger.info(text)

    def snapshot(self):
        with self.lock:
            return dict(connected=self.connected, active=self.active, busy=self.busy,
                        ble_connected=self.ble_connected, protocol=self.protocol,
                        message=self.message, preview=self.preview, metrics=self.metrics.copy(), logs=list(self.logs))

    def configure(self, settings, hwnd):
        settings.validate()
        with self.lock:
            if self.active or self.busy:
                raise ValueError("请先关闭辅助再修改参数")
            self.settings, self.hwnd = replace(settings), hwnd
            self.epoch += 1

    def connect(self, port):
        with self.lock:
            if self.busy or self.connected:
                return
            if not port:
                raise ValueError("请选择指令串口")
            self.busy = True
            self.message = "正在打开串口…"
        self.commands.put(("connect", port))

    def disconnect(self):
        self.set_active(False, "断开设备")
        with self.lock:
            self.busy = True
        self.commands.put(("disconnect", None))

    def set_active(self, enabled, source="界面"):
        with self.lock:
            if enabled and (not self.connected or self.busy or not self.hwnd):
                raise ValueError("请先连接设备并选择目标窗口")
            if enabled and self.ble_connected is False:
                raise ValueError("请先连接 Windows 蓝牙中的 ESP Mouse")
            if self.active == enabled:
                return
            self.active = enabled
            self.epoch += 1
            self.preview = None
            self.metrics = dict(fps=0., inference=0., serial=0., targets=0, moves=0)
            self.message = "正在加载模型；切回目标窗口后开始识别。" if enabled else "辅助已关闭，截图、识别与位移发送已暂停。"
            self.log(f"{source} · 辅助{'开启' if enabled else '关闭'}")

    def shutdown(self):
        self.set_active(False, "退出程序")
        self.quit.set()

    def _run(self):
        board = mouse = detector = capture = None
        detector_key = None
        tracker = TargetTracker()
        local_epoch = -1
        last_presence = last_preview = time.monotonic()
        sample_start, sample_count = time.monotonic(), 0
        try:
            while not self.quit.is_set():
                started = time.monotonic()
                try:
                    try:
                        command, value = self.commands.get_nowait()
                    except queue.Empty:
                        command = None
                    if command == "connect":
                        board = open_board(value)
                        board.write_timeout = .1
                        board.timeout = 0
                        mouse = Esp32Mouse(board, flush=False)
                        protocol = mouse.negotiate()
                        with self.lock:
                            self.protocol = protocol
                            self.ble_connected = mouse.ble_connected
                            self.connected, self.busy = True, False
                            self.message = f"{value} 已连接 · {protocol}；蓝牙状态见设备连接区。"
                        self.log(self.message)
                    elif command == "disconnect":
                        if board:
                            mouse.cancel()
                            board.close()
                        board = mouse = None
                        with self.lock:
                            self.connected, self.busy = False, False
                            self.ble_connected = None
                            self.protocol = ""
                            self.message = "设备已断开。"
                        self.log(self.message)

                    if board and started - last_presence >= 1:
                        last_presence = started
                        ports = {p.device.lower() for p in serial.tools.list_ports.comports()}
                        if board.port.lower() not in ports:
                            raise OSError("串口设备已拔出")
                        if mouse.protocol == "legacy" and board.in_waiting:
                            board.read(min(board.in_waiting, 4096))

                    if mouse:
                        mouse.poll()
                        with self.lock:
                            self.ble_connected = mouse.ble_connected
                            if self.active and self.ble_connected is False:
                                raise OSError("ESP Mouse 蓝牙已断开")

                    with self.lock:
                        active, epoch, settings, hwnd = self.active, self.epoch, self.settings, self.hwnd
                    if epoch != local_epoch:
                        local_epoch = epoch
                        tracker.reset()
                        if mouse:
                            mouse.max_rate = settings.output_rate
                        sample_start, sample_count = started, 0
                        if board:
                            mouse.cancel()
                    if not active:
                        if capture:
                            capture.close()
                            capture = None
                        self.quit.wait(.02)
                        continue
                    key = (settings.model, settings.provider, settings.crop_size)
                    if key != detector_key:
                        detector = Detector(settings)
                        detector_key = key
                        self.log(f"模型已加载：{settings.model} · {settings.provider}")
                    with self.lock:
                        if not self.active or epoch != self.epoch:
                            continue
                    if capture is None:
                        import mss
                        capture = mss.mss()
                    region = capture_region(hwnd, settings.crop_size, capture.monitors[0])
                    if region is None:
                        tracker.reset()
                        sample_start, sample_count = time.monotonic(), 0
                        with self.lock:
                            if epoch == self.epoch:
                                self.message = "等待目标窗口回到前台，截图与输出已暂停。"
                                self.preview = None
                                self.metrics.update(fps=0., inference=0., serial=0., targets=0)
                        self.quit.wait(.05)
                        continue
                    frame = np.array(capture.grab(region))[:, :, :3].copy()
                    if settings.mask and settings.mask_width and settings.mask_height:
                        h = min(settings.mask_height, frame.shape[0])
                        w = min(settings.mask_width, frame.shape[1])
                        if settings.mask_side == "left":
                            frame[-h:, :w] = 0
                        else:
                            frame[-h:, -w:] = 0
                    inference_start = time.monotonic()
                    detections = detector.detect(frame, settings.confidence)
                    center = (frame.shape[1] / 2, frame.shape[0] / 2)
                    target, delta = tracker.select(detections, center, settings)
                    inference_ms = (time.monotonic() - inference_start) * 1000
                    if target and any(delta):
                        # A result that arrives just before the next output slot
                        # should wait for that slot instead of losing a correction.
                        self.quit.wait(max(0., mouse.next_move_at - time.monotonic()))
                    # Cancellation and output share a lock: a completed stop cannot be
                    # followed by an older inference result sending another command.
                    with self.lock:
                        if not self.active or epoch != self.epoch:
                            continue
                        if user32().GetForegroundWindow() != hwnd:
                            tracker.reset()
                            continue
                        send_start = time.monotonic()
                        sent = mouse.move_relative(*delta) if target else False
                        serial_ms = (time.monotonic() - send_start) * 1000 if sent else 0.
                        self.metrics.update(inference=inference_ms, serial=serial_ms, targets=len(detections))
                        self.metrics["moves"] += int(sent)
                        self.message = "正在识别 · 已选定目标" if target else "正在识别 · 范围内暂无目标"
                    sample_count += 1
                    now = time.monotonic()
                    if now - sample_start >= .5:
                        with self.lock:
                            if epoch == self.epoch:
                                self.metrics["fps"] = sample_count / (now - sample_start)
                        sample_start, sample_count = now, 0
                    if now - last_preview >= .1:
                        last_preview = now
                        cx, cy = map(int, center)
                        cv2.circle(frame, (cx, cy), settings.radius, (190, 160, 120), 1)
                        cv2.drawMarker(frame, (cx, cy), (235, 235, 235), cv2.MARKER_CROSS, 18, 1)
                        for detection in detections:
                            color = (100, 195, 40) if detection is target else (180, 160, 100)
                            cv2.rectangle(frame, (int(detection.x1), int(detection.y1)), (int(detection.x2), int(detection.y2)), color, 1)
                            cv2.putText(frame, f"{detection.score:.2f}", (int(detection.x1), max(12, int(detection.y1) - 4)), cv2.FONT_HERSHEY_SIMPLEX, .4, color, 1)
                        if target:
                            cv2.circle(frame, tuple(map(int, target.aim(settings.aim_height))), 3, (100, 195, 40), -1)
                        with self.lock:
                            if epoch == self.epoch and self.active:
                                self.preview = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    self.quit.wait(max(0, 1 / settings.rate - (time.monotonic() - started)))
                except Exception as exc:
                    self.logger.exception("运行失败")
                    self.set_active(False, "运行异常")
                    if board:
                        try:
                            board.reset_output_buffer()
                            board.close()
                        except Exception:
                            pass
                    board = mouse = None
                    if capture:
                        capture.close()
                        capture = None
                    with self.lock:
                        self.connected, self.busy = False, False
                        self.ble_connected = None
                        self.protocol = ""
                        self.message = str(exc)
                    self.log(f"已停止并断开设备：{exc}")
                    self.quit.wait(.05)
        finally:
            if capture:
                capture.close()
            if board:
                try:
                    mouse.cancel()
                finally:
                    board.close()
            for handler in self.logger.handlers[:]:
                handler.close()
                self.logger.removeHandler(handler)
