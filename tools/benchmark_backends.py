"""Compare available CPU/GPU backends using a local fixture; never opens hardware."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np
import onnxruntime as ort

from aim_assist.benchmark import compare_backends
from aim_assist.settings import ROOT, Settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=Settings().model)
    parser.add_argument("--image", type=Path, help="Optional local image (default: repository fixture center crop)")
    parser.add_argument("--cpu-threads", type=int, default=0)
    parser.add_argument("--frames", type=int, default=60)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    args = parser.parse_args()
    settings = replace(Settings(), model=str(Path(args.model).resolve()), cpu_threads=args.cpu_threads).validate()
    path = args.image or ROOT / "tests/fixtures/rust-validation.jpg"
    frame = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        parser.error("Cannot read the input image")
    if args.image is None:
        frame = frame[576:896, 1088:1408].copy()
    available = ort.get_available_providers()
    providers = [provider for provider in ("CPUExecutionProvider", "DmlExecutionProvider", "CUDAExecutionProvider")
                 if provider in available]
    report = compare_backends(settings, frame, providers, warmup=args.warmup, frames=args.frames, rounds=args.rounds)
    report.update(onnxruntime=ort.__version__, image=str(path.resolve()), python=sys.version.split()[0])
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded)
    return 0 if report["recommended_provider"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
