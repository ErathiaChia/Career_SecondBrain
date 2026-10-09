"""The Judge: one JSON call per investigation round that either answers or
names up to 3 tool calls from the registry catalog. The controller (agent.py)
enforces the budget; the Judge only proposes."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from era_mcp import config, llm

_PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
_LOADED: dict[str, bool] = {}

PHASES = ("discovery", "investigation", "verification")
_PHASE_GUIDE = {
    "discovery": "Find WHICH documents/projects/facts matter (search_knowledge, search_by_project, resolve_project).",
    "investigation": "Gather the evidence itself (read_section, find_evidence, get_project_facts, get_achievement).",
    "verification": "Only if needed: compare_documents, find_latest_version, find_conflicts, trace_decision. Then answer.",
}

FALLBACK_SYSTEM = (
    "You are the Career Intelligence Judge inside a bounded investigation loop over a personal work knowledge "
    "base. Each round, decide whether the CONTEXT already answers the QUESTION (action=answer) or name at most 3 "
    "tool calls from TOOLS that would add missing evidence (action=tools). Never repeat a call in TRAJECTORY. "
    "Never call a tool merely because it might reveal something. Return ONLY JSON: {thought, sufficient, "
    "confidence, missing, action, tool_calls:[{tool, args, why}]}."
)


def load_prompt(name: str = "judge_agent.md") -> str:
    try:
        text = (_PROMPTS / name).read_text(encoding="utf-8").strip()
        _LOADED[name] = True
        return text
    except OSError:
        _LOADED[name] = False
        logging.getLogger(__name__).warning("prompt %s missing under %s; using inline fallback", name, _PROMPTS)
        return FALLBACK_SYSTEM


def prompts_loaded() -> dict[str, bool]:
    return dict(_LOADED)


def normalize_verdict(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        data = {}
    action = str(data.get("action", "")).strip().lower()
    calls_raw = data.get("tool_calls") or []
    calls: list[dict[str, Any]] = []
    if isinstance(calls_raw, list):
        for c in calls_raw:
            if not isinstance(c, dict):
                continue
            tool = str(c.get("tool") or c.get("name") or "").strip()
            if not tool:
                continue
            args = c.get("args") if isinstance(c.get("args"), dict) else {}
            calls.append({"tool": tool, "args": args, "why": str(c.get("why") or "")[:200]})
    if action not in ("tools", "answer"):
        action = "tools" if calls else "answer"
    if action == "tools" and not calls:
        action = "answer"
    conf = data.get("confidence", 0.0)
    try:
        conf = max(0.0, min(1.0, float(conf)))
    except (TypeError, ValueError):
        conf = 0.0
    return {
        "thought": str(data.get("thought", "")).strip()[:600],
        "sufficient": bool(data.get("sufficient", False)),
        "confidence": conf,
        "missing": str(data.get("missing", "")).strip()[:400],
        "action": action,
        # Up to 6 proposals are kept; the controller executes at most 3 VALID
        # ones per round, so an unknown or duplicate call does not eat the cap.
        "tool_calls": calls[:6],
    }


def user_message(question: str, phase: str, phase_no: int, max_phases: int, catalog: str,
                 trajectory: list[dict[str, Any]], context_digest: str, budget: dict[str, Any],
                 project: dict[str, Any] | None, seed_tools: list[str] | None = None) -> str:
    parts = [f"QUESTION: {question}", "",
             f"PHASE {phase_no}/{max_phases}: {phase} — {_PHASE_GUIDE.get(phase, '')}",
             f"BUDGET: iterations left {budget.get('max_iterations', 0) - budget.get('iterations_used', 0)}, "
             f"tool calls left {budget.get('max_tool_calls', 0) - budget.get('tool_calls_used', 0)} (max 3 this round), "
             f"documents {budget.get('documents_used', 0)}/{budget.get('max_documents', 0)}, "
             f"context tokens {budget.get('context_tokens', 0)}/{budget.get('max_context_tokens', 0)}"]
    if phase_no >= max_phases:
        parts.append("This is the LAST round: choose action=answer unless ONE verification call is clearly needed.")
    if project:
        parts += ["", f"PROJECT: {project.get('name')} (key {project.get('project_key')}, client {project.get('client')}, "
                      f"status {project.get('status')})"]
    if seed_tools:
        parts += ["", "ROUTER HINTS (tools that usually fit this kind of question): " + ", ".join(seed_tools)]
    parts += ["", "TRAJECTORY SO FAR:"]
    parts += [json.dumps(s, ensure_ascii=False)[:700] for s in trajectory] or ["(none)"]
    parts += ["", "CONTEXT DIGEST (evidence already gathered):", context_digest, "", "TOOLS:", catalog, "",
              "Respond with ONLY the JSON object."]
    return "\n".join(parts)


async def decide(question: str, phase: str, phase_no: int, max_phases: int, catalog: str,
                 trajectory: list[dict[str, Any]], context_digest: str, budget: dict[str, Any],
                 project: dict[str, Any] | None = None, seed_tools: list[str] | None = None,
                 timeout: float | None = None) -> dict[str, Any]:
    system = load_prompt().replace("{{TOOLS}}", catalog)
    data = await llm.chat_json(
        [{"role": "system", "content": system},
         {"role": "user", "content": user_message(question, phase, phase_no, max_phases, catalog, trajectory,
                                                  context_digest, budget, project, seed_tools)}],
        timeout=timeout or config.llm_primary_timeout(),
        model=config.llm_judge_model(),
    )
    return normalize_verdict(data)
