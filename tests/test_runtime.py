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


def test_stop_discards_inflight_inference(rig):
    runtime, entered, release, writes, _ = rig
    runtime.set_active(True)
    assert entered.wait(2)
    runtime.set_active(False)
    release.set()
    time.sleep(.15)
    assert writes == []
    assert runtime.snapshot()["preview"] is None


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

    def move_when_ready(mouse, *delta):
        now = time.monotonic()
        ready = now >= mouse.next_move_at
        ready_at_send.append(ready)
        if ready:
            mouse.next_move_at = now + 1 / mouse.max_rate
        return ready

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


def test_capture_failure_disconnects(rig, monkeypatch):
    runtime, _, _, writes, _ = rig

    def fail(*args):
        raise RuntimeError("capture unavailable")

    monkeypatch.setattr(module, "capture_region", fail)
    runtime.set_active(True)
    wait_for(lambda: not runtime.snapshot()["connected"])
    assert not runtime.snapshot()["active"]
    assert "capture unavailable" in runtime.snapshot()["message"]
    assert writes == []


def test_write_failure_disconnects(rig, monkeypatch):
    runtime, _, release, _, _ = rig

    def fail(*args):
        raise OSError("write failed")

    monkeypatch.setattr(module.Esp32Mouse, "move_relative", fail)
    release.set()
    runtime.set_active(True)
    wait_for(lambda: not runtime.snapshot()["connected"])
    assert not runtime.snapshot()["active"]
    assert "write failed" in runtime.snapshot()["message"]
