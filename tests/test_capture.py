import unittest
from unittest.mock import Mock, patch

from gameSelection import CaptureSession, capture_region, gameSelection, select_window
from runtime import Settings


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.windows = Mock()
        self.windows.IsWindow.return_value = True
        self.windows.IsIconic.return_value = False
        self.windows.GetForegroundWindow.return_value = 7
        self.windows.GetClientRect.return_value = (0, 0, 800, 600)
        self.origin = [100, 100]
        self.windows.ClientToScreen.side_effect = lambda hwnd, point: (point[0] + self.origin[0], point[1] + self.origin[1])
        self.camera = Mock()
        self.camera.is_capturing = True
        self.camera._BetterCam__frame_available.wait.return_value = True
        self.capture = CaptureSession(self.camera, 7, Settings(), self.windows, (0, 0, 1920, 1080))

    def test_monitor_relative_coordinates_and_boundary_checks(self):
        self.assertEqual(capture_region((-1700, 100, -900, 700), (-1920, 0, 0, 1080), 320, 320),
                         (460, 240, 780, 560))
        self.assertIsNone(capture_region((0, 0, 100, 100), (0, 0, 1920, 1080), 320, 320))
        self.assertIsNone(capture_region((-1000, 0, -200, 600), (0, 0, 1920, 1080), 320, 320))

    def test_move_restarts_capture_and_invalidates_previous_frame(self):
        self.capture.read()
        self.assertTrue(self.capture.is_current())
        self.assertEqual(self.capture.revision, 1)
        self.origin[0] += 100
        self.assertFalse(self.capture.is_current())
        self.capture.read()
        self.assertEqual(self.capture.revision, 2)
        self.camera.stop.assert_called_once()
        self.assertEqual(self.camera.start.call_count, 2)
        self.assertFalse(self.camera.start.call_args.kwargs["video_mode"])

    @patch("gameSelection.time.sleep")
    def test_focus_loss_pauses_capture_and_resume_restarts_it(self, sleep):
        self.capture.read()
        self.windows.GetForegroundWindow.return_value = 99
        self.assertFalse(self.capture.is_current())
        self.assertIsNone(self.capture.read())
        self.camera.stop.assert_called_once()
        self.windows.GetForegroundWindow.return_value = 7
        self.capture.read()
        self.assertEqual(self.camera.start.call_count, 2)

    @patch("gameSelection.time.sleep")
    def test_minimized_and_off_output_windows_pause(self, sleep):
        self.windows.IsIconic.return_value = True
        self.assertIsNone(self.capture.read())
        self.windows.IsIconic.return_value = False
        self.origin[0] = -1500
        self.assertIsNone(self.capture.read())
        self.camera.start.assert_not_called()

    def test_static_desktop_wait_is_bounded(self):
        self.camera._BetterCam__frame_available.wait.return_value = False
        self.assertIsNone(self.capture.read())
        self.camera._BetterCam__frame_available.wait.assert_called_once_with(timeout=.1)
        self.camera.get_latest_frame.assert_not_called()

    def test_closed_window_and_dead_worker_are_reported(self):
        self.windows.IsWindow.return_value = False
        with self.assertRaisesRegex(RuntimeError, "closed"):
            self.capture.read()
        self.windows.IsWindow.return_value = True
        self.camera.is_capturing = False
        with self.assertRaisesRegex(RuntimeError, "worker"):
            self.capture.read()

    def test_close_is_idempotent(self):
        self.capture.close()
        self.capture.close()
        self.camera.release.assert_called_once()

    def test_selection_rejects_negative_non_numeric_and_out_of_range(self):
        window = Mock(title="Example", isMinimized=False)
        module = Mock()
        module.getAllWindows.return_value = [window]
        with patch.dict("sys.modules", {"pygetwindow": module}), patch("builtins.input", side_effect=["-1", "abc", "5", "0"]):
            self.assertIs(select_window(), window)
        window.activate.assert_called_once()

    def test_legacy_tuple_api_preserves_repeated_frame_mode(self):
        capture = Mock()
        capture._window_region.return_value = (0, 0, 320, 320)
        with patch("gameSelection.open_capture", return_value=capture):
            camera, width, height = gameSelection()
        self.assertIs(camera, capture.camera)
        self.assertEqual((width, height), (160, 160))
        self.assertTrue(camera.start.call_args.kwargs["video_mode"])

    def test_legacy_start_failure_releases_capture(self):
        capture = Mock()
        capture.camera.start.side_effect = RuntimeError("capture failed")
        with patch("gameSelection.open_capture", return_value=capture):
            with self.assertRaisesRegex(RuntimeError, "capture failed"):
                gameSelection()
        capture.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
