# Intelligent MCP — Agentic Retrieval Design

> **Status:** design only (not yet built). Scope: **`era_mcp` only.** The
> Auditor/Librarian (vault cleanup) is **not touched** by this work. The one
> thing they share is a neutral **Vault Manifest** reference (see §5).

## 1. Context — why

Two real failures from live Open WebUI transcripts motivate this:

1. **Relevance ("what's the latest on IBF?")** — single-pass retrieval returned
   unrelated chunks and *didn't try harder*; the user had to manually coach it
   over 6 turns. The agent can't tell good results from bad and never retries.
2. **Wrong tool ("how many projects? list all folders")** — these are *census*
   (enumeration) questions, but the agent answers with *semantic search*, which
   returns the top-K most **similar** chunks — a **sample**, never a complete
   list. So every answer was hedged ("may not be complete") or empty. The
   answer is plain data in `file_registry.file_path`, but no tool exposes it and
   nothing routes the question to a structural query.

**Goal:** turn `/ask` from a one-shot search-and-summarize into an **intelligent
MCP agent** that (a) picks the right *strategy* for the question, (b) plows
through the vault — iterating and re-querying — until it has a suitable answer,
and (c) returns a **structured JSON** result the Open WebUI agent can act on.

## 2. Where it runs (unchanged split, uses the M1 Max)

| Role | Model / store | Host |
|---|---|---|
| Agent loop + routing orchestration | (Python) | NAS `era-vault-mcp` |
| Embeddings | `qwen3-embedding:0.6b` | NAS Ollama |
| Reranker / cheap relevance gate | `bge-reranker-v2-m3` (Infinity) | **Mac :7997** |
| **Router + Judge + Synthesis** | large **Gemma** (`JUDGE_MODEL`) | **Mac :11434** (64 GB) |
| Structural inventory | SQL over `file_registry` / Vault Manifest | NAS |

NAS does retrieval + structural queries; the Mac does the thinking.

## 3. The agent, end to end

```
question
  │
  ▼  ROUTE  (cheap rules + rewriter intent; escalate to Judge if ambiguous)
  ├── STRUCTURAL  ("how many / list all / where is / folder / project inventory")
  │      → query the inventory (file_registry path tree, or Vault Manifest §5)
  │      → deterministic, COMPLETE, no vector search, usually no loop
  │
  └── SEMANTIC / LOOKUP / "latest on X"
         → BOUNDED RETRIEVAL LOOP (§4)
            retrieve+rerank → cheap gate → Judge: sufficient?
              ├ yes → out
              └ no  → reformulate → retrieve → MERGE pool → repeat (capped)
  │
  ▼  SYNTHESIZE (Gemma) → structured JSON "MCP" response → Open WebUI agent
```

The **router is the new front**. It fixes failure #2: enumeration questions go
to a structural tool instead of the semantic hammer. The Judge can also
**re-route mid-loop** if it realizes a question is actually structural.

## 4. The agentic loop — the Judge DRIVES re-search & re-write

The Judge does **not** just grade results — it **drives the next move** and calls
back through the MCP's own retrieval. Each turn it picks an **action**: re-write +
re-search, switch tool (e.g. to the structural inventory), pull more context for a
promising doc, or answer now. A bounded controller executes the chosen action and
loops — so the Judge has real agency, but **cannot run away on a local model**
("bounded agentic"; the Judge chooses the *moves*, the controller enforces the
*limits*).

**Confidence gate (replaces an opt-in flag).** Every query gets a cheap route +
one retrieval pass; the **reranker top score is the confidence signal**:
- **≥ ~80%** (`STRONG_RERANK_THRESHOLD`) → answer directly — the fast single pass.
- **< ~80%** → hand control to the Judge loop.

