"""Consumption tiers and the headers that select them.

The Gemini Agent Platform exposes its consumption options through two HTTP
headers. This module is the single place that knows how to spell them, and the
single place that knows which model/tier/endpoint combinations actually exist.

The ladder only ever asks for on-demand lanes; see :class:`Tier`.

Reference:
  https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/deploy/consumption-options
"""

from __future__ import annotations

from enum import Enum

#: The date every empirical set in this module was last confirmed against the
#: live API, by ``demo/probe_matrix.py``.
#:
#: One constant rather than a date repeated in prose, because the sets below
#: are a *cache of an observation, not a contract* and they have already
#: expired once. Re-probe, then move this date and only this date:
#:
#:     python demo/probe_matrix.py --check
#:
#: ``--check`` diffs the live platform against what is declared here and exits
#: non-zero on any drift, so the staleness is discoverable instead of silent.
#: It also runs as part of ``pytest -m live``.
PROBED_ON = "2026-08-16"

#: Header that chooses reserved vs on-demand capacity.
REQUEST_TYPE_HEADER = "X-Vertex-AI-LLM-Request-Type"

#: Header that chooses which on-demand lane to use.
SHARED_REQUEST_TYPE_HEADER = "X-Vertex-AI-LLM-Shared-Request-Type"


class Tier(str, Enum):
    """A Gemini consumption option.

    The ladder itself uses only the three on-demand lanes -- ``STANDARD``,
    ``PRIORITY`` and ``FLEX`` -- because the whole premise of this package is
    surviving 429s *without* a Provisioned Throughput order.

    The two reserved-capacity members are kept for completeness of the wire
    vocabulary, and neither appears in a shipped ladder:

    * ``PT_THEN_PAYGO`` is what you get when no headers are sent -- reserved
      capacity first, silently spilling to pay-as-you-go. Useful to name if you
      *do* hold an order.
    * ``DEDICATED`` refuses to spill. On a project with no order it returns an
      instant 429, which is the only free, deterministic 429 available to a
      client -- so ``demo/live_ladder.py`` uses it to manufacture a real
      failure instead of faking one.
    """

    PT_THEN_PAYGO = "pt_then_paygo"
    DEDICATED = "dedicated"
    STANDARD = "standard"
    PRIORITY = "priority"
    FLEX = "flex"


def headers_for(tier: Tier) -> dict[str, str]:
    """Return the HTTP headers that select ``tier``."""
    if tier is Tier.PT_THEN_PAYGO:
        return {}
    if tier is Tier.DEDICATED:
        return {REQUEST_TYPE_HEADER: "dedicated"}
    if tier is Tier.STANDARD:
        return {REQUEST_TYPE_HEADER: "shared"}
    # Priority and Flex pin the request to on-demand and then pick the lane.
    # Omitting REQUEST_TYPE_HEADER would let Provisioned Throughput serve first,
    # which is a legitimate pattern but not what an explicit ladder step means.
    return {
        REQUEST_TYPE_HEADER: "shared",
        SHARED_REQUEST_TYPE_HEADER: tier.value,
    }


#: ``usage_metadata.traffic_type`` values, keyed by the tier that produces them.
#: Used to detect a *silent downgrade*: the API happily accepts a tier header it
#: cannot honour and serves you from a different lane instead.
EXPECTED_TRAFFIC_TYPE: dict[Tier, tuple[str, ...]] = {
    Tier.DEDICATED: ("PROVISIONED_THROUGHPUT",),
    Tier.PT_THEN_PAYGO: ("PROVISIONED_THROUGHPUT", "ON_DEMAND"),
    Tier.STANDARD: ("ON_DEMAND",),
    Tier.PRIORITY: ("ON_DEMAND_PRIORITY",),
    Tier.FLEX: ("ON_DEMAND_FLEX",),
}

#: Multi-region endpoints. These keep ML processing inside a jurisdiction and
#: are reached via ``https://aiplatform.{loc}.rep.googleapis.com`` -- the Gen AI
#: SDK derives that base URL for you when ``location`` is ``"us"`` or ``"eu"``.
MULTI_REGION_LOCATIONS = frozenset({"us", "eu"})

#: The global endpoint. Routes dynamically across capacity and is the *only*
#: endpoint where Priority and Flex exist.
GLOBAL_LOCATION = "global"

#: Tiers that Google offers on the global endpoint only.
GLOBAL_ONLY_TIERS = frozenset({Tier.PRIORITY, Tier.FLEX})

