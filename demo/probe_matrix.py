#!/usr/bin/env python3
"""Probe which (model, tier, endpoint) combinations your project can actually serve.

The support matrix in ``play_smart.tiers`` is empirical, not aspirational, and
it will drift as models launch and retire. Run this against your own project
before trusting it -- especially the multi-region list, which is materially
smaller than the global catalogue and is not documented anywhere.

Usage:
    python demo/probe_matrix.py [--project PROJECT]      # print the full matrix
    python demo/probe_matrix.py --check [--project ...]  # diff it against the code

``--check`` is the one that keeps working after today. It probes the live API
and compares the result against the sets declared in ``play_smart.tiers``,
exiting non-zero on any disagreement -- so a matrix that has gone stale
announces itself instead of quietly lying. It also runs as part of
``pytest -m live``.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from google import genai
from google.genai import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# The SDK logs an automatic-function-calling advisory on the first request of
# every process. This package sends no tools, so it does not apply -- and it
# lands in the middle of a progress line.
logging.getLogger("google_genai.models").setLevel(logging.ERROR)

from play_smart.tiers import (
    FLEX_MODELS,
    GLOBAL_LOCATION,
    MULTI_REGION_LOCATIONS,
    MULTI_REGION_MODELS,
    PRIORITY_MODELS,
    PROBED_ON,
    Tier,
    headers_for,
)

MODELS = [
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash",
]
TIERS = [Tier.PT_THEN_PAYGO, Tier.DEDICATED, Tier.STANDARD, Tier.PRIORITY, Tier.FLEX]
LOCATIONS = ["global", "us", "eu"]

PROMPT = "Reply with the single word: ok"


def probe(client: genai.Client, model: str, tier: Tier, timeout_s: float = 90.0) -> str:
    """Return the granted traffic type, or a short failure label."""
    try:
        response = client.models.generate_content(
            model=model,
            contents=PROMPT,
            config=types.GenerateContentConfig(
                http_options=types.HttpOptions(
                    headers=headers_for(tier),
                    timeout=int(timeout_s * 1000),
                    retry_options=types.HttpRetryOptions(attempts=1),
                ),
                max_output_tokens=16,
            ),
        )
        usage = getattr(response, "usage_metadata", None)
        traffic = getattr(usage, "traffic_type", None)
        return getattr(traffic, "name", None) or str(traffic or "OK")
    except Exception as exc:
        text = str(exc)
        if "429" in text or "RESOURCE_EXHAUSTED" in text:
            return "429"
        if "not supported" in text.lower():
            return "unsupported"
        if "404" in text or "not found" in text.lower():
            return "404"
        return type(exc).__name__


#: What a single probe result tells us about whether a combination *exists*.
#:
#: ``INCONCLUSIVE`` earns its own bucket rather than being folded into either
#: side: a 429 means the combination exists and was busy, and a transport error
#: means nothing at all. Counting either as evidence would make ``--check``
#: flaky, and a drift check that cries wolf gets switched off.
SERVED = "served"
ABSENT = "absent"
INCONCLUSIVE = "inconclusive"


def note(message: str, end: str = "\n") -> None:
    """Progress goes to stderr, so stdout stays a paste-ready report."""
    print(message, end=end, file=sys.stderr, flush=True)


def outcome(result: str) -> str:
    """Bucket a :func:`probe` result."""
    if result in ("404", "unsupported"):
        return ABSENT
    if result.startswith(("ON_DEMAND", "PROVISIONED_THROUGHPUT", "OK")):
        return SERVED
    return INCONCLUSIVE


def _compare(
    *,
    declared: bool,
    result: str,
    subject: str,
    declared_in: str,
    drift: list[str],
    unclear: list[str],
) -> None:
    state = outcome(result)
    if state == INCONCLUSIVE:
        unclear.append(f"{subject}: {result}")
    elif declared and state == ABSENT:
        drift.append(f"{subject} is listed in {declared_in} but returned {result}")
    elif not declared and state == SERVED:
        drift.append(f"{subject} is served ({result}) but is missing from {declared_in}")


def check(project: str) -> int:
    """Diff the live platform against the sets declared in ``play_smart.tiers``.

    Existence only. The *granted lane* is deliberately not asserted here,
    because a Priority request on a project without the entitlement returns
    ``200 OK`` with ``traffic_type: ON_DEMAND`` -- a real finding, documented
    in ``tests/test_live.py``, but not matrix drift.
    """
    drift: list[str] = []
    unclear: list[str] = []
    locations = sorted(MULTI_REGION_LOCATIONS)
    groups = len(locations) + 1
    note(
        f"{len(MODELS)} models across {groups} endpoint groups, one request at a "
        "time. About a minute."
    )

    for index, location in enumerate(locations, start=1):
        client = genai.Client(vertexai=True, project=project, location=location)
        note(f"[{index}/{groups}] {location:<8} ", end="")
        for model in MODELS:
            result = probe(client, model, Tier.STANDARD)
            note("." if outcome(result) != INCONCLUSIVE else "?", end="")
            _compare(
                declared=model in MULTI_REGION_MODELS,
                result=result,
                subject=f"{model} on {location}",
                declared_in="MULTI_REGION_MODELS",
                drift=drift,
                unclear=unclear,
            )
        note("")

    client = genai.Client(vertexai=True, project=project, location=GLOBAL_LOCATION)
    note(f"[{groups}/{groups}] {GLOBAL_LOCATION:<8} ", end="")
    for model in MODELS:
        for tier, declared_set, name in (
            (Tier.FLEX, FLEX_MODELS, "FLEX_MODELS"),
            (Tier.PRIORITY, PRIORITY_MODELS, "PRIORITY_MODELS"),
        ):
            result = probe(client, model, tier)
            note("." if outcome(result) != INCONCLUSIVE else "?", end="")
            _compare(
                declared=model in declared_set,
                result=result,
                subject=f"{model} on {tier.value}",
                declared_in=name,
                drift=drift,
                unclear=unclear,
            )
    note("\n")

    print(f"play_smart.tiers declares its matrix current as of {PROBED_ON}.")
    print(f"Probed {len(MODELS)} models: {', '.join(MODELS)}")

    unchecked = sorted(
        (FLEX_MODELS | PRIORITY_MODELS | MULTI_REGION_MODELS) - set(MODELS)
    )
    if unchecked:
        print(
            f"\nNot checked ({len(unchecked)} models are declared but not probed): "
            f"{', '.join(unchecked)}"
        )

    if unclear:
        print("\nInconclusive -- busy or unreachable, not evidence either way:")
        for line in unclear:
            print(f"  ? {line}")

    if drift:
        print(f"\nDRIFT ({len(drift)}):")
        for line in drift:
            print(f"  ! {line}")
        print(
            "\nThe platform has moved. Update the set in play_smart/tiers.py, move\n"
            "PROBED_ON to today, and re-date the tests that pinned the old answer."
        )
        return 1

    print("\nNo drift. Every probed combination matches what the code declares.")
    return 0


def matrix(project: str) -> int:
    for location in LOCATIONS:
        client = genai.Client(vertexai=True, project=project, location=location)
        print(f"\n### endpoint: {location}")
        header = f"{'model':<24}" + "".join(f"{t.value:<18}" for t in TIERS)
        print(header)
        print("-" * len(header))
        for model in MODELS:
            row = f"{model:<24}"
            for tier in TIERS:
                # Priority and Flex are global-only; do not waste a call.
                if location != "global" and tier in (Tier.PRIORITY, Tier.FLEX):
                    row += f"{'n/a':<18}"
                else:
                    row += f"{probe(client, model, tier):<18}"
            print(row)

    print(
        "\nRead the PRIORITY column carefully: a value of ON_DEMAND rather than\n"
        "ON_DEMAND_PRIORITY means the request succeeded but was not reported as\n"
        "Priority. Whether it was refused or merely unlabelled is not visible\n"
        "from here -- check your billing. Either way it is not an error, and\n"
        "nothing but this field will tell you."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT"))
    parser.add_argument(
        "--check",
        action="store_true",
        help="diff the live API against play_smart.tiers; exit 1 on drift",
    )
    args = parser.parse_args()
    if not args.project:
        parser.error("pass --project or set GOOGLE_CLOUD_PROJECT")

    return check(args.project) if args.check else matrix(args.project)


if __name__ == "__main__":
    raise SystemExit(main())
