import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

from replay import center_crop, run_replay
from runtime import Settings


class ReplayTests(unittest.TestCase):
    def test_crop_preserves_original_scale_and_rejects_small_recordings(self):
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        image[360, 640] = 255
        crop = center_crop(image, Settings())
        np.testing.assert_array_equal(crop[160, 160], [255, 255, 255])
        with self.assertRaises(ValueError):
            center_crop(image[:100], Settings())

    def test_replay_logs_movement_and_rejects_injected_stale_results(self):
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder) / "synthetic_test_only.avi"
            writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), 30, (640, 480))
            self.assertTrue(writer.isOpened())
            for _ in range(12):
                writer.write(np.zeros((480, 640, 3), dtype=np.uint8))
            writer.release()
            backend = Mock(description="Synthetic test detections (not Apex)")
            backend.postprocess.return_value = np.array([[200, 180, 20, 40, .9]], dtype=np.float32)
            for delay in (0, 200):
                output = Path(folder) / str(delay)
                with patch("replay.save_plot"):
                    summary = run_replay(video, Settings(), backend, output, seconds=.4, extra_delay_ms=delay)
                self.assertEqual(summary["violations"], [])
                self.assertTrue((output / "annotated.mp4").is_file())
                with (output / "commands.csv").open() as handle:
                    rows = list(csv.DictReader(handle))
                self.assertGreater(len(rows), 0)
                if delay:
                    self.assertEqual(summary["frames_with_movement"], 0)
                    self.assertGreater(summary["reasons"].get("stale", 0), 0)
                else:
                    self.assertGreater(summary["frames_with_movement"], 0)


if __name__ == "__main__":
    unittest.main()
