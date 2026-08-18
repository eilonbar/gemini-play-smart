#!/usr/bin/env python3
"""Watch the ladder traverse, against the real API.

The interesting scenario is the failure path, and it is awkward to demonstrate
honestly because you cannot make Google's capacity run out on request. So this
demo uses the one 429 you can summon reliably and for free: the ``dedicated``
header on a project with no Provisioned Throughput order returns
``RESOURCE_EXHAUSTED`` immediately.

That gives a real 429 from the real API, and the steps below it are real
fallbacks. Nothing here is simulated.

Usage:
    python demo/live_ladder.py [--project PROJECT]
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# The SDK logs an automatic-function-calling advisory on the first request of
# every process. This package sends no tools, so it does not apply -- and it
# lands in the middle of a progress line.
logging.getLogger("google_genai.models").setLevel(logging.ERROR)

from play_smart import (
    CapacityLadder,
    LadderSpec,
    Step,
    Tier,
    play_smart_default,
)

PROMPT = "In one sentence: why do distributed systems need backpressure?"


def forced_failure_ladder(primary: str = "gemini-3.7-flash") -> LadderSpec:
    """A ladder whose first step is guaranteed to 429 on most projects.

    The prepended step is *not* part of the ladder and is not a strategy. It
    exists purely as a 429 generator: the ``dedicated`` header demands reserved
    capacity and refuses to spill, so on a project with no Provisioned
    Throughput order it returns an instant, free, deterministic capacity error
    -- exactly the condition the rest of the ladder exists to survive, and the
    only way to produce one on demand without waiting for a real outage.
    """
    default = play_smart_default(primary)
    return LadderSpec(
        name="forced-failure-demo",
        primary_model=primary,
        steps=(
            Step(
                name="dedicated",
                tier=Tier.DEDICATED,
                timeout_s=20.0,
                attempts=1,
                note="Not a ladder step -- a 429 generator. See the docstring.",
            ),
            *default.steps,
        ),
        description="Starts from a manufactured 429 so the fallthrough is visible.",
    )


def run(ladder: CapacityLadder, title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")
    print(ladder.spec.describe())
    print()
    try:
        result = ladder.generate_content(PROMPT)
    except Exception as exc:
        print(f"ladder failed: {exc}")
        return

    print(result.table())
    print()
    print(f"answer      : {(result.text or '').strip()[:200]}")
    print(f"served by   : step {result.step_used!r}")
    print(f"total time  : {result.total_latency_ms:.0f} ms")

    for attempt in result.attempts:
        if attempt.downgraded:
            print(
                f"\nWARNING  step {attempt.step!r} asked for "
                f"{attempt.tier_requested!r} and was served "
                f"{attempt.tier_granted!r}.\n"
                f"         The request succeeded, so nothing raised, but you are\n"
                f"         not getting the tier you are paying for."
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT"))
    parser.add_argument("--model", default="gemini-3.7-flash")
    parser.add_argument("--deadline", type=float, default=180.0)
    parser.add_argument("--verbose", action="store_true", help="log every attempt")
    args = parser.parse_args()
    if not args.project:
        parser.error("pass --project or set GOOGLE_CLOUD_PROJECT")

    if args.verbose:
        logging.basicConfig(level=logging.INFO, format="%(message)s")

    common = {"project": args.project, "deadline_s": args.deadline}
    if not args.verbose:
        common["sink"] = None

    run(
        CapacityLadder(play_smart_default(args.model), **common),
        "1. The Play Smart ladder, healthy path",
    )
    run(
        CapacityLadder(forced_failure_ladder(args.model), **common),
        "2. The same ladder, starting from a real 429",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
