"""A step: one bounded attempt at buying capacity.

The whole architecture rests on this being *data*. A ladder is a tuple of
steps, so changing your capacity strategy is editing a list, not editing
control flow. That is what makes "cost-optimised" and "latency-optimised" two
tuples rather than two codebases.

Design rule enforced throughout: **each step changes exactly one variable**
relative to the one above it -- the lane, or the model, or the endpoint, never
two at once. When a traversal shows up in your logs at 3am, that discipline is
what lets you read off which dimension actually bought the recovery.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from .tiers import GLOBAL_LOCATION, Tier, tier_supports


class InvalidStep(ValueError):
    """A step that Google's API cannot serve. Raised at construction."""


@dataclass(frozen=True)
class Step:
    """One attempt at one capacity source.

    Args:
        name: Short label. Shows up in every telemetry record, so make it
            readable at a glance.
        tier: Which consumption option to request.
        location: ``"global"``, a multi-region (``"us"``/``"eu"``), or a
            standard region such as ``"us-central1"``.
        model: Model ID, or ``None`` to inherit the ladder's primary model.
        timeout_s: Per-request wall clock cap. This is the knob that turns a
            cheap-but-slow lane into a bounded bet.
        attempts: Total attempts at this step, including the first, handed to the
            SDK's ``HttpRetryOptions``. ``1`` means no retry at this step.
        initial_delay_s: First backoff delay.
        exp_base: Backoff multiplier.
        max_delay_s: Backoff ceiling.
        jitter: Randomisation factor, to stop every client retrying in lockstep.
        note: Free text explaining *why* this step exists. Surfaced in
            ``describe()`` and in the demo output.
    """

    name: str
    tier: Tier
    location: str = GLOBAL_LOCATION
    model: str | None = None
    timeout_s: float = 60.0
    attempts: int = 1
    initial_delay_s: float = 1.0
    exp_base: float = 2.0
    max_delay_s: float = 60.0
    jitter: float = 1.0
    note: str = ""

    def resolved(self, primary_model: str) -> Step:
        """Return this step with ``model`` filled in and validated.

        Validation is deferred to here because a step may legitimately be
        written without a model, inheriting the ladder's primary. We cannot
        check a triple until we know all three parts of it.
        """
        model = self.model or primary_model
        ok, reason = tier_supports(self.tier, model, self.location)
        if not ok:
            raise InvalidStep(f"step {self.name!r}: {reason}")
        return replace(self, model=model)

    @property
    def worst_case_s(self) -> float:
        """Upper bound on wall clock for this step, including backoff.

        Used by the deadline budget to skip steps that cannot finish in time
        rather than starting them and blowing the SLA anyway.
        """
        backoff = 0.0
        delay = self.initial_delay_s
        for _ in range(max(0, self.attempts - 1)):
            backoff += min(delay, self.max_delay_s)
            delay *= self.exp_base
        return self.attempts * self.timeout_s + backoff

    def describe(self) -> str:
        target = f"{self.model or '<primary>'} @ {self.location}"
        retry = f"{self.attempts}x" if self.attempts > 1 else "no retry"
        return (
            f"{self.name:<16} {self.tier.value:<14} {target:<34} "
            f"{self.timeout_s:>5.0f}s  {retry}"
        )


@dataclass(frozen=True)
class LadderSpec:
    """An ordered capacity strategy."""

    name: str
    primary_model: str
    steps: tuple[Step, ...]
    description: str = ""
    _resolved: tuple[Step, ...] = field(default=(), repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.steps:
            raise InvalidStep(f"ladder {self.name!r} has no steps")
        # Validate every step now, at construction, so a misconfigured ladder
        # fails on import rather than on the first 429 in production.
        resolved = tuple(step.resolved(self.primary_model) for step in self.steps)
        seen: set[str] = set()
        for step in resolved:
            if step.name in seen:
                raise InvalidStep(f"duplicate step name {step.name!r}")
            seen.add(step.name)
        object.__setattr__(self, "_resolved", resolved)

    @property
    def resolved_steps(self) -> tuple[Step, ...]:
        """Steps with models filled in and validated."""
        return self._resolved

    @property
    def worst_case_s(self) -> float:
        """Upper bound on a full traversal. Compare this to your SLA."""
        return sum(step.worst_case_s for step in self._resolved)

    def describe(self) -> str:
        header = f"{self.name}  (worst case {self.worst_case_s:.0f}s)"
        lines = [header, "=" * len(header)]
        if self.description:
            lines += [self.description, ""]
        for index, step in enumerate(self._resolved, start=1):
            lines.append(f"{index}. {step.describe()}")
            if step.note:
                lines.append(f"   {step.note}")
        return "\n".join(lines)
