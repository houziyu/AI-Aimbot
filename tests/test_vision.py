from dataclasses import replace
import numpy as np
import pytest
from aim_assist.settings import Settings, load_settings, save_settings
from aim_assist.vision import Detection, TargetTracker, decode, letterbox


def test_letterbox_rgb_dtype_and_padding():
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    frame[:, :] = [0, 0, 255]
    tensor, scale, left, top = letterbox(frame, 320, 320, np.float16)
    assert (scale, left, top) == (1.6, 0, 80)
    assert tensor.shape == (1, 3, 320, 320)
    assert tensor.dtype == np.float16
    np.testing.assert_allclose(tensor[0, :, 100, 100], [1, 0, 0])
    np.testing.assert_allclose(tensor[0, :, 0, 0], [114 / 255] * 3, atol=.001)


def test_decode_confidence_class_nms_and_coordinate_mapping():
    output = np.array([[
        [160, 160, 80, 80, .9, .9, .1],
        [161, 160, 80, 80, .8, .9, .1],
        [80, 100, 30, 50, .9, .1, .9],
        [100, 100, 30, 50, .1, .9, .1],
        [np.nan, 100, 30, 50, .9, .9, .1],
    ]], dtype=np.float32)
    detections = decode(output, .4, 1.6, 0, 80, (100, 200, 3))
    assert len(detections) == 1
    d = detections[0]
    assert (d.x1, d.y1, d.x2, d.y2) == (75, 25, 125, 75)
    assert d.score == pytest.approx(.81)


def target(x, y):
    return Detection(x - 10, y - 30, x + 10, y + 70, .9)


def test_target_retention_deadzone_and_loss():
    tracker = TargetTracker()
    settings = Settings()
    first = target(190, 160)
    assert tracker.select([first], (160, 160), settings)[1] == (12, 0)
    nearby = target(195, 160)
    distractor = target(150, 160)
    assert tracker.select([nearby, distractor], (160, 160), settings)[0] is nearby
    assert tracker.select([], (160, 160), settings) == (None, (0, 0))
    assert tracker.previous is None
    assert tracker.select([target(165, 155)], (160, 160), settings)[1] == (0, 0)
    assert tracker.select([target(500, 500)], (160, 160), settings)[0] is None


def test_settings_atomic_roundtrip_and_validation(tmp_path):
    path = tmp_path / "settings.json"
    save_settings(replace(Settings(), confidence=.55), path)
    assert load_settings(path).confidence == .55
    for values in (dict(rate=0), dict(strength=float('nan')), dict(crop_size=320.5), dict(mask="false")):
        with pytest.raises(ValueError):
            replace(Settings(), **values).validate()


def test_unsupported_output_rejected():
    with pytest.raises(ValueError):
        decode(np.zeros((1, 84, 2100)).transpose(0, 2, 1)[0], .4, 1, 0, 0, (320, 320, 3))
