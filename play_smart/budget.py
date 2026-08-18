"""A wall clock shared across the whole traversal.

Without this, a failover ladder is a latency bomb. Five steps that each look
reasonable in isolation compose into a two-minute worst case, and the caller
who set a 30-second SLA finds out in production.

The budget makes the trade explicit: every step's timeout is clamped to the
time remaining, and a step is skipped only once there is no useful time left
for it at all.
"""

from __future__ import annotations

import time


class Budget:
    """Tracks time remaining for one ladder traversal."""

    def __init__(self, deadline_s: float | None) -> None:
        """Args:
        deadline_s: Total wall clock allowed, or ``None`` for unbounded.
        """
        if deadline_s is not None and deadline_s <= 0:
            raise ValueError("deadline_s must be positive or None")
        self.deadline_s = deadline_s
        self._start = time.monotonic()

    @property
    def elapsed_s(self) -> float:
        return time.monotonic() - self._start

    @property
    def remaining_s(self) -> float:
        """Seconds left, or ``inf`` when unbounded."""
        if self.deadline_s is None:
            return float("inf")
        return max(0.0, self.deadline_s - self.elapsed_s)

    @property
    def expired(self) -> bool:
        return self.remaining_s <= 0

    def allows(self, needed_s: float, *, min_useful_s: float = 1.0) -> bool:
        """Whether a step needing ``needed_s`` is worth starting.

        A step is started if either its full worst case fits, or enough time
        remains to give it a genuine chance -- a truncated attempt at the last
        step still beats returning nothing.
        """
        remaining = self.remaining_s
        if remaining == float("inf"):
            return True
        return remaining >= min(needed_s, min_useful_s)

    def clamp(self, timeout_s: float) -> float:
        """Shrink a per-request timeout so it cannot outlive the budget."""
        if self.deadline_s is None:
            return timeout_s
        return max(0.0, min(timeout_s, self.remaining_s))
