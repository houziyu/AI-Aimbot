"""Shared, device-independent frame processing and runtime configuration."""

from collections import deque
from dataclasses import dataclass, fields
from math import hypot, isfinite
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
    controlReferenceFps: float = 120.0
    controlMaxIntervalMs: float = 50.0
    movementDeadzone: float = 1.5
    maxMovePerFrame: int = 40
    targetMemoryMs: float = 250.0
    maxFrameAgeMs: float = 80.0
    targetClasses: tuple = (0,)
    headAimOffset: float = 0.38
    bodyAimOffset: float = 0.2
    targetRadius: float = 140.0
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
        for name in ("screenShotWidth", "screenShotHeight", "captureFps", "captureBuffer", "maxDetections", "maxMovePerFrame"):
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
        for name in ("aaMovementAmp", "headAimOffset", "bodyAimOffset"):
            value = getattr(self, name)
            maximum = 1 if name == "aaMovementAmp" else 0.5
            if type(value) not in (int, float) or not isfinite(value) or not 0 <= value <= maximum:
                raise ValueError(f"{name} must be between 0 and {maximum}")
        for name in ("controlReferenceFps", "controlMaxIntervalMs", "targetMemoryMs", "maxFrameAgeMs",
                     "movementDeadzone", "targetRadius"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not isfinite(value) or value < 0:
                raise ValueError(f"{name} must be a finite non-negative number")
            if name not in ("movementDeadzone", "targetRadius") and value == 0:
                raise ValueError(f"{name} must be greater than zero")
        if (not isinstance(self.targetClasses, (tuple, list)) or not self.targetClasses
                or any(type(value) is not int or value < 0 for value in self.targetClasses)
                or len(set(self.targetClasses)) != len(self.targetClasses)):
            raise ValueError("targetClasses must contain distinct non-negative integer class IDs")
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


@dataclass(frozen=True)
class CapturedFrame:
    image: np.ndarray
    captured_at: float  # perf_counter at the START of acquisition, never the consumer read time


@dataclass(frozen=True)
class ControlDecision:
    target: object = None
    dx: int = 0
    dy: int = 0
    reason: str = "no_target"
    age_ms: float = 0.0


class AimController:
    """Pure control state shared by the live loop and offline replay; never sends OS input."""

    def __init__(self, settings):
        self.settings = settings
        self.reset()

    def reset_motion(self):
        self.last_control_at = None
        self.remainder = np.zeros(2, dtype=np.float64)

    def reset(self):
        self.previous = None
        self.last_target_at = None
        self.last_frame_at = None
        self.reset_motion()

    def idle(self, now, paused=False):
        # No output on timeouts. Only target-selection memory survives a short wait.
        if paused or (self.last_target_at is not None
                      and now - self.last_target_at >= self.settings.targetMemoryMs / 1000):
            self.reset()
        else:
            self.reset_motion()

    def is_fresh(self, captured_at, now):
        return (isfinite(captured_at) and isfinite(now)
                and 0 <= now - captured_at <= self.settings.maxFrameAgeMs / 1000)

    def aim_point(self, target):
        offset = self.settings.headAimOffset if self.settings.headshot_mode else self.settings.bodyAimOffset
        return np.array([target[0], target[1] - target[3] * offset], dtype=np.float64)

    def update(self, targets, captured_at, now, enabled=True, current=True):
        age = (now - captured_at) * 1000
        if not current or not self.is_fresh(captured_at, now):
            self.reset()
            return ControlDecision(reason="paused" if not current else "stale", age_ms=age)
        if self.last_frame_at is not None and captured_at <= self.last_frame_at:
            self.reset_motion()
            return ControlDecision(reason="duplicate", age_ms=age)
        if self.last_target_at is not None and now - self.last_target_at >= self.settings.targetMemoryMs / 1000:
            self.previous = None
            self.reset_motion()
        self.last_frame_at = captured_at
        targets = np.asarray(targets)
        if self.settings.targetRadius > 0 and len(targets):
            distances = np.array([np.linalg.norm(self.aim_point(t) - self.settings.center) for t in targets])
            targets = targets[distances <= self.settings.targetRadius]
        target = select_target(targets, self.settings.center, self.previous, self.settings.centerOfScreen)
        if target is None:
            self.previous = self.last_target_at = None
            self.reset_motion()
            return ControlDecision(age_ms=age)
        self.previous = tuple(float(v) for v in target[:2])
        self.last_target_at = captured_at
        if not enabled:
            self.reset_motion()
            return ControlDecision(target=target, reason="disabled", age_ms=age)
        error = self.aim_point(target) - self.settings.center
        dt = (1 / self.settings.controlReferenceFps if self.last_control_at is None
              else max(0, now - self.last_control_at))
        dt = min(dt, self.settings.controlMaxIntervalMs / 1000)
        self.last_control_at = now
        if hypot(*error) <= self.settings.movementDeadzone or self.settings.aaMovementAmp == 0:
            self.remainder[:] = 0
            return ControlDecision(target=target, reason="deadzone", age_ms=age)
        # Same continuous exponential response at different frame rates. At the
        # reference FPS, alpha equals aaMovementAmp (the original per-frame gain).
        alpha = 1 - (1 - self.settings.aaMovementAmp) ** (dt * self.settings.controlReferenceFps)
        self.remainder[self.remainder * error <= 0] = 0
        desired = error * alpha + self.remainder
        length = hypot(*desired)
        limited = length > self.settings.maxMovePerFrame
        if limited:
            desired *= self.settings.maxMovePerFrame / length
        movement = np.trunc(desired).astype(int)
        self.remainder = np.zeros(2) if limited else desired - movement
        return ControlDecision(target=target, dx=int(movement[0]), dy=int(movement[1]),
                               reason="limited" if limited else "tracking", age_ms=age)


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
