from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from .config import AppConfig


T = TypeVar("T", bound=BaseModel)


class OpenAIClient:
    def __init__(self, config: AppConfig):
        self.config = config
        api_key = os.getenv(config.openai.api_key_env)
        if not api_key:
            raise RuntimeError(
                f"Missing OpenAI API key. Set {config.openai.api_key_env} in .env or the environment."
            )
        self.client = OpenAI(api_key=api_key)

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
