#!/usr/bin/env python3
"""Isolate why a Priority PayGo request does not report as Priority.

The Priority PayGo doc gives two header spellings -- one that consumes any
Provisioned Throughput quota first, one that pins the request to Priority --
and this library uses the second. Both have been observed returning
``traffic_type: ON_DEMAND`` rather than ``ON_DEMAND_PRIORITY``, on models that
are on Priority's own supported list, on the global endpoint it requires.

That observation invites a tidy explanation, and there isn't one available
from out here. This script exists to narrow the space rather than guess at it,
by running the variants side by side against controls:

  * both documented Priority spellings, to rule out sending the wrong headers
  * the same client path with ``flex``, to prove headers reach the service and
    that ``traffic_type`` does reflect a granted lane
  * ``flex`` on an unsupported model, to show the service *does* reject a
    shared-request-type it cannot honour -- loudly, with a 400
  * no headers at all, as a baseline

If Priority reports ON_DEMAND while Flex reports ON_DEMAND_FLEX on the same
client, the remaining explanations are an unadvertised project entitlement,
a capacity-based fallback, or a labelling gap where the tier is honoured but
not reported. **None of those are distinguishable from a client.** Only your
billing data separates them, which is the actual takeaway: verify the tier you
are paying for against the invoice, not against a 200.

Usage:
    python demo/probe_priority_headers.py [--project PROJECT] [--model MODEL]
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
    REQUEST_TYPE_HEADER,
    SHARED_REQUEST_TYPE_HEADER,
)

PROMPT = "Reply with the single word: ok"

#: The two spellings the Priority doc documents, plus controls. Order matters
#: for readability: variants first, controls after.
VARIANTS: list[tuple[str, dict[str, str], str]] = [
    (
        "priority (PT-first spelling)",
        {SHARED_REQUEST_TYPE_HEADER: "priority"},
        "Doc: 'use PT quota if available, then Priority'",
    ),
    (
        "priority (pinned spelling)",
        {REQUEST_TYPE_HEADER: "shared", SHARED_REQUEST_TYPE_HEADER: "priority"},
        "Doc: 'use only Priority PayGo' -- what this library sends",
    ),
    (
        "flex (control)",
        {REQUEST_TYPE_HEADER: "shared", SHARED_REQUEST_TYPE_HEADER: "flex"},
        "Proves headers arrive and traffic_type reflects the lane",
    ),
    (
        "no headers (baseline)",
        {},
        "PT-then-PayGo default",
    ),
]


def probe(project: str, model: str, headers: dict[str, str]) -> str:
    """Return the reported traffic type, or a short failure label."""
    try:
        client = genai.Client(
            vertexai=True,
            project=project,
            location="global",
            http_options=types.HttpOptions(api_version="v1", headers=headers),
        )
        response = client.models.generate_content(
            model=model,
            contents=PROMPT,
            config=types.GenerateContentConfig(
                # Generous on purpose: Gemini 3.x spends output budget on
                # thinking tokens first, and an empty .text from MAX_TOKENS
                # looks exactly like a failure it is not.
                max_output_tokens=512,
            ),
        )
        traffic = response.usage_metadata.traffic_type
        return getattr(traffic, "name", str(traffic))
    except Exception as exc:  # a probe reports failures, it does not raise them
        text = str(exc).replace("\n", " ")
        if "not supported" in text:
            return "400 not supported"
        return f"ERROR {text[:40]}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT"))
    parser.add_argument(
        "--model",
        default="gemini-3.7-flash",
        help="A model on Priority's supported list.",
    )
    parser.add_argument(
        "--unsupported-model",
        default="gemini-2.5-flash",
        help="A model Flex does not support, used to show the loud rejection.",
    )
    args = parser.parse_args()

    if not args.project:
        print("Set GOOGLE_CLOUD_PROJECT or pass --project", file=sys.stderr)
        return 2

    print(f"project={args.project}  location=global  model={args.model}\n")
    print(f"{'variant':<32}{'reported traffic_type':<26}note")
    print("-" * 104)
    for label, headers, note in VARIANTS:
        print(f"{label:<32}{probe(args.project, args.model, headers):<26}{note}")

    flex_headers = {REQUEST_TYPE_HEADER: "shared", SHARED_REQUEST_TYPE_HEADER: "flex"}
    print(
        f"{'flex on ' + args.unsupported_model:<32}"
        f"{probe(args.project, args.unsupported_model, flex_headers):<26}"
        "The service DOES reject an unhonourable lane -- for Flex"
    )

    print(
        "\nIf the two priority rows read ON_DEMAND while the flex control reads\n"
        "ON_DEMAND_FLEX, the headers are correct and reaching the service. What\n"
        "you cannot conclude from here is why: entitlement, capacity fallback and\n"
        "a reporting gap are indistinguishable at this layer. Take it to billing."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
