#!/usr/bin/env python3
"""Measure each step in isolation, so the ladder's ordering rests on data.

The Play Smart ladder puts Flex first and accepts a latency penalty for a
cheaper token. Whether that trade is worth taking is an empirical question
about *your* project, and the answer moves. This is how you check.

Prints a markdown table, because it is meant to be pasted into a design doc.
Requests go out one at a time, so this takes minutes: progress goes to stderr,
the table to stdout, and ``> results.md`` keeps only the table.

Usage:
    python demo/bench.py [--project PROJECT] [-n 5]
"""

from __future__ import annotations

import argparse
import logging
import os
import statistics
import sys
import time

from google import genai
from google.genai import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# The SDK logs an automatic-function-calling advisory on the first request of
# every process. This package sends no tools, so it does not apply -- and it
# lands in the middle of a progress line.
logging.getLogger("google_genai.models").setLevel(logging.ERROR)

from play_smart.telemetry import read_usage
from play_smart.tiers import Tier, headers_for

PROMPT = (
    "List three causes of tail latency in distributed inference serving. One line each."
)


def note(message: str, end: str = "\n") -> None:
    """Progress goes to stderr, so stdout stays a paste-ready markdown table."""
    print(message, end=end, file=sys.stderr, flush=True)


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    index = min(len(ordered) - 1, round(fraction * (len(ordered) - 1)))
    return ordered[index]


def bench_one(
    client: genai.Client, model: str, tier: Tier, runs: int, timeout_s: float
) -> dict:
    latencies: list[float] = []
    granted: set[str] = set()
    failures: list[str] = []

    for _ in range(runs):
        started = time.monotonic()
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
                    max_output_tokens=200,
                ),
            )
        except Exception as exc:
            failures.append("429" if "429" in str(exc) else type(exc).__name__)
            note("x", end="")
            continue
        latencies.append((time.monotonic() - started) * 1000.0)
        note(".", end="")
        traffic = read_usage(response).get("tier_granted")
        if traffic:
            granted.add(traffic)

    return {
        "runs": runs,
        "ok": len(latencies),
        "granted": ",".join(sorted(granted)) or "-",
        "median_ms": statistics.median(latencies) if latencies else float("nan"),
        "p90_ms": percentile(latencies, 0.9),
        "min_ms": min(latencies) if latencies else float("nan"),
        "max_ms": max(latencies) if latencies else float("nan"),
        "failures": ",".join(sorted(set(failures))) or "-",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT"))
    parser.add_argument("--model", default="gemini-3.7-flash")
    parser.add_argument("--alternative-model", default="gemini-3.6-flash")
    parser.add_argument("-n", "--runs", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args()
    if not args.project:
        parser.error("pass --project or set GOOGLE_CLOUD_PROJECT")

    targets = [
        ("flex", args.model, "global", Tier.FLEX),
        ("standard", args.model, "global", Tier.STANDARD),
        ("priority", args.model, "global", Tier.PRIORITY),
        ("alternative_model", args.alternative_model, "global", Tier.STANDARD),
        ("multi_region_us", args.alternative_model, "us", Tier.STANDARD),
        ("multi_region_eu", args.alternative_model, "eu", Tier.STANDARD),
    ]

    clients: dict[str, genai.Client] = {}
    print(f"project={args.project}  runs={args.runs}  prompt={len(PROMPT)} chars\n")
    print(
        "| step | tier requested | model | endpoint | ok | granted "
        "| median ms | p90 ms | failures |"
    )
    print("|---|---|---|---|---|---|---:|---:|---|")

    note(
        f"{len(targets)} steps x {args.runs} runs, one request at a time. "
        "Flex is the slow one; budget minutes, not seconds."
    )
    began = time.monotonic()

    for position, (name, model, location, tier) in enumerate(targets, start=1):
        if location not in clients:
            clients[location] = genai.Client(
                vertexai=True, project=args.project, location=location
            )
        note(f"[{position}/{len(targets)}] {name:<17} ", end="")
        stats = bench_one(clients[location], model, tier, args.runs, args.timeout)
        note(f" {stats['ok']}/{stats['runs']} ok, median {stats['median_ms']:.0f} ms")
        print(
            f"| `{name}` | {tier.value} | `{model}` | {location} "
            f"| {stats['ok']}/{stats['runs']} | `{stats['granted']}` "
            f"| {stats['median_ms']:.0f} | {stats['p90_ms']:.0f} "
            f"| {stats['failures']} |"
        )

    took = time.monotonic() - began
    note(f"done in {took:.0f} s" if took < 90 else f"done in {took / 60:.1f} min")
    print(
        "\nA `granted` of `ON_DEMAND` on the priority row means the tier was not\n"
        "honoured. The call succeeded; the guarantee did not."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
