"""Tests that hit the real API. Opt in with ``pytest -m live``.

These exist because the support matrix in ``play_smart.tiers`` is empirical.
Model catalogues drift, tiers get enabled, endpoints gain coverage -- and when
that happens these tests should fail so the matrix gets updated rather than
quietly lying to everyone who depends on it.

Requires ADC and ``GOOGLE_CLOUD_PROJECT``.
"""

from __future__ import annotations

import os

import pytest

from play_smart import CapacityLadder, Tier, play_smart_default
from play_smart.tiers import headers_for

pytestmark = pytest.mark.live

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT")

pytest_plugins: list[str] = []


@pytest.fixture(scope="module")
def project() -> str:
    if not PROJECT:
        pytest.skip("GOOGLE_CLOUD_PROJECT is not set")
    return PROJECT


@pytest.fixture(scope="module")
def genai_module():
    return pytest.importorskip("google.genai")


def _call(genai, project: str, model: str, location: str, tier: Tier):
    from google.genai import types

    client = genai.Client(vertexai=True, project=project, location=location)
    return client.models.generate_content(
        model=model,
        contents="Reply with the single word: ok",
        config=types.GenerateContentConfig(
            http_options=types.HttpOptions(
                headers=headers_for(tier),
                # Five minutes, not the ladder's 60 seconds. Step 1 caps Flex
                # because a *bet* needs a bound; this test only asks whether
                # the tier was granted, and a Flex tail past 90 s failed the
                # suite with a ReadTimeout that was not a finding.
                timeout=300_000,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
            # Generous, deliberately. Gemini 3.x spends output budget on
            # thinking tokens first, so a tight cap can consume the entire
            # allowance and return finish_reason=MAX_TOKENS with empty text --
            # which looks exactly like an endpoint failure and is not one.
            max_output_tokens=512,
        ),
    )


class TestEndpointModelCoupling:
    """Multi-region carries a different catalogue than global.

    You cannot move an endpoint without checking the model came with you --
    which is why step 4 (alternate model) sits above steps 5-6 (alternate
    endpoint).

    The catalogue also moves. On 2026-07-28 ``gemini-3.6-flash`` 404'd on
    ``us`` and ``eu``; on 2026-08-12 it served from both. These tests pin
    what is true now, and are expected to need re-dating.
    """

    def test_alternative_model_is_served_from_multi_region(self, genai_module, project):
        response = _call(genai_module, project, "gemini-3.5-flash", "us", Tier.STANDARD)
        assert response.text

    def test_primary_model_is_now_served_from_multi_region(self, genai_module, project):
        """Was a 404 on 2026-07-28. Re-probe before trusting either answer."""
        response = _call(genai_module, project, "gemini-3.6-flash", "us", Tier.STANDARD)
        assert response.text

    def test_some_models_are_still_absent_from_multi_region(self, genai_module, project):
        """The catalogues differ; only *which* models differ has changed."""
        with pytest.raises(Exception, match=r"404|not found|does not have access"):
            _call(genai_module, project, "gemini-2.5-flash", "us", Tier.STANDARD)


class TestMatrixDrift:
    """The declared matrix is a cache. This is its expiry check.

    Everything else in this file pins one combination that mattered enough to
    write a test about. This runs the whole diff, so a model that quietly
    appears on an endpoint fails the suite even though nobody thought to
    assert it.
    """

    def test_the_declared_matrix_still_matches_the_live_platform(self, project, capsys):
        from demo.probe_matrix import check

        exit_code = check(project)
        # Surface the drift lines: pytest swallows stdout on a bare assert,
        # and "assert 1 == 0" is a useless failure message.
        assert exit_code == 0, capsys.readouterr().out


class TestTierGrants:
    def test_flex_is_actually_granted(self, genai_module, project):
        response = _call(genai_module, project, "gemini-3.6-flash", "global", Tier.FLEX)
        traffic = response.usage_metadata.traffic_type
        assert getattr(traffic, "name", str(traffic)) == "ON_DEMAND_FLEX"

    def test_flex_rejects_an_unsupported_model(self, genai_module, project):
        with pytest.raises(Exception, match="not supported"):
            _call(genai_module, project, "gemini-2.5-flash", "global", Tier.FLEX)

    @pytest.mark.xfail(
        reason=(
            "Observed on 2026-07-29: a documented Priority request on a "
            "supported model returns 200 with traffic_type ON_DEMAND, not "
            "ON_DEMAND_PRIORITY. Both documented header spellings behave the "
            "same, and the identical code path returns ON_DEMAND_FLEX for "
            "Flex, so this is not a transport bug. The cause is not "
            "determinable from a client -- entitlement, capacity fallback and "
            "a labelling gap all look like this. An xpass means Priority is "
            "now reporting correctly, and the docs should be re-read."
        ),
        strict=False,
    )
    def test_priority_is_actually_granted(self, genai_module, project):
        response = _call(
            genai_module, project, "gemini-3.6-flash", "global", Tier.PRIORITY
        )
        traffic = response.usage_metadata.traffic_type
        assert getattr(traffic, "name", str(traffic)) == "ON_DEMAND_PRIORITY"


class TestLadderTraversal:
    def test_ladder_recovers_from_a_real_429(self, project):
        """``dedicated`` with no Provisioned Throughput order is a free, real 429."""
        from play_smart import LadderSpec, Step

        spec = LadderSpec(
            name="live-failover",
            primary_model="gemini-3.6-flash",
            steps=(
                Step(name="dedicated", tier=Tier.DEDICATED, timeout_s=20, attempts=1),
                Step(name="standard", tier=Tier.STANDARD, timeout_s=60, attempts=2),
            ),
        )
        result = CapacityLadder(spec, project=project, sink=None).generate_content(
            "Reply with the single word: ok"
        )

        assert result.attempts[0].ok is False
        assert result.attempts[0].status == 429
        assert result.step_used == "standard"

    def test_default_ladder_returns_an_answer(self, project):
        result = CapacityLadder(
            play_smart_default(), project=project, deadline_s=180, sink=None
        ).generate_content("Reply with the single word: ok")
        assert result.text
        assert result.step_used
