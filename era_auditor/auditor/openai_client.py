from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from .config import AppConfig, is_private_url


T = TypeVar("T", bound=BaseModel)


class OpenAIClient:
    """OpenAI-compatible chat client. Local Ollama by default; a cloud endpoint
    only when ``openai.cloud_optin`` is set (organisation policy)."""

    def __init__(self, config: AppConfig):
        self.config = config
        base_url = config.openai.base_url.rstrip("/")
        api_key = os.getenv(config.openai.api_key_env) or ""
        if config.openai.cloud_optin:
            if not api_key:
                raise RuntimeError(
                    f"Cloud LLM opted in but no API key: set {config.openai.api_key_env}."
                )
        else:
            if not is_private_url(base_url):
                raise RuntimeError(
                    f"openai.base_url {base_url!r} is not a local/private host and "
                    "AUDITOR_CLOUD_OPTIN is off. Vault content must stay local."
                )
            api_key = api_key or "ollama"  # local servers ignore the key
        self.client = OpenAI(api_key=api_key, base_url=base_url)

    def load_prompt(self, name: str) -> str:
        path = self.config.base_dir / "auditor" / "prompts" / name
        return path.read_text(encoding="utf-8")

    def json_completion(
        self,
        system_prompt: str,
        payload: dict[str, Any],
        response_model: type[T],
    ) -> T:
        last_error: Exception | None = None
        for attempt in range(1, self.config.openai.max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.config.openai.model,
                    temperature=self.config.openai.temperature,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
                    ],
                )
                content = response.choices[0].message.content or "{}"
                parsed = json.loads(content)
                return response_model.model_validate(parsed)
            except (json.JSONDecodeError, ValidationError, Exception) as exc:
                last_error = exc
                if attempt == self.config.openai.max_retries:
                    break
                time.sleep(min(2**attempt, 8))

        raise RuntimeError(f"OpenAI request failed after retries: {last_error}") from last_error


class FindingsResponse(BaseModel):
    findings: list[Any]
