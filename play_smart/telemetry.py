"""What happened, per step.

Two things here are load-bearing rather than decorative.

First, ``tier_granted``. The tier you ask for and the tier you get are
different fields. Requesting Priority on a supported model has been observed
returning 200 with ``traffic_type: ON_DEMAND`` -- Standard -- with no error,
warning or header to say so. Whether the tier was refused or merely not
labelled is not determinable from the client, which is precisely the problem:
the only evidence you get either way is ``usage_metadata.traffic_type``, so
this module records requested and granted side by side and flags the gap.

Second, ``cached_tokens``. Cache hits are a capacity lever, not just a
discount -- tokens you do not send are throughput you do not have to buy.
Attributing them per attempt is how you prove that.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from .tiers import EXPECTED_TRAFFIC_TYPE, Tier

logger = logging.getLogger("play_smart")


@dataclass
class AttemptRecord:
    """One step's attempt at one request."""

    step: str
    tier_requested: str
    model: str
    location: str
    ok: bool = False
    status: int | None = None
    #: Attempts the SDK was allowed *inside* this step, first one included.
    #: A failed step used all of them; a successful one may have used fewer,
    #: which the SDK does not report back.
    max_attempts: int = 1
    #: The whole step: every internal attempt and the backoff between them.
    latency_ms: float = 0.0
    tier_granted: str | None = None
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    error_reason: str | None = None
    error_detail: str | None = None

    @property
    def downgraded(self) -> bool:
        """True when the API reported a different lane than the one requested.

        Not an error -- you got a response -- and not proof of overcharging
        either, since this compares *reported* tiers and cannot see the
        invoice. It means the reliability guarantee you asked for is
        unconfirmed, which is worth a dashboard of its own.
        """
        if not self.ok or self.tier_granted is None:
            return False
        try:
            tier = Tier(self.tier_requested)
        except ValueError:
            return False
        expected = EXPECTED_TRAFFIC_TYPE.get(tier)
        return bool(expected) and self.tier_granted not in expected

    def to_json(self) -> str:
        payload = asdict(self)
        payload["downgraded"] = self.downgraded
        return json.dumps(payload, separators=(",", ":"))


@dataclass
class LadderResult:
    """The outcome of one traversal."""

    response: Any
    attempts: list[AttemptRecord] = field(default_factory=list)

    @property
    def succeeded_on(self) -> AttemptRecord | None:
        return next((a for a in self.attempts if a.ok), None)

    @property
    def step_used(self) -> str | None:
        winner = self.succeeded_on
        return winner.step if winner else None

    @property
    def total_latency_ms(self) -> float:
        return sum(a.latency_ms for a in self.attempts)

    @property
    def text(self) -> str | None:
        """Convenience passthrough to ``response.text``."""
        return getattr(self.response, "text", None)

    def table(self) -> str:
        """A fixed-width summary. This is what the demos print."""
        head = (
            f"{'#':<3}{'step':<20}{'requested':<11}{'granted':<21}"
            f"{'model':<19}{'loc':<8}{'tries':>6}{'step ms':>9}  result"
        )
        lines = [head, "-" * len(head)]
        for index, a in enumerate(self.attempts, start=1):
            if a.ok:
                result = "OK" + ("   <-- SILENT DOWNGRADE" if a.downgraded else "")
            else:
                result = f"FAIL  {a.error_reason}"
            lines.append(
                f"{index:<3}{a.step[:19]:<20}{a.tier_requested[:10]:<11}"
                f"{(a.tier_granted or '-')[:20]:<21}{a.model[:18]:<19}"
                f"{a.location[:7]:<8}{a.max_attempts:>6}{a.latency_ms:>9.0f}  {result}"
            )
        return "\n".join(lines)


#: A sink receives every completed attempt. Point it at Cloud Logging, OTel,
#: or your metrics pipeline.
Sink = Callable[[AttemptRecord], None]


def log_sink(record: AttemptRecord) -> None:
    """Default sink: one structured JSON line per attempt."""
    level = logging.INFO if record.ok else logging.WARNING
    logger.log(level, record.to_json())


class Stopwatch:
    """Monotonic elapsed-time helper, in milliseconds."""

    def __init__(self) -> None:
        self._start = time.monotonic()

    @property
    def ms(self) -> float:
        return (time.monotonic() - self._start) * 1000.0


def read_usage(response: Any) -> dict[str, Any]:
    """Pull the fields we care about out of ``usage_metadata``.

    Defensive by design: this runs on the success path of every request, and a
    telemetry ``AttributeError`` must never be the thing that fails a call the
    ladder already won.
    """
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return {}
    traffic = getattr(usage, "traffic_type", None)
    if traffic is not None:
        # The SDK returns ``TrafficType``, a *str* enum -- so an isinstance(str)
        # guard silently does nothing and you end up logging the repr
        # "TrafficType.ON_DEMAND_FLEX" instead of the value. Always go via
        # .name, and fall back to trimming the repr for plain strings.
        traffic = getattr(traffic, "name", None) or str(traffic).rsplit(".", 1)[-1]
    return {
        "tier_granted": traffic,
        "prompt_tokens": getattr(usage, "prompt_token_count", None),
        "output_tokens": getattr(usage, "candidates_token_count", None),
        "cached_tokens": getattr(usage, "cached_content_token_count", None),
    }
