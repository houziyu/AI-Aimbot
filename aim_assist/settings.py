from dataclasses import asdict, dataclass
import json
import math
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "AimAssist" / "settings.json"


@dataclass(frozen=True)
class Settings:
    model: str = str(ROOT / "yolov5s320Half.onnx")
    provider: str = "CPUExecutionProvider"
    port: str = ""
    crop_size: int = 320
    rate: int = 60
    strength: float = 0.4
    confidence: float = 0.4
    aim_height: float = 0.3
    radius: int = 140
    deadzone: int = 12
    max_step: int = 40
    mask: bool = False
    mask_side: str = "left"
    mask_width: int = 80
    mask_height: int = 200
    right_click_hotkey: bool = False
    caps_lock_hotkey: bool = True
    output_rate: int = 60
    result_max_age_ms: int = 100
    sound_enabled: bool = False
    cpu_threads: int = 0

    def validate(self):
        if type(self.cpu_threads) is not int or not 0 <= self.cpu_threads <= 256:
            raise ValueError("CPU 推理线程数必须为 0–256 的整数")
        if type(self.result_max_age_ms) is not int or not 20 <= self.result_max_age_ms <= 500:
            raise ValueError("结果有效期必须为 20–500 毫秒")
        if not isinstance(self.sound_enabled, bool):
            raise ValueError("提示音开关必须为布尔值")
        if type(self.output_rate) is not int or not 30 <= self.output_rate <= 60:
            raise ValueError("位移发送上限必须为 30–60 条 / 秒")
        if not isinstance(self.right_click_hotkey, bool) or not isinstance(self.caps_lock_hotkey, bool):
            raise ValueError("快捷键开关必须为布尔值")
        if self.rate not in (30, 60, 120):
            raise ValueError("识别频率必须为 30、60 或 120")
        for name, low, high in (("crop_size", 160, 1280),
                                ("strength", .05, 1), ("confidence", .1, .95),
                                ("aim_height", .05, .5), ("radius", 10, 640),
                                ("deadzone", 0, 100), ("max_step", 1, 100),
                                ("mask_width", 0, 1280), ("mask_height", 0, 1280)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"参数 {name} 必须在 {low}–{high} 之间")
        for name in ("crop_size", "radius", "deadzone", "max_step", "mask_width", "mask_height", "rate"):
            if type(getattr(self, name)) is not int:
                raise ValueError(f"参数 {name} 必须为整数")
        if not isinstance(self.mask, bool) or self.mask_side not in ("left", "right"):
            raise ValueError("遮罩参数无效")
        if self.provider not in ("CPUExecutionProvider", "DmlExecutionProvider", "CUDAExecutionProvider"):
            raise ValueError("不支持的计算设备")
        if not isinstance(self.model, str) or not isinstance(self.port, str):
            raise ValueError("模型路径或串口无效")
        return self


def load_settings(path=CONFIG_PATH):
    if not path.exists():
        return Settings()
    return Settings(**json.loads(path.read_text(encoding="utf-8"))).validate()


def save_settings(settings, path=CONFIG_PATH):
    settings.validate()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(settings), indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
