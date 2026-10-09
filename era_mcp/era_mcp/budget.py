"""The investigation budget (brief §2): max 3 iterations x 3 tool calls,
10 documents, 20k context tokens, plus a wall-clock budget with a reserve for
the final synthesis call. Pure; no I/O."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from era_mcp import config


def estimate_tokens(text: str | None) -> int:
    """Tokenizer-free estimate (~3.6 chars/token for mixed English + markup)."""
    if not text:
        return 0
    return int(len(text) / 3.6) + 1


@dataclass
class Budget:
    max_iterations: int = 3
    max_tool_calls_per_iteration: int = 3
    max_documents: int = 10
    max_context_tokens: int = 20000
    time_budget_s: float = 120.0
    synth_reserve_s: float = 35.0
    est_judge_s: float = 15.0
    started: float = field(default_factory=time.monotonic)
    iterations_used: int = 0
    tool_calls_used: int = 0
    stop_reason: str | None = None

    @classmethod
    def from_config(cls) -> "Budget":
        return cls(
            max_iterations=max(1, config.agent_max_iters()),
            max_tool_calls_per_iteration=max(1, config.agent_max_tool_calls_per_iteration()),
            max_documents=max(1, config.agent_max_documents()),
            max_context_tokens=effective_context_cap(),
            time_budget_s=config.agent_time_budget(),
            synth_reserve_s=config.agent_synth_reserve_s(),
            est_judge_s=config.agent_est_judge_s(),
        )

    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def remaining_time(self) -> float:
        return max(0.0, self.time_budget_s - self.elapsed())

    def can_iterate(self) -> bool:
        """Another Judge round fits only if the judge call AND the synthesis
        reserve still fit inside the wall-clock budget."""
        if self.iterations_used >= self.max_iterations:
            self.stop_reason = self.stop_reason or "max_iterations"
            return False
        if self.elapsed() + self.est_judge_s + self.synth_reserve_s > self.time_budget_s:
            self.stop_reason = self.stop_reason or "time_budget"
            return False
        return True

    def synthesis_timeout(self) -> float:
        return max(15.0, self.remaining_time())

    def snapshot(self) -> dict[str, Any]:
        return {
            "iterations_used": self.iterations_used,
            "max_iterations": self.max_iterations,
            "tool_calls_used": self.tool_calls_used,
            "max_tool_calls": self.max_iterations * self.max_tool_calls_per_iteration,
            "max_documents": self.max_documents,
            "max_context_tokens": self.max_context_tokens,
            "elapsed_s": round(self.elapsed(), 1),
            "time_budget_s": self.time_budget_s,
            "stop_reason": self.stop_reason,
        }


def effective_context_cap() -> int:
    """The evidence context can never exceed what the model window leaves after
    the answer and the prompt scaffolding."""
    return int(min(config.agent_max_context_tokens(),
                   config.llm_num_ctx() - config.llm_max_tokens() - 1500))
