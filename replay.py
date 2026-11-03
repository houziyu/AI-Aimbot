"""Offline video inference and mouse-command tracing. Never imports WindowsControls."""

import argparse
import csv
import json
import math
import time
from collections import Counter
from dataclasses import asdict, replace
from pathlib import Path

import cv2
import numpy as np

from app import draw_targets
from runtime import AimController, ControlDecision, Settings, prepare_frame


def center_crop(frame, settings):
    height, width = frame.shape[:2]
    if width < settings.screenShotWidth or height < settings.screenShotHeight:
        raise ValueError("Video is smaller than the configured capture area; use the original-resolution recording")
    left = width // 2 - settings.screenShotWidth // 2
    top = height // 2 - settings.screenShotHeight // 2
    return frame[top:top + settings.screenShotHeight, left:left + settings.screenShotWidth]


def save_plot(rows, output):
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    fig, axes = plt.subplots(2, 1, figsize=(11, 7), constrained_layout=True)
    timestamps = [row["time_s"] for row in rows]
    axes[0].plot(timestamps, [r["dx"] for r in rows], label="dx", linewidth=.8)
    axes[0].plot(timestamps, [r["dy"] for r in rows], label="dy", linewidth=.8)
    axes[0].set(xlabel="Video time (s)", ylabel="Relative mouse command", title="Planned commands per source frame")
    axes[0].legend()
    axes[1].plot([r["sum_dx"] for r in rows], [r["sum_dy"] for r in rows], linewidth=1)
    axes[1].invert_yaxis()
    axes[1].set(xlabel="Accumulated dx (command units)", ylabel="Accumulated dy (command units)",
                title="Accumulated command path — NOT an in-game cursor trajectory")
    for ax in axes:
        ax.grid(alpha=.25)
    fig.savefig(output / "trajectory.png", dpi=150)
    plt.close(fig)


