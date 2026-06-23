"""LLM provider abstraction: Mac (Ollama / OpenAI-compatible MLX) primary,
OpenAI fallback.

era_mcp runs on the always-on NAS; the heavy LLM runs on the M1 Max, which may be
asleep or off. A short connect timeout makes an unreachable Mac fail fast so we
fall back to OpenAI (when a key is set) or, ultimately, raise ``LLMUnavailable``
for callers to degrade on. Everything is plain ``httpx`` — no extra deps.
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from era_mcp import config


class LLMUnavailable(Exception):
    """Raised only when every configured provider fails or is unset."""


def provider_status() -> dict[str, Any]:
    """Echoed in responses so the caller can see which providers are wired."""
    return {
        "primary": f"{config.llm_primary_kind()}@{config.llm_primary_base_url()}",
        "primary_model": config.llm_primary_model(),
        "fallback": (
            f"openai:{config.openai_model()}"
            if config.llm_fallback_enabled() and config.openai_api_key()
            else "disabled"
        ),
    }


def _timeout(read: float | None) -> httpx.Timeout:
    # Short connect timeout: an asleep/off Mac fails in ~3s instead of hanging.
    return httpx.Timeout(connect=3.0, read=read or config.llm_primary_timeout(),
                         write=10.0, pool=3.0)


async def _chat_ollama(base_url: str, model: str, messages: list[dict[str, str]],
                       temperature: float, max_tokens: int, read_timeout: float,
                       json_mode: bool) -> str:
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature, "num_predict": max_tokens},
    }
    if json_mode:
        payload["format"] = "json"
    async with httpx.AsyncClient(timeout=_timeout(read_timeout)) as client:
        resp = await client.post(f"{base_url}/api/chat", json=payload)
        resp.raise_for_status()
        data = resp.json()
    return (data.get("message", {}) or {}).get("content", "") or ""


async def _chat_openai_compat(base_url: str, model: str, api_key: str,
                              messages: list[dict[str, str]], temperature: float,
                              max_tokens: int, read_timeout: float,
                              json_mode: bool) -> str:
    # base_url already ends in /v1 for OpenAI; MLX/llama.cpp servers also expose
    # /v1/chat/completions.
    url = f"{base_url}/chat/completions" if base_url.endswith("/v1") else f"{base_url}/v1/chat/completions"
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    async with httpx.AsyncClient(timeout=_timeout(read_timeout)) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    return data["choices"][0]["message"]["content"] or ""


_TRANSIENT = (httpx.HTTPError, httpx.TimeoutException, KeyError, ValueError, OSError)


async def chat(
    messages: list[dict[str, str]],
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    timeout: float | None = None,
    json_mode: bool = False,
) -> str:
    """Return the assistant text. Try the Mac primary, then OpenAI fallback.

    Raises ``LLMUnavailable`` only if every configured provider fails.
    """
    temp = config.llm_temperature() if temperature is None else temperature
    max_tok = config.llm_max_tokens() if max_tokens is None else max_tokens
    errors: list[str] = []

    # 1) Primary (Mac).
    try:
        if config.llm_primary_kind() == "openai_compat":
            return await _chat_openai_compat(
                config.llm_primary_base_url(), config.llm_primary_model(), "",
                messages, temp, max_tok, timeout, json_mode)
        return await _chat_ollama(
            config.llm_primary_base_url(), config.llm_primary_model(),
            messages, temp, max_tok, timeout, json_mode)
    except _TRANSIENT as e:
        errors.append(f"primary({type(e).__name__})")

    # 2) Fallback (OpenAI), only if enabled and a key is set.
    if config.llm_fallback_enabled() and config.openai_api_key():
        try:
            return await _chat_openai_compat(
                config.openai_base_url(), config.openai_model(),
                config.openai_api_key(), messages, temp, max_tok, timeout, json_mode)
        except _TRANSIENT as e:
            errors.append(f"fallback({type(e).__name__})")

    raise LLMUnavailable("; ".join(errors) or "no providers configured")


def _extract_json(raw: str) -> Any:
    """Best-effort JSON parse: strip ``` fences, else grab the first {...}/[...]."""
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1] if s.count("```") >= 2 else s.strip("`")
        if s.lstrip().startswith("json"):
            s = s.lstrip()[4:]
    try:
        return json.loads(s)
    except ValueError:
        pass
    for open_c, close_c in (("{", "}"), ("[", "]")):
        start, end = s.find(open_c), s.rfind(close_c)
        if start != -1 and end > start:
            try:
                return json.loads(s[start:end + 1])
            except ValueError:
                continue
    raise ValueError("no JSON object found in LLM response")


async def chat_json(
    messages: list[dict[str, str]],
    *,
    timeout: float | None = None,
) -> Any:
    """``chat`` with JSON mode + robust extraction. Raises on unparseable output
    or ``LLMUnavailable`` when no provider answers."""
    raw = await chat(messages, timeout=timeout, json_mode=True)
    return _extract_json(raw)
