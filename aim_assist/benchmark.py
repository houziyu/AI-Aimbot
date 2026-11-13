"""Repeatable backend comparison on an offline frame, without device access."""
from dataclasses import replace
import time

import numpy as np

from .vision import Detector


def detections_agree(reference, candidate):
    """Do not recommend a faster provider if this fixture's outputs disagree."""
    remaining = list(candidate)
    if len(reference) != len(remaining):
        return False
    for detection in reference:
        if not remaining:
            return False
        match = max(remaining, key=detection.iou)
        if detection.iou(match) < .9 or abs(detection.score - match.score) > .05:
            return False
        remaining.remove(match)
    return True


def compare_backends(settings, frame, providers, *, warmup=10, frames=60, rounds=3):
    if warmup < 1 or frames < 1 or rounds < 1:
        raise ValueError("warmup, frames and rounds must be positive")
    # Always use CPU as the output reference, without changing the user's settings.
    providers = list(dict.fromkeys(["CPUExecutionProvider", *providers]))
    results, reference = [], None
    for provider in providers:
        row = dict(provider=provider)
        detector = None
        try:
            detector = Detector(replace(settings, provider=provider))
            for _ in range(warmup):
                detections = detector.detect(frame, settings.confidence)
            durations, stage_samples, batches = [], [], []
            cpu_start, wall_start = time.process_time(), time.perf_counter()
            for _ in range(rounds):
                batch = []
                for _ in range(frames):
                    started = time.perf_counter()
                    detections = detector.detect(frame, settings.confidence)
                    batch.append((time.perf_counter() - started) * 1000)
                    stage_samples.append(dict(detector.timings))
                durations.extend(batch)
                batches.append(dict(p50_ms=float(np.percentile(batch, 50)), p95_ms=float(np.percentile(batch, 95))))
            wall = time.perf_counter() - wall_start
            cpu = time.process_time() - cpu_start
            if provider == "CPUExecutionProvider":
                reference = detections
            agrees = reference is not None and detections_agree(reference, detections)
            row.update(status="ok", agrees_with_cpu=agrees, detections=len(detections),
                       p50_ms=float(np.percentile(durations, 50)), p95_ms=float(np.percentile(durations, 95)),
                       cpu_core_equivalents=cpu / max(wall, 1e-9), rounds=batches,
                       stages_ms={key: float(np.median([sample[key] for sample in stage_samples]))
                                  for key in ("preprocess", "inference", "postprocess")})
        except Exception as exc:
            row.update(status="error", error=str(exc))
        finally:
            del detector
        results.append(row)
    eligible = [row for row in results if row["status"] == "ok" and row["agrees_with_cpu"]]
    best = min(eligible, key=lambda row: row["p95_ms"]) if eligible else None
    return dict(model=settings.model, cpu_threads=settings.cpu_threads, warmup=warmup,
                frames_per_round=frames, rounds=rounds, frame_shape=list(frame.shape), results=results,
                recommended_provider=best["provider"] if best else None,
                scope="Offline detect(): preprocessing + inference + postprocessing; excludes capture, serial and HID. "
                      "Recommendation applies only to this fixture and current load; settings are not modified.")
