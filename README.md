# Gemini Play Smart — a 429-survival capacity ladder

**Combine, don't choose** — creative failover on the Gemini Agent Platform.

When a Gemini request comes back `RESOURCE_EXHAUSTED`, the usual advice is to
retry the same call against the same capacity that just refused it. This library
does something else: it walks a **ladder** of steps, changing exactly one
variable per step, until one of them answers.

This is a demonstration of a concept, not a production library. Read it, take
the pattern, write your own.

![Happy user, got their answer, no failure. Underneath, this unlucky call walked three steps; most stop at the first. Above the line, what the user sees: one request, one call, no error handling, and a 200 OK — no 429 ever reached the user. Below the line, inside that one call, each step changes exactly one variable — tier, model or endpoint — and the ladder stops at the first that answers. On gemini-3.7-flash: Flex hit its 60-second cap and moved on, Standard PayGo returned a 429, Priority PayGo answered with a 200, and that is the 200 the user got. A fourth step, another model then multi-region, was never reached.](docs/concept.png)

[Provisioned Throughput](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/provisioned-throughput)
is an excellent consumption option for real-time production and critical
workloads. That said, **this solution requires no Provisioned Throughput order** — it is the route for teams who cannot reserve
capacity, have not yet, or would rather find out how far they get without it.

In a hurry? The whole argument fits on
[a one-pager](docs/one-pager.pdf) — the ladder, the 60-second Flex bet, the two
presets, and what a fully failed traversal actually costs. The long version,
with the reasoning behind every step, is [the article](ARTICLE.md). What follows
is what you need to run it.

At its core is one idea: **you don't choose a consumption option, you order
them.** A ladder is an ordered list of steps, and the six below are a worked
example, not a prescription. Reordering that list changes your entire cost and
latency posture without touching a line of client code.

```python
from play_smart import CapacityLadder, play_smart_default

ladder = CapacityLadder(play_smart_default(), project="my-project")
result = ladder.generate_content("Summarise this contract.")

print(result.text)
print(result.step_used)  # 'flex' — or wherever it actually landed
print(result.table())  # every hop, tier requested vs tier granted
```

Your `GenerateContentConfig` passes through untouched — system instructions,
tools, response schemas, sampling:

```python
from google.genai import types

result = ladder.generate_content(
    "Summarise this contract.",
    config=types.GenerateContentConfig(
        system_instruction="You are a contracts analyst. Answer in three bullets.",
        temperature=0.2,
    ),
)
```

---

## The default ladder

`play_smart_default()` opens on the cheapest capacity and escalates only when
refused, bounded at every step.

| # | Step | Consumption option | Model | Endpoint | Timeout | Attempts per step |
|---|---|---|---|---|---|---|
| 1 | `flex` | Flex PayGo | `gemini-3.7-flash` | `global` | **60 s** | 1 |
| 2 | `standard` | Standard PayGo | `gemini-3.7-flash` | `global` | 60 s | 3 |
| 3 | `priority` | Priority PayGo | `gemini-3.7-flash` | `global` | 30 s | 3 |
| 4 | `alternative_model` | Standard PayGo | `gemini-3.6-flash` | `global` | 30 s | 2 |
| 5 | `multi_region_us` | Standard PayGo | `gemini-3.6-flash` | `us` | 60 s | 2 |
| 6 | `multi_region_eu` | Standard PayGo | `gemini-3.6-flash` | `eu` | 60 s | 2 |

Steps 1–3 are the same request to three separate pools, selected by two HTTP
headers and nothing else.

### Each step changes exactly one variable — consumption option, model or endpoint

- **Steps 1–3** vary only the **consumption option**: Flex → Standard → Priority.
- **Step 4** changes only the **model**.
- **Steps 5–6** change only the **endpoint**.

None of them moves more than one element, on purpose.

### Two kinds of retry, and the line between them

