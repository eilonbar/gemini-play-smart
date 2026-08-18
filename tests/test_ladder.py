"""Traversal behaviour: does the ladder go where it should, and stop when it should."""

from __future__ import annotations

import pytest
from google.genai import types

from play_smart import CapacityLadder, LadderAborted, LadderExhausted, play_smart_default
from play_smart.tiers import (
    REQUEST_TYPE_HEADER,
    SHARED_REQUEST_TYPE_HEADER,
)
from tests.conftest import FakeAPIError, FakeResponse

PROJECT = "test-project"


def make_ladder(**kwargs) -> CapacityLadder:
    return CapacityLadder(play_smart_default(), project=PROJECT, sink=None, **kwargs)


def test_first_step_wins_and_stops():
    """A healthy Flex step ends the traversal immediately."""
    ladder = make_ladder()
    ladder._client = lambda loc: _scripted(loc, [FakeResponse()])
    result = ladder.generate_content("hi")

    assert result.step_used == "flex"
    assert len(result.attempts) == 1
    assert result.text == "ok"


def test_429_advances_to_next_step(fake_transport):
    """Capacity exhaustion moves down the ladder rather than failing."""
    calls = fake_transport(FakeAPIError(429, "Too many requests"), FakeResponse())
    result = make_ladder().generate_content("hi")

    assert [a.step for a in result.attempts] == ["flex", "standard"]
    assert result.step_used == "standard"
    assert result.attempts[0].error_reason == "capacity exhausted (429)"
    assert len(calls) == 2


def test_full_traversal_to_multi_region(fake_transport):
    """Every step failing lands on the multi-region escape hatch."""
    fake_transport(
        FakeAPIError(429),
        FakeAPIError(429),
        FakeAPIError(503),
        FakeAPIError(429),
        FakeResponse(),
    )
    result = make_ladder().generate_content("hi")

    assert [a.step for a in result.attempts] == [
        "flex",
        "standard",
        "priority",
        "alternative_model",
        "multi_region_us",
    ]
    assert result.attempts[-1].location == "us"


def test_exhaustion_raises_with_full_trail(fake_transport):
    """When nothing works, the failure carries the evidence."""
    fake_transport(*[FakeAPIError(429) for _ in range(6)])
    with pytest.raises(LadderExhausted) as excinfo:
        make_ladder().generate_content("hi")

    assert len(excinfo.value.attempts) == 6
    assert "multi_region_eu" in str(excinfo.value)


@pytest.mark.parametrize(
    "error",
    [
        FakeAPIError(400, "Invalid JSON payload"),
        FakeAPIError(403, "Permission denied"),
        FakeAPIError(200, "Response blocked by safety filters"),
    ],
)
def test_unfixable_errors_abort_immediately(fake_transport, error):
    """No step can fix a bad request, so we do not burn five of them trying."""
    calls = fake_transport(error, FakeResponse())
    with pytest.raises(LadderAborted):
        make_ladder().generate_content("hi")
    assert len(calls) == 1


def test_model_unavailable_advances_without_retrying(fake_transport):
    """A 404 on one endpoint is a routing fact, not a transient error."""
    fake_transport(
        FakeAPIError(
            404,
            "Publisher model was not found or your project does not have access to it",
        ),
        FakeResponse(),
    )
    result = make_ladder().generate_content("hi")
    assert result.attempts[0].error_reason == (
        "model unavailable on this tier or endpoint"
    )
    assert result.step_used == "standard"


