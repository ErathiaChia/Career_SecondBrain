"""Local-first policy: the OpenAI fallback is off unless explicitly opted in."""
from __future__ import annotations

import pytest

from era_mcp import config, llm


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("CLOUD_LLM_OPTIN", "LLM_FALLBACK_ENABLED", "OPENAI_API_KEY", "LLM_JUDGE_MODEL"):
        monkeypatch.delenv(var, raising=False)


def test_fallback_disabled_by_default(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-present-but-unused")
    assert config.cloud_llm_optin() is False
    assert config.llm_fallback_enabled() is False
    assert llm.provider_status()["fallback"] == "disabled (policy)"


def test_legacy_flag_alone_does_not_enable(monkeypatch):
    monkeypatch.setenv("LLM_FALLBACK_ENABLED", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    assert config.llm_fallback_enabled() is False
    assert llm.provider_status()["fallback"] == "disabled (policy)"


def test_optin_without_key_is_disabled(monkeypatch):
    monkeypatch.setenv("CLOUD_LLM_OPTIN", "1")
    monkeypatch.setenv("LLM_FALLBACK_ENABLED", "1")
    assert config.llm_fallback_enabled() is True
    assert llm.provider_status()["fallback"] == "disabled"


def test_explicit_optin_enables(monkeypatch):
    monkeypatch.setenv("CLOUD_LLM_OPTIN", "1")
    monkeypatch.setenv("LLM_FALLBACK_ENABLED", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    assert llm.provider_status()["fallback"].startswith("openai:")


def test_judge_model_defaults_to_primary(monkeypatch):
    monkeypatch.setenv("LLM_PRIMARY_MODEL", "qwen3.5:35b")
    assert config.llm_judge_model() == "qwen3.5:35b"
    monkeypatch.setenv("LLM_JUDGE_MODEL", "other:1b")
    assert config.llm_judge_model() == "other:1b"


def test_unavailable_detail_shape():
    d = llm.unavailable_detail(llm.LLMUnavailable("primary(ConnectError)"))
    assert d["error"] == "llm_unavailable"
    assert "primary(ConnectError)" in d["reason"]
    assert d["provider"]["fallback"] == "disabled (policy)"
