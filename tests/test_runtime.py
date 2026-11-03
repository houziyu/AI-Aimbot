import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from runtime import (PerformanceStats, Settings, detections_to_targets, model_path,
                     prepare_frame, select_target, validate_input_shape)


class FrameTests(unittest.TestCase):
    def test_bgra_red_is_rgb_and_capture_is_not_modified(self):
        settings = Settings(screenShotWidth=2, screenShotHeight=1)
        source = np.array([[[0, 0, 255, 255], [255, 0, 0, 255]]], dtype=np.uint8)
        original = source.copy()
        rgb, bgr = prepare_frame(source, settings)
        np.testing.assert_array_equal(rgb[:, 0, 0], [255, 0, 0])
        np.testing.assert_array_equal(rgb[:, 0, 1], [0, 0, 255])
        np.testing.assert_array_equal(bgr, original[:, :, :3])
        np.testing.assert_array_equal(source, original)
        self.assertTrue(rgb.flags.c_contiguous)

    def test_bgr_and_bgra_produce_same_rgb(self):
        frame = np.arange(24, dtype=np.uint8).reshape(2, 3, 4)
        settings = Settings(screenShotWidth=3, screenShotHeight=2)
        np.testing.assert_array_equal(prepare_frame(frame, settings)[0], prepare_frame(frame[:, :, :3], settings)[0])

    def test_mask_sides_and_source_ownership(self):
        source = np.full((3, 4, 4), 255, dtype=np.uint8)
        for side, x in (("LEFT", 0), ("right", 3)):
            settings = Settings(screenShotWidth=4, screenShotHeight=3, useMask=True,
                                maskSide=side, maskWidth=1, maskHeight=2)
            settings.validate()
            _, bgr = prepare_frame(source, settings)
            self.assertTrue((bgr[-2:, x] == 0).all())
            self.assertTrue((bgr[0] == 255).all())
            self.assertTrue((source == 255).all())

    def test_bad_frame_and_wrong_size_are_rejected(self):
        for frame in (None, np.zeros((320, 320, 4)), np.zeros((1, 1, 4), dtype=np.uint8)):
            with self.subTest(frame_type=type(frame)):
                with self.assertRaises(ValueError):
                    prepare_frame(frame, Settings())


class TargetTests(unittest.TestCase):
    def setUp(self):
        self.targets = np.array([[150, 160, 20, 60, .95], [250, 160, 20, 60, .90]], dtype=np.float32)

    def test_previous_coordinates_override_center_and_confidence(self):
        for center_mode in (True, False):
            selected = select_target(self.targets, (160, 160), (250, 160), center_mode)
            np.testing.assert_array_equal(selected[:2], [250, 160])

    def test_first_target_uses_center_or_input_order(self):
        targets = self.targets[::-1]
        self.assertEqual(select_target(targets, (160, 160))[0], 150)
        self.assertEqual(select_target(targets, (160, 160), center_of_screen=False)[0], 250)

    def test_empty_frame_clears_selection(self):
        self.assertIsNone(select_target(np.empty((0, 5)), (160, 160), (250, 160)))

    def test_coordinates_stay_in_pixels_and_invalid_boxes_are_removed(self):
        boxes = np.array([[100, 120, 140, 200, .8, 0], [1, 1, 0, 2, .9, 0],
                          [0, 0, np.nan, 10, .9, 0]], dtype=np.float32)
        result = detections_to_targets(boxes)
        self.assertEqual(result.shape, (1, 5))
        np.testing.assert_allclose(result[0], [120, 160, 40, 80, .8])


class SettingsTests(unittest.TestCase):
    def test_config_module_remains_compatible(self):
        settings = Settings.from_module(SimpleNamespace(confidence=.6))
        self.assertEqual(settings.confidence, .6)
        self.assertEqual(settings.captureBuffer, 4)

    def test_invalid_values_fail_before_capture(self):
        for changes in ({"screenShotWidth": 0}, {"captureBuffer": 1}, {"captureFps": 1001},
                        {"confidence": float("nan")}, {"iouThreshold": 2}, {"onnxChoice": 4},
                        {"aaQuitKey": "QUIT"}, {"aaMovementAmp": -1}, {"visuals": "False"},
                        {"useMask": True, "maskWidth": 0}, {"useMask": True, "maskHeight": 321},
                        {"useMask": True, "maskSide": "top"}, {"captureOutput": -1}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    replace(Settings(), **changes).validate()

    def test_fixed_and_dynamic_model_input_shapes(self):
        validate_input_shape([1, 3, 320, 320], Settings().input_shape)
        validate_input_shape(["batch", 3, None, -1], Settings().input_shape)
        for shape in ([1, 3, 640, 640], [1, 320, 320, 3], [3, 320, 320], [2, 3, 320, 320]):
            with self.assertRaises(ValueError):
                validate_input_shape(shape, Settings().input_shape)

    def test_relative_models_resolve_from_project(self):
        self.assertTrue(model_path("yolov5s.pt").is_absolute())
        self.assertEqual(model_path("yolov5s.pt").parent, Path(__file__).resolve().parents[1])

    def test_latency_history_is_bounded(self):
        stats = PerformanceStats(capacity=2)
        for value in (100, .001, .003):
            stats.record({"total": value})
        self.assertEqual(len(stats.samples), 2)
        self.assertIn("avg 2.00 ms", stats.summary())
        self.assertIn("p95 2.90 ms", stats.summary())


if __name__ == "__main__":
    unittest.main()
