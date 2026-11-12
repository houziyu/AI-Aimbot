"""YOLOv5 raw ONNX output, independent of torch and the legacy CLI."""
from dataclasses import dataclass
import math
import time
import cv2
import numpy as np


@dataclass(frozen=True)
class Detection:
    x1: float
    y1: float
    x2: float
    y2: float
    score: float

    def aim(self, height):
        return ((self.x1 + self.x2) / 2, self.y1 + (self.y2 - self.y1) * height)

    def distance_to(self, point):
        """Distance from a point to the nearest point in this box."""
        dx = max(self.x1 - point[0], 0, point[0] - self.x2)
        dy = max(self.y1 - point[1], 0, point[1] - self.y2)
        return float(np.hypot(dx, dy))

    def iou(self, other):
        width = max(0, min(self.x2, other.x2) - max(self.x1, other.x1))
        height = max(0, min(self.y2, other.y2) - max(self.y1, other.y1))
        intersection = width * height
        union = ((self.x2 - self.x1) * (self.y2 - self.y1)
                 + (other.x2 - other.x1) * (other.y2 - other.y1) - intersection)
        return intersection / union if union > 0 else 0.


def letterbox(frame, width, height, dtype):
    h, w = frame.shape[:2]
    scale = min(width / w, height / h)
    nw, nh = round(w * scale), round(h * scale)
    left, top = (width - nw) // 2, (height - nh) // 2
    canvas = np.full((height, width, 3), 114, dtype=np.uint8)
    canvas[top:top + nh, left:left + nw] = cv2.resize(frame[:, :, :3], (nw, nh))
    # MSS supplies BGR; YOLOv5 expects RGB / NCHW.
    # Normalize in float32 to avoid slow CPU float16 division, then convert
    # once to the model's input type.
    working_dtype = np.float32 if dtype == np.float16 else dtype
    tensor = np.ascontiguousarray(canvas[:, :, ::-1].transpose(2, 0, 1)[None], dtype=working_dtype)
    tensor /= 255
    return tensor.astype(dtype, copy=False), scale, left, top


def decode(output, confidence, scale, left, top, frame_shape, iou_threshold=.45):
    prediction = np.asarray(output)
    if prediction.ndim != 3 or prediction.shape[0] != 1 or not 6 <= prediction.shape[2] <= 1005:
        raise ValueError("仅支持 YOLOv5 原始输出 [1, N, 5+类别数] 的 ONNX 模型")
    rows = prediction[0]
    # Class 0 is the only accepted class. Filter its score before converting
    # and scanning every class in all 6,300 proposals from the bundled model.
    scores = rows[:, 4].astype(np.float32) * rows[:, 5].astype(np.float32)
    candidates = scores >= confidence
    rows, scores = rows[candidates].astype(np.float32), scores[candidates]
    if not len(rows):
        return []
    classes = rows[:, 5:].argmax(axis=1)
    keep = np.isfinite(rows).all(axis=1) & (classes == 0) & (rows[:, 2] > 0) & (rows[:, 3] > 0)
    rows, scores = rows[keep], scores[keep]
    if not len(rows):
        return []
    # Bound worst-case NMS work for custom models.
    order = scores.argsort()[::-1][:3000]
    rows, scores = rows[order], scores[order]
    boxes = rows[:, :4].copy()
    boxes[:, :2] -= boxes[:, 2:] / 2
    indices = cv2.dnn.NMSBoxes(boxes.tolist(), scores.tolist(), confidence, iou_threshold)
    h, w = frame_shape[:2]
    detections = []
    for i in np.asarray(indices).reshape(-1)[:50]:
        x, y, bw, bh = boxes[i]
        x1, x2 = np.clip([(x - left) / scale, (x + bw - left) / scale], 0, w)
        y1, y2 = np.clip([(y - top) / scale, (y + bh - top) / scale], 0, h)
        if x2 > x1 and y2 > y1:
            detections.append(Detection(float(x1), float(y1), float(x2), float(y2), float(scores[i])))
    return detections


