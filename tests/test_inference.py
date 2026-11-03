import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import torch

from inference import Backend, OnnxBackend, TorchBackend
from runtime import Settings


class BackendTests(unittest.TestCase):
    def make_onnx(self, dtype="tensor(float16)", shape=(1, 3, 320, 320), choice=1, active=None):
        ort = Mock()
        provider = OnnxBackend.PROVIDERS[choice]
        ort.get_available_providers.return_value = [provider, "CPUExecutionProvider"]
        session = ort.InferenceSession.return_value
        session.get_inputs.return_value = [SimpleNamespace(name="custom_input", type=dtype, shape=shape)]
        session.get_outputs.return_value = [SimpleNamespace(name="custom_output", shape=[1, 6300, 85])]
        session.get_providers.return_value = active if active is not None else [provider]
        session.run.return_value = [np.zeros((1, 6300, 85), dtype=np.float16)]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "model.onnx"
            path.touch()
            settings = Settings(onnxWeights=str(path), onnxChoice=choice)
            with patch("inference.require_module", return_value=ort):
                backend = OnnxBackend(settings)
        return backend, ort

    def test_onnx_uses_metadata_names_and_dtype(self):
        for dtype, expected in (("tensor(float16)", np.float16), ("tensor(float)", np.float32)):
            backend, ort = self.make_onnx(dtype=dtype)
            source = np.full((3, 320, 320), 255, dtype=np.uint8)
            image = backend.preprocess(source)
            self.assertEqual(image.dtype, expected)
            self.assertEqual(image.shape, (1, 3, 320, 320))
            self.assertTrue(image.flags.c_contiguous)
            self.assertTrue((image == 1).all())
            self.assertTrue((source == 255).all())
            backend.infer(image)
            names, feed = backend.session.run.call_args.args
            self.assertEqual(names, ["custom_output"])
            self.assertIs(feed["custom_input"], image)
            backend.session.disable_fallback.assert_called_once()

    def test_onnx_rejects_shape_and_dtype_mismatches(self):
        for kwargs in ({"shape": [1, 3, 640, 640]}, {"dtype": "tensor(uint8)"}):
            with self.assertRaises(ValueError):
                self.make_onnx(**kwargs)

    def test_unavailable_provider_fails_instead_of_falling_back(self):
        ort = Mock()
        ort.get_available_providers.return_value = ["CPUExecutionProvider"]
        with patch("inference.require_module", return_value=ort):
            with self.assertRaisesRegex(RuntimeError, "unavailable"):
                OnnxBackend(Settings(onnxChoice=3))
        ort.InferenceSession.assert_not_called()

    def test_session_fallback_is_reported(self):
        with self.assertRaisesRegex(RuntimeError, "did not activate"):
            self.make_onnx(choice=2, active=["CPUExecutionProvider"])

    def test_directml_session_options_are_explicit(self):
        _, ort = self.make_onnx(choice=2)
        options = ort.InferenceSession.call_args.kwargs["sess_options"]
        self.assertFalse(options.enable_mem_pattern)
        self.assertEqual(options.execution_mode, ort.ExecutionMode.ORT_SEQUENTIAL)

    def test_torch_preprocessing_matches_onnx(self):
        source = np.arange(3 * 320 * 320, dtype=np.uint8).reshape(3, 320, 320)
        for dtype in (torch.float16, torch.float32):
            backend = TorchBackend.__new__(TorchBackend)
            backend.torch, backend.device, backend.dtype = torch, torch.device("cpu"), dtype
            image = backend.preprocess(source)
            self.assertEqual(image.dtype, dtype)
            self.assertTrue(image.is_contiguous())
            np.testing.assert_allclose(image.numpy(), source[None].astype(image.numpy().dtype) / 255)

    def test_nms_filters_classes_and_overlapping_boxes(self):
        backend = Backend()
        backend.settings = Settings()
        # Two overlapping people, one separate non-person. Only the best person remains.
        raw = np.array([[[100, 120, 40, 60, .9, .9, .1],
                         [101, 121, 40, 60, .8, .9, .1],
                         [250, 120, 30, 40, .9, .1, .9]]], dtype=np.float32)
        targets = backend.postprocess(raw)
        self.assertEqual(targets.shape, (1, 5))
        np.testing.assert_allclose(targets[0], [100, 120, 40, 60, .81], rtol=1e-5)

    def test_configured_class_is_selected_and_out_of_range_class_fails(self):
        backend = Backend()
        backend.settings = Settings(targetClasses=(1,))
        raw = np.array([[[100, 120, 40, 60, .9, .9, .1],
                         [250, 120, 30, 40, .9, .1, .9]]], dtype=np.float32)
        result = backend.postprocess(raw)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0, 0], 250)
        backend.settings = Settings(targetClasses=(2,))
        with self.assertRaisesRegex(ValueError, "classes"):
            backend.postprocess(raw)


if __name__ == "__main__":
    unittest.main()
