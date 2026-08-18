"""Configuration validation: impossible ladders must fail loudly, at build time.

Every assertion here corresponds to a combination the API rejects at runtime.
Catching them in a constructor is the difference between a failing import in
CI and a pager at 3am.
"""

from __future__ import annotations

import itertools

import pytest

from play_smart import InvalidStep, LadderSpec, Step, Tier, tier_supports
from play_smart.presets import play_smart_default


class TestImpossibleCombinations:
    def test_flex_is_rejected_on_multi_region(self):
        """Flex exists on the global endpoint only."""
        with pytest.raises(InvalidStep, match="global endpoint only"):
            LadderSpec(
                name="bad",
                primary_model="gemini-3.5-flash",
                steps=(Step(name="x", tier=Tier.FLEX, location="us"),),
            )

    def test_priority_is_rejected_on_a_regional_endpoint(self):
        with pytest.raises(InvalidStep, match="global endpoint only"):
            LadderSpec(
                name="bad",
                primary_model="gemini-3.5-flash",
                steps=(Step(name="x", tier=Tier.PRIORITY, location="us-central1"),),
            )

    def test_flex_is_rejected_for_an_unsupported_model(self):
        """Measured live: gemini-2.5-flash returns 'Flex API is not supported'."""
        with pytest.raises(InvalidStep, match="Flex PayGo does not support"):
            LadderSpec(
                name="bad",
                primary_model="gemini-2.5-flash",
                steps=(Step(name="x", tier=Tier.FLEX),),
            )

    def test_multi_region_is_rejected_for_a_global_only_model(self):
        """Measured live: gemini-2.5-flash 404s on the us endpoint."""
        with pytest.raises(InvalidStep, match="multi-region endpoint"):
            LadderSpec(
                name="bad",
                primary_model="gemini-2.5-flash",
                steps=(Step(name="x", tier=Tier.STANDARD, location="us"),),
            )

    def test_duplicate_step_names_are_rejected(self):
        """Names are telemetry keys; ambiguous ones make logs unreadable."""
        with pytest.raises(InvalidStep, match="duplicate step name"):
            LadderSpec(
                name="bad",
                primary_model="gemini-3.5-flash",
                steps=(
                    Step(name="x", tier=Tier.STANDARD),
                    Step(name="x", tier=Tier.PRIORITY),
                ),
            )

    def test_empty_ladder_is_rejected(self):
        with pytest.raises(InvalidStep, match="no steps"):
            LadderSpec(name="bad", primary_model="gemini-3.5-flash", steps=())


class TestTierSupport:
    @pytest.mark.parametrize(
        ("tier", "model", "location", "expected"),
        [
            (Tier.FLEX, "gemini-3.6-flash", "global", True),
            (Tier.FLEX, "gemini-2.5-flash", "global", False),
            (Tier.FLEX, "gemini-3.6-flash", "us", False),
            (Tier.PRIORITY, "gemini-2.5-flash", "global", True),
            (Tier.PRIORITY, "gemini-2.5-flash", "eu", False),
            (Tier.STANDARD, "gemini-3.5-flash", "us", True),
            # Re-probed 2026-08-12: this was False on 2026-07-28.
            (Tier.STANDARD, "gemini-3.6-flash", "us", True),
            (Tier.STANDARD, "gemini-2.5-flash", "us", False),
            (Tier.STANDARD, "gemini-3.6-flash", "global", True),
            (Tier.DEDICATED, "gemini-3.6-flash", "global", True),
        ],
    )
    def test_matrix(self, tier, model, location, expected):
        ok, reason = tier_supports(tier, model, location)
        assert ok is expected
        assert bool(reason) is not expected


class TestModelInheritance:
    def test_step_without_a_model_inherits_the_primary(self):
        spec = LadderSpec(
            name="t",
            primary_model="gemini-3.5-flash",
            steps=(Step(name="a", tier=Tier.STANDARD),),
        )
        assert spec.resolved_steps[0].model == "gemini-3.5-flash"

    def test_an_explicit_step_model_overrides_the_primary(self):
        spec = LadderSpec(
            name="t",
            primary_model="gemini-3.6-flash",
            steps=(Step(name="a", tier=Tier.STANDARD, model="gemini-2.5-flash"),),
        )
        assert spec.resolved_steps[0].model == "gemini-2.5-flash"