def run_replay(video, settings, backend, output, start=0.0, seconds=30.0, sample_fps=None, extra_delay_ms=0.0):
    settings.validate()
    for name, value in (("start", start), ("seconds", seconds), ("extra_delay_ms", extra_delay_ms)):
        if not math.isfinite(value) or value < 0 or (name == "seconds" and value == 0):
            raise ValueError(f"Invalid {name}")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(video))
    writer = None
    rows = []
    detections_log = []
    violations = []
    controller = AimController(settings)
    try:
        if not capture.isOpened():
            raise ValueError(f"Cannot open video: {video}")
        fps = capture.get(cv2.CAP_PROP_FPS)
        if not math.isfinite(fps) or fps <= 0:
            raise ValueError("Video must have a valid frame rate")
        rate = fps if sample_fps is None else sample_fps
        if not math.isfinite(rate) or not 0 < rate <= fps + 1e-3:
            raise ValueError(f"sample_fps must be between 0 and the source FPS ({fps:g}); frames are not duplicated")
        first = int(start * fps)
        capture.set(cv2.CAP_PROP_POS_FRAMES, first)
        width, height = settings.screenShotWidth, settings.screenShotHeight
        canvas_width = max(width, 560)
        writer = cv2.VideoWriter(str(output / "annotated.mp4"), cv2.VideoWriter_fourcc(*"mp4v"),
                                 fps, (canvas_width, height + 100))
        if not writer.isOpened():
            raise RuntimeError("Cannot create annotated.mp4")
        next_ready, next_sample = first / fps, first / fps
        sum_dx = sum_dy = 0
        previous_pts = None
        for index in range(first, first + int(seconds * fps)):
            ok, frame = capture.read()
            if not ok:
                break
            # Use decoder presentation timestamps when valid (including VFR clips).
            pts = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000
            t = pts if math.isfinite(pts) and pts >= first / fps - 1 / fps and (previous_pts is None or pts > previous_pts) else index / fps
            if previous_pts is not None and t <= previous_pts:
                t = previous_pts + 1 / fps
            previous_pts = t
            if t >= start + seconds:
                break
            crop = center_crop(frame, settings)
            targets = np.empty((0, 5), dtype=np.float32)
            duration_ms = 0.0
            processed = t + 1e-9 >= next_ready and t + 1e-9 >= next_sample
            if processed:
                began = time.perf_counter()
                rgb, _ = prepare_frame(crop, settings)
                targets = backend.postprocess(backend.infer(backend.preprocess(rgb)))
                duration_ms = (time.perf_counter() - began) * 1000
                now = t + (duration_ms + extra_delay_ms) / 1000
                decision = controller.update(targets, t, now)
                next_ready = now
                next_sample = t + 1 / rate
                detections_log.append({"frame": index, "time_s": t, "targets": targets.tolist()})
            else:
                decision = ControlDecision(reason="busy" if t < next_ready else "sampling")
            aim = controller.aim_point(decision.target) if decision.target is not None else (None, None)
            if math.hypot(decision.dx, decision.dy) > settings.maxMovePerFrame + 1e-9:
                violations.append({"frame": index, "check": "movement_limit"})
            if decision.reason not in ("tracking", "limited") and (decision.dx or decision.dy):
                violations.append({"frame": index, "check": "unexpected_movement"})
            if aim[0] is not None and (decision.dx * (aim[0] - settings.center[0]) < 0
                                       or decision.dy * (aim[1] - settings.center[1]) < 0):
                violations.append({"frame": index, "check": "wrong_direction"})
            sum_dx += decision.dx
            sum_dy += decision.dy
            rows.append(dict(frame=index, time_s=t, processed=int(processed), reason=decision.reason,
                             processing_ms=duration_ms, age_ms=decision.age_ms, target_count=len(targets),
                             aim_x=aim[0], aim_y=aim[1], dx=decision.dx, dy=decision.dy,
                             sum_dx=sum_dx, sum_dy=sum_dy))
            display = draw_targets(cv2, crop, targets)
            cv2.drawMarker(display, settings.center, (255, 255, 255), cv2.MARKER_CROSS, 14, 1)
            if settings.targetRadius:
                cv2.circle(display, settings.center, int(settings.targetRadius), (180, 180, 0), 1)
            if aim[0] is not None:
                point = tuple(int(v) for v in aim)
                cv2.circle(display, point, 4, (0, 0, 255), -1)
                cv2.arrowedLine(display, settings.center,
                                (settings.center[0] + decision.dx, settings.center[1] + decision.dy), (0, 255, 255), 2)
            canvas = np.zeros((height + 100, canvas_width, 3), dtype=np.uint8)
            canvas[:height, :width] = display
            lines = (f"t={t:.3f}s  {decision.reason}  age={decision.age_ms:.1f}ms",
                     f"planned dx={decision.dx}, dy={decision.dy}  detections={len(targets)}",
                     "OFFLINE OPEN LOOP - no OS mouse movement")
            for line, y in zip(lines, (height + 23, height + 50, height + 77)):
                cv2.putText(canvas, line, (8, y), cv2.FONT_HERSHEY_SIMPLEX, .48, (230, 230, 230), 1)
            writer.write(canvas)
    finally:
        capture.release()
        if writer is not None:
            writer.release()
    if not rows:
        raise ValueError("No frames read; check the start time and video")
    with (output / "commands.csv").open("w", newline="", encoding="utf-8") as handle:
        table = csv.DictWriter(handle, fieldnames=list(rows[0]))
        table.writeheader()
        table.writerows(rows)
    with (output / "detections.jsonl").open("w", encoding="utf-8") as handle:
        for row in detections_log:
            handle.write(json.dumps(row) + "\n")
    processed_rows = [row for row in rows if row["processed"]]
    summary = {
        "source": str(Path(video).resolve()), "backend": backend.description,
        "source_fps": fps, "sample_fps": rate, "frames": len(rows),
        "processed_frames": len(processed_rows), "frames_with_detections": sum(r["target_count"] > 0 for r in rows),
        "frames_with_movement": sum(bool(r["dx"] or r["dy"]) for r in rows),
        "reasons": dict(Counter(r["reason"] for r in rows)), "violations": violations,
        "processing_p95_ms": float(np.percentile([r["processing_ms"] for r in processed_rows], 95)),
        "settings": asdict(settings), "extra_delay_ms": extra_delay_ms,
        "limitations": ["Open-loop planned commands only; no OS input is sent or captured.",
                        "Cumulative commands are not in-game camera or screen-cursor coordinates.",
                        "No enemy/teammate ground truth; zero invariant violations does not prove target accuracy.",
                        "Source timestamps + measured processing simulate availability; desktop capture latency is not measured.",
                        "Annotated video uses nominal source FPS; CSV timestamps are authoritative for VFR clips."]}
    (output / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    save_plot(rows, output)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("--backend", choices=("torch", "onnx", "tensorrt"), default="torch")
    parser.add_argument("--output", type=Path, default=Path("artifacts/replay"))
    parser.add_argument("--start", type=float, default=0)
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--sample-fps", type=float)
    parser.add_argument("--extra-delay-ms", type=float, default=0, help="Simulate a capture/processing stall without sleeping")
    parser.add_argument("--weights", help="Optional model path for the selected backend")
    args = parser.parse_args()
    import config
    from inference import create_backend
    settings = Settings.from_module(config)
    if args.weights:
        key = {"torch": "modelWeights", "onnx": "onnxWeights", "tensorrt": "tensorrtWeights"}[args.backend]
        settings = replace(settings, **{key: args.weights})
    backend = create_backend(args.backend, settings)
    backend.warmup()
    summary = run_replay(args.video, settings, backend, args.output, args.start, args.seconds,
                         args.sample_fps, args.extra_delay_ms)
    print(json.dumps({key: summary[key] for key in ("frames", "processed_frames", "frames_with_detections",
                                                   "frames_with_movement", "reasons", "violations")}, indent=2))
    print(f"Replay artifacts: {args.output.resolve()}")
    if summary["violations"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
