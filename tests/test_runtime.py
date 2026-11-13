"""Exercise real worker cancellation with fake capture/serial, never move the cursor."""
from dataclasses import replace
import threading
import time
from types import SimpleNamespace
import numpy as np
import pytest
import aim_assist.runtime as module
from aim_assist.settings import Settings
from aim_assist.vision import Detection
from esp32_ble_mouse import decode_frame, encode_frame


def wait_for(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError("worker timed out")


@pytest.fixture
def rig(monkeypatch, tmp_path):
    entered, release = threading.Event(), threading.Event()
    writes = []
    board = SimpleNamespace(port="COM_TEST", in_waiting=0, reset_output_buffer=lambda: None,
                            close=lambda: None, write=lambda value: writes.append(value) or len(value))
    monkeypatch.setattr(module, "CONFIG_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(module, "open_board", lambda port: board)
    monkeypatch.setattr(module.Esp32Mouse, "negotiate", lambda self: "legacy")
    ports = [SimpleNamespace(device="COM_TEST")]
    monkeypatch.setattr(module.serial.tools.list_ports, "comports", lambda: ports)
    monkeypatch.setattr(module, "user32", lambda: SimpleNamespace(GetForegroundWindow=lambda: 42))
    monkeypatch.setattr(module, "capture_region", lambda *args: dict(left=0, top=0, width=320, height=320))
    import mss
    monkeypatch.setattr(mss, "mss", lambda: SimpleNamespace(monitors=[{}], grab=lambda region: np.zeros((320, 320, 4), np.uint8), close=lambda: None))

    class Detector:
        def __init__(self, settings):
            pass

        def detect(self, frame, confidence):
            entered.set()
            assert release.wait(3)
            return [Detection(180, 130, 220, 230, .9)]

    monkeypatch.setattr(module, "Detector", Detector)
    runtime = module.Runtime(Settings())
    runtime.configure(Settings(), 42)
    runtime.connect("COM_TEST")
    wait_for(lambda: runtime.snapshot()["connected"])
    yield runtime, entered, release, writes, ports
    release.set()
    runtime.shutdown()
    runtime.thread.join(3)
    assert not runtime.thread.is_alive()
    assert not runtime.io_thread.is_alive()


def test_stop_discards_inflight_inference(rig):
    runtime, entered, release, writes, _ = rig
    runtime.set_active(True)
    assert entered.wait(2)
    runtime.set_active(False)
    release.set()
    time.sleep(.15)
    assert writes == []
    assert runtime.snapshot()["preview"] is None


def test_percentiles_are_outside_state_lock_and_discarded_after_reconfigure(rig, monkeypatch):
    runtime, _, _, _, _ = rig
    calculating, release = threading.Event(), threading.Event()

    def percentile(*args):
        calculating.set()
        assert release.wait(2)
        return 100., 200.

    monkeypatch.setattr(module.np, "percentile", percentile)
    with runtime.lock:
        runtime.latencies.extend([10., 20., 30.])
    reader = threading.Thread(target=runtime.snapshot)
    reader.start()
    try:
        assert calculating.wait(1)
        assert runtime.lock.acquire(timeout=.1)
        runtime.lock.release()
        runtime.configure(Settings(), 42)
    finally:
        release.set()
        reader.join(2)
    assert runtime.metrics["latency_p95"] == 0.


def test_percentiles_refresh_at_most_five_times_per_second(rig, monkeypatch):
    runtime, _, _, _, _ = rig
    calls = []
    monkeypatch.setattr(module.np, "percentile", lambda *args: calls.append(True) or (20., 30.))
    with runtime.lock:
        runtime.latencies.extend([10., 20., 30.])
    for _ in range(20):
        assert runtime.snapshot()["metrics"]["latency_p95"] == 30.
    assert len(calls) == 1


def test_f8_invalidates_queued_results_while_serial_write_is_blocked(rig, monkeypatch):
    runtime, entered, _, writes, _ = rig
    write_started = threading.Event()
    release_write = threading.Event()
    stopped = threading.Event()
    purged = threading.Event()

    def write(data):
        write_started.set()
        assert release_write.wait(2)
        writes.append(data)
        return len(data)

    board = module.open_board("COM_TEST")
    monkeypatch.setattr(board, "write", write)
    monkeypatch.setattr(board, "reset_output_buffer", lambda: purged.set() if write_started.is_set() else None)
    runtime.set_active(True)
    assert entered.wait(2)
    with runtime.lock:
        runtime.latest = module.Result(runtime.epoch, time.monotonic(), (20, 0))
    assert write_started.wait(2)

    def stop():
        runtime.set_active(False, "F8")
        stopped.set()

    stopper = threading.Thread(target=stop)
    try:
        assert runtime.lock.acquire(timeout=.5)
        try:
            runtime.latest = module.Result(runtime.epoch, time.monotonic(), (-30, 0))
        finally:
            runtime.lock.release()
        stopper.start()
        assert stopped.wait(.5)
        assert not runtime.snapshot()["active"]
        assert runtime.latest is None
        assert writes == []
    finally:
        release_write.set()
        if stopper.ident is not None:
            stopper.join(2)
    assert purged.wait(2)
    assert writes == [b"d"]
    assert runtime.snapshot()["metrics"]["moves"] == 1


def test_output_and_disconnect(rig):
    runtime, entered, release, writes, _ = rig
    release.set()
    runtime.set_active(True)
    wait_for(lambda: len(writes) > 0)
    assert writes[0] == b'd'
    runtime.disconnect()
    count = len(writes)
    wait_for(lambda: not runtime.snapshot()["connected"])
    time.sleep(.1)
    assert len(writes) == count


def test_fast_detection_waits_for_next_output_slot(rig, monkeypatch):
    runtime, _, release, _, _ = rig
    runtime.configure(replace(Settings(), rate=120, output_rate=30), 42)
    ready_at_send = []

    def move_when_ready(mouse, *delta, can_send, expires_at):
        now = time.monotonic()
        ready = now >= mouse.next_move_at
        ready_at_send.append(ready)
        if ready and can_send():
            mouse.next_move_at = now + 1 / mouse.max_rate
            return True
        return False

    monkeypatch.setattr(module.Esp32Mouse, "move_relative", move_when_ready)
    release.set()
    runtime.set_active(True)
    wait_for(lambda: len(ready_at_send) >= 4)
    runtime.set_active(False)
    assert all(ready_at_send)


def test_unplug_while_idle(rig):
    runtime, _, _, _, ports = rig
    ports.clear()
    wait_for(lambda: not runtime.snapshot()["connected"])
    assert "拔出" in runtime.snapshot()["message"]


def test_parameters_locked_while_active(rig):
    runtime, _, release, _, _ = rig
    release.set()
    runtime.set_active(True)
    with pytest.raises(ValueError):
        runtime.configure(replace(Settings(), rate=30), 42)


def test_foreground_loss_pauses_capture(rig, monkeypatch):
    runtime, entered, release, writes, _ = rig
    monkeypatch.setattr(module, "capture_region", lambda *args: None)
    runtime.set_active(True)
    wait_for(lambda: "前台" in runtime.snapshot()["message"])
    assert not entered.is_set()
    assert writes == []


def test_capture_failure_preserves_device(rig, monkeypatch):
    runtime, _, _, writes, _ = rig

    def fail(*args):
        raise RuntimeError("capture unavailable")

    monkeypatch.setattr(module, "capture_region", fail)
    runtime.set_active(True)
    wait_for(lambda: runtime.snapshot()["status"] == "capture_error")
    assert runtime.snapshot()["connected"]
    assert not runtime.snapshot()["active"]
    assert "capture unavailable" in runtime.snapshot()["message"]
    assert writes == []


def test_preview_without_device_and_f8_stop(rig):
    runtime, entered, release, writes, _ = rig
    runtime.disconnect()
    wait_for(lambda: not runtime.snapshot()["connected"])
    release.set()
    runtime.set_preview(True)
    wait_for(lambda: runtime.snapshot()["preview"] is not None)
    state = runtime.snapshot()
    assert state["status"] == "preview"
    assert state["preview_enabled"] and not state["active"]
    assert state["metrics"]["fps"] > 0
    assert state["metrics"]["output_fps"] == 0
    assert state["metrics"]["ack"] is None
    assert writes == []
    runtime.set_active(False, "F8")
    assert not runtime.snapshot()["preview_enabled"]
    assert runtime.snapshot()["preview"] is None


def test_preview_with_device_cannot_be_promoted_by_hotkey(rig):
    runtime, _, release, writes, _ = rig
    release.set()
    runtime.set_preview(True)
    wait_for(lambda: runtime.snapshot()["preview"] is not None)
    with pytest.raises(ValueError, match="预览"):
        runtime.set_active(True, "Caps Lock")
    with pytest.raises(ValueError):
        runtime.configure(Settings(), 42)
    assert writes == []


@pytest.mark.parametrize("phase", ["load", "inference"])
def test_model_errors_preserve_device_and_allow_retry(rig, monkeypatch, phase):
    runtime, _, release, writes, _ = rig
    working_detector = module.Detector

    class FailingDetector:
        def __init__(self, settings):
            if phase == "load":
                raise ValueError("bad model")

        def detect(self, *args):
            raise ValueError("bad model")

    monkeypatch.setattr(module, "Detector", FailingDetector)
    runtime.set_active(True)
    wait_for(lambda: runtime.snapshot()["status"] == "model_error")
    assert runtime.snapshot()["connected"]
    assert not runtime.snapshot()["active"]
    assert writes == []
    monkeypatch.setattr(module, "Detector", working_detector)
    release.set()
    runtime.set_active(True)
    wait_for(lambda: len(writes) > 0)


def test_window_geometry_pause_recovers_without_reconnecting(rig, monkeypatch):
    runtime, _, release, writes, _ = rig
    valid_region = module.capture_region

    def unavailable(*args):
        raise module.WindowCaptureError("resize window")

    monkeypatch.setattr(module, "capture_region", unavailable)
    runtime.set_active(True)
    wait_for(lambda: runtime.snapshot()["status"] == "waiting_window")
    assert runtime.snapshot()["connected"] and runtime.snapshot()["active"]
    assert writes == []
    monkeypatch.setattr(module, "capture_region", valid_region)
    release.set()
    wait_for(lambda: len(writes) > 0)


def test_closed_window_stops_but_keeps_device(rig, monkeypatch):
    runtime, _, _, _, _ = rig

    def closed(*args):
        raise module.WindowClosedError("window closed")

    monkeypatch.setattr(module, "capture_region", closed)
    runtime.set_active(True)
    wait_for(lambda: runtime.snapshot()["status"] == "window_error")
    assert runtime.snapshot()["connected"] and not runtime.snapshot()["active"]


def test_slow_inference_result_is_expired(rig, monkeypatch):
    runtime, entered, release, writes, _ = rig

    class SlowDetector:
        def __init__(self, settings):
            pass

        def detect(self, *args):
            entered.set()
            assert release.wait(3)
            release.clear()  # Block the next frame until fixture teardown.
            return [Detection(180, 130, 220, 230, .9)]

    monkeypatch.setattr(module, "Detector", SlowDetector)
    runtime.configure(replace(Settings(), result_max_age_ms=20), 42)
    runtime.set_active(True)
    assert entered.wait(2)
    time.sleep(.04)
    release.set()
    wait_for(lambda: runtime.snapshot()["metrics"]["expired"] >= 1)
    assert writes == []
    assert runtime.snapshot()["metrics"]["latency_p95"] > 20


def test_vision_does_not_wait_for_output_slot(rig, monkeypatch):
    runtime, _, release, _, _ = rig
    calls = []

    def slow_output(mouse, *delta, can_send, expires_at):
        if not can_send():
            return False
        calls.append(delta)
        mouse.next_move_at = time.monotonic() + 1
        return True

    monkeypatch.setattr(module.Esp32Mouse, "move_relative", slow_output)
    runtime.configure(replace(Settings(), rate=120), 42)
    release.set()
    runtime.set_active(True)
    wait_for(lambda: len(calls) == 1)
    with runtime.lock:
        frames_before = len(runtime.frame_times)
    wait_for(lambda: len(runtime.frame_times) >= frames_before + 6, timeout=.8)
    assert len(calls) == 1


def test_latest_result_is_consumed_once_and_stale_mailbox_is_discarded(rig, monkeypatch):
    runtime, entered, _, _, _ = rig
    calls = []
    def move(mouse, *delta, can_send, expires_at):
        if not can_send():
            return False
        calls.append(delta)
        return True

    monkeypatch.setattr(module.Esp32Mouse, "move_relative", move)
    runtime.set_active(True)
    assert entered.wait(2)  # Keep vision blocked while exercising the device worker.
    with runtime.lock:
        runtime.latest = module.Result(runtime.epoch, time.monotonic() - 1, (20, 0))
    wait_for(lambda: runtime.snapshot()["metrics"]["expired"] == 1)
    assert calls == []
    with runtime.lock:
        runtime.latest = module.Result(runtime.epoch, time.monotonic(), (10, 0))
        runtime.latest = module.Result(runtime.epoch, time.monotonic(), (25, 0))
    wait_for(lambda: len(calls) == 1)
    time.sleep(.06)
    assert calls == [(25, 0)]
    assert runtime.snapshot()["metrics"]["age"] <= 100


def test_new_result_replaces_selection_before_write(rig, monkeypatch):
    runtime, entered, _, writes, _ = rig
    selected = threading.Event()
    resume = threading.Event()
    move_relative = module.Esp32Mouse.move_relative

    def delayed_move(mouse, dx, dy, **kwargs):
        if dx > 0:
            selected.set()
            assert resume.wait(2)
        return move_relative(mouse, dx, dy, **kwargs)

    monkeypatch.setattr(module.Esp32Mouse, "move_relative", delayed_move)
    runtime.set_active(True)
    assert entered.wait(2)
    try:
        with runtime.lock:
            runtime.latest = module.Result(runtime.epoch, time.monotonic(), (25, 0))
        assert selected.wait(2)
        with runtime.lock:
            runtime.latest = module.Result(runtime.epoch, time.monotonic(), (-25, 0))
    finally:
        resume.set()
    wait_for(lambda: runtime.snapshot()["metrics"]["moves"] == 1)
    assert writes == [b"a"]


def test_cpu_thread_change_reloads_cached_model(rig, monkeypatch):
    runtime, _, release, _, _ = rig
    original = module.Detector
    loaded = []

    def detector(settings):
        loaded.append(settings.cpu_threads)
        return original(settings)

    monkeypatch.setattr(module, "Detector", detector)
    release.set()
    for threads in (0, 8):
        runtime.configure(replace(Settings(), cpu_threads=threads), 42)
        runtime.set_preview(True)
        wait_for(lambda: runtime.snapshot()["preview"] is not None)
        runtime.set_preview(False)
    assert loaded == [0, 8]


@pytest.mark.parametrize("failure", ["SEND", None])
def test_xy_write_and_ack_statistics_are_separate(rig, monkeypatch, failure):
    runtime, entered, _, _, _ = rig
    runtime.disconnect()
    wait_for(lambda: not runtime.snapshot()["connected"])
    board = module.open_board("COM_TEST")
    move_status = "OK"
    response = b""

    def write(data):
        nonlocal response
        kind, token, seq, *_ = decode_frame(data.splitlines()[-1])
        status = move_status if kind == "M" else "STATUS"
        if status is not None:
            response = encode_frame(f"A {token} {seq} 1000 1 {status}")
            board.in_waiting = len(response)
        return len(data)

    def read(count):
        board.in_waiting = 0
        return response

    def negotiate(mouse):
        mouse.protocol = "xy1"
        mouse.ble_connected = True
        mouse.reply_at = time.monotonic()
        return mouse.protocol

    monkeypatch.setattr(board, "write", write)
    monkeypatch.setattr(board, "read", read, raising=False)
    monkeypatch.setattr(module.Esp32Mouse, "negotiate", negotiate)
    runtime.connect(board.port)
    wait_for(lambda: runtime.snapshot()["connected"])
    runtime.set_active(True)
    assert entered.wait(2)

    for index, move_status in enumerate(("OK", "EXPIRED", "BUSY", failure), start=1):
        with runtime.lock:
            runtime.latest = module.Result(runtime.epoch, time.monotonic(), (20, 0))
        if index < 4:
            wait_for(lambda: (stats := runtime.snapshot()["metrics"])["accepted"] + stats["rejected"] == index)

    wait_for(lambda: not runtime.snapshot()["connected"])
    state = runtime.snapshot()
    assert state["status"] == "device_error"
    metrics = state["metrics"]
    assert (metrics["moves"], metrics["accepted"], metrics["rejected"]) == (4, 1, 2 + (failure is not None))
    assert (metrics["rejected_expired"], metrics["rejected_busy"], metrics["expired"]) == (1, 1, 0)
    assert metrics["ack_timeouts"] == int(failure is None)


def test_device_polling_continues_during_inference(rig, monkeypatch):
    runtime, entered, _, _, _ = rig
    polls = []
    monkeypatch.setattr(module.Esp32Mouse, "poll", lambda mouse: polls.append(time.monotonic()))
    runtime.set_active(True)
    assert entered.wait(2)
    count = len(polls)
    wait_for(lambda: len(polls) >= count + 5, timeout=.5)


def test_focus_loss_discards_queued_result(rig, monkeypatch):
    runtime, entered, _, writes, _ = rig
    runtime.set_active(True)
    assert entered.wait(2)
    monkeypatch.setattr(module, "user32", lambda: SimpleNamespace(GetForegroundWindow=lambda: 7))
    with runtime.lock:
        runtime.latest = module.Result(runtime.epoch, time.monotonic(), (40, 0))
    wait_for(lambda: runtime.latest is None)
    assert writes == []


def test_serial_failure_does_not_stop_preview(rig, monkeypatch):
    runtime, _, release, writes, _ = rig
    release.set()
    runtime.set_preview(True)
    wait_for(lambda: runtime.snapshot()["preview"] is not None)

    def fail(mouse):
        raise OSError("device gone")

    monkeypatch.setattr(module.Esp32Mouse, "poll", fail)
    wait_for(lambda: not runtime.snapshot()["connected"])
    assert runtime.snapshot()["preview_enabled"]
    assert runtime.snapshot()["status"] == "preview"
    assert writes == []


def test_bluetooth_loss_keeps_serial_and_requires_manual_restart(rig, monkeypatch):
    runtime, entered, _, writes, _ = rig
    runtime.set_active(True)
    assert entered.wait(2)
    connected = [False]

    def poll(mouse):
        mouse.ble_connected = connected[0]

    monkeypatch.setattr(module.Esp32Mouse, "poll", poll)
    wait_for(lambda: runtime.snapshot()["status"] == "waiting_bluetooth")
    assert runtime.snapshot()["connected"] and not runtime.snapshot()["active"]
    connected[0] = True
    wait_for(lambda: runtime.snapshot()["status"] == "idle")
    assert not runtime.snapshot()["active"] and writes == []


def test_bluetooth_rejection_keeps_serial(rig, monkeypatch):
    runtime, entered, _, _, _ = rig
    runtime.set_active(True)
    assert entered.wait(2)
    calls = []

    def poll(mouse):
        mouse.ble_connected = False
        if not calls:
            calls.append(True)
            raise module.BleDisconnectedError("BLE")

    monkeypatch.setattr(module.Esp32Mouse, "poll", poll)
    wait_for(lambda: runtime.snapshot()["status"] == "waiting_bluetooth")
    assert runtime.snapshot()["connected"] and not runtime.snapshot()["active"]


def test_write_failure_disconnects(rig, monkeypatch):
    runtime, _, release, _, _ = rig

    def fail(*args, **kwargs):
        raise OSError("write failed")

    monkeypatch.setattr(module.Esp32Mouse, "move_relative", fail)
    release.set()
    runtime.set_active(True)
    wait_for(lambda: not runtime.snapshot()["connected"])
    assert not runtime.snapshot()["active"]
    assert "write failed" in runtime.snapshot()["message"]
