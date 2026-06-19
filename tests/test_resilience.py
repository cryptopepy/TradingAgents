"""Resilience / retry helpers."""

import pytest

from tradingagents.resilience import DEFAULT_API_RETRY_DELAYS, retry_with_backoff, retry_with_backoff_optional


@pytest.mark.unit
def test_retry_with_backoff_succeeds_on_second_attempt(monkeypatch):
    calls = {"n": 0}
    sleeps: list[float] = []
    monkeypatch.setattr("tradingagents.resilience.time.sleep", sleeps.append)

    def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("api down")
        return "ok"

    result = retry_with_backoff(flaky, delays=(0.0, 0.0), label="test")
    assert result == "ok"
    assert calls["n"] == 2
    assert sleeps == [0.0]


@pytest.mark.unit
def test_retry_with_backoff_optional_returns_none(monkeypatch):
    monkeypatch.setattr("tradingagents.resilience.time.sleep", lambda _s: None)

    def always_fail():
        raise RuntimeError("api down")

    result = retry_with_backoff_optional(always_fail, delays=(0.0,), label="test")
    assert result is None


@pytest.mark.unit
def test_default_delays_match_paper_spec():
    assert DEFAULT_API_RETRY_DELAYS == (10.0, 30.0, 180.0)
