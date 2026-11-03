import unittest
from dataclasses import replace

import numpy as np

from runtime import AimController, Settings


def boxes(*points):
    return np.array([[x, y, 20, 40, .9] for x, y in points], dtype=np.float32).reshape(-1, 5)


class ControllerTests(unittest.TestCase):
    def controller(self, **changes):
        return AimController(replace(Settings(), headAimOffset=0, targetRadius=0, **changes))

    def test_frame_rates_have_similar_closed_loop_response(self):
        remaining = []
        for fps in (30, 60, 120, 240):
            control = self.controller(aaMovementAmp=.05, movementDeadzone=0, maxMovePerFrame=1000)
            control.last_control_at = 0
            x = 260.0
            for i in range(1, int(fps * .1) + 1):
                now = i / fps
                result = control.update(boxes((x, 160)), now, now)
                x -= result.dx  # Idealized feedback: one command unit = one image pixel.
            remaining.append(x - 160)
        self.assertLessEqual(max(remaining) - min(remaining), 2, remaining)
        self.assertTrue(all(50 < value < 60 for value in remaining), remaining)

    def test_fractional_motion_accumulates_and_reversal_clears_residue(self):
        control = self.controller(aaMovementAmp=.1, movementDeadzone=0)
        steps = [control.update(boxes((162, 160)), i / 120, i / 120).dx for i in range(1, 12)]
        self.assertGreaterEqual(sum(steps), 2)
        reverse = control.update(boxes((158, 160)), .1, .1)
        self.assertLessEqual(reverse.dx, 0)

    def test_deadzone_clears_residual(self):
        control = self.controller()
        control.remainder[:] = .9
        result = control.update(boxes((161, 160)), 1, 1)
        self.assertEqual((result.dx, result.dy, result.reason), (0, 0, "deadzone"))
        self.assertFalse(control.remainder.any())

    def test_radial_limit_and_no_catchup_after_timeout(self):
        control = self.controller(maxMovePerFrame=10)
        result = control.update(boxes((300, 300)), 1, 1)
        self.assertLessEqual(np.hypot(result.dx, result.dy), 10)
        self.assertEqual(result.reason, "limited")
        control.idle(1.2)
        result = control.update(boxes((170, 160)), 1.21, 1.21)
        self.assertEqual(result.dx, 4)

    def test_timeout_retains_memory_until_expiration(self):
        control = self.controller()
        control.update(boxes((240, 160)), 1, 1)
        control.idle(1.1)
        self.assertEqual(control.previous, (240, 160))
        result = control.update(boxes((160, 160), (240, 160)), 1.15, 1.15)
        self.assertEqual(result.target[0], 240)
        control.idle(1.41)
        self.assertIsNone(control.previous)
        result = control.update(boxes((160, 160), (240, 160)), 1.42, 1.42)
        self.assertEqual(result.target[0], 160)

    def test_paused_empty_stale_and_disabled_never_move(self):
        for kind in ("paused", "empty", "stale", "disabled"):
            control = self.controller()
            control.update(boxes((240, 160)), 1, 1)
            result = control.update(boxes() if kind == "empty" else boxes((240, 160)),
                                    1.1, 1.3 if kind == "stale" else 1.1,
                                    enabled=kind != "disabled", current=kind != "paused")
            self.assertEqual((result.dx, result.dy), (0, 0), kind)
            if kind != "disabled":
                self.assertIsNone(control.previous)

    def test_duplicate_frame_and_future_timestamp_are_rejected(self):
        control = self.controller()
        control.update(boxes((240, 160)), 1, 1)
        duplicate = control.update(boxes((240, 160)), 1, 1.01)
        future = control.update(boxes((240, 160)), 2, 1.02)
        self.assertEqual((duplicate.reason, duplicate.dx), ("duplicate", 0))
        self.assertEqual((future.reason, future.dx), ("stale", 0))

    def test_radius_is_applied_to_configured_aim_point(self):
        control = AimController(Settings(targetRadius=10, headAimOffset=.5))
        result = control.update(boxes((160, 180), (170, 140)), 1, 1)
        self.assertEqual(result.target[1], 180)
        self.assertEqual(result.reason, "deadzone")
        control = AimController(Settings(targetRadius=10, headshot_mode=False, bodyAimOffset=0))
        result = control.update(boxes((160, 180)), 1, 1)
        self.assertEqual(result.reason, "no_target")

    def test_new_configuration_is_validated(self):
        for changes in ({"aaMovementAmp": 1.1}, {"headAimOffset": .51}, {"bodyAimOffset": -1},
                        {"maxFrameAgeMs": 0}, {"controlReferenceFps": 0}, {"targetRadius": -1},
                        {"movementDeadzone": float("nan")}, {"maxMovePerFrame": 0},
                        {"targetClasses": ()}, {"targetClasses": (0, 0)}, {"targetClasses": (True,)},
                        {"targetClasses": (1.5,)}, {"targetMemoryMs": float("inf")}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(Settings(), **changes).validate()


if __name__ == "__main__":
    unittest.main()