class TestWorstCase:
    def test_worst_case_includes_backoff_not_just_timeouts(self):
        step = Step(
            name="a",
            tier=Tier.STANDARD,
            timeout_s=10.0,
            attempts=3,
            initial_delay_s=1.0,
            exp_base=2.0,
        )
        # 3 attempts x 10s, plus backoff of 1s + 2s.
        assert step.worst_case_s == pytest.approx(33.0)

    def test_a_single_attempt_step_has_no_backoff(self):
        step = Step(name="a", tier=Tier.STANDARD, timeout_s=10.0, attempts=1)
        assert step.worst_case_s == pytest.approx(10.0)

    def test_ladder_worst_case_is_the_sum_of_its_steps(self):
        spec = play_smart_default()
        assert spec.worst_case_s == pytest.approx(
            sum(r.worst_case_s for r in spec.resolved_steps)
        )


class TestPresets:
    @pytest.mark.parametrize(
        "factory_name",
        ["play_smart_default", "latency_first"],
    )
    def test_shipped_presets_are_valid(self, factory_name):
        """Every preset must survive its own validation."""
        from play_smart import presets

        spec = getattr(presets, factory_name)()
        assert spec.resolved_steps
        assert spec.describe()

    def test_default_ladder_is_the_requested_five_step_sequence(self):
        spec = play_smart_default()
        assert [r.name for r in spec.resolved_steps] == [
            "flex",
            "standard",
            "priority",
            "alternative_model",
            "multi_region_us",
            "multi_region_eu",
        ]

    def test_default_ladder_is_cost_ascending_at_the_top(self):
        tiers = [r.tier for r in play_smart_default().resolved_steps]
        assert tiers[:3] == [Tier.FLEX, Tier.STANDARD, Tier.PRIORITY]

    def test_alternative_model_step_carries_no_priority_tier(self):
        """Step 4 is a model swap. Nothing about it should say 'priority'."""
        step = next(
            r
            for r in play_smart_default().resolved_steps
            if r.name == "alternative_model"
        )
        assert step.tier is Tier.STANDARD

    def test_latency_first_is_the_premium_lane_across_three_models(self):
        """One lane, three models. No Standard floor, no multi-region step."""
        from play_smart.presets import latency_first

        steps = latency_first().resolved_steps
        assert [r.name for r in steps] == [
            "priority",
            "priority_alternative_model",
            "priority_third_model",
        ]
        assert {r.tier for r in steps} == {Tier.PRIORITY}
        assert len({r.model for r in steps}) == 3
        assert {r.location for r in steps} == {"global"}

    def test_latency_first_moves_one_variable_per_step(self):
        """Only the model ever changes -- never the lane, never the endpoint."""
        from play_smart.presets import latency_first

        steps = latency_first().resolved_steps
        for above, below in itertools.pairwise(steps):
            changed = sum(
                (
                    above.tier is not below.tier,
                    above.model != below.model,
                    above.location != below.location,
                )
            )
            assert changed == 1, f"{above.name} -> {below.name} changed {changed}"

    def test_latency_first_timeouts_never_grow(self):
        """A fail-fast ladder must not get more patient as it descends."""
        from play_smart.presets import latency_first

        timeouts = [r.timeout_s for r in latency_first().resolved_steps]
        assert timeouts == sorted(timeouts, reverse=True)

    def test_flex_bet_is_capped_at_sixty_seconds_by_default(self):
        step = play_smart_default().resolved_steps[0]
        assert step.timeout_s == 60.0
        assert step.attempts == 1

    def test_no_shipped_ladder_depends_on_reserved_capacity(self):
        """The whole point: this route works without a PT order."""
        from play_smart import presets

        for factory_name in ("play_smart_default", "latency_first"):
            spec = getattr(presets, factory_name)()
            tiers = {r.tier for r in spec.resolved_steps}
            assert Tier.DEDICATED not in tiers
            assert Tier.PT_THEN_PAYGO not in tiers
