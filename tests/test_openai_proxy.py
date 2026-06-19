"""OpenAI-compatible proxy / backend_url behavior."""

import pytest

from tradingagents.llm_clients.openai_client import _should_use_responses_api


@pytest.mark.unit
def test_responses_api_disabled_for_local_proxy():
    assert _should_use_responses_api("openai", "http://localhost:1135/v1", None) is False
    assert _should_use_responses_api("openai", "http://127.0.0.1:11434/v1", None) is False


@pytest.mark.unit
def test_responses_api_enabled_for_native_openai():
    assert _should_use_responses_api("openai", "https://api.openai.com/v1", None) is True
    assert _should_use_responses_api("openai", None, None) is True


@pytest.mark.unit
def test_responses_api_config_override():
    assert _should_use_responses_api("openai", "http://localhost:1135/v1", True) is True
    assert _should_use_responses_api("openai", "https://api.openai.com/v1", False) is False