`HttpRetryOptions` retries **within** a step — same model, consumption option
and endpoint,
exponential backoff with jitter. The ladder retries **across** steps. This
library configures the first per step rather than replacing it, and enforces the
line in the type system: `classify()` returns `ADVANCE` or `ABORT`, and
`Disposition` deliberately has no `RETRY` member. [Further explanation on this
topic](ARTICLE.md#two-kinds-of-retry-and-the-line-between-them).

---

## Choosing a ladder

Two presets, one engine. They differ only in the order and parameters of their
steps — which *is* the argument. Neither requires a Provisioned Throughput
order.

| Preset | Shape | For |
|---|---|---|
| `play_smart_default()` | Flex → Standard → Priority → alternative model → `us` → `eu` | Latency-tolerant, agentic, batch-ish |
| `latency_first()` | Priority on three models, tight timeouts | Interactive, user-facing |

Or write your own — it is a dozen lines of data:

```python
from play_smart import LadderSpec, Step, Tier

LadderSpec(
    name="my-ladder",
    primary_model="gemini-3.7-flash",
    steps=(
        Step(name="flex", tier=Tier.FLEX, timeout_s=45, attempts=1),
        Step(name="standard", tier=Tier.STANDARD, timeout_s=60, attempts=3),
    ),
)
```

---

## The 60-second bet

Step 1 caps Flex at 60 seconds, one attempt, no retry. It is not a fallback —
**it is a priced wager.** Flex is a published
[**50% discount**](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing)
against Standard PayGo, so the step spends up to a minute of latency for a
coin-flip at half price. The cap is the trick: Flex's default timeout is **ten
minutes**, correct for the offline work it is sold for, a stall as a synchronous
first hop.

Flex is best-effort and these runs promise nothing about yours; I have had Flex
calls that did not finish inside the cap. If your SLA cannot absorb the opening
bet, pass `deadline_s` or use `latency_first()`, which opens on Priority.
[The case for the bet](ARTICLE.md#the-60-second-bet), including why the step
gets no retry.

---

## What we measured

Twenty-one traversals, every one forced to fail, three at each depth from 0 to
6. The sweep, the medians and one attempt-by-attempt trail are in
[the article](ARTICLE.md#what-my-runs-said). Full outputs from every run are in
[`demo/results/`](demo/results/), and
[`bench_ladder.py`](#test-the-ladder-against-live-traffic) reproduces them on
your own capacity.

---

## Install

```bash
git clone https://github.com/eilonbar/gemini-play-smart
cd gemini-play-smart

python3 run.py
```

Standard library only — nothing to install before installing. It builds `.venv`,
puts the package in it, and runs the mocked tests. About ten seconds, and it
ends by printing the line that activates the venv, which everything below
assumes. `python3 run.py help` lists what else it can drive.

### If you'd rather do it by hand

`run.py` exists for one specific failure: on Debian and Ubuntu `ensurepip` lives
in a separate `python3-venv` package, so the obvious recipe dies with `ensurepip
is not available` and leaves a broken `.venv` behind. `run.py` bootstraps pip
itself instead. If your Python has `ensurepip`, the recipe is the one you
already know:

```bash
python3 -m venv .venv && source .venv/bin/activate   # Python 3.10+
pip install -e ".[dev]"
```

## How can you call the ladder instead of calling Gemini directly?

This is the point of the package; everything below it is verification. Two
lines of setup:

```bash
gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT=your-project-id
```

and this file runs as written:

```python
from google.genai import types

from play_smart import CapacityLadder, play_smart_default

# project= is optional once GOOGLE_CLOUD_PROJECT is set.
ladder = CapacityLadder(play_smart_default())

result = ladder.generate_content(
    "Summarise this contract.",
    config=types.GenerateContentConfig(
        system_instruction="You are a contracts analyst. Answer in three bullets.",
        temperature=0.2,
    ),
)

print(result.text)  # the answer, exactly as the SDK would have given it
print(result.step_used)  # 'flex' — or wherever it actually landed
print(result.table())  # every hop, tier requested vs tier granted
```

That is the whole change at the call site. Where you had

```python
response = client.models.generate_content(model=..., contents=..., config=...)
```

you have

```python
result = ladder.generate_content(contents, config=...)
```

The model comes from the ladder spec rather than the call, and your
`GenerateContentConfig` passes through untouched. `result.text` is the
passthrough you already use; `result.step_used`, `result.attempts` and
`result.table()` are the trail of what it took to get it. Pass `deadline_s` to
bound a whole traversal — compare it against `spec.worst_case_s` first.

## Test the library against mocked traffic

`python3 run.py` already ran these. To run them again — after a change, or if
you installed by hand:

```bash
pytest -q -m "not live"
```

No cloud account, no credentials, about a second. Eighty-one tests against a
mocked transport: traversal and classification, the deadline arithmetic, and
the construction-time rejection of steps that cannot work.

Drop the `-q` to see all 81 by name; they are written to read as sentences. The
nine live tests in [`tests/test_live.py`](tests/test_live.py) are held back by
`-m "not live"`; `python3 run.py live` runs them once you have the credentials
above.

## Test the ladder against live traffic

This one calls the real API and bills your project. A minute or so. It runs the
ladder twice, printing every attempt: once on the healthy path, then again
starting from a real 429.

That 429 is not simulated. The second run prepends a step sent with
`X-Vertex-AI-LLM-Request-Type: dedicated`, which demands reserved capacity — and
a project with no Provisioned Throughput order has none, so the platform refuses
instantly and for free. It is a **429 generator for the demo, not a ladder
step**, and the only one you can summon on demand.

```bash
gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT=your-project-id

python demo/live_ladder.py
```

That is one path. For all of them, `bench_ladder.py` forces the ladder to fail
at every depth in turn — three traversals at each depth from 0 to 6, 21 in
all — and reproduces [the sweep in the
article](ARTICLE.md#what-my-runs-said) on your own capacity. Four to seven
minutes.

It poisons the first *k* steps with that same `dedicated` header, so every
failure is a real refusal and everything below step *k* runs against real
capacity. Progress goes to stderr and the table to stdout, so `> results.md`
keeps just the table; `--records` swaps the progress for the attempt trail as
JSON, the auditable record behind every number here.

```bash
python demo/bench_ladder.py -n 3
```

## Extras

Everything here needs the credentials above.

```bash
python demo/bench.py -n 20            # per-step latency and grant rates (6-10 min)
python demo/probe_matrix.py           # print the model × tier × endpoint matrix
python demo/probe_matrix.py --check   # whether the table in the code still matches the platform
```

`bench.py` is the other half of the measurement. It times each step *in
isolation* — the numbers that decide a ladder's order — and never traverses
one; `bench_ladder.py` above measures what traversing costs. Same conventions:
one request at a time, progress on stderr, table on stdout.

## Instructions for an AI agent

**Running this with an AI agent?** Say:

```
clone https://github.com/eilonbar/gemini-play-smart and run according to
instructions for AI agent in the readme
```

That is the whole prompt — the agent does not need the repo open already.
Everything below is addressed to the agent, not to you: setup, the order to
run things in, what it may spend, which surprising results are expected, and
what to report back.

---

Agent: this section is that instruction. Follow it start to finish, then
report back.

**Set up in a fresh directory.** Clone this repo somewhere new — do not reuse
an existing clone or an existing `.venv`. A stale virtualenv is the most common
way to end up with a `google-genai` below the floor in `pyproject.toml`, and
the multi-region steps then fail for reasons that have nothing to do with this
code.

```bash
python3 run.py
```

That single command builds a venv, installs the package, and runs the 81
offline tests.

**Python.** This repo needs 3.10 or newer, and the `python3` on the box may be
older. If it is, use any 3.10+ interpreter already installed — check
`/usr/local/bin`, `/opt/homebrew/bin`, `/Library/Frameworks/Python.framework`,
and `pyenv` — and say which one you used. Do **not** install a Python, do
**not** edit `requires-python`, and do not otherwise work around the floor. If
no 3.10+ interpreter exists anywhere, stop and say so.

**SDK version.** Report the resolved `google-genai` version, but do not gate on
it. The dependency floor in `pyproject.toml` is the real guard.

**Credentials.** Assume the operator has already run `gcloud auth
application-default login`. If credentials are missing, `run.py` exits saying
exactly what is absent — report that rather than attempting a login yourself.

**Project id.** Do not ask for it, and do not print it in your report or in any
output you quote — write `<PROJECT>` instead. Resolve it yourself, in this
order:

1. `$GOOGLE_CLOUD_PROJECT`, if already set
2. `gcloud config get-value project`
3. the `quota_project_id` field in the ADC file

Export it before the live targets. If all three fail, stop — do not guess one.
These targets bill real money.

**The run.** In order, substituting whichever interpreter you settled on. Stop
if one fails, except `check` — see below.

```bash
python3 run.py check     # declared matrix vs. the live API
python3 run.py live      # the live pytest suite
python3 run.py headers   # both Priority spellings against a Flex control
python3 run.py ladder    # forces a real 429, watch the recovery
python3 run.py matrix    # the full model × tier × endpoint matrix
python3 run.py sweep     # 21 traversals, forced to fail at every depth
```

`ladder` takes about a minute and `sweep` four to seven. That is normal — let
them finish, do not kill them.

**Do not run `bench`.** Ask first. It is 20 samples per step, six to ten
minutes, and the most expensive target here. `matrix` and `sweep` also make
real billable calls; report roughly how many you made.

**Three results look like failures and may not be.** Do not pattern-match these
and wave them through — for each, say what in the output distinguishes the
benign case from a genuine fault.

- `check` exits non-zero on **matrix drift**. The matrix declared in
  [`play_smart/tiers.py`](play_smart/tiers.py) is a dated cache of a live
  observation, not a contract, and the platform moves without announcement. A
  `DRIFT` report is the detector working. Record exactly what drifted and keep
  going — `live` runs the same check and fails the same way, so note it and
  continue to `headers`. A crash, an auth error or a timeout from `check` is a
  real failure; stop for those.
- The `priority` rows report `ON_DEMAND` rather than `ON_DEMAND_PRIORITY`
  unless the project has Priority PayGo enabled.
- `gemini-2.5-flash` returns 404 on the `us` and `eu` endpoints.

**Report.** Per-target pass/fail with exit codes and the headline numbers, plus
the raw output of anything that failed. Call out any judgment call you made
rather than burying it. Do not edit the repo to make something pass, and do not
commit or push — confirm the working tree is clean when you finish.

## Layout

```
play_smart/     the library
  tiers.py      Tier enum, headers, and the model × tier × endpoint matrix
  steps.py      Step and LadderSpec — validated at construction
  errors.py     classify() -> ADVANCE | ABORT
  ladder.py     CapacityLadder.generate_content() — the traversal engine
  budget.py     Wall-clock deadline accounting shared across steps
  presets.py    The two ladders
  telemetry.py  AttemptRecord, LadderResult, silent-downgrade detection
demo/           five scripts that call the real API; results/ holds every run
tests/          the mocked suite, plus the live one behind -m live
docs/           the one-pager and the figures, with their sources
run.py          installs and drives all of the above — python3 run.py help
```

## References

- [Consumption options](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/deploy/consumption-options) — where the two headers are specified
- [Retry strategy and consumption options](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/retry-strategy)
- [Provisioned Throughput](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/provisioned-throughput)
- [Flex PayGo](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/flex-paygo)
- [Priority PayGo](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/priority-paygo)
- [Pricing](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing) — where the Flex discount is published
- [`configure_retries.ipynb`](https://github.com/GoogleCloudPlatform/generative-ai/blob/main/sdk/retries/configure_retries.ipynb) — the Google notebook this extends
- [The article](ARTICLE.md) — the argument in full, with the measurements that produced it
- [One-pager](docs/one-pager.pdf) ([source](docs/index.html)) — the whole argument on a single printed page

## What's next

This package is deliberately only the ladder. Context caching and Batch
inference are real capacity levers too — for some workloads they are the bigger
win — but folding them in here would blur the single claim this repo is making.

Caching is the next one. **[Follow me on Medium](https://medium.com/@eilonbar)**
for a companion article coming
soon on context caching as a complementary optimisation for production
workloads.

## License

Apache 2.0.

## Disclaimer

This code is provided "as-is" as a demonstration only to illustrate a potential
solution. The code does not constitute a Google product or service of any kind,
and Google offers no support, warranties, or liability of any kind with its
regard. Whoever chooses to use this code accepts all responsibility related to
it, including for its implementation, use, and ongoing maintenance. For the
avoidance of doubt, this code is not eligible for the Google Open Source
Software Vulnerability Rewards Program.
