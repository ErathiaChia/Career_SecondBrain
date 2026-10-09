"""The explicit tool layer (brief §11). Every tool is a ToolSpec wrapping an
existing read function; the bounded agent calls tools ONLY through
``call()``, which validates arguments, times out, never raises, and returns a
compact summary for the Judge plus Sources for the context builder."""
from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal

from era_mcp import config
from era_mcp.agent_tools.sources import Source
from era_mcp.budget import estimate_tokens

ToolGroup = Literal["knowledge", "document", "investigation", "career", "structural"]


@dataclass
class ToolResult:
    ok: bool
    summary: str
    sources: list[Source] = field(default_factory=list)
    data: Any = None
    error: str | None = None
    elapsed_ms: int = 0


@dataclass(frozen=True)
class ToolSpec:
    name: str
    group: str
    description: str
    input_schema: dict[str, Any]
    fn: Callable[..., Awaitable[ToolResult]]
    cost: str = "db"               # db | embed | llm — llm tools are refused inside the loop
    judge_visible: bool = True     # shown in the Judge catalog
    max_result_tokens: int = 1200  # the observation text is cut to this

    def signature(self) -> str:
        props = self.input_schema.get("properties") or {}
        required = set(self.input_schema.get("required") or [])
        args = []
        for k, v in props.items():
            t = v.get("type", "any")
            args.append(f"{k}{'' if k in required else '?'}: {t}")
        return f"{self.name}({', '.join(args)})"


REGISTRY: dict[str, ToolSpec] = {}


def register(spec: ToolSpec) -> ToolSpec:
    if spec.name in REGISTRY:
        raise ValueError(f"duplicate tool {spec.name}")
    REGISTRY[spec.name] = spec
    return spec


def get(name: str) -> ToolSpec | None:
    return REGISTRY.get(name)


def names(group: str | None = None) -> list[str]:
    return sorted(n for n, s in REGISTRY.items() if group is None or s.group == group)


def catalog(judge_only: bool = True) -> str:
    """One line per tool, grouped, for the Judge prompt (kept ~600-800 tokens)."""
    lines: list[str] = []
    for group in ("knowledge", "document", "investigation", "career", "structural"):
        specs = [s for s in REGISTRY.values() if s.group == group and (s.judge_visible or not judge_only)]
        if not specs:
            continue
        lines.append(f"## {group}")
        for s in sorted(specs, key=lambda x: x.name):
            lines.append(f"- {s.signature()}: {s.description}")
    return "\n".join(lines)


_COERCE = {"integer": int, "number": float, "boolean": lambda v: str(v).lower() in ("1", "true", "yes", "on"),
           "string": str}


def validate_args(spec: ToolSpec, args: dict[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
    """Drop unknown keys, coerce scalars to the declared type, check required."""
    props = spec.input_schema.get("properties") or {}
    required = spec.input_schema.get("required") or []
    clean: dict[str, Any] = {}
    errors: list[str] = []
    for k, v in (args or {}).items():
        if k not in props:
            continue
        if v is None or v == "":
            continue
        typ = props[k].get("type")
        if typ == "array":
            if isinstance(v, str):
                v = [x.strip() for x in v.split(",") if x.strip()]
            elif not isinstance(v, list):
                v = [v]
        elif typ in _COERCE:
            try:
                v = _COERCE[typ](v)
            except (TypeError, ValueError):
                errors.append(f"{k}: expected {typ}")
                continue
        clean[k] = v
    for k in required:
        if k not in clean:
            errors.append(f"{k}: required")
    return clean, errors


async def call(name: str, args: dict[str, Any] | None, *, timeout: float | None = None) -> ToolResult:
    """Execute a tool. Never raises: unknown tool, bad args, exceptions and
    timeouts all come back as ok=False with an explanation the Judge can read."""
    t0 = time.monotonic()
    spec = REGISTRY.get(name)
    if spec is None:
        return ToolResult(ok=False, summary=f"unknown tool {name!r}", error="unknown_tool")
    clean, errors = validate_args(spec, args)
    if errors:
        return ToolResult(ok=False, summary=f"{name}: invalid args ({'; '.join(errors)})", error="invalid_args")
    timeout = timeout if timeout is not None else config.tool_timeout_s()
    try:
        coro = spec.fn(**clean)
        if not inspect.isawaitable(coro):
            raise TypeError(f"tool {name} is not async")
        result: ToolResult = await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        result = ToolResult(ok=False, summary=f"{name}: timed out after {timeout:.0f}s", error="timeout")
    except Exception as e:  # noqa: BLE001 — a tool failure is an observation, not a crash
        result = ToolResult(ok=False, summary=f"{name}: {type(e).__name__}: {e}"[:300], error=type(e).__name__)
    result.elapsed_ms = int((time.monotonic() - t0) * 1000)
    if estimate_tokens(result.summary) > spec.max_result_tokens:
        result.summary = result.summary[: int(spec.max_result_tokens * 3.6)] + " …"
    return result


def tool(name: str, group: str, description: str, input_schema: dict[str, Any], *, cost: str = "db",
         judge_visible: bool = True, max_result_tokens: int = 1200):
    """Decorator: register an async tool function."""
    def deco(fn: Callable[..., Awaitable[ToolResult]]):
        register(ToolSpec(name=name, group=group, description=description, input_schema=input_schema, fn=fn,
                          cost=cost, judge_visible=judge_visible, max_result_tokens=max_result_tokens))
        return fn
    return deco
