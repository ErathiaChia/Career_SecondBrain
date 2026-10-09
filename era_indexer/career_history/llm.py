"""Local JSON-mode LLM calls for project-intelligence jobs (state rollups,
contradiction judging, impact notes, enrichment).

Uses the same Ollama endpoint as graph extraction. The model is
``models.reasoning_model`` (falls back to ``graph_extraction_model``); use a
non-thinking model because reasoning models return empty output under forced JSON.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from career_history import config


class LLMError(RuntimeError):
    """Raised when the model is unreachable or returns unparseable output."""


def _model() -> str:
    models = config.get().get("models", {})
    return (
        os.environ.get("ERA_REASONING_MODEL")
        or models.get("reasoning_model")
        or models.get("graph_extraction_model")
        or "llama3.1"
    )


def _base_url() -> str:
    return (
        os.environ.get("OLLAMA_BASE_URL")
        or config.v2().get("graph_ollama_base_url")
        or "http://localhost:11434"
    ).rstrip("/")


def _timeout() -> int:
    raw = os.environ.get("ERA_REASONING_TIMEOUT") or config.get().get("models", {}).get("reasoning_timeout")
    try:
        return int(raw) if raw else 600
    except (TypeError, ValueError):
        return 600


def generate_json(prompt: str, *, model: str | None = None, timeout: int | None = None) -> dict[str, Any]:
    """Run one JSON-mode generation and return the parsed object."""
    from career_history.graph import _loads_json_object, ollama_json_options

    payload = {
        "model": model or _model(),
        "prompt": prompt,
        "stream": False,
        "format": "json",
        **ollama_json_options(),
    }
    req = urllib.request.Request(
        f"{_base_url()}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout or _timeout()) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise LLMError(f"Ollama request failed: {e}") from e
    try:
        return _loads_json_object(body.get("response") or "{}")
    except ValueError as e:
        raise LLMError(f"Unparseable LLM output: {e}") from e
