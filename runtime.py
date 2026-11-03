"""Shared, device-independent frame processing and runtime configuration."""

from collections import deque
from dataclasses import dataclass, fields
from math import isfinite
from pathlib import Path
from typing import Optional

import numpy as np

ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Settings:
    screenShotWidth: int = 320
    screenShotHeight: int = 320
    useMask: bool = False
    maskSide: str = "left"
    maskWidth: int = 80
    maskHeight: int = 200
    aaMovementAmp: float = 0.4
    confidence: float = 0.4
    iouThreshold: float = 0.45
    maxDetections: int = 100
    aaQuitKey: str = "Q"
    headshot_mode: bool = True
    cpsDisplay: bool = True
    performanceDisplay: bool = False
    visuals: bool = False
    centerOfScreen: bool = True
    modelWeights: str = "yolov5s.pt"
    onnxWeights: str = "yolov5s320Half.onnx"
    tensorrtWeights: str = "yolov5s320Half.engine"
    onnxChoice: int = 1
    captureFps: int = 120
    captureBuffer: int = 4
    captureDevice: int = 0
    captureOutput: Optional[int] = None

    @classmethod
    def from_module(cls, module):
        settings = cls(**{f.name: getattr(module, f.name) for f in fields(cls) if hasattr(module, f.name)})
        settings.validate()
        return settings

    @property
    def input_shape(self):
        return (1, 3, self.screenShotHeight, self.screenShotWidth)

    @property
    def center(self):
        return (self.screenShotWidth // 2, self.screenShotHeight // 2)

    def validate(self):
        for name in ("screenShotWidth", "screenShotHeight", "captureFps", "captureBuffer", "maxDetections"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.captureFps > 1000:
            raise ValueError("captureFps must be at most 1000 for BetterCam's timer")
        if self.captureBuffer < 2:
            raise ValueError("captureBuffer must be at least 2")
        for name in ("useMask", "headshot_mode", "cpsDisplay", "performanceDisplay", "visuals", "centerOfScreen"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be True or False")
        for name in ("confidence", "iouThreshold"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")
        if not isinstance(self.aaMovementAmp, (int, float)) or not isfinite(self.aaMovementAmp) or self.aaMovementAmp < 0:
            raise ValueError("aaMovementAmp must be a finite non-negative number")
        if not isinstance(self.aaQuitKey, str) or len(self.aaQuitKey) != 1 or not self.aaQuitKey.isascii() or not self.aaQuitKey.isalnum():
            raise ValueError("aaQuitKey must be one ASCII letter or digit")
        if type(self.onnxChoice) is not int or self.onnxChoice not in (1, 2, 3):
            raise ValueError("onnxChoice must be 1 (CPU), 2 (DirectML), or 3 (CUDA)")
        for name in ("captureDevice", "captureOutput"):
            value = getattr(self, name)
            if name == "captureOutput" and value is None:
                continue
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        for name in ("modelWeights", "onnxWeights", "tensorrtWeights"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name} must be a non-empty path")
        if self.useMask:
            if not isinstance(self.maskSide, str) or self.maskSide.lower() not in ("left", "right"):
                raise ValueError('maskSide must be "left" or "right"')
            for name, maximum in (("maskWidth", self.screenShotWidth), ("maskHeight", self.screenShotHeight)):
                value = getattr(self, name)
                if type(value) is not int or not 0 < value <= maximum:
                    raise ValueError(f"{name} must be between 1 and {maximum} when useMask is enabled")


def model_path(value):
    """Resolve configured local models independently of the current directory."""
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


def validate_input_shape(shape, expected):
    """Accept symbolic/dynamic dimensions, reject incompatible fixed dimensions."""
    if len(shape) != 4:
        raise ValueError(f"Expected a BCHW model input, got {shape}")
    for actual, wanted in zip(shape, expected):
        if isinstance(actual, (int, np.integer)) and actual > 0 and actual != wanted:
            raise ValueError(f"Model input {tuple(shape)} does not match configured input {tuple(expected)}")


def prepare_frame(frame, settings):
    """Return RGB CHW uint8 for inference and BGR HWC for display, without mutating capture data."""
    if not isinstance(frame, np.ndarray) or frame.dtype != np.uint8 or frame.ndim != 3 or frame.shape[2] not in (3, 4):
        raise ValueError("Capture must return a uint8 BGR or BGRA image")
    if frame.shape[:2] != (settings.screenShotHeight, settings.screenShotWidth):
        raise ValueError(f"Unexpected capture size {frame.shape[:2]}; expected {settings.input_shape[2:]}")
    bgr = frame[:, :, :3]
    if settings.useMask:
        bgr = bgr.copy()
        columns = slice(-settings.maskWidth, None) if settings.maskSide.lower() == "right" else slice(0, settings.maskWidth)
        bgr[-settings.maskHeight:, columns] = 0
    rgb_chw = np.ascontiguousarray(bgr[:, :, ::-1].transpose(2, 0, 1))
    return rgb_chw, bgr


def detections_to_targets(detections):
    """Convert Nx6 xyxy/conf/class detections to Nx5 pixel xywh/conf targets."""
    boxes = np.asarray(detections, dtype=np.float32)
    if boxes.ndim != 2 or boxes.shape[1] != 6:
        raise ValueError(f"Expected Nx6 detections, got {boxes.shape}")
    valid = np.isfinite(boxes).all(axis=1) & (boxes[:, 2] > boxes[:, 0]) & (boxes[:, 3] > boxes[:, 1])
    boxes = boxes[valid]
    targets = np.empty((len(boxes), 5), dtype=np.float32)
    targets[:, :2] = (boxes[:, :2] + boxes[:, 2:4]) * 0.5
    targets[:, 2:4] = boxes[:, 2:4] - boxes[:, :2]
    targets[:, 4] = boxes[:, 4]
    return targets


def select_target(targets, center, last_mid_coord=None, center_of_screen=True):
    if not len(targets):
        return None
    # Preserve the previous target when possible; otherwise prefer the screen center.
    reference = last_mid_coord if last_mid_coord is not None else (center if center_of_screen else None)
    if reference is None:
        return targets[0]
    distances = np.sum((targets[:, :2] - np.asarray(reference)) ** 2, axis=1)
    return targets[int(np.argmin(distances))]


class PerformanceStats:
    """Bounded per-stage latency samples; never grows with runtime duration."""

    def __init__(self, capacity=240):
        self.samples = deque(maxlen=capacity)

    def record(self, stages):
        self.samples.append(dict(stages))

    def summary(self):
        if not self.samples:
            return ""
        parts = []
        for name in self.samples[0]:
            values = [sample[name] for sample in self.samples]
            parts.append(f"{name}: avg {np.mean(values) * 1000:.2f} ms, p95 {np.percentile(values, 95) * 1000:.2f} ms")
        return " | ".join(parts)