class Detector:
    def __init__(self, settings):
        import onnxruntime as ort
        if settings.provider not in ort.get_available_providers():
            raise ValueError(f"当前环境不可用：{settings.provider}")
        options = ort.SessionOptions()
        if settings.provider == "DmlExecutionProvider":
            options.enable_mem_pattern = False
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        self.session = ort.InferenceSession(settings.model, sess_options=options, providers=[settings.provider])
        if settings.provider not in self.session.get_providers():
            raise RuntimeError("所选计算设备初始化失败，请改用 CPU")
        inputs = self.session.get_inputs()
        if len(inputs) != 1 or len(inputs[0].shape) != 4:
            raise ValueError("模型必须只有一个 NCHW 图像输入")
        self.input = inputs[0]
        batch, channels, height, width = self.input.shape
        if isinstance(batch, int) and batch != 1 or isinstance(channels, int) and channels != 3:
            raise ValueError("模型输入必须是 batch=1、RGB 三通道")
        if self.input.type not in ("tensor(float16)", "tensor(float)"):
            raise ValueError("模型输入仅支持 float16 / float32")
        self.dtype = np.float16 if self.input.type == "tensor(float16)" else np.float32
        self.height = height if isinstance(height, int) else settings.crop_size
        self.width = width if isinstance(width, int) else settings.crop_size

    def detect(self, frame, confidence):
        tensor, scale, left, top = letterbox(frame, self.width, self.height, self.dtype)
        output = self.session.run(None, {self.input.name: tensor})[0]
        return decode(output, confidence, scale, left, top, frame.shape)


class TargetTracker:
    LOST_TARGET_GRACE = .050
    MOVEMENT_RISE_TIME = .025

    def __init__(self):
        self.reset()

    def reset(self):
        self.previous = None
        self.previous_detection = None
        self.last_seen = None
        self.missed = False
        self.movement = (0., 0.)

    def select(self, detections, center, settings, *, now=None):
        def distance(a, b):
            return float(np.hypot(a[0] - b[0], a[1] - b[1]))

        if now is None:
            now = time.monotonic()

        # A close-up person's aim point can leave the circle while their body
        # still fills its center. Gate on the visible box instead.
        candidates = [d for d in detections if d.distance_to(center) <= settings.radius]
        if self.last_seen is not None and (self.missed or not candidates):
            if now - self.last_seen > self.LOST_TARGET_GRACE:
                self.reset()
        if not candidates:
            self.missed = self.last_seen is not None
            return None, (0, 0)
        target = min(candidates, key=lambda d: distance(d.aim(settings.aim_height), center))
        retained = False
        if self.previous is not None:
            previous = min(candidates, key=lambda d: distance(d.aim(settings.aim_height), self.previous))
            if distance(previous.aim(settings.aim_height), self.previous) <= 45:
                target = previous
                retained = True
            overlapping = max(candidates, key=lambda d: d.iou(self.previous_detection))
            if overlapping.iou(self.previous_detection) >= .2:
                target = overlapping
                retained = True

        if retained:
            elapsed = min(now - self.last_seen, 1 / 30)
        else:
            self.movement = (0., 0.)
            elapsed = 1 / 120
        self.last_seen = now
        self.missed = False
        self.previous_detection = target
        self.previous = target.aim(settings.aim_height)

        rise = -math.expm1(-elapsed / self.MOVEMENT_RISE_TIME)
        self.movement = tuple(self._axis_movement(aim - origin, previous, settings, rise)
                              for aim, origin, previous in zip(self.previous, center, self.movement))
        return target, tuple(round(value) for value in self.movement)

    @staticmethod
    def _axis_movement(error, previous, settings, rise):
        # Fade in the proportional correction just outside the deadzone.
        outside = max(0., abs(error) - settings.deadzone)
        weight = min(1., outside / max(4., 2. * settings.deadzone))
        desired = min(settings.max_step, abs(error) * settings.strength * weight)

        # Limit increases in force. Slow down immediately when the error shrinks
        # and discard the previous direction when the aim point crosses center.
        carried = abs(previous) if previous * error > 0 else 0.
        magnitude = min(desired, carried + (desired - carried) * rise)
        return math.copysign(magnitude, error)
