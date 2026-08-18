"""Fakes that let the ladder be tested without touching the network."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest


class FakeAPIError(Exception):
    """Stands in for a Gen AI SDK error, carrying an HTTP status."""

    def __init__(self, code: int, message: str = "") -> None:
        self.code = code
        super().__init__(message or f"{code} error")


@dataclass
class FakeUsage:
    traffic_type: str = "ON_DEMAND"
    prompt_token_count: int = 100
    candidates_token_count: int = 50
    cached_content_token_count: int = 0


@dataclass
class FakeResponse:
    text: str = "ok"
    usage_metadata: FakeUsage = field(default_factory=FakeUsage)


@dataclass
class Call:
    """One recorded generate_content call."""

    model: str
    location: str
    headers: dict[str, str]
    timeout_ms: int
    attempts: int


class FakeModels:
    def __init__(self, client: FakeClient) -> None:
        self._client = client

    def generate_content(self, *, model: str, contents: Any, config: Any) -> Any:
        http = config.http_options
        self._client.calls.append(
            Call(
                model=model,
                location=self._client.location,
                headers=dict(http.headers or {}),
                timeout_ms=http.timeout,
                attempts=http.retry_options.attempts,
            )
        )
        outcome = self._client.script.pop(0) if self._client.script else FakeResponse()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeClient:
    """A stand-in for ``genai.Client`` driven by a scripted outcome list."""

    def __init__(self, location: str, script: list[Any], calls: list[Call]) -> None:
        self.location = location
        self.script = script
        self.calls = calls
        self.models = FakeModels(self)


@pytest.fixture
def fake_transport(monkeypatch):
    """Patch ``CapacityLadder._client`` to return scripted fakes.

    Returns a factory: call it with the sequence of outcomes (responses or
    exceptions) the ladder should encounter, in order, across all steps.
    """
    from play_smart.ladder import CapacityLadder

    calls: list[Call] = []

    def install(*outcomes: Any) -> list[Call]:
        script = list(outcomes)

        def _client(self: CapacityLadder, location: str) -> FakeClient:
            return FakeClient(location, script, calls)

        monkeypatch.setattr(CapacityLadder, "_client", _client)
        return calls

    return install
