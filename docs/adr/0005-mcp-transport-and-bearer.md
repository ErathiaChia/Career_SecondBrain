# ADR 0005 — One intelligence layer, two transports, three tools, one bearer token

**Status:** accepted (2026-10-09)

## Context
The brief wants the layer reachable from any client (Open WebUI, Claude Code,
Codex). V4 exposed 29 raw project tools to Open WebUI, where the model's native
tool-calling has no loop limit (the §19 anti-pattern).

## Decision
- Clients see exactly `ask_vault`, `search_vault`, `pipeline_status`.
- `/ask` owns the investigation budget; all other capabilities are internal
  tools of its registry (`era_mcp/agent_tools/`), hidden from OpenAPI.
- MCP is served by the FastMCP SDK (`mcp<2`) mounted inside the same FastAPI
  process at `MCP_PATH` (`/mcp`, streamable HTTP, stateless); a stdio entry
  point exists for clients without HTTP MCP.
- `API_BEARER_TOKEN` gates every path except health/docs/openapi/graph; the
  same token is used by Open WebUI (tool-server key) and MCP clients
  (`Authorization: Bearer`). Reach the NAS over Tailscale, never a public port.

## Consequences
- The 3-loop / 9-tool-call / 10-document / 20k-token budget is enforced in one
  place for every client.
- Open WebUI must re-sync the tool server after deploy; the system prompt
  (`prompts/ai_secondbrain_agent.md`) now only relays `ask_vault` results.
