# Gemini Play Smart — a 429-survival capacity ladder

### Creative failover on the Gemini Agent Platform, combining consumption options, models and endpoints. No Provisioned Throughput order required.

![Happy user, got their answer, no failure. Underneath, the ladder was refused twice and answered on the third step. You customise the ladder as you wish in each step — a different tier, model or endpoint. Above the line, what the user sees: one request, one call, and a 200 OK. Below the line, what the client actually did, all three on gemini-3.7-flash: Flex refused with a 429, Standard PayGo refused with a 429, Priority PayGo answered.](docs/concept.png)

*The caller makes one request and gets one answer. Underneath, two pools
refused and a third answered. Image by author.*

---

I work closely with some amazing companies running Gemini in production at
scale. One question comes up more than any other:

> "We're getting 429s. Do we need to buy Provisioned Throughput?"

Plenty of production traffic never sees a `RESOURCE_EXHAUSTED`. When a burst
does hit one,
**[Provisioned Throughput](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/provisioned-throughput)
is an excellent answer** — reserved capacity, no competing for a shared pool,
the right consumption option for real-time production and critical workloads.
If you can commit to it, commit to it. It is also a commitment with a bill that
arrives whether or not you use it, and this article is about the other route:
**no Provisioned Throughput order required**, for teams who cannot reserve
capacity or would rather find out how far they get without it.

That route is a **smart capacity strategy** with creative failover. When a
request comes back `RESOURCE_EXHAUSTED`, don't ask the same pool the same
question again. Move — different consumption option, different model, different
endpoint — until something answers.
**Combine, don't choose.**

I have worked this through with several of those companies. The numbers below
come from live runs against a real project — not a benchmark, just my own small
runs.

