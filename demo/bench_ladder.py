#!/usr/bin/env python3
"""Measure a whole ladder traversal, at every depth, against the live API.

``bench.py`` measures each step in isolation, which is what you need to decide
the *order* of a ladder. It never traverses one. This measures the other
question: once a step has refused you, what does falling through to the next
one actually cost?

Depth *k* poisons the first *k* steps by swapping their tier for
``dedicated``, which on a project with no Provisioned Throughput order returns
an instant, free ``RESOURCE_EXHAUSTED``. Everything from step *k+1* down is the
real ladder against real capacity. So depth 0 is the ordinary path, depth 1
forces one hop, depth 5 forces five, and depth 6 forces the ladder to run out
of steps entirely.

The failures are manufactured; nothing about them is simulated. Each poisoned
step keeps its configured ``attempts``, so the timings include the SDK's own
in-step retries and backoff -- which is what a real 429 at that step would
cost you.

Every run also asserts the traversal did what the design promises: the first
*k* attempts failed with 429, and the ladder then answered from a step below
them. Organic 429s -- real capacity refusals on an un-poisoned step -- are
reported separately, because they are evidence, not a broken test.

This takes minutes. Progress goes to stderr and the table to stdout, so
``> results.md`` captures just the table. ``--records`` replaces the progress
with the attempt trail as JSON, one object per attempt, which is the auditable
record behind every number here: ``--records 2> trail.jsonl``.

Usage:
    python demo/bench_ladder.py [--project PROJECT] [-n 3] [--max-depth 6]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import statistics
import sys
import time
from dataclasses import asdict, replace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# The SDK logs an automatic-function-calling advisory on the first request of
# every process. This package sends no tools, so it does not apply -- and it
# lands in the middle of a progress line.
logging.getLogger("google_genai.models").setLevel(logging.ERROR)

from play_smart import (
    CapacityLadder,
    LadderExhausted,
    LadderSpec,
    Tier,
    play_smart_default,
)

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


def poisoned_spec(base: LadderSpec, depth: int) -> LadderSpec:
    """Return ``base`` with the first ``depth`` steps forced to 429.

    Only the tier changes. Names, models, endpoints, timeouts and attempt
    counts are left alone, so the attempt trail reads like the real ladder
    with the top of it unavailable.
    """
    steps = tuple(
        replace(step, tier=Tier.DEDICATED) if index < depth else step
        for index, step in enumerate(base.steps)
    )
    return LadderSpec(
        name=f"{base.name}-depth-{depth}",
        primary_model=base.primary_model,
        steps=steps,
        description=f"First {depth} step(s) forced to 429.",
    )


def stderr_sink(record) -> None:
    """Write the attempt trail to stderr, keeping stdout pure markdown.

    Off by default. Twenty-one traversals produce hundreds of these, and a
    reader who has not been told they are coming reads a wall of
    ``RESOURCE_EXHAUSTED`` as a crash rather than as the point of the run.
    ``--records`` turns it on, and then it is the only thing on stderr, so
    ``2> trail.jsonl`` is parseable.
    """
    print(json.dumps(asdict(record), default=str), file=sys.stderr)


def check(attempts: list, depth: int, exhausted: bool) -> tuple[str, list[str]]:
    """Check the traversal against what the design promises.

    Returns ``(verdict, organic)``: a verdict of ``ok`` or a list of design
    violations, plus the un-poisoned steps that refused on their own.
    """
    problems = []
    if len(attempts) < depth:
        problems.append(f"only {len(attempts)} attempts, expected at least {depth}")
    for record in attempts[:depth]:
        if record.ok:
            problems.append(f"forced {record.step} succeeded")
        elif record.status != 429:
            problems.append(f"forced {record.step} gave {record.status}, not 429")

    organic = [
        f"{record.step} {record.status}"
        for record in attempts[depth:]
        if not record.ok and record.status is not None
    ]

    last = attempts[-1] if attempts else None
    if exhausted:
        if last is not None and last.ok:
            problems.append("succeeded, expected exhaustion")
    elif last is None or not last.ok:
        problems.append("no success")

    return ("ok" if not problems else "; ".join(problems)), organic


def run_depth(
    base: LadderSpec,
    depth: int,
    project: str,
    runs: int,
    deadline_s: float,
    sink=None,
) -> dict:
    spec = poisoned_spec(base, depth)
    ladder = CapacityLadder(spec, project=project, deadline_s=deadline_s, sink=sink)
    # One mark per traversal, unless the trail already occupies stderr.
    tick = note if sink is None else lambda *_, **__: None
    exhausted = depth >= len(base.steps)
    first_live = "-- none left --" if exhausted else base.steps[depth].name

    latencies: list[float] = []
    answered: set[str] = set()
    granted: set[str] = set()
    verdicts: set[str] = set()
    organic: set[str] = set()

    for _ in range(runs):
        started = time.monotonic()
        try:
            result = ladder.generate_content(PROMPT)
        except LadderExhausted as exc:
            elapsed = (time.monotonic() - started) * 1000.0
            verdict, extra = check(exc.attempts, depth, exhausted)
            verdicts.add(verdict if exhausted else "exhausted, expected a success")
            organic.update(extra)
            answered.add("-- exhausted --")
            latencies.append(elapsed)
            tick("-", end="")
            continue
        except Exception as exc:
            verdicts.add(type(exc).__name__)
            tick("x", end="")
            continue
        latencies.append((time.monotonic() - started) * 1000.0)
        tick(".", end="")
        verdict, extra = check(result.attempts, depth, exhausted)
        verdicts.add(verdict)
        organic.update(extra)
        answered.add(result.attempts[-1].step)
        if result.attempts[-1].tier_granted:
            granted.add(result.attempts[-1].tier_granted)

    return {
        "depth": depth,
        "first_live": first_live,
        "answered": ", ".join(f"`{name}`" for name in sorted(answered)) or "-",
        "ok": len(latencies),
        "runs": runs,
        "median_ms": statistics.median(latencies) if latencies else float("nan"),
        "p90_ms": percentile(latencies, 0.9),
        "granted": ", ".join(sorted(granted)) or "-",
        "verdict": ", ".join(sorted(verdicts)) or "-",
        "organic": ", ".join(sorted(organic)) or "-",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT"))
    parser.add_argument("--model", default="gemini-3.7-flash")
    parser.add_argument("-n", "--runs", type=int, default=3)
    parser.add_argument("--max-depth", type=int, default=6)
    parser.add_argument("--deadline", type=float, default=900.0)
    parser.add_argument(
        "--trail", action="store_true", help="print the attempt trail of one deep run"
    )
    parser.add_argument(
        "--records",
        action="store_true",
        help="stream every attempt to stderr as JSON instead of progress",
    )
    args = parser.parse_args()
    if not args.project:
        parser.error("pass --project or set GOOGLE_CLOUD_PROJECT")

    base = play_smart_default(args.model)
    depths = range(0, min(args.max_depth, len(base.steps)) + 1)

    print(
        f"project={args.project}  runs per depth={args.runs}  "
        f"ladder={base.name}  prompt={len(PROMPT)} chars\n"
    )
    print(
        "| forced 429s | first live step | answered at | measured | granted "
        "| median s | p90 s | hops verified | organic 429s |"
    )
    print("|---:|---|---|---|---|---:|---:|---|---|")

    sink = stderr_sink if args.records else None
    quiet = sink is not None
    if not quiet:
        note(
            f"{len(depths)} depths x {args.runs} traversals, one request at a "
            "time. Every one is forced to fail; budget minutes."
        )
    began = time.monotonic()

    for position, depth in enumerate(depths, start=1):
        if not quiet:
            note(f"[{position}/{len(depths)}] {depth} forced 429s ", end="")
        stats = run_depth(base, depth, args.project, args.runs, args.deadline, sink)
        if not quiet:
            note(
                f" {stats['median_ms'] / 1000:.1f} s median, answered at "
                f"{stats['answered'].replace('`', '')}"
            )
        print(
            f"| {stats['depth']} | `{stats['first_live']}` | {stats['answered']} "
            f"| {stats['ok']}/{stats['runs']} | `{stats['granted']}` "
            f"| {stats['median_ms'] / 1000:.1f} | {stats['p90_ms'] / 1000:.1f} "
            f"| {stats['verdict']} | {stats['organic']} |"
        )

    if not quiet:
        took = time.monotonic() - began
        note(f"done in {took:.0f} s" if took < 90 else f"done in {took / 60:.1f} min")

    if args.trail:
        depth = min(args.max_depth, len(base.steps) - 1)
        spec = poisoned_spec(base, depth)
        ladder = CapacityLadder(
            spec, project=args.project, deadline_s=args.deadline, sink=None
        )
        print(f"\nAttempt trail, {depth} forced 429s:\n")
        print(ladder.generate_content(PROMPT).table())

    print(
        "\nForced 429s are real: the first N steps are sent with the `dedicated`\n"
        "header, which a project with no Provisioned Throughput order cannot serve.\n"
        "Every step below them runs against real capacity, so an organic 429 there\n"
        "is a genuine refusal, not part of the setup. The timing is wall clock from\n"
        "the call to the ladder's verdict -- an answer on every row but the last,\n"
        "where the verdict is `LadderExhausted`."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
