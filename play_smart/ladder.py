"""The capacity ladder.

There is a clean division of labour here, and it is the whole idea:

* The **Gen AI SDK** retries *within* a capacity lane. ``HttpRetryOptions``
  already does exponential backoff with jitter over the right status codes,
  and it is the supported, documented mechanism. We do not reimplement it.
* The **ladder** retries *across* capacity lanes -- a dimension the SDK has no
  way to express, because changing lane means changing headers, model, or
  endpoint mid-flight.

Stacked, they turn "capacity is exhausted" from a 429 your user sees into a
routing decision your telemetry records.

References:
  https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/retry-strategy
  https://github.com/GoogleCloudPlatform/generative-ai/blob/main/sdk/retries/configure_retries.ipynb
"""

from __future__ import annotations

import os
from typing import Any

from google import genai
from google.genai import types

from .budget import Budget
from .errors import (
    RETRYABLE_STATUS_CODES,
    Disposition,
    LadderAborted,
    LadderExhausted,
    classify,
    status_of,
)
from .steps import LadderSpec, Step
from .telemetry import (
    AttemptRecord,
    LadderResult,
    Sink,
    Stopwatch,
    log_sink,
    read_usage,
)
from .tiers import headers_for


class CapacityLadder:
    """Runs a :class:`~play_smart.steps.LadderSpec` against the Gemini Agent Platform.

    Example:
        >>> from play_smart import CapacityLadder, play_smart_default
        >>> ladder = CapacityLadder(play_smart_default(), project="my-project")
        >>> result = ladder.generate_content("Summarise this contract.")
        >>> result.step_used
        'flex'
    """

    def __init__(
        self,
        spec: LadderSpec,
        *,
        project: str | None = None,
        deadline_s: float | None = None,
        sink: Sink | None = log_sink,
    ) -> None:
        """Args:
        spec: The ordered capacity strategy to run.
        project: Google Cloud project. Defaults to
            ``$GOOGLE_CLOUD_PROJECT``.
        deadline_s: Wall clock cap for a whole traversal. Strongly
            recommended for interactive traffic -- compare against
            ``spec.worst_case_s`` before you pick a number.
        sink: Called once per attempt. ``None`` disables telemetry.
        """
        self.spec = spec
        self.project = project or os.environ.get("GOOGLE_CLOUD_PROJECT")
        if not self.project:
            raise ValueError(
                "project is required (pass project= or set GOOGLE_CLOUD_PROJECT)"
            )
        self.deadline_s = deadline_s
        self.sink = sink
        self._clients: dict[str, genai.Client] = {}

    def _client(self, location: str) -> genai.Client:
        """One client per endpoint, created lazily.

        Everything that varies per step -- headers, timeout, retry policy --
        rides on the request instead, so a handful of clients covers any
        ladder. For multi-region locations the SDK derives the
        ``aiplatform.{loc}.rep.googleapis.com`` base URL itself.
        """
        if location not in self._clients:
            self._clients[location] = genai.Client(
                vertexai=True, project=self.project, location=location
            )
        return self._clients[location]

    @staticmethod
    def _http_options(step: Step, timeout_s: float) -> types.HttpOptions:
        return types.HttpOptions(
            headers=headers_for(step.tier),
            timeout=int(timeout_s * 1000),
            retry_options=types.HttpRetryOptions(
                initial_delay=step.initial_delay_s,
                attempts=step.attempts,
                exp_base=step.exp_base,
                max_delay=step.max_delay_s,
                jitter=step.jitter,
                http_status_codes=list(RETRYABLE_STATUS_CODES),
            ),
        )

    def _emit(self, record: AttemptRecord) -> AttemptRecord:
        if self.sink is not None:
            self.sink(record)
        return record

    def generate_content(
        self,
        contents: Any,
        *,
        config: types.GenerateContentConfig | None = None,
        deadline_s: float | None = None,
    ) -> LadderResult:
        """Generate content, descending the ladder until something works.

        Args:
            contents: Prompt, in any form the Gen AI SDK accepts.
            config: Generation config. Any ``http_options`` on it is
                overwritten per step -- that is the ladder's job.
            deadline_s: Overrides the instance deadline for this call.

        Returns:
            A :class:`~play_smart.telemetry.LadderResult` carrying the
            response and the full attempt trail, including the steps that
            failed. The trail is the point: it is the evidence for which
            capacity source is actually carrying your traffic.

        Raises:
            LadderAborted: An error no step can fix (bad request, safety
                block, auth failure).
            LadderExhausted: Every step was tried or skipped.
        """
        budget = Budget(deadline_s if deadline_s is not None else self.deadline_s)
        attempts: list[AttemptRecord] = []

        for step in self.spec.resolved_steps:
            if not budget.allows(step.worst_case_s):
                attempts.append(
                    self._emit(
                        AttemptRecord(
                            step=step.name,
                            tier_requested=step.tier.value,
                            model=step.model or "",
                            location=step.location,
                            max_attempts=step.attempts,
                            error_reason="skipped: deadline budget exhausted",
                        )
                    )
                )
                continue

            record = AttemptRecord(
                step=step.name,
                tier_requested=step.tier.value,
                model=step.model or "",
                location=step.location,
                max_attempts=step.attempts,
            )
            timeout_s = budget.clamp(step.timeout_s)
            call_config = _with_http_options(config, self._http_options(step, timeout_s))
            watch = Stopwatch()

            try:
                response = self._client(step.location).models.generate_content(
                    model=step.model,
                    contents=contents,
                    config=call_config,
                )
            except Exception as exc:
                record.latency_ms = watch.ms
                record.status = status_of(exc)
                disposition, reason = classify(exc)
                record.error_reason = reason
                record.error_detail = str(exc)[:500]
                attempts.append(self._emit(record))
                if disposition is Disposition.ABORT:
                    raise LadderAborted(attempts, reason) from exc
                continue

            record.latency_ms = watch.ms
            record.ok = True
            record.status = 200
            for key, value in read_usage(response).items():
                setattr(record, key, value)
            attempts.append(self._emit(record))
            return LadderResult(response=response, attempts=attempts)

        raise LadderExhausted(attempts)


def _with_http_options(
    config: types.GenerateContentConfig | None,
    http_options: types.HttpOptions,
) -> types.GenerateContentConfig:
    """Clone ``config`` with the step's transport settings applied.

    Timeout and retry policy belong to the step and are replaced outright --
    they *are* the step. Headers are merged instead, because a caller's
    headers are usually nothing to do with capacity: a proxy token, a tracing
    id, a tenant tag. Dropping those silently is a nasty surprise to debug.
    The two tier headers win any collision, since without them the step is
    not the step.
    """
    if config is None:
        return types.GenerateContentConfig(http_options=http_options)
    updated = config.model_copy(deep=True)
    caller = updated.http_options
    if caller is not None and caller.headers:
        http_options = http_options.model_copy(
            update={"headers": {**caller.headers, **(http_options.headers or {})}}
        )
    updated.http_options = http_options
    return updated
