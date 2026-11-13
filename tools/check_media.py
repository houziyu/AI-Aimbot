"""Evaluate local screenshots/video with the real detector and tracker, without serial I/O.

Coverage is NOT accuracy: this tool has no ground-truth enemy/team/visibility labels.
Video is replayed at source timestamps, using a centered crop like the desktop runtime.
"""
import argparse
from dataclasses import asdict, replace
import json
import math
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np

from aim_assist.settings import Settings
from aim_assist.vision import Detector, TargetTracker


def crop_frame(frame, size):
    h, w = frame.shape[:2]
    size = min(size, h, w)
    x, y = (w - size) // 2, (h - size) // 2
    return frame[y:y + size, x:x + size].copy(), (x, y, size, size)


def overlay(frame, region, detections, target, title):
    shown = frame.copy()
    x, y, w, h = region
    cv2.rectangle(shown, (x, y), (x + w, y + h), (255, 200, 0), 2)
    for detection in detections:
        color = (0, 230, 0) if detection is target else (0, 180, 255)
        p1, p2 = (round(x + detection.x1), round(y + detection.y1)), (round(x + detection.x2), round(y + detection.y2))
        cv2.rectangle(shown, p1, p2, color, 2)
        cv2.putText(shown, f"{detection.score:.2f}", p1, cv2.FONT_HERSHEY_SIMPLEX, .6, color, 2)
    shown = cv2.resize(shown, (640, 360))
    cv2.rectangle(shown, (0, 0), (640, 28), (25, 25, 25), -1)
    cv2.putText(shown, title, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, .48, (255, 255, 255), 1)
    return shown


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--model", default=Settings().model)
    parser.add_argument("--provider", default="CPUExecutionProvider")
    parser.add_argument("--crop", type=int, default=320)
    parser.add_argument("--confidence", type=float, default=.4)
    parser.add_argument("--sample-fps", type=float, default=30., help="Maximum sampled video frames/sec")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.sample_fps <= 0:
        parser.error("--sample-fps must be positive")
    settings = replace(Settings(), model=str(Path(args.model).resolve()), provider=args.provider,
                       crop_size=args.crop, confidence=args.confidence).validate()
    args.output.mkdir(parents=True, exist_ok=True)
    detector = Detector(settings)
    for _ in range(5):
        detector.detect(np.zeros((args.crop, args.crop, 3), np.uint8), settings.confidence)
    report = dict(settings=asdict(settings), scope=__doc__, files=[])
    for path in args.inputs:
        tracker, entries, thumbs, durations = TargetTracker(), [], [], []
        is_image = path.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp", ".webp")
        capture = None
        if is_image:
            frame = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                raise ValueError(f"Cannot decode {path}")
            frames = [(0., frame, "full"), (0., frame, "center")]
        else:
            capture = cv2.VideoCapture(str(path))
            if not capture.isOpened():
                raise ValueError(f"Cannot open {path}")
            fps = capture.get(cv2.CAP_PROP_FPS)
            if fps <= 0:
                raise ValueError(f"Invalid video FPS: {fps}")
            stride = max(1, math.ceil(fps / args.sample_fps))

            def video_frames():
                index = 0
                while True:
                    ok, frame = capture.read()
                    if not ok:
                        return
                    if index % stride == 0:
                        yield index / fps, frame, "center"
                    index += 1

            frames = video_frames()
        previous_scene = None
        last_thumb = -10.
        try:
            for timestamp, frame, mode in frames:
                if mode == "full":
                    observed, region = frame.copy(), (0, 0, frame.shape[1], frame.shape[0])
                else:
                    observed, region = crop_frame(frame, args.crop)
                scene = cv2.resize(frame, (32, 18)).astype(np.float32)
                cut = previous_scene is not None and np.mean(np.abs(scene - previous_scene)) > 45
                if is_image or cut:
                    tracker.reset()
                previous_scene = scene
                started = time.perf_counter()
                detections = detector.detect(observed, settings.confidence)
                target, delta = tracker.select(detections, (observed.shape[1] / 2, observed.shape[0] / 2), settings, now=timestamp)
                elapsed = (time.perf_counter() - started) * 1000
                durations.append(elapsed)
                entries.append(dict(seconds=timestamp, mode=mode, region=region, detections=[asdict(d) for d in detections],
                                    selected=asdict(target) if target else None, track_generation=tracker.generation,
                                    correction_at_60hz=delta, scene_cut=bool(cut), process_ms=elapsed, **detector.timings))
                if is_image or timestamp - last_thumb >= 4:
                    last_thumb = timestamp
                    title = f"{path.stem} | {mode} {timestamp:.1f}s | detections={len(detections)}"
                    thumbs.append(overlay(frame, region, detections, target, title))
            if not entries:
                raise ValueError(f"No decoded frames: {path}")
        finally:
            if capture is not None:
                capture.release()
        # Contact sheets preserve representative empty frames as well as detections.
        for page in range(0, len(thumbs), 12):
            tiles = thumbs[page:page + 12]
            while len(tiles) % 2:
                tiles.append(np.zeros((360, 640, 3), np.uint8))
            sheet = np.vstack([np.hstack(tiles[i:i + 2]) for i in range(0, len(tiles), 2)])
            cv2.imencode(".jpg", sheet)[1].tofile(str(args.output / f"{path.stem}-sheet-{page // 12}.jpg"))
        details_path = args.output / f"{path.stem}-frames.json"
        details_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
        summary = dict(path=str(path.resolve()), frames=len(entries),
                       frames_with_detections=sum(bool(e["detections"]) for e in entries),
                       frames_with_selection=sum(e["selected"] is not None for e in entries),
                       p50_ms=float(np.percentile(durations, 50)), p95_ms=float(np.percentile(durations, 95)),
                       details=str(details_path.resolve()))
        report["files"].append(summary)
        print(json.dumps(summary), flush=True)
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
