"""Backend adapters: shared RGB input and YOLOv5 postprocessing, no screen or input access."""

import importlib
import os

import numpy as np

from runtime import detections_to_targets, model_path, validate_input_shape


def require_module(name, install_hint):
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        raise RuntimeError(f"Cannot load {name}. {install_hint}") from exc


class Backend:
    def synchronize(self):
        pass

    def warmup(self):
        image = np.zeros(self.settings.input_shape[1:], dtype=np.uint8)
        self.postprocess(self.infer(self.preprocess(image)))
        self.synchronize()

    def postprocess(self, prediction):
        import torch
        from utils.general import non_max_suppression

        if isinstance(prediction, np.ndarray):
            prediction = torch.from_numpy(prediction)
        with torch.inference_mode():
            detections = non_max_suppression(
                prediction, self.settings.confidence, self.settings.iouThreshold,
                classes=[0], max_det=self.settings.maxDetections,
            )[0]
        # One bulk transfer after NMS, rather than synchronizing for every coordinate.
        return detections_to_targets(detections.detach().float().cpu().numpy())


class TorchBackend(Backend):
    def __init__(self, settings, engine=False):
        self.settings = settings
        self.torch = require_module("torch", "Install PyTorch and torchvision before running this entry point.")
        use_cuda = self.torch.cuda.is_available()
        if engine:
            if not use_cuda:
                raise RuntimeError("TensorRT requires an available CUDA GPU")
            trt = require_module("tensorrt", "Install the TensorRT 8 bindings matching your Python and CUDA environment.")
            if not hasattr(trt.ICudaEngine, "num_bindings"):
                raise RuntimeError("The bundled TensorRT adapter requires TensorRT 8; re-export the engine in that environment")
        self.device = self.torch.device("cuda:0" if use_cuda else "cpu")
        weights = model_path(settings.tensorrtWeights if engine else settings.modelWeights)
        if engine and not weights.is_file():
            raise FileNotFoundError(f"TensorRT model not found: {weights}")
        if not engine and weights.suffix.lower() != ".pt":
            raise ValueError("main.py expects .pt weights; use the ONNX or TensorRT entry point for other formats")
        from models.common import AutoShape, DetectMultiBackend

        self.backend = DetectMultiBackend(str(weights), device=self.device, data="", fp16=use_cuda)
        self.model = self.backend if engine else AutoShape(self.backend, verbose=False)
        if engine:
            validate_input_shape(self.backend.bindings["images"].shape, settings.input_shape)
        else:
            stride = int(self.backend.stride)
            if any(size % stride for size in settings.input_shape[2:]):
                raise ValueError(f"Screenshot dimensions must be multiples of the model stride ({stride})")
        self.dtype = self.torch.float16 if self.backend.fp16 else self.torch.float32
        self.description = f"{'TensorRT' if engine else 'PyTorch'} | {self.device} | {self.dtype} | {settings.input_shape} | {weights.name}"

    def preprocess(self, rgb_chw):
        return self.torch.from_numpy(rgb_chw).unsqueeze(0).to(device=self.device, dtype=self.dtype).div_(255)

    def infer(self, image):
        with self.torch.inference_mode():
            return self.model(image)

    def synchronize(self):
        if self.device.type == "cuda":
            self.torch.cuda.synchronize(self.device)


class OnnxBackend(Backend):
    PROVIDERS = {1: "CPUExecutionProvider", 2: "DmlExecutionProvider", 3: "CUDAExecutionProvider"}

    def __init__(self, settings):
        self.settings = settings
        ort = require_module("onnxruntime", "Install one requirements-onnx-*.txt backend file.")
        provider = self.PROVIDERS[settings.onnxChoice]
        available = ort.get_available_providers()
        if provider not in available:
            raise RuntimeError(f"Requested ONNX provider {provider} is unavailable. Available: {available}. Install the matching requirements-onnx-*.txt file.")
        weights = model_path(settings.onnxWeights)
        if not weights.is_file():
            raise FileNotFoundError(f"ONNX model not found: {weights}")
        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        if provider == "DmlExecutionProvider":
            options.enable_mem_pattern = False
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        self.session = ort.InferenceSession(str(weights), sess_options=options, providers=[provider])
        self.session.disable_fallback()
        active = self.session.get_providers()
        if not active or active[0] != provider:
            raise RuntimeError(f"ONNX did not activate {provider}; active providers: {active}")
        inputs = self.session.get_inputs()
        if len(inputs) != 1:
            raise ValueError("Expected a YOLOv5 model with one image input")
        input_meta = inputs[0]
        validate_input_shape(input_meta.shape, settings.input_shape)
        dtypes = {"tensor(float16)": np.float16, "tensor(float)": np.float32}
        if input_meta.type not in dtypes:
            raise ValueError(f"Unsupported ONNX input type: {input_meta.type}")
        self.dtype = dtypes[input_meta.type]
        self.input_name = input_meta.name
        output_meta = self.session.get_outputs()[0]
        if len(output_meta.shape) != 3:
            raise ValueError("Expected raw YOLOv5 output with shape [batch, boxes, 5 + classes]")
        self.output_name = output_meta.name
        self.description = f"ONNX | {provider} | {input_meta.type} | {input_meta.shape} | {weights.name}"

    def preprocess(self, rgb_chw):
        # ORT accepts host memory directly: no Torch/CuPy upload-download-upload cycle.
        image = np.ascontiguousarray(rgb_chw[None], dtype=self.dtype)
        image /= 255
        return image

    def infer(self, image):
        return self.session.run([self.output_name], {self.input_name: image})[0]


def create_backend(name, settings):
    settings.validate()
    # Optional export backends must never install or upgrade packages at runtime.
    os.environ["YOLOv5_AUTOINSTALL"] = "false"
    os.environ["YOLO_AUTOINSTALL"] = "false"
    if name == "onnx":
        return OnnxBackend(settings)
    if name in ("torch", "tensorrt"):
        return TorchBackend(settings, engine=name == "tensorrt")
    raise ValueError(f"Unknown inference backend: {name}")
