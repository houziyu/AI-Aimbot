import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

import numpy as np

from app import WindowsControls, run_loop
from runtime import CapturedFrame, Settings


class LoopTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(cpsDisplay=False)
        self.clock = 1.0
        timer = patch("app.time.perf_counter", side_effect=lambda: self.clock)
        timer.start()
        self.addCleanup(timer.stop)
        self.capture = Mock(revision=0)
        self.capture.read.return_value = CapturedFrame(np.zeros((320, 320, 4), dtype=np.uint8), .99)
        self.capture.is_current.return_value = True
        self.backend = Mock()
        self.backend.postprocess.return_value = np.array([[200, 180, 40, 60, .9]], dtype=np.float32)
        self.controls = Mock()
        self.controls.should_quit.side_effect = [False, False, True]
        self.controls.enabled.return_value = True
        self.cv2 = Mock()

    def run_loop(self, **changes):
        run_loop(replace(self.settings, **changes), self.backend, self.capture, self.controls, self.cv2)

    def assert_cleaned(self):
        self.capture.close.assert_called_once()
        self.cv2.destroyAllWindows.assert_called_once()

    def test_normal_exit_cleans_up(self):
        self.run_loop()
        self.controls.move.assert_called_once_with(16, -1)
        self.assert_cleaned()

    def test_focus_loss_during_inference_blocks_input(self):
        self.capture.is_current.return_value = False
        self.controls.should_quit.side_effect = [False, True]
        self.run_loop()
        self.controls.move.assert_not_called()
        self.assert_cleaned()

    def test_disabled_toggle_blocks_input(self):
        self.controls.enabled.return_value = False
        self.run_loop()
        self.controls.move.assert_not_called()

    def test_inference_failure_cleans_up_and_propagates(self):
        self.backend.infer.side_effect = RuntimeError("inference failed")
        with self.assertRaisesRegex(RuntimeError, "inference failed"):
            self.run_loop()
        self.assert_cleaned()

    def test_keyboard_interrupt_cleans_up(self):
        self.capture.read.side_effect = KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            self.run_loop()
        self.assert_cleaned()

    def test_invalid_frame_cleans_up(self):
        self.capture.read.return_value = CapturedFrame(np.zeros((10, 10, 4), dtype=np.uint8), .99)
        with self.assertRaises(ValueError):
            self.run_loop()
        self.assert_cleaned()

    def test_preview_quit_uses_configured_key_and_cleans_up(self):
        self.cv2.waitKey.return_value = ord("x")
        self.controls.should_quit.side_effect = [False, False]
        self.run_loop(visuals=True, aaQuitKey="X")
        self.assert_cleaned()

    def test_profiler_syncs_gpu_only_when_enabled(self):
        self.run_loop()
        self.backend.synchronize.assert_not_called()

    def test_enabled_profiler_synchronizes_stage_boundaries(self):
        self.run_loop(performanceDisplay=True)
        self.assertEqual(self.backend.synchronize.call_count, 2)

    def test_no_detections_do_not_move_mouse(self):
        self.backend.postprocess.return_value = np.empty((0, 5), dtype=np.float32)
        self.run_loop()
        self.controls.move.assert_not_called()
        self.assert_cleaned()

    def test_idle_capture_remains_quittable(self):
        self.capture.read.return_value = None
        self.controls.should_quit.side_effect = [False, True]
        self.run_loop()
        self.backend.infer.assert_not_called()
        self.assert_cleaned()

    def test_stale_frame_skips_inference(self):
        self.clock = 2.0
        self.controls.should_quit.side_effect = [False, True]
        self.run_loop()
        self.backend.infer.assert_not_called()
        self.controls.move.assert_not_called()

    def test_inference_stall_blocks_old_result(self):
        def slow_infer(image):
            self.clock += .2
            return None
        self.backend.infer.side_effect = slow_infer
        self.run_loop()
        self.controls.move.assert_not_called()

    def test_timeout_keeps_selection_but_never_sends_old_command(self):
        source = self.capture.read.return_value.image
        frames = iter([(1.0, CapturedFrame(source, 1.0)), (1.1, None),
                       (1.15, CapturedFrame(source, 1.15))])
        def read():
            self.clock, packet = next(frames)
            return packet
        self.capture.read.side_effect = read
        self.backend.postprocess.side_effect = [np.array([[240, 160, 20, 40, .9]]),
                                               np.array([[160, 160, 20, 40, .9], [240, 160, 20, 40, .9]])]
        self.controls.should_quit.side_effect = [False, False, False, False, False, True]
        self.run_loop(headAimOffset=0, targetRadius=0)
        self.assertEqual(self.controls.move.call_count, 2)
        self.assertEqual(self.controls.move.call_args_list[0].args, (32, 0))
        self.assertEqual(self.controls.move.call_args_list[1].args, (32, 0))

    def test_preview_quit_works_during_capture_timeout(self):
        self.capture.read.return_value = None
        self.controls.should_quit.side_effect = [False]
        self.cv2.waitKey.return_value = ord("q")
        self.run_loop(visuals=True)
        self.assert_cleaned()


class ControlsTests(unittest.TestCase):
    def test_caps_lock_reads_toggle_bit_not_key_down_bit(self):
        api, constants = Mock(), Mock(MOUSEEVENTF_MOVE=1)
        with patch.dict("sys.modules", {"win32api": api, "win32con": constants}):
            controls = WindowsControls("q")
        api.GetKeyState.return_value = 0x8000
        self.assertFalse(controls.enabled())
        api.GetKeyState.return_value = 1
        self.assertTrue(controls.enabled())
        api.GetAsyncKeyState.return_value = 0x8000
        self.assertTrue(controls.should_quit())
        api.GetAsyncKeyState.assert_called_with(ord("Q"))


if __name__ == "__main__":
    unittest.main()