Worked example:
**[github.com/eilonbar/gemini-play-smart](https://github.com/eilonbar/gemini-play-smart)**.
Every code snippet below is from that repository and is licensed under
[Apache 2.0](https://github.com/eilonbar/gemini-play-smart/blob/main/LICENSE).

---

## Two kinds of retry, and the line between them

Start with what already exists and is good. The Gen AI SDK ships
`HttpRetryOptions`: exponential backoff, jitter, status-code filtering, all of
it configurable per request, and documented in Google's
[retry strategy guide](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/retry-strategy).
It is the right tool for a **transient error**, and I recommend using it rather
than rebuilding it.

```python
from google.genai import types

retry = types.HttpRetryOptions(attempts=3, initial_delay=1.0, exp_base=2.0, jitter=1.0)
```

**What it cannot do is change *what* it is retrying.** Every attempt goes to the
same consumption option, the same model, the same endpoint — so against a pool
that is genuinely out of capacity it burns your latency budget and raises,
having never tried the model, endpoint or other consumption option next door.

That is the line:

- **Within a step** — same option, model, endpoint. Handles transient error. The SDK
  already does this. Use it.
- **Across steps** — a genuinely different capacity pool. Handles shortage.
  It is the concept I demonstrate in this repo.

So this solution keeps the SDK's retries *inside* each step and adds one outer
loop that walks a **ladder**: an ordered list of steps that automatically tries
different consumption options, models and endpoints until one answers. The order
and the parameters of each step are yours to set.

## The ladder

Six steps, cheapest first, bounded at every one. This is the shipped default:

| # | Step | Consumption option | Model | Endpoint | Timeout | Attempts per step |
|---|---|---|---|---|---|---|
| 1 | `flex` | Flex PayGo | `gemini-3.7-flash` | `global` | **60 s** | 1 |
| 2 | `standard` | Standard PayGo | `gemini-3.7-flash` | `global` | 60 s | 3 |
| 3 | `priority` | Priority PayGo | `gemini-3.7-flash` | `global` | 30 s | 3 |
| 4 | `alternative_model` | Standard PayGo | `gemini-3.6-flash` | `global` | 30 s | 2 |
| 5 | `multi_region_us` | Standard PayGo | `gemini-3.6-flash` | `us` | 60 s | 2 |
| 6 | `multi_region_eu` | Standard PayGo | `gemini-3.6-flash` | `eu` | 60 s | 2 |

Steps 1–3 are selected by [two HTTP
headers](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/deploy/consumption-options).
That is the entire mechanism:

```python
STANDARD = {"X-Vertex-AI-LLM-Request-Type": "shared"}
FLEX = {**STANDARD, "X-Vertex-AI-LLM-Shared-Request-Type": "flex"}  # -50% cost
PRIORITY = {**STANDARD, "X-Vertex-AI-LLM-Shared-Request-Type": "priority"}  # premium
```

**Each step changes exactly one variable.**

- **Steps 1–3** vary only the **consumption option**: Flex → Standard → Priority.
- **Step 4** changes only the **model**.
- **Steps 5–6** change only the **endpoint**.

This is the design rule I would most like people to steal: it costs nothing, and
at 3am it tells you which dimension bought the recovery. A step that moves model
*and* endpoint *and* consumption option together still rescues the request, and
teaches you nothing.

## How it's built

The whole thing is about 60 lines of real logic, and the interesting decisions
are in what it refuses to do.

**You don't choose a consumption option, you order them.** A `Step` is five
fields — consumption option, model, endpoint, timeout, attempts — and a ladder
is an ordered list of them, traversed by one `for` loop. The six steps above are
a worked example, not a prescription. Reorder that list and you change your
entire cost and latency posture without touching a line of client code.
`play_smart_default` and `latency_first` are two such lists, ready to use, but
you can also define your own:

```python
from play_smart import CapacityLadder, LadderSpec, Step, Tier

spec = LadderSpec(
    name="my-ladder",
    primary_model="gemini-3.7-flash",
    steps=(
        Step(name="flex", tier=Tier.FLEX, timeout_s=60, attempts=1),
        Step(name="standard", tier=Tier.STANDARD, timeout_s=60, attempts=3),
        Step(name="alt", tier=Tier.STANDARD, model="gemini-3.6-flash", attempts=2),
    ),
)
ladder = CapacityLadder(spec, project="my-project")
result = ladder.generate_content("Summarise this contract.")
```

**The two retry loops never overlap.** Per step the ladder hands the SDK
`HttpRetryOptions` and the ladder owns only the outer loop. The classifier returns
`ADVANCE` or `ABORT` — there is deliberately **no `RETRY` member on the enum**.
`ABORT` is reserved for errors no step can fix: malformed request, auth failure,
safety block. Everything else advances, including anything unrecognised, because
wasting a step is cheaper than dropping a request.

**A wall-clock budget bounds the whole traversal.** Six generous steps is a
ten-minute worst case, so a traversal can carry a deadline that shrinks each
step's timeout to the time remaining. Steps with no useful time left are
skipped, and still recorded; a trail with a gap is worse than no trail.

**The attempt trail is the product.** Every attempt emits a JSON record —
failures included, with `tier_requested` beside `tier_granted`. Without it you
have a system that mysteriously works, which is one incident away from a system
that mysteriously doesn't.

## Run the tests against your own project

The repo is not just the engine. It ships the tests I used, in two halves.

One half needs no cloud account: about eighty tests against a mocked transport,
covering traversal, classification, backoff and the deadline in about a second.
That is the
[first thing the README has you run](https://github.com/eilonbar/gemini-play-smart#test-the-library-against-mocked-traffic).

The other half calls the real API, so the answers are yours — your
entitlements, your quota, your regions:

```bash
python demo/live_ladder.py            # one traversal, printed attempt by attempt
python demo/bench_ladder.py -n 3      # whole traversals, forced to fail at every depth
python demo/bench.py -n 20            # each step on its own: latency, and what you were granted
python demo/probe_matrix.py --check   # whether the table in the code still matches the platform
```

Run them.
[The README](https://github.com/eilonbar/gemini-play-smart#test-the-ladder-against-live-traffic)
has the credentials, the order to run them in, and what each one costs you in
minutes.

### How to generate a real 429

Testing failover honestly needs a real 429, and you can't make Google run out
of capacity on request. One is free to summon:
`X-Vertex-AI-LLM-Request-Type: dedicated` demands reserved capacity and refuses
to spill, so on a project with no PT order it returns `RESOURCE_EXHAUSTED`
instantly — 100% of requests, every run. A 429 generator, not a ladder step.
Nothing below is simulated.

## What my runs said

I drove the whole ladder, 21 traversals, every one forced to fail.
`demo/bench_ladder.py` poisons the first *k* steps by swapping their consumption
option for `dedicated` — the free, instant, real 429 from above. Everything
below step *k* runs against real capacity. Three runs at each depth from 0 to 6:

![Every step refused, one depth at a time. A grid of seven rows, one per run
depth, and six columns, one per ladder step: flex, standard, priority,
alternative_model, multi_region_us, multi_region_eu. Row 0 poisons nothing and
flex answers 200 OK. Each row below poisons one more step — shown as a 429 —
and the 200 OK moves one column right. Row 6 poisons all six and the ladder
raises. Median traversal times, right: 11.5s, 4.9s, 8.5s, 12.6s, 14.9s, 16.0s,
12.3s.](docs/depth_sweep.png)

*The green box always sits immediately after the last red one: every run landed
on the first live step. Image by author, plotted from the runs in
[`demo/results/`](https://github.com/eilonbar/gemini-play-smart/tree/main/demo/results).*

Below is the trail of one run from the `5` row: five forced refusals, then an
answer out of Europe. `tries` is the attempts allowed inside the step; `step ms`
is the whole step, backoff included.

```
#  step                requested  granted    model             loc     tries  step ms  result
1  flex                dedicated  -          gemini-3.6-flash  global      1      952  FAIL 429
2  standard            dedicated  -          gemini-3.6-flash  global      3     3715  FAIL 429
3  priority            dedicated  -          gemini-3.6-flash  global      3     2612  FAIL 429
4  alternative_model   dedicated  -          gemini-3.5-flash  global      2     1822  FAIL 429
5  multi_region_us     dedicated  -          gemini-3.5-flash  us          2     2678  FAIL 429
6  multi_region_eu     standard   ON_DEMAND  gemini-3.5-flash  eu          2     6814  OK
```

## The 60-second bet

Step 1 caps Flex at 60 seconds, one attempt, no retry. People argue with the no
retry, and the
[retry-strategy guide](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/retry-strategy)
answers them: Flex is discounted precisely because it is allowed to refuse you,
so a 429 there means the cheap capacity is busy, not that you were unlucky.
Asking it twice is asking the same pool the same question.

The step is not a fallback — **it is a priced wager.** Flex is a published
[50% discount](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing),
exactly half of Standard on every Gemini row of the pricing table, so the step
says: *spend up to a minute of latency for a coin-flip at half price.* Losing
costs 60 seconds; winning halves the bill. For work no human is watching —
enrichment, evaluation, document pipelines, most agentic sub-calls — that is
arithmetic, not compromise.

Flex is best-effort and my small runs promise nothing about yours. On one day of
testing it answered in about 8 seconds, 18.2 as a median; on another, not one
call finished inside the 60-second cap. That is the bet losing on the terms it
was written for, which is the point of writing the cap down.

The cap is the trick. Flex's default timeout is **ten minutes** — correct for
the offline work it is sold for, catastrophic as a synchronous first hop. An
unmodified Flex client is not a cost optimisation; it is a ten-minute stall with
a discount attached.

If your SLA can't absorb a 60-second opening bet, open on
[`latency_first`](https://github.com/eilonbar/gemini-play-smart#choosing-a-ladder)
instead, or set your own order.

---

## The bottom line

429s are usually read as a signal to buy more capacity. Often they are a signal
that you are only using one kind.

If you encounter 429s, commit to Provisioned Throughput — or spend an afternoon
on the ladder first. Send the two headers you have never sent. Put an alternate
model behind your primary and a multi-region endpoint behind that. Then measure
on your own project, because the distribution matters more than the number.

Combine, don't choose.

---

**What's next.** Context caching and Batch inference are real capacity levers
too, and for some workloads they are the bigger win. I left them out on purpose:
this article is only the ladder — a concept for making production workloads
robust and driving the impact of 429s toward zero.
**[Follow me on Medium](https://medium.com/@eilonbar)** for a
companion article coming soon on context caching as a complementary optimisation
for production workloads.

**Now your turn.** Install and run it, following the guidelines at
[github.com/eilonbar/gemini-play-smart#install](https://github.com/eilonbar/gemini-play-smart#install).

**References:**
[Consumption options](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/deploy/consumption-options) ·
[Retry strategy](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/retry-strategy) ·
[Provisioned Throughput](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/provisioned-throughput) ·
[Flex PayGo](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/flex-paygo) ·
[Priority PayGo](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/priority-paygo) ·
[Pricing](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing) ·
[configure_retries.ipynb](https://github.com/GoogleCloudPlatform/generative-ai/blob/main/sdk/retries/configure_retries.ipynb)

---

**Disclaimer.** This code is provided "as-is" as a demonstration only to
illustrate a potential solution. The code does not constitute a Google product
or service of any kind, and Google offers no support, warranties, or liability
of any kind with its regard. Whoever chooses to use this code accepts all
responsibility related to it, including for its implementation, use, and ongoing
maintenance. For the avoidance of doubt, this code is not eligible for the
Google Open Source Software Vulnerability Rewards Program.