class TestHeaders:
    """The headers are the entire mechanism; they get their own tests."""

    def test_flex_step_sends_flex_headers(self, fake_transport):
        calls = fake_transport(FakeResponse())
        make_ladder().generate_content("hi")
        assert calls[0].headers == {
            REQUEST_TYPE_HEADER: "shared",
            SHARED_REQUEST_TYPE_HEADER: "flex",
        }

    def test_standard_step_omits_the_lane_header(self, fake_transport):
        calls = fake_transport(FakeAPIError(429), FakeResponse())
        make_ladder().generate_content("hi")
        assert calls[1].headers == {REQUEST_TYPE_HEADER: "shared"}

    def test_priority_step_sends_priority_headers(self, fake_transport):
        calls = fake_transport(FakeAPIError(429), FakeAPIError(429), FakeResponse())
        make_ladder().generate_content("hi")
        assert calls[2].headers == {
            REQUEST_TYPE_HEADER: "shared",
            SHARED_REQUEST_TYPE_HEADER: "priority",
        }

    def test_multi_region_step_sends_no_lane_header(self, fake_transport):
        """Priority and Flex do not exist off the global endpoint."""
        calls = fake_transport(*[FakeAPIError(429)] * 4, FakeResponse())
        make_ladder().generate_content("hi")
        assert SHARED_REQUEST_TYPE_HEADER not in calls[4].headers
        assert calls[4].location == "us"

    def test_callers_own_headers_survive_every_step(self, fake_transport):
        """A proxy token or tracing id has nothing to do with capacity."""
        calls = fake_transport(FakeAPIError(429), FakeResponse())
        make_ladder().generate_content(
            "hi",
            config=types.GenerateContentConfig(
                http_options=types.HttpOptions(headers={"X-Tenant": "acme"})
            ),
        )
        assert all(call.headers["X-Tenant"] == "acme" for call in calls)
        assert calls[0].headers[SHARED_REQUEST_TYPE_HEADER] == "flex"
        assert calls[1].headers[REQUEST_TYPE_HEADER] == "shared"

    def test_the_tier_headers_win_a_collision(self, fake_transport):
        """Without them the step is not the step."""
        calls = fake_transport(FakeResponse())
        make_ladder().generate_content(
            "hi",
            config=types.GenerateContentConfig(
                http_options=types.HttpOptions(headers={REQUEST_TYPE_HEADER: "dedicated"})
            ),
        )
        assert calls[0].headers[REQUEST_TYPE_HEADER] == "shared"


class TestStepIsolation:
    """Each step changes exactly one variable relative to the one above it."""

    def test_alternative_model_step_changes_only_the_model(self, fake_transport):
        calls = fake_transport(*[FakeAPIError(429)] * 3, FakeResponse())
        make_ladder().generate_content("hi")
        priority, alt = calls[2], calls[3]
        assert alt.model != priority.model
        assert alt.location == priority.location == "global"

    def test_multi_region_step_changes_only_the_endpoint(self, fake_transport):
        calls = fake_transport(*[FakeAPIError(429)] * 4, FakeResponse())
        make_ladder().generate_content("hi")
        alt, multi_region = calls[3], calls[4]
        assert multi_region.model == alt.model
        assert multi_region.location != alt.location


class TestTransportConfig:
    """Per-step timeout and retry policy reach the SDK intact."""

    def test_flex_timeout_is_capped_at_sixty_seconds(self, fake_transport):
        calls = fake_transport(FakeResponse())
        make_ladder().generate_content("hi")
        assert calls[0].timeout_ms == 60_000

    def test_flex_step_does_not_retry(self, fake_transport):
        """The doc is explicit: do not retry Flex aggressively."""
        calls = fake_transport(FakeResponse())
        make_ladder().generate_content("hi")
        assert calls[0].attempts == 1

    def test_standard_step_retries_in_place(self, fake_transport):
        calls = fake_transport(FakeAPIError(429), FakeResponse())
        make_ladder().generate_content("hi")
        assert calls[1].attempts == 3


class TestDeadlineBudget:
    """A ladder without a wall clock is a latency bomb."""

    def test_steps_that_cannot_finish_are_skipped_not_started(self, fake_transport):
        calls = fake_transport(FakeAPIError(429), FakeResponse())
        with pytest.raises(LadderExhausted) as excinfo:
            make_ladder(deadline_s=0.001).generate_content("hi")

        assert calls == []
        assert all("deadline" in a.error_reason for a in excinfo.value.attempts)

    def test_timeout_is_clamped_to_remaining_budget(self, fake_transport):
        calls = fake_transport(FakeResponse())
        make_ladder(deadline_s=10).generate_content("hi")
        assert calls[0].timeout_ms <= 10_000

    def test_per_call_deadline_overrides_the_instance_default(self, fake_transport):
        calls = fake_transport(FakeResponse())
        make_ladder(deadline_s=600).generate_content("hi", deadline_s=5)
        assert calls[0].timeout_ms <= 5_000


def _scripted(location: str, outcomes: list):
    from tests.conftest import FakeClient

    return FakeClient(location, list(outcomes), [])
