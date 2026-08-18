"""Ready-made ladders.

Two strategies, one engine. The fact that these are the same handful of lines
of data with the steps in a different order *is* the argument: 429 survival is
configuration, and different workloads deserve different ladders without
anyone rewriting a client.

Neither ladder requires a Provisioned Throughput order. That is deliberate:
this package is the route for teams who cannot or will not reserve capacity.
"""

from __future__ import annotations

from .steps import LadderSpec, Step
from .tiers import Tier

#: Sensible defaults, every one of them served by the live API as of
#: ``tiers.PROBED_ON``. Re-check with ``python demo/probe_matrix.py --check``.
DEFAULT_PRIMARY = "gemini-3.7-flash"
DEFAULT_ALTERNATIVE = "gemini-3.6-flash"
#: Third choice, for ladders that fail over across models rather than lanes.
#: A smaller model, deliberately: by the time two models have refused, a fast
#: answer from a lighter one beats a late answer from a heavy one.
DEFAULT_THIRD = "gemini-3.5-flash-lite"
#: Multi-region carries a smaller model catalogue than global, so the last
#: step pins a model known to exist there. See ``tiers.MULTI_REGION_MODELS``.
#:
#: It matches :data:`DEFAULT_ALTERNATIVE` on purpose. Step 4 has already moved
#: the model, so steps 5 and 6 move only the endpoint -- one variable per step,
#: which is the whole point of the ladder being readable in a log.
DEFAULT_MULTI_REGION_MODEL = DEFAULT_ALTERNATIVE


def play_smart_default(
    primary_model: str = DEFAULT_PRIMARY,
    *,
    alternative_model: str = DEFAULT_ALTERNATIVE,
    multi_region_model: str = DEFAULT_MULTI_REGION_MODEL,
    flex_timeout_s: float = 60.0,
    multi_regions: tuple[str, ...] = ("us", "eu"),
) -> LadderSpec:
    """The Play Smart ladder: cheapest capacity first, bounded at every step.

    Cost-ascending by design. Step 1 is a *bet*: spend up to
    ``flex_timeout_s`` of latency to win the Flex discount, and abandon the
    bet the instant it stops paying. Everything below it is progressively more
    expensive insurance.

    This suits latency-tolerant and agentic work -- document processing,
    enrichment, evaluation, background summarisation -- where a minute of
    patience is worth roughly half the bill. For interactive traffic use
    :func:`latency_first` instead.

    Note the last two steps each move exactly one variable: step 4 changes the
    model, step 5 changes the endpoint. Keeping them separate is what makes a
    log line diagnostic rather than merely alarming.
    """
    steps = [
        Step(
            name="flex",
            tier=Tier.FLEX,
            timeout_s=flex_timeout_s,
            attempts=1,
            note=(
                "The bet. Flex is discounted but slower and more throttled, so we "
                "cap it hard instead of accepting the 10-minute default timeout. "
                "One attempt only -- the retry-strategy doc is explicit that Flex "
                "should not be retried aggressively."
            ),
        ),
        Step(
            name="standard",
            tier=Tier.STANDARD,
            timeout_s=60.0,
            attempts=3,
            initial_delay_s=1.0,
            note=(
                "The workhorse. Shared capacity, so this is where exponential "
                "backoff with jitter earns its keep against transient spikes."
            ),
        ),
        Step(
            name="priority",
            tier=Tier.PRIORITY,
            timeout_s=30.0,
            attempts=3,
            initial_delay_s=0.5,
            note=(
                "Premium on-demand lane. Costs more per token, so it sits below "
                "standard in a cost-ascending ladder. Check tier_granted: on a "
                "project where Priority is not enabled these requests still "
                "return 200 and are served as ON_DEMAND, with no error at all."
            ),
        ),
        Step(
            name="alternative_model",
            tier=Tier.STANDARD,
            model=alternative_model,
            timeout_s=30.0,
            attempts=2,
            note=(
                "Second-option alternative model. Capacity pressure is per-model, "
                "so a different model is a genuinely different pool. Changes the "
                "model and nothing else."
            ),
        ),
    ]
    steps += [
        Step(
            name=f"multi_region_{location}",
            tier=Tier.STANDARD,
            location=location,
            model=multi_region_model,
            timeout_s=60.0,
            attempts=2,
            note=(
                f"Jurisdictional escape hatch. The {location!r} multi-region "
                "endpoint is separate capacity from global, and Standard is the "
                "only tier that exists there -- Priority and Flex are "
                "global-only. Changes the endpoint and nothing else."
            ),
        )
        for location in multi_regions
    ]

    return LadderSpec(
        name="play-smart-default",
        primary_model=primary_model,
        steps=tuple(steps),
        description=(
            "Cost-ascending. Flex bet -> Standard -> Priority -> alternate model "
            "-> multi-region. Built for latency-tolerant and agentic workloads."
        ),
    )


def latency_first(
    primary_model: str = DEFAULT_PRIMARY,
    *,
    alternative_model: str = DEFAULT_ALTERNATIVE,
    third_model: str = DEFAULT_THIRD,
) -> LadderSpec:
    """Fail fast throughout: the premium lane only, across three models.

    The mirror image of :func:`play_smart_default`, for user-facing traffic
    where a slow answer is a failed answer. Flex is dropped entirely -- a
    60-second bet is not a bet an interactive request can make -- and each step
    gets a smaller timeout than the one above it.

    Every step is Priority. The variable this ladder moves is the *model*,
    never the lane, because capacity pressure is per-model: when the premium
    lane is congested for one model it says nothing about another, whereas
    Standard on a model whose Priority just refused is the weakest option left.
    Interactive traffic would rather ask a smaller model quickly than a busy
    one slowly, so the models descend in size as the ladder descends.

    There is deliberately no Standard floor and no multi-region step. Both cost
    a round trip that this ladder would rather spend, and the multi-region
    endpoint does not serve Priority at all. If all three models refuse, the
    ladder raises rather than quietly buying you a slower answer -- an
    interactive caller usually wants to degrade in its own way, not wait.

    Like the default ladder, this assumes no Provisioned Throughput order.
    """
    return LadderSpec(
        name="latency-first",
        primary_model=primary_model,
        steps=(
            Step(
                name="priority",
                tier=Tier.PRIORITY,
                timeout_s=15.0,
                attempts=2,
                initial_delay_s=0.25,
                note=(
                    "Premium lane; buys reliability without a commitment. "
                    "Check tier_granted -- see the measured findings."
                ),
            ),
            Step(
                name="priority_alternative_model",
                tier=Tier.PRIORITY,
                model=alternative_model,
                timeout_s=10.0,
                attempts=2,
                initial_delay_s=0.25,
                note=(
                    "Same premium lane, second-option model. Priority admission "
                    "is granted per model, so a congested primary says nothing "
                    "about this one. Keeps reliability high instead of trading "
                    "it away at the first refusal. Changes the model and "
                    "nothing else."
                ),
            ),
            Step(
                name="priority_third_model",
                tier=Tier.PRIORITY,
                model=third_model,
                timeout_s=10.0,
                attempts=1,
                note=(
                    "Last shot, smallest model, no retry. Two models have "
                    "already refused the premium lane, so the remaining "
                    "question is whether an answer arrives at all -- and a "
                    "lighter model answers faster. Changes the model and "
                    "nothing else."
                ),
            ),
        ),
        description=(
            "Tight timeouts throughout, Priority at every step, failing over "
            "across three models. For interactive traffic where a late answer "
            "is a wrong answer."
        ),
    )
