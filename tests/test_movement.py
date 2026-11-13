import pytest

from aim_assist.movement import MovementScaler
from aim_assist.settings import Settings
from aim_assist.vision import Detection, TargetTracker


@pytest.mark.parametrize("recognition_rate,output_rate", [(30, 30), (60, 30), (120, 30), (60, 60), (120, 60)])
def test_equal_duration_replays_have_equal_displacement(recognition_rate, output_rate):
    scaler = MovementScaler()
    total = 0
    next_output = 0.
    for i in range(2 * recognition_rate):
        now = i / recognition_rate
        if now + 1e-9 < next_output:
            continue
        delta, state = scaler.prepare((8, 0), now, 1, 40)
        scaler.commit(state, now)
        total += delta[0]
        next_output = now + 1 / output_rate
    assert total == pytest.approx(8 * 60 * 2, rel=.02)


def test_tracker_and_output_together_keep_strength_across_frame_rates():
    totals = []
    for recognition_rate, output_rate in ((30, 30), (60, 30), (120, 30), (60, 60), (120, 60)):
        tracker, scaler, settings = TargetTracker(), MovementScaler(), Settings()
        target = Detection(190, 130, 210, 230, .9)
        next_output, total = 0., 0
        for index in range(recognition_rate * 2):
            now = index / recognition_rate
            _, correction = tracker.select([target], (160, 160), settings, now=now)
            if now + 1e-9 >= next_output:
                delta, state = scaler.prepare(correction, now, tracker.generation, settings.max_step)
                scaler.commit(state, now)
                total += delta[0]
                next_output = now + 1 / output_rate
        totals.append(total)
    assert min(totals) / max(totals) > .97


def test_pause_target_change_and_reversal_do_not_release_accumulated_movement():
    scaler = MovementScaler()
    delta, state = scaler.prepare((10, 0), 0., 1, 40)
    scaler.commit(state, 0.)
    assert scaler.prepare((10, 0), 10., 1, 40)[0] == (10, 0)
    assert scaler.prepare((10, 0), .04, 2, 40)[0] == (10, 0)
    assert scaler.prepare((-10, 0), .02, 1, 40)[0][0] < 0
    scaler.reset()
    assert scaler.prepare((10, 0), .05, 1, 40)[0] == (10, 0)


def test_limit_is_honored_and_failed_writes_do_not_change_history():
    scaler = MovementScaler()
    delta, state = scaler.prepare((30, -30), 0., 1, 40)
    scaler.commit(state, 0.)
    assert scaler.prepare((30, -30), .04, 1, 40)[0] == (40, -40)
    # No commit: a failed or superseded write must not advance its clock/residual.
    assert scaler.last_sent == 0.
    assert scaler.prepare((2, -2), .04, 1, 40)[0] == (4, -4)
