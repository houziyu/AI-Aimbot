from dataclasses import replace
import numpy as np
import pytest
from aim_assist.settings import Settings, load_settings, save_settings
from aim_assist.vision import Detection, TargetTracker, decode, letterbox


def test_legacy_settings_use_independent_hotkey_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"confidence": 0.65}', encoding="utf-8")
    settings = load_settings(path)
    assert settings.confidence == .65
    assert not settings.right_click_hotkey
    assert settings.caps_lock_hotkey
    with pytest.raises(ValueError, match="快捷键"):
        replace(settings, right_click_hotkey="false").validate()


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
    assert tracker.select([first], (160, 160), settings, now=0)[0] is first
    nearby = target(195, 160)
    distractor = target(155, 155)
    assert tracker.select([], (160, 160), settings, now=.01) == (None, (0, 0))
    assert tracker.select([nearby, distractor], (160, 160), settings, now=.02)[0] is nearby
    assert tracker.select([], (160, 160), settings, now=.08) == (None, (0, 0))
    assert tracker.previous is None
    assert tracker.select([distractor], (160, 160), settings, now=.09)[1] == (0, 0)
    assert tracker.select([target(500, 500)], (160, 160), settings, now=.10)[0] is None


def test_movement_ramps_up_and_slows_down_near_center():
    tracker = TargetTracker()
    settings = replace(Settings(), strength=.85, deadzone=2, max_step=70)
    far = target(240, 160)
    corrections = [tracker.select([far], (160, 160), settings, now=i / 120)[1][0] for i in range(20)]
    assert 0 < corrections[0] < corrections[2] < corrections[-1] == 68

    # Keep the same box while moving the screen center to simulate closed-loop correction.
    assert tracker.select([far], (232, 160), settings, now=.17)[1] == (7, 0)
    assert tracker.select([far], (237, 160), settings, now=.18)[1] == (1, 0)
    assert tracker.select([far], (238, 160), settings, now=.19)[1] == (0, 0)
    assert tracker.select([far], (246, 160), settings, now=.20)[1][0] < 0


def test_movement_rejects_deadzone_jitter_but_corrects_persistent_error():
    tracker = TargetTracker()
    settings = replace(Settings(), strength=.85, deadzone=2)
    for i in range(12):
        jitter = target(162 + i % 2, 160)
        assert tracker.select([jitter], (160, 160), settings, now=i / 120)[1] == (0, 0)

    steady = target(163, 160)
    for i in range(12, 20):
        _, correction = tracker.select([steady], (160, 160), settings, now=i / 120)
    assert correction == (1, 0)


def test_movement_restarts_gently_when_switching_targets():
    tracker = TargetTracker()
    settings = replace(Settings(), strength=.85, deadzone=2, max_step=70)
    first = target(240, 160)
    second = target(250, 110)
    opening = tracker.select([first], (160, 160), settings, now=0)[1][0]
    assert tracker.select([first], (160, 160), settings, now=.03)[1][0] > opening
    assert tracker.select([second], (160, 160), settings, now=.04) == (None, (0, 0))
    assert tracker.select([second], (160, 160), settings, now=.065) == (None, (0, 0))
    replacement, delta = tracker.select([second], (160, 160), settings, now=.095)
    assert replacement is second
    assert opening <= delta[0] <= 20


def test_close_target_remains_selected_when_aim_leaves_circle():
    tracker = TargetTracker()
    settings = replace(Settings(), radius=100)
    first = Detection(60, 0, 220, 320, .9)
    moved = Detection(150, 0, 310, 320, .9)
    distractor = target(160, 160)
    assert tracker.select([first], (160, 160), settings, now=0)[0] is first
    # Aim moves by 90 px. The larger body overlap retains this person even
    # though a different, smaller person is closer to the crosshair.
    assert tracker.select([moved, distractor], (160, 160), settings, now=.10)[0] is moved
    edge = Detection(210, 0, 350, 320, .9)
    assert np.linalg.norm(np.array(edge.aim(settings.aim_height)) - (160, 160)) > settings.radius
    assert tracker.select([edge], (160, 160), settings, now=.20)[0] is edge
    assert tracker.select([], (160, 160), settings, now=.26) == (None, (0, 0))
    # Low-rate observations get a bounded longer grace period, with zero output.
    assert tracker.previous_detection is edge
    assert tracker.select([], (160, 160), settings, now=.36) == (None, (0, 0))
    assert tracker.previous_detection is None
    assert tracker.select([Detection(300, 0, 350, 320, .9)], (160, 160), settings, now=.37)[0] is None


@pytest.mark.parametrize("rate", [30, 60, 120])
def test_better_target_needs_sustained_advantage(rate):
    tracker, settings = TargetTracker(), Settings()
    original, better = target(240, 160), target(165, 160)
    tracker.select([original], (160, 160), settings, now=0)
    for i in range(1, round(.1 * rate) + 1):
        selected, _ = tracker.select([original, better], (160, 160), settings, now=i / rate)
        assert selected is original
    selected, _ = tracker.select([original, better], (160, 160), settings, now=.1 + 1 / rate)
    assert selected is better


def test_intermittent_challenger_cannot_force_switch():
    tracker, settings = TargetTracker(), Settings()
    original, challenger = target(240, 160), target(165, 160)
    tracker.select([original], (160, 160), settings, now=0)
    for i in range(1, 30):
        candidates = [original, challenger] if i % 2 else [original]
        assert tracker.select(candidates, (160, 160), settings, now=i / 60)[0] is original


def test_crossing_targets_follow_motion_despite_reversed_input_order():
    tracker, settings = TargetTracker(), replace(Settings(), radius=300)
    tracker.select([target(120, 160)], (160, 160), settings, now=0)
    for i in range(1, 12):
        forward = target(120 + 8 * i, 160)
        backward = target(220 - 8 * i, 160)
        candidates = [forward, backward] if i % 2 else [backward, forward]
        selected, _ = tracker.select(candidates, (160, 160), settings, now=i / 60)
        assert selected is forward


def test_missing_target_does_not_move_towards_unconfirmed_replacement():
    tracker, settings = TargetTracker(), Settings()
    tracker.select([target(240, 160)], (160, 160), settings, now=0)
    stranger = target(90, 80)
    for now in (.01, .02, .03):
        assert tracker.select([stranger], (160, 160), settings, now=now) == (None, (0, 0))


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
