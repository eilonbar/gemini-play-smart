"""Deciding what a failure means.

A retry loop has one job that matters: telling apart "try that again" from
"try something else" from "stop". Conflating the three is how you get both
cascading retry storms and 30-second waits on an error that will never clear.

Reference:
  https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/retry-strategy
"""

from __future__ import annotations

import re
from enum import Enum


class Disposition(str, Enum):
    """What the ladder should do about a failed attempt."""

    #: Transient and lane-specific. The SDK's own backoff already handled this
    #: within the step; seeing it here means the step is exhausted.
    ADVANCE = "advance"

    #: The request itself is wrong. No step will fix it.
    ABORT = "abort"


#: Status codes the retry-strategy doc classifies as transient.
#: These are handed to the SDK's ``HttpRetryOptions`` for backoff within a step.
RETRYABLE_STATUS_CODES: tuple[int, ...] = (408, 429, 500, 502, 503, 504)

#: Permanent for *this step*, but potentially fine on the next one, because a
#: step changes model, endpoint, or capacity lane. A 404 means "this model is
#: not on this endpoint": retrying is pointless, advancing is not.
#:
#: Deliberately narrow. A generic 400 belongs in ABORT -- the request itself is
#: malformed and no step will fix it. The tier-specific 400s ("Flex API is not
#: supported for model") are caught earlier by ``_UNSUPPORTED_PATTERNS``.
_STEP_SCOPED_STATUS_CODES: frozenset[int] = frozenset({404})

_UNSUPPORTED_PATTERNS = (
    re.compile(r"not supported for model", re.I),
    re.compile(r"was not found or your project does not have access", re.I),
    re.compile(r"is not (?:allowed|supported|available)", re.I),
)

_SAFETY_PATTERNS = (
    re.compile(r"blocked", re.I),
    re.compile(r"safety", re.I),
    re.compile(r"prohibited_content", re.I),
    re.compile(r"recitation", re.I),
)

_AUTH_STATUS_CODES = frozenset({401, 403})


def status_of(exc: BaseException) -> int | None:
    """Best-effort HTTP status extraction from a Gen AI SDK exception."""
    for attr in ("code", "status_code", "http_status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int) and 100 <= value < 600:
            return value
    match = re.search(r"\b([45]\d\d)\b", str(exc))
    return int(match.group(1)) if match else None


def is_timeout(exc: BaseException) -> bool:
    """True when the failure is a client-side or socket timeout."""
    if isinstance(exc, TimeoutError):
        return True
    return bool(re.search(r"timed?\s*out|deadline exceeded", str(exc), re.I))


def classify(exc: BaseException) -> tuple[Disposition, str]:
    """Map an exception to a ladder action and a short human reason.

    The bias is deliberate: anything ambiguous *advances* rather than aborts.
    A ladder that advances too eagerly wastes a little money; a ladder that
    aborts too eagerly drops a customer request on the floor.
    """
    message = str(exc)
    status = status_of(exc)

    if any(pattern.search(message) for pattern in _SAFETY_PATTERNS):
        return Disposition.ABORT, "content blocked by safety filters"

    if status in _AUTH_STATUS_CODES:
        return Disposition.ABORT, f"authorization failure ({status})"

    if any(pattern.search(message) for pattern in _UNSUPPORTED_PATTERNS):
        return Disposition.ADVANCE, "model unavailable on this tier or endpoint"

    if is_timeout(exc):
        return Disposition.ADVANCE, "timed out"

    if status in RETRYABLE_STATUS_CODES:
        label = "capacity exhausted (429)" if status == 429 else f"transient {status}"
        return Disposition.ADVANCE, label

    if status in _STEP_SCOPED_STATUS_CODES:
        return Disposition.ADVANCE, f"rejected by this step ({status})"

    if status is not None and 400 <= status < 500:
        return Disposition.ABORT, f"malformed request ({status})"

    # Unknown, e.g. a bare connection reset. Another endpoint may well work.
    return Disposition.ADVANCE, "unclassified error"


class LadderExhausted(RuntimeError):
    """Every step was tried and none produced a response."""

    def __init__(self, attempts: list, message: str | None = None) -> None:
        self.attempts = attempts
        detail = " -> ".join(f"{a.step}:{a.error_reason or 'ok'}" for a in attempts)
        super().__init__(message or f"all {len(attempts)} steps failed: {detail}")


class LadderAborted(RuntimeError):
    """A step hit an error no other step can fix."""

    def __init__(self, attempts: list, reason: str) -> None:
        self.attempts = attempts
        self.reason = reason
        super().__init__(f"aborted after {len(attempts)} attempt(s): {reason}")
