# Connecting clients

One intelligence layer, three tools (`ask_vault`, `search_vault`,
`pipeline_status`), two transports:

| Client | Transport | Config |
|---|---|---|
| Open WebUI | OpenAPI tool server | Settings → Tools → add `http://<nas>:8808/openapi.json`; set the bearer key to `API_BEARER_TOKEN`; load `era_mcp/prompts/ai_secondbrain_agent.md` as the model's system prompt |
| Claude Code | MCP (streamable HTTP) | `claude mcp add --transport http career-intel http://<nas>:8808/mcp --header "Authorization: Bearer $ERA_MCP_TOKEN"` or copy `claude_code.mcp.json` to the project's `.mcp.json` |
| Codex | MCP (HTTP or stdio bridge) | `codex.config.toml` |
| Anything else | stdio | `python -m era_mcp.mcp_server --stdio` on a machine with the `.env` (DB + Mac LLM reachable) |

`ERA_MCP_TOKEN` is the same value as `API_BEARER_TOKEN` in the server's `.env`.
Generate one with `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`.
Reach the NAS over Tailscale (MagicDNS name) rather than exposing the port.

Ask things like: "brief me on <project>", "what did we decide about pricing for
<client>?", "compare the last two versions of the <client> proposal",
"what evidence do I have of leading AI delivery?", "build STAR examples for
stakeholder management", "what changed this week?", "is the knowledge base
current?" (→ `pipeline_status`).