#: Flex PayGo's published discount against Standard PayGo.
#:
#: Quoting the Flex PayGo doc directly: "Flex PayGo offers a 50% discount
#: compared to Standard PayGo." This is an exact published figure, not an
#: estimate -- which is what makes the 60-second Flex cap a *priced* bet
#: rather than a hunch. See ``play_smart.presets.play_smart_default``.
FLEX_DISCOUNT = 0.50

#: Flex PayGo's default and maximum request timeouts, in seconds.
#:
#: The default is the trap. Ten minutes is a sensible ceiling for the offline
#: batch-ish work Flex is sold for, and a catastrophe for a synchronous first
#: hop: an unmodified Flex client turns a 429 into a ten-minute stall. Any
#: ladder that opens on Flex must set its own timeout.
FLEX_DEFAULT_TIMEOUT_S = 600.0
FLEX_MAX_TIMEOUT_S = 1800.0

#: Inline payload ceiling for Flex PayGo requests, in bytes (20 MB).
#: Larger inputs must be passed by Cloud Storage URI instead of inline bytes.
FLEX_MAX_INLINE_PAYLOAD_BYTES = 20 * 1024 * 1024

#: Priority PayGo publishes no multiplier -- the doc says only that you are
#: "charged per token usage at a higher rate than Standard PayGo". Deliberately
#: left as ``None`` rather than guessed; price your own ladder from the
#: pricing page.
PRIORITY_PRICE_MULTIPLIER: float | None = None

#: Models supporting Flex PayGo, per the Flex PayGo documentation.
FLEX_MODELS = frozenset(
    {
        "gemini-3.7-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-3.1-flash-lite-image",
        "gemini-3.1-flash-image",
        "gemini-3.1-pro-preview",
        "gemini-3-flash-preview",
        "gemini-3-pro-image",
    }
)

#: Models supporting Priority PayGo, per the Priority PayGo documentation.
PRIORITY_MODELS = frozenset(
    {
        "gemini-3.7-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-3.1-pro-preview",
        "gemini-3-flash-preview",
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
    }
)

#: Models confirmed reachable on the ``us``/``eu`` multi-region endpoints.
#:
#: This list is deliberately short and empirical. Multi-region carries a
#: *different* model catalogue than global, and the difference is not
#: advertised anywhere: on 2026-07-28 ``gemini-3.5-flash`` and
#: ``gemini-3.5-flash-lite`` served from both ``us`` and ``eu`` while
#: ``gemini-3.6-flash`` and ``gemini-2.5-flash`` returned 404 on both.
#:
#: Re-probed on 2026-08-12: ``gemini-3.6-flash`` now serves from ``us`` and
#: ``eu`` too. Same SDK version, same project, so the platform moved -- which
#: is the real lesson, and the reason this module ships a probe rather than
#: trusting its own output. ``gemini-3.7-flash`` was added on 2026-08-16 and
#: served from both endpoints on its first probe. Current as of
#: :data:`PROBED_ON`; treat a 404 here as "advance the ladder", never as
#: "retry".
MULTI_REGION_MODELS = frozenset(
    {
        "gemini-3.7-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
    }
)


def tier_supports(tier: Tier, model: str, location: str) -> tuple[bool, str]:
    """Check a (tier, model, endpoint) triple.

    Returns ``(ok, reason)``. ``reason`` is empty when ``ok`` is True.

    This is the check that turns a 3am pager into an import-time exception.
    """
    if tier in GLOBAL_ONLY_TIERS and location != GLOBAL_LOCATION:
        return False, (
            f"{tier.value} is available on the global endpoint only, "
            f"but this step targets {location!r}. Use Tier.STANDARD for "
            f"regional and multi-region endpoints."
        )
    if tier is Tier.FLEX and model not in FLEX_MODELS:
        return False, (
            f"Flex PayGo does not support {model!r}. "
            f"Supported: {', '.join(sorted(FLEX_MODELS))}"
        )
    if tier is Tier.PRIORITY and model not in PRIORITY_MODELS:
        return False, (
            f"Priority PayGo does not support {model!r}. "
            f"Supported: {', '.join(sorted(PRIORITY_MODELS))}"
        )
    if location in MULTI_REGION_LOCATIONS and model not in MULTI_REGION_MODELS:
        return False, (
            f"{model!r} is not known to be served from the {location!r} "
            f"multi-region endpoint. Known-good: "
            f"{', '.join(sorted(MULTI_REGION_MODELS))}. "
            f"Failing over to multi-region usually means changing the model too."
        )
    return True, ""
