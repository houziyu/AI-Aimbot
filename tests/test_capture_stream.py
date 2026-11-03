import threading
import time
import unittest
from unittest.mock import Mock

import numpy as np

from capture_stream import LatestFrameStream


class StreamTests(unittest.TestCase):
    def test_capture_timestamp_precedes_grab_completion_and_image_is_owned(self):
        source = np.ones((2, 2, 3), dtype=np.uint8)
        completed = []
        def grab(region):
            completed.append(time.perf_counter())
            return source if len(completed) == 1 else None
        stream = LatestFrameStream(Mock(grab=grab), 120)
        stream.start((0, 0, 2, 2))
        try:
            packet = stream.read(timeout=1)
            self.assertIsNotNone(packet)
            self.assertLessEqual(packet.captured_at, completed[0])
            source[:] = 9
            self.assertTrue((packet.image == 1).all())
            self.assertIsNone(stream.read(timeout=.02))
        finally:
            stream.stop()

    def test_latest_frame_overwrites_unread_old_frame(self):
        third_grab = threading.Event()
        count = 0
        def grab(region):
            nonlocal count
            count += 1
            if count > 2:
                third_grab.set()
                return None
            return np.full((1, 1, 3), count, dtype=np.uint8)
        stream = LatestFrameStream(Mock(grab=grab), 1000)
        stream.start((0, 0, 1, 1))
        try:
            self.assertTrue(third_grab.wait(1))
            packet = stream.read(timeout=.1)
            self.assertTrue((packet.image == 2).all())
        finally:
            stream.stop()

    def test_worker_failure_is_propagated_and_stop_is_idempotent(self):
        stream = LatestFrameStream(Mock(grab=Mock(side_effect=ValueError("driver failure"))), 120)
        stream.start((0, 0, 1, 1))
        try:
            with self.assertRaisesRegex(RuntimeError, "worker"):
                stream.read(timeout=1)
        finally:
            stream.stop()
            stream.stop()


if __name__ == "__main__":
    unittest.main()
