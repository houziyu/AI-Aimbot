"""A bounded, timestamped latest-frame producer using BetterCam's public grab API."""

import threading
import time

from runtime import CapturedFrame


class LatestFrameStream:
    def __init__(self, camera, fps):
        self.camera = camera
        self.interval = 1 / fps
        self.condition = threading.Condition()
        self.stop_event = threading.Event()
        self.thread = None
        self.latest = None
        self.error = None

    def start(self, region):
        if self.thread is not None and self.thread.is_alive():
            raise RuntimeError("Capture worker is already running")
        self.latest = self.error = None
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._produce, args=(region,), name="TimestampedCapture", daemon=True)
        self.thread.start()

    def _produce(self, region):
        try:
            while not self.stop_event.is_set():
                started = time.perf_counter()
                image = self.camera.grab(region=region)
                if image is not None:
                    packet = CapturedFrame(image.copy(), started)
                    with self.condition:
                        self.latest = packet  # overwrite, never build an old-frame queue
                        self.condition.notify_all()
                self.stop_event.wait(max(0, self.interval - (time.perf_counter() - started)))
        except Exception as exc:
            with self.condition:
                self.error = exc
                self.condition.notify_all()

    def read(self, timeout=0.1):
        with self.condition:
            self.condition.wait_for(lambda: self.latest is not None or self.error is not None
                                    or self.stop_event.is_set(), timeout)
            if self.error is not None:
                raise RuntimeError("The screen capture worker stopped unexpectedly") from self.error
            packet, self.latest = self.latest, None
            return packet

    def stop(self):
        self.stop_event.set()
        with self.condition:
            self.condition.notify_all()
        if self.thread is not None:
            self.thread.join(timeout=2)
            if self.thread.is_alive():
                # Do not release a device while grab() is still using it.
                raise RuntimeError("Capture worker did not stop; the display driver may be unresponsive")
        self.latest = None
