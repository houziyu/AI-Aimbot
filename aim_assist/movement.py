"""Convert a 60 Hz correction into bounded, time-normalized XY commands."""


class MovementScaler:
    REFERENCE_RATE = 60.
    MAX_INTERVAL = 1 / 30
    RESET_AFTER = .1

    def __init__(self):
        self.reset()

    def reset(self):
        self.last_sent = None
        self.target_id = None
        self.remainder = (0., 0.)
        self.direction = (0., 0.)

    def prepare(self, delta, now, target_id, max_step):
        """Return a command and tentative state; failed writes never accumulate debt."""
        fresh = (self.last_sent is None or target_id != self.target_id
                 or now - self.last_sent > self.RESET_AFTER)
        elapsed = 1 / self.REFERENCE_RATE if fresh else min(self.MAX_INTERVAL, max(0., now - self.last_sent))
        command, remainder = [], []
        for value, carry, previous in zip(delta, self.remainder, self.direction):
            if fresh or value * previous <= 0:
                carry = 0.
            scaled = value * elapsed * self.REFERENCE_RATE + carry
            limited = max(-max_step, min(max_step, scaled))
            step = round(limited)
            command.append(step)
            # Discard saturation, direction-change and deadzone debt.
            remainder.append(limited - step if value and abs(scaled) <= max_step else 0.)
        return tuple(command), (target_id, tuple(remainder), tuple(delta))

    def commit(self, state, sent_at):
        self.target_id, self.remainder, self.direction = state
        self.last_sent = sent_at
