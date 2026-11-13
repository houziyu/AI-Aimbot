"""Independent vision and device workers with a single, expiring result mailbox."""
from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler
import queue
import threading
import time

import cv2
import numpy as np
import serial.tools.list_ports

from esp32_ble_mouse import AckTimeoutError, BleDisconnectedError, Esp32Mouse, open_board
from .settings import CONFIG_PATH
from .movement import MovementScaler
from .vision import Detector, TargetTracker
from .windows import capture_region, user32, WindowCaptureError, WindowClosedError


OUTPUT_TOTALS = ("moves", "expired", "accepted", "rejected", "rejected_expired",
                 "rejected_busy", "ack_timeouts", "xy1_output")


@dataclass(frozen=True)
class Result:
    epoch: int
    captured_at: float
    delta: tuple
    ready_at: float = 0.
    target_id: int = 0


def empty_metrics():
    return dict(fps=0., output_fps=0., capture=0., preprocess=0., inference=0., postprocess=0.,
                selection=0., send_wait=0., serial=0., ack=None,
                latency_p50=0., latency_p95=0., age=0., expired=0, targets=0, moves=0,
                accepted=0, rejected=0, rejected_expired=0, rejected_busy=0, ack_timeouts=0, xy1_output=False)


class Runtime:
    def __init__(self, settings):
        self.settings = settings
        self.lock = threading.RLock()
        self.commands = queue.Queue()
        self.quit = threading.Event()
        self.device_wake = threading.Event()
        self.connected = False
        self.ble_connected = None
        self.protocol = ""
        self.active = False
        self.preview_enabled = False
        self.busy = False
        self.epoch = 0
        self.hwnd = 0
        self.preview = None
        self.latest = None
        self.status = "idle"
        self.notice = 0
        self.metrics = empty_metrics()
        self.frame_times = deque(maxlen=500)
        self.move_times = deque(maxlen=250)
        self.latencies = deque(maxlen=120)
        self.latency_summary_at = 0.
        self.output_scaler = MovementScaler()
        self.started_at = time.monotonic()
        self.message = "选择目标窗口可仅识别预览；连接设备后可开启辅助。"
        self.logs = deque(maxlen=200)
        self.logger = logging.getLogger(f"aim_assist.{id(self)}")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(CONFIG_PATH.parent / "runtime.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        self.logger.addHandler(handler)
        self.io_thread = threading.Thread(target=self._device_loop, name="aim-device", daemon=True)
        self.thread = threading.Thread(target=self._run, name="aim-vision", daemon=True)
        self.io_thread.start()
        self.thread.start()
        self.log("程序已就绪；仅识别预览无需连接设备，不发送位移。")

    def log(self, text):
        with self.lock:
            self.logs.appendleft(f"{datetime.now():%H:%M:%S}   {text}")
            self.logger.info(text)

    def snapshot(self):
        samples = None
        with self.lock:
            now = time.monotonic()
            if self.latencies and now - self.latency_summary_at >= .2:
                samples, epoch = tuple(self.latencies), self.epoch
                self.latency_summary_at = now
        # Percentiles are a display statistic. Never make device/F8 wait on NumPy.
        if samples:
            p50, p95 = np.percentile(samples, [50, 95])
            with self.lock:
                if epoch == self.epoch and self.latencies and self.latency_summary_at == now:
                    self.metrics.update(latency_p50=float(p50), latency_p95=float(p95))
        with self.lock:
            now = time.monotonic()
            for samples, key in ((self.frame_times, "fps"), (self.move_times, "output_fps")):
                while samples and samples[0] < now - 1:
                    samples.popleft()
                self.metrics[key] = len(samples) / max(.1, min(1., now - self.started_at))
            return dict(connected=self.connected, active=self.active, busy=self.busy,
                        preview_enabled=self.preview_enabled, status=self.status, notice=self.notice,
                        ble_connected=self.ble_connected, protocol=self.protocol,
                        message=self.message, preview=self.preview, metrics=self.metrics.copy(), logs=list(self.logs))

    def configure(self, settings, hwnd):
        settings.validate()
        with self.lock:
            if self.active or self.preview_enabled or self.busy:
                raise ValueError("请先停止辅助或预览再修改参数")
            self.settings, self.hwnd = replace(settings), hwnd
            self.epoch += 1
            self.device_wake.set()

    def connect(self, port):
        with self.lock:
            if self.busy or self.connected:
                return
            if not port:
                raise ValueError("请选择指令串口")
            self.busy = True
            if not self.preview_enabled:
                self.status, self.message = "connecting", "正在打开串口…"
        self.commands.put(("connect", port))
        self.device_wake.set()

    def disconnect(self):
        with self.lock:
            if self.active:
                self._set_mode(False, False, "断开设备")
            self.busy = True
        self.commands.put(("disconnect", None))
        self.device_wake.set()

    def _set_mode(self, active, preview, source):
        """Caller holds lock. Invalidates in-flight vision and queued movement."""
        if (self.active, self.preview_enabled) == (active, preview):
            return
        self.active, self.preview_enabled = active, preview
        self.epoch += 1
        self.device_wake.set()
        self.notice += 1
        self.preview = self.latest = None
        if active or preview:
            self.metrics = empty_metrics()
            self.metrics["xy1_output"] = active and self.protocol == "xy1"
        else:
            self.metrics.update({key: value for key, value in empty_metrics().items() if key not in OUTPUT_TOTALS})
        self.frame_times.clear()
        self.move_times.clear()
        self.latencies.clear()
        self.latency_summary_at = 0.
        self.started_at = time.monotonic()
        self.status = "loading" if active or preview else "idle"
        self.message = "正在加载模型；切回目标窗口后开始识别。" if active or preview else "已停止截图、识别与位移发送。"
        mode = "辅助开启" if active else "仅识别预览开启" if preview else "辅助与预览已关闭"
        self.log(f"{source} · {mode}")

    def set_active(self, enabled, source="界面"):
        with self.lock:
            if enabled and self.preview_enabled:
                raise ValueError("请先停止仅识别预览，再开启辅助")
            if enabled and (not self.connected or self.busy or not self.hwnd):
                raise ValueError("请先连接设备并选择目标窗口")
            if enabled and self.ble_connected is False:
                raise ValueError("请先连接 Windows 蓝牙中的 ESP Mouse")
            self._set_mode(enabled, False, source)

    def set_preview(self, enabled, source="界面"):
        with self.lock:
            if enabled and self.active:
                raise ValueError("请先关闭辅助，再开启仅识别预览")
            if enabled and not self.hwnd:
                raise ValueError("请先选择目标窗口")
            if enabled or self.preview_enabled:
                self._set_mode(False, enabled, source)

    def shutdown(self):
        self.set_active(False, "退出程序")
        self.quit.set()
        self.device_wake.set()

    def _pause(self, message, epoch):
        with self.lock:
            if epoch != self.epoch:
                return
            if self.message != message:
                self.log(message)
            self.status, self.message = "waiting_window", message
            self.preview = self.latest = None
            self.frame_times.clear()
            self.move_times.clear()
            self.latencies.clear()
            self.latency_summary_at = 0.
            self.metrics.update(targets=0, capture=0., preprocess=0., inference=0., postprocess=0.,
                                selection=0., send_wait=0., serial=0., age=0., latency_p50=0., latency_p95=0.)

    def _vision_error(self, exc, status, epoch):
        with self.lock:
            if epoch != self.epoch:
                return
            self.logger.exception("识别链路失败")
            self._set_mode(False, False, "识别异常")
            self.status = status
            self.message = f"{exc}；请调整后重新开启，设备连接不受影响。"
            self.log(self.message)

    def _send_result(self, mouse, result, expires_at):
        send_start = 0.
        metrics = None
        delta = result.delta
        scaled_state = None
        if not any(delta):
            with self.lock:
                if self.latest is result:
                    self.latest = None
                    self.output_scaler.reset()
            return
        if mouse.protocol == "xy1":
            delta, scaled_state = self.output_scaler.prepare(
                delta, time.monotonic(), result.target_id, self.settings.max_step)

        def can_send():
            nonlocal send_start, metrics
            with self.lock:
                if not self.active or result.epoch != self.epoch or self.status == "waiting_window":
                    return False
                if self.latest is not result:
                    return False
                if user32().GetForegroundWindow() != self.hwnd:
                    self.latest = None
                    return False
                self.latest = None
                send_start = time.monotonic()
                metrics = self.metrics
                return True

        # Serial I/O may block. Only the state check above takes the lock;
        # a write already in progress is handled by the next device-loop stop.
        sent = mouse.move_relative(*delta, expires_at=expires_at, can_send=can_send)
        finished = time.monotonic()
        if metrics is None:
            return
        with self.lock:
            if sent:
                if scaled_state is not None:
                    self.output_scaler.commit(scaled_state, send_start)
                metrics["moves"] += 1
                if result.epoch == self.epoch:
                    wait = max(0., send_start - result.ready_at) * 1000 if result.ready_at else 0.
                    metrics.update(serial=(finished - send_start) * 1000, age=(send_start - result.captured_at) * 1000,
                                   send_wait=wait)
                    self.move_times.append(finished)
            elif finished >= expires_at:
                metrics["expired"] += 1

    def _record_move_ack(self, mouse, epoch):
        with self.lock:
            if mouse.ack_kind != "M" or not self.active or epoch != self.epoch:
                return
            self.metrics["ack"] = mouse.ack_ms
            if mouse.last_status == "OK":
                self.metrics["accepted"] += 1
            else:
                self.metrics["rejected"] += 1
                if mouse.last_status == "EXPIRED":
                    self.metrics["rejected_expired"] += 1
                elif mouse.last_status == "BUSY":
                    self.metrics["rejected_busy"] += 1

    def _device_loop(self):
        # Only this thread opens, polls, writes and closes the serial device.
        board = mouse = None
        local_epoch = -1
        last_presence = time.monotonic()
        ack_count = 0
        try:
            while not self.quit.is_set():
                self.device_wake.clear()
                try:
                    try:
                        command, value = self.commands.get_nowait()
                    except queue.Empty:
                        command = None
                    if command == "connect":
                        board = open_board(value)
                        board.write_timeout, board.timeout = .1, 0
                        mouse = Esp32Mouse(board, flush=False)
                        protocol = mouse.negotiate()
                        ack_count, local_epoch = 0, -1
                        with self.lock:
                            self.protocol, self.ble_connected = protocol, mouse.ble_connected
                            self.connected, self.busy = True, False
                            if not self.preview_enabled:
                                self.status = "waiting_bluetooth" if self.ble_connected is False else "idle"
                                self.message = "请在 Windows 中连接 ESP Mouse 蓝牙。" if self.ble_connected is False else f"{value} 已连接，可以开启辅助或仅识别预览。"
                        self.log(f"{value} 已连接 · {protocol}")
                    elif command == "disconnect":
                        if board:
                            try:
                                mouse.cancel()
                            finally:
                                board.close()
                        board = mouse = None
                        with self.lock:
                            self.connected = self.busy = False
                            self.ble_connected, self.protocol = None, ""
                            if not self.preview_enabled:
                                self.status, self.message = "idle", "设备已断开。"
                        self.log("设备已断开。")
                    if mouse is None:
                        self.device_wake.wait(.02)
                        continue
                    with self.lock:
                        epoch = self.epoch
                        rate = self.settings.output_rate
                    if local_epoch != epoch:
                        self.output_scaler.reset()
                        mouse.max_rate = rate
                        mouse.cancel()
                        local_epoch = epoch
                    now = time.monotonic()
                    if now - last_presence >= 1:
                        last_presence = now
                        ports = {p.device.lower() for p in serial.tools.list_ports.comports()}
                        if board.port.lower() not in ports:
                            raise OSError("串口设备已拔出")
                        if mouse.protocol == "legacy" and board.in_waiting:
                            board.read(min(board.in_waiting, 4096))
                    try:
                        mouse.poll()
                    except AckTimeoutError as exc:
                        with self.lock:
                            if local_epoch != self.epoch and exc.kind == "M":
                                # Stop supersedes an old request; the next iteration sends S.
                                continue
                        raise
                    finally:
                        if mouse.ack_count != ack_count:
                            ack_count = mouse.ack_count
                            self._record_move_ack(mouse, local_epoch)
                    to_send = None
                    with self.lock:
                        self.ble_connected = mouse.ble_connected
                        if self.active and self.ble_connected is False:
                            self._set_mode(False, False, "蓝牙断开")
                            self.status, self.message = "waiting_bluetooth", "蓝牙已断开；串口连接保留，蓝牙恢复后请手动开启辅助。"
                            self.log(self.message)
                        elif self.status == "waiting_bluetooth" and self.ble_connected:
                            self.status, self.message = "idle", "蓝牙已恢复，请手动开启辅助。"
                        result = self.latest
                        if self.active and result is not None and result.epoch == local_epoch == self.epoch:
                            now = time.monotonic()
                            expires_at = result.captured_at + self.settings.result_max_age_ms / 1000
                            if now >= expires_at:
                                self.latest = None
                                if any(result.delta):
                                    self.metrics["expired"] += 1
                            elif mouse.pending is None and now >= mouse.next_move_at:
                                to_send = result, expires_at
                        elif result is not None and result.epoch != self.epoch:
                            self.latest = None
                    if to_send is not None:
                        self._send_result(mouse, *to_send)
                    self.device_wake.wait(.002)
                except BleDisconnectedError:
                    with self.lock:
                        self.ble_connected = False
                        if self.active:
                            self._set_mode(False, False, "蓝牙断开")
                        if not self.preview_enabled:
                            self.status, self.message = "waiting_bluetooth", "蓝牙已断开；串口连接保留，蓝牙恢复后请手动开启辅助。"
                        self.log("蓝牙未连接，串口连接保留。")
                except Exception as exc:
                    self.logger.exception("设备通信失败")
                    with self.lock:
                        if isinstance(exc, AckTimeoutError) and exc.kind == "M" and local_epoch == self.epoch:
                            self.metrics["ack_timeouts"] += 1
                        if self.active:
                            self._set_mode(False, False, "设备异常")
                        self.latest = None
                        self.connected = self.busy = False
                        self.ble_connected, self.protocol = None, ""
                        if not self.preview_enabled:
                            self.status, self.message = "device_error", f"设备已断开：{exc}"
                        self.notice += 1
                        self.log(f"设备已断开：{exc}")
                    if board:
                        try:
                            board.reset_output_buffer()
                        except Exception:
                            pass
                        try:
                            board.close()
                        except Exception:
                            pass
                    board = mouse = None
        finally:
            if board:
                try:
                    mouse.cancel()
                except Exception:
                    self.logger.exception("退出时停止设备失败")
                finally:
                    try:
                        board.close()
                    except Exception:
                        self.logger.exception("退出时关闭串口失败")

    def _run(self):
        detector = capture = None
        detector_key = None
        tracker = TargetTracker()
        local_epoch = -1
        last_preview = 0.
        try:
            while not self.quit.is_set():
                started = time.monotonic()
                with self.lock:
                    running = self.active or self.preview_enabled
                    epoch, settings, hwnd = self.epoch, self.settings, self.hwnd
                if epoch != local_epoch:
                    local_epoch = epoch
                    tracker.reset()
                    last_preview = 0.
                if not running:
                    if capture:
                        try:
                            capture.close()
                        except Exception:
                            self.logger.exception("释放截图资源失败")
                        capture = None
                    self.quit.wait(.02)
                    continue
                stage = "model_error"
                try:
                    cpu_threads = settings.cpu_threads if settings.provider == "CPUExecutionProvider" else 0
                    key = (settings.model, settings.provider, settings.crop_size, cpu_threads)
                    if key != detector_key:
                        detector = Detector(settings)
                        detector_key = key
                        threads = f" · CPU 推理线程 {cpu_threads or '自动'}" if settings.provider == "CPUExecutionProvider" else ""
                        self.log(f"模型已加载：{settings.model} · {settings.provider}{threads}")
                    with self.lock:
                        if epoch != self.epoch:
                            continue
                    stage = "capture_error"
                    if capture is None:
                        import mss
                        capture = mss.mss()
                    region = capture_region(hwnd, settings.crop_size, capture.monitors[0])
                    if region is None:
                        tracker.reset()
                        self._pause("等待目标窗口回到前台，截图与输出已暂停。", epoch)
                        self.quit.wait(.05)
                        continue
                    captured_at = time.monotonic()
                    frame = np.array(capture.grab(region))[:, :, :3].copy()
                    capture_ms = (time.monotonic() - captured_at) * 1000
                    if settings.mask and settings.mask_width and settings.mask_height:
                        h = min(settings.mask_height, frame.shape[0])
                        w = min(settings.mask_width, frame.shape[1])
                        if settings.mask_side == "left":
                            frame[-h:, :w] = 0
                        else:
                            frame[-h:, -w:] = 0
                    stage = "model_error"
                    inference_start = time.monotonic()
                    detections = detector.detect(frame, settings.confidence)
                    detected_at = time.monotonic()
                    center = (frame.shape[1] / 2, frame.shape[0] / 2)
                    target, delta = tracker.select(detections, center, settings)
                    now = time.monotonic()
                    timings = getattr(detector, "timings", dict(preprocess=0., postprocess=0.,
                                       inference=(detected_at - inference_start) * 1000))
                    latency_ms = (now - captured_at) * 1000
                    with self.lock:
                        if epoch != self.epoch:
                            continue
                        if user32().GetForegroundWindow() != hwnd:
                            tracker.reset()
                            self._pause("等待目标窗口回到前台，截图与输出已暂停。", epoch)
                            continue
                        self.frame_times.append(now)
                        self.latencies.append(latency_ms)
                        self.metrics.update(capture=capture_ms, **timings, targets=len(detections),
                                            selection=(now - detected_at) * 1000)
                        self.latest = None
                        if self.active:
                            if latency_ms < settings.result_max_age_ms:
                                self.latest = Result(epoch, captured_at, delta, now, tracker.generation)
                            elif target and any(delta):
                                self.metrics["expired"] += 1
                        self.status = "running" if self.active else "preview"
                        self.message = ("正在识别 · " if self.active else "仅识别预览 · 不发送位移 · ") + ("已选定目标" if target else "范围内暂无目标")
                        self.device_wake.set()
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
                        preview = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        with self.lock:
                            if epoch == self.epoch:
                                self.preview = preview
                    self.quit.wait(max(0, 1 / settings.rate - (time.monotonic() - started)))
                except WindowCaptureError as exc:
                    tracker.reset()
                    self._pause(str(exc), epoch)
                    self.quit.wait(.2)
                except WindowClosedError as exc:
                    self._vision_error(exc, "window_error", epoch)
                except Exception as exc:
                    if stage == "model_error":
                        detector_key = None
                    self._vision_error(exc, stage, epoch)
        finally:
            # thread.join() remains a complete shutdown barrier for callers.
            self.quit.set()
            self.device_wake.set()
            try:
                if capture:
                    capture.close()
            finally:
                self.io_thread.join()
                for handler in self.logger.handlers[:]:
                    handler.close()
                    self.logger.removeHandler(handler)