```python
pool = {}; tried = set()
queries = [rewrite(q)] + sub_queries(q)            # cheap FIRST-PASS rewrite only
merge_dedup(pool, retrieve(queries)); rerank(pool, q)
if top_rerank(pool) >= STRONG_RERANK_THRESHOLD:    # confident → single pass
    return synthesize(q, best(pool))
for _ in range(MAX_ITERS):                         # else: the JUDGE drives
    act = judge(q, summarize(pool))                # Gemma → {action, ...}
    if act.action == "answer":     break
    if act.action == "structural": return structural_tool(act.query)
    if act.action == "research":                   # Judge RE-WRITES + RE-SEARCHES
        nxt = [x for x in act.reformulations if x not in tried]
        if not nxt: break                          # nothing new to try → stop
        tried |= set(nxt)
        merge_dedup(pool, retrieve(nxt)); rerank(pool, q)
    if time_spent() > TIME_BUDGET: break
return synthesize(q, best(pool))
```

**Judge verdict — it issues an ACTION, not just a grade** (compact input → JSON;
full chunks are never sent to the Judge, only summaries, so each turn stays fast):
```json
// IN:  question + [{n, file_name, folder, snippet(~200c), rerank_score}]
// OUT:
{ "action": "research|structural|answer",
  "sufficient": false,
  "missing": "no doc mentions the IBF award/kickoff, only the RFP",
  "reformulations": ["IBF programme accreditation award outcome", "..."], // action=research
  "query": "projects under 01 Project/2026",                              // action=structural
  "confidence": 0.4 }
```

The Judge can also **re-route to the structural tool mid-investigation** if it
realizes the question is really an inventory/census question.

