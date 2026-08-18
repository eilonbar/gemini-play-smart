"""Play Smart: a 429-survival ladder for the Gemini Agent Platform.

One problem, one answer. When a Gemini request comes back 429, the usual
advice is to retry the same call against the same capacity that just refused
it. This package does something else: it walks a *ladder* of lanes, models and
endpoints, changing exactly one variable per step, until one of them answers.

No Provisioned Throughput order required. The ladder is the route for teams
who cannot or will not reserve capacity.

Quickstart:
    >>> from play_smart import CapacityLadder, play_smart_default
    >>> ladder = CapacityLadder(play_smart_default(), project="my-project")
    >>> result = ladder.generate_content("Summarise this filing.")
    >>> print(result.text)
    >>> print(result.table())
"""

from __future__ import annotations

from .budget import Budget
from .errors import Disposition, LadderAborted, LadderExhausted, classify
from .ladder import CapacityLadder
from .presets import latency_first, play_smart_default
from .steps import InvalidStep, LadderSpec, Step
from .telemetry import AttemptRecord, LadderResult, log_sink
from .tiers import Tier, headers_for, tier_supports

__version__ = "0.1.0"

__all__ = [
    "AttemptRecord",
    "Budget",
    "CapacityLadder",
    "Disposition",
    "InvalidStep",
    "LadderAborted",
    "LadderExhausted",
    "LadderResult",
    "LadderSpec",
    "Step",
    "Tier",
    "classify",
    "headers_for",
    "latency_first",
    "log_sink",
    "play_smart_default",
    "tier_supports",
]
