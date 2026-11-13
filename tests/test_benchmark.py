from dataclasses import replace

import numpy as np

import aim_assist.benchmark as module
from aim_assist.settings import Settings
from aim_assist.vision import Detection


def test_recommendation_excludes_backend_errors_and_different_detections(monkeypatch):
    class FakeDetector:
        def __init__(self, settings):
            self.provider = settings.provider
            if self.provider == "CUDAExecutionProvider":
                raise RuntimeError("unavailable")
            self.timings = dict(preprocess=1., inference=2., postprocess=1.)

        def detect(self, *args):
            return [Detection(10, 20, 30, 80, .9)] if self.provider == "CPUExecutionProvider" else []

    monkeypatch.setattr(module, "Detector", FakeDetector)
    settings = replace(Settings(), provider="DmlExecutionProvider")
    report = module.compare_backends(settings, np.zeros((320, 320, 3), np.uint8),
                                     ["DmlExecutionProvider", "CUDAExecutionProvider"], warmup=1, frames=2, rounds=2)
    assert report["recommended_provider"] == "CPUExecutionProvider"
    assert report["results"][1]["agrees_with_cpu"] is False
    assert report["results"][2]["status"] == "error"
    assert settings.provider == "DmlExecutionProvider"


def test_detection_agreement_requires_one_to_one_geometry_and_confidence():
    first = Detection(0, 0, 20, 60, .9)
    second = Detection(80, 0, 100, 60, .8)
    assert module.detections_agree([first, second], [second, first])
    assert not module.detections_agree([first, second], [first, first])
    assert not module.detections_agree([first], [Detection(0, 0, 20, 60, .6)])
