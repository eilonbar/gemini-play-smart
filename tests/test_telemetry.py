"""Telemetry, error classification, and budget accounting."""

from __future__ import annotations

import json

import pytest

from play_smart import (
    AttemptRecord,
    Budget,
    CapacityLadder,
    Disposition,
    classify,
    play_smart_default,
)
from tests.conftest import FakeAPIError, FakeResponse, FakeUsage


class TestSilentDowngradeDetection:
    """The finding this whole library exists to make visible.

    The Priority header has been observed returning 200 with a ``traffic_type``
    of ``ON_DEMAND``. Nothing in the response says so except ``traffic_type``,
    and no client can tell from there whether the tier was refused or simply
    not labelled -- so the least this library can do is surface the mismatch.
    """

    def test_priority_served_as_standard_is_flagged(self):
        record = AttemptRecord(
            step="priority",
            tier_requested="priority",
            model="gemini-3.6-flash",
            location="global",
            ok=True,
            tier_granted="ON_DEMAND",
        )
        assert record.downgraded is True

    def test_priority_served_as_priority_is_not_flagged(self):
        record = AttemptRecord(
            step="priority",
            tier_requested="priority",
            model="gemini-3.6-flash",
            location="global",
            ok=True,
            tier_granted="ON_DEMAND_PRIORITY",
        )
        assert record.downgraded is False

    def test_flex_served_as_flex_is_not_flagged(self):
        record = AttemptRecord(
            step="flex",
            tier_requested="flex",
            model="gemini-3.6-flash",
            location="global",
            ok=True,
            tier_granted="ON_DEMAND_FLEX",
        )
        assert record.downgraded is False

    def test_pt_spilling_to_on_demand_is_expected_not_a_downgrade(self):
        """PT_THEN_PAYGO is *defined* as spilling. That is not a surprise."""
        record = AttemptRecord(
            step="provisioned",
            tier_requested="pt_then_paygo",
            model="gemini-3.6-flash",
            location="global",
            ok=True,
            tier_granted="ON_DEMAND",
        )
        assert record.downgraded is False

    def test_a_failed_attempt_is_never_a_downgrade(self):
        record = AttemptRecord(
            step="priority",
            tier_requested="priority",
            model="m",
            location="global",
            ok=False,
        )
        assert record.downgraded is False

    def test_downgrade_appears_in_the_serialised_record(self):
        record = AttemptRecord(
            step="priority",
            tier_requested="priority",
            model="m",
            location="global",
            ok=True,
            tier_granted="ON_DEMAND",
        )
        assert json.loads(record.to_json())["downgraded"] is True


class TestUsageExtraction:
    def test_traffic_type_and_tokens_land_on_the_record(self, fake_transport):
        fake_transport(
            FakeResponse(
                usage_metadata=FakeUsage(
                    traffic_type="ON_DEMAND_FLEX",
                    prompt_token_count=1000,
                    candidates_token_count=200,
                    cached_content_token_count=800,
                )
            )
        )
        ladder = CapacityLadder(play_smart_default(), project="p", sink=None)
        attempt = ladder.generate_content("hi").attempts[0]

        assert attempt.tier_granted == "ON_DEMAND_FLEX"
        assert attempt.prompt_tokens == 1000
        assert attempt.cached_tokens == 800

    def test_a_response_without_usage_metadata_does_not_break_the_call(
        self, fake_transport
    ):
        """Telemetry must never fail a request the ladder already won."""

        class Bare:
            text = "ok"

        fake_transport(Bare())
        ladder = CapacityLadder(play_smart_default(), project="p", sink=None)
        result = ladder.generate_content("hi")
        assert result.text == "ok"
        assert result.attempts[0].tier_granted is None


class TestSink:
    def test_every_attempt_reaches_the_sink(self, fake_transport):
        fake_transport(FakeAPIError(429), FakeResponse())
        seen: list[AttemptRecord] = []
        CapacityLadder(
            play_smart_default(), project="p", sink=seen.append
        ).generate_content("hi")

        assert [r.step for r in seen] == ["flex", "standard"]
        assert [r.ok for r in seen] == [False, True]


class TestResultSummary:
    def test_table_renders_every_attempt(self, fake_transport):
        fake_transport(FakeAPIError(429), FakeResponse())
        result = CapacityLadder(
            play_smart_default(), project="p", sink=None
        ).generate_content("hi")
        table = result.table()

        assert "flex" in table
        assert "FAIL" in table
        assert "OK" in table

    def test_total_latency_sums_all_attempts(self, fake_transport):
        fake_transport(FakeAPIError(429), FakeResponse())
        result = CapacityLadder(
            play_smart_default(), project="p", sink=None
        ).generate_content("hi")
        assert result.total_latency_ms == pytest.approx(
            sum(a.latency_ms for a in result.attempts)
        )


class TestClassification:
    @pytest.mark.parametrize(
        ("error", "disposition"),
        [
            (FakeAPIError(429), Disposition.ADVANCE),
            (FakeAPIError(408), Disposition.ADVANCE),
            (FakeAPIError(500), Disposition.ADVANCE),
            (FakeAPIError(503), Disposition.ADVANCE),
            (FakeAPIError(404, "model not found"), Disposition.ADVANCE),
            (TimeoutError("read timed out"), Disposition.ADVANCE),
            (FakeAPIError(400, "bad payload"), Disposition.ABORT),
            (FakeAPIError(401, "unauthorized"), Disposition.ABORT),
            (FakeAPIError(403, "permission denied"), Disposition.ABORT),
        ],
    )
    def test_disposition(self, error, disposition):
        assert classify(error)[0] is disposition

    def test_unknown_errors_advance_rather_than_abort(self):
        """Bias: wasting a step is cheaper than dropping a request."""
        assert classify(ConnectionResetError("connection reset"))[0] is (
            Disposition.ADVANCE
        )

    def test_flex_unsupported_model_advances(self):
        error = FakeAPIError(400, "Flex API is not supported for model: x")
        assert classify(error)[0] is Disposition.ADVANCE

    def test_safety_blocks_abort_even_on_a_2xx_shaped_error(self):
        assert classify(Exception("Response blocked for safety"))[0] is (
            Disposition.ABORT
        )


class TestBudget:
    def test_unbounded_budget_allows_everything(self):
        budget = Budget(None)
        assert budget.remaining_s == float("inf")
        assert budget.allows(10_000)
        assert budget.clamp(99.0) == 99.0

    def test_clamp_shrinks_a_timeout_to_what_is_left(self):
        assert Budget(10).clamp(60.0) <= 10.0

    def test_an_impossible_step_is_not_allowed(self):
        assert Budget(0.001).allows(60.0, min_useful_s=1.0) is False

    def test_a_step_is_allowed_when_a_partial_attempt_is_still_useful(self):
        assert Budget(5).allows(60.0, min_useful_s=1.0) is True

    def test_a_non_positive_deadline_is_rejected(self):
        with pytest.raises(ValueError, match="must be positive"):
            Budget(0)