**Guardrails (why it's bounded, not free-roaming):**
- `AGENT_MAX_ITERS` 2–3; `AGENT_TIME_BUDGET` ~45–60s.
- **No-new-docs early exit:** a re-search that adds zero new files can't help — stop.
- **Confidence gate first:** strong top rerank score → answer without ever calling
  the Judge (fast path for clear lookups).
- **Always degrade:** Judge/Gemma down → fall back to the single pass with
  `degraded: true`. Never hard-fail.

## 5. Structural inventory — dynamic, and a neutral SHARED reference

**The folder structure is dynamic** — files and folders are added, removed,
reorganized, and renamed continuously. The inventory must therefore be
**derived, never a static snapshot**, and its schema must be **taxonomy-agnostic**
(store the *observed* tree generically — path, name, parent, counts; do **not**
hardcode "project/stage" rules that break the moment the vault is reorganized).

Three layers, in the order `era_mcp` should rely on them:

- **Primary — live derivation (always fresh):** at query time, derive the
  folder/project inventory from `file_registry.file_path` (`SELECT DISTINCT` over
  path prefixes). **Always current** for folders with indexed content — no build
  step, no staleness. This is the structural branch's default and answers today's
  failing questions.
- **Auto-refresh:** `file_registry` is already maintained by the indexer's
  `discover`/`sync` cycle (new/changed/removed files update it), so the live
  derivation tracks the vault automatically as it evolves — no separate job.
- **Enrichment — the Vault Manifest (future, Librarian-owned):** a neutral
  curated artifact that *adds* what the raw tree can't infer — canonical project
  names, project-vs-container, lifecycle/status, and *empty* folders. **In the
  future the AI Librarian Agent maintains and configures it as new files/folders
  appear** (Librarian = curator/writer; `era_mcp` = read-only consumer). It
  carries `generated_at` + a version so staleness is detectable.

```jsonc
// Vault Manifest entry — generic/flexible; "kind" is advisory, not a fixed taxonomy
{ "path": ".../14. ST-Engg/01 Project/2026/16_HC3",
  "name": "HC3", "kind": "project?", "parent": "01 Project/2026",
  "file_count": 12, "last_modified": "2026-05-30",
  "generated_at": "…", "manifest_version": 7 }
```

**Freshness rule:** `era_mcp` must treat the Manifest as possibly **stale or
absent** and **fall back to the live `file_registry` derivation** whenever it is
missing, old, or doesn't cover a path — so a dynamic vault can never yield a
wrong-because-stale structural answer.

**Decoupling rule:** `era_mcp` must NOT import or query any `auditor_*` table or
auditor code. The Manifest is the *only* cross-agent touch-point — a plain shared
artifact (a `vault_manifest` table and/or a JSON export, **whichever you
prefer**) that the future Librarian **writes** and `era_mcp` **reads**. It is the
hand-off contract between the answer-agent and the cleanup-agent, nothing more.

## 6. Output — the structured "MCP" JSON for Open WebUI

```jsonc
{ "answer": "…markdown with [n] citations…",
  "route": "structural|semantic",
  "sufficient": true,
  "confidence": 0.82,
  "gaps": "award outcome not found in the vault",
  "results": [ /* structural rows OR citation chunks */ ],
  "citations": [{ "n":1, "file_name":"…", "file_path":"…", "folder":"…", "snippet":"…" }],
  "iterations": 2,
  "queries_tried": ["…"],
  "max_iters_reached": false,
  "trajectory": [ /* ReAct steps: {thought, action, queries, observation} */ ],
  "degraded": false,
  "provider": { "judge_model":"gemma4:31b-mlx", "reranker":"infinity" } }
```

`route` + `sufficient` + `gaps` + `confidence` let the Open WebUI agent decide
whether to answer, hedge, or ask a follow-up — instead of confidently returning
stale/sampled junk.

## 7. Scope boundaries

- **In `era_mcp`:** router, the Judge-driven loop, Judge/synthesis calls,
  structural branch, and a single **confidence-gated `/ask`** (no opt-in flag — a
  strong first-pass rerank score answers directly; a weak one escalates into the
  Judge loop).
- **NOT touched:** the Auditor/Librarian and its `auditor_*` tables — that
  remains the *cleanup* agent.
- **Shared, neutral:** the Vault Manifest only.

## 8. Reuse vs new

- **Reuse:** `multi_search_async` (multi-query + rerank), `embed_query`, rerank
  scores, `query_understanding` (rewrite + `complexity`), `llm.chat_json`,
  `list_folders` (extend it / add a path-tree query).
- **New:** `era_mcp/agent.py` (router + Judge-driven loop); judge prompt +
  action/verdict schema; the structural-inventory query (+ optional Manifest
  reader); config knobs `JUDGE_MODEL`, `AGENT_MAX_ITERS`, `AGENT_TIME_BUDGET`,
  `STRONG_RERANK_THRESHOLD` (the ~80% confidence gate); a richer `/ask` response.

## 9. Decisions

**Settled:**
- **Build both now:** the full Judge-driven agentic loop **and** the structural-
  inventory tool.
- **No opt-in flag — a confidence gate decides the path** automatically:
  first-pass rerank score ≥ ~80% → single pass; < ~80% → Judge loop.
- **Routing:** cheap rules + confidence first (e.g. "how many / list all /
  under <path>" → structural); escalate to the Gemma Judge only when rules fail
  or it's clearly necessary.
- **The Judge drives re-search & re-write** — it issues actions and a bounded
  controller executes them (not a free-roaming ReAct agent, to stay safe on a
  local model).
- **Models (default):** one Gemma does rewrite+route+judge+synthesis to start;
  splittable later (a small model would take over only the trivial *first-pass*
  rewrite + routing) as a drop-in optimization if per-query latency bites.

**Still open:**
- **Manifest storage form** (`vault_manifest` table vs JSON export vs both) — the
  future **AI Librarian** owns/maintains it; live `file_registry` derivation is the
  default until then, so this isn't blocking.
- **Calibrating the ~80% gate** to an actual rerank-score threshold (needs the
  reranker live + the scorecard to tune).
- **Reranker dependency:** the confidence gate needs trustworthy rerank scores, so
  the cross-encoder (Fix 4) should be on before the gate is meaningful.
