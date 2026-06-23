# AI Knowledge Steward Agent (`era_auditor`)

Standalone, read-only folder auditor for periodically cleaning up a knowledge vault.

The auditor observes, analyzes, recommends, and explains. It does **not** move,
rename, delete, archive, or create user knowledge folders. Its identity is a
**Knowledge Steward, not a knowledge architect**: it preserves the human's
existing organization and only surfaces findings that make the vault easier for
a human (and a future AI Librarian) to understand. See
[Knowledge Steward Principles](#knowledge-steward-principles).

**TL;DR for a fresh start:**

```bash
cd era_auditor
python -m auditor.cli init-db     # create/refresh schema + sync registries
python -m auditor.cli run         # full steward pass (scan -> assets -> AI -> findings -> report)
python -m auditor.cli report latest
```

## Ecosystem

| Component | Role |
|-----------|------|
| [`era_indexer`](../era_indexer) | Write — discover, convert, chunk, embed, graph extract |
| [`era_mcp`](../era_mcp) | Read — hybrid search, `/ask` agent, OpenAPI tools |
| **era_auditor** (this) | Steward — vault hygiene, semantic dupes, Librarian training |
| [`era_graph_web`](../era_graph_web) | Visualize — Sigma.js graph viewer at `/graph` |

The auditor scans the same vault roots as the indexer, writes `auditor_*` tables,
and optionally reads indexer embeddings for semantic dupes and placement simulation.
See the [repo masterplan](../README.md) for the full architecture.

## Architecture

The auditor reasons about KNOWLEDGE ASSETS, not folder names. Folders are
infrastructure; assets (decks, documents, spreadsheets) are the knowledge.

```text
Filesystem roots
      -> scanner (subtree ignores, code-repo leaf detection, content hashing)
      -> auditor_* Postgres inventory + auditor_assets registry
      -> folder roles (CONTAINER/TEMPORAL folders are exempt from auditing)
      -> deterministic constitution + initiative archetypes + template-diff validation
      -> OpenAI folder classification (batched, only for unresolved folders)
      -> findings (each must pass a steward gate): physical duplicates (SHA256),
         semantic duplicates (era_indexer pgvector bridge, clustered),
         reusable-asset advisory (copy-not-move), architecture review, naming, registry
      -> Markdown report in asset-centric priority order + reuse leaderboard
```

## Project Layout

What lives in each folder/file of `era_auditor/`:

```text
era_auditor/
├── README.md                  This document.
├── config.yaml                Active config: scan roots, ignore rules, semantic
│                              thresholds, model/db references. Secrets come from
│                              the workspace-root ../.env (never committed here).
├── config.yaml.example        Template to copy when setting up a new machine.
├── requirements.txt           Python dependencies (SQLAlchemy, Pydantic, Typer, ...).
├── schema.sql                 Idempotent Postgres schema for all auditor_* tables
│                              (CREATE TABLE IF NOT EXISTS + ADD COLUMN IF NOT EXISTS).
│
├── auditor/                   The package (all application logic).
│   ├── cli.py                 Typer entrypoint. Commands: init-db, scan, classify,
│   │                          audit, run, bootstrap-registry, findings/report/
│   │                          registry/assets/placement sub-apps.
│   ├── config.py              Loads config.yaml + ../.env, builds the DB URL from
│   │                          ERA_VAULT_DB_* vars, validates with Pydantic.
│   ├── models.py              Pydantic models: FolderRecord, FileSnapshot,
│   │                          FolderClassification, AuditFinding, KnowledgeAsset, ...
│   ├── db.py                  AuditorDatabase: schema init, scan upserts, run
│   │                          lifecycle, findings/assets read+write, registry sync.
│   │
│   ├── scanner.py             Walks the vault roots, applies ignore rules, detects
│   │                          code-repo leaves, hashes file content (SHA256).
│   ├── constitution.py        Deterministic folder classifier: root/temporal/
│   │                          customer/initiative/stage rules + customer dictionary.
│   ├── classifier.py          OpenAI fallback classifier for folders the
│   │                          constitution cannot resolve (batched).
│   ├── folder_roles.py        FolderRoleResolver -> the 9 directive roles
│   │                          (ROOT/PROJECT/CUSTOMER/INITIATIVE/STAGE/CONTAINER/
│   │                          TEMPORAL/RESOURCE_LIBRARY/ADMINISTRATIVE). CONTAINER
│   │                          and TEMPORAL are audit-exempt.
│   ├── template_diff.py       Validates initiatives against the canonical stage
│   │                          tree (required-core + open-extension, renumbering).
│   ├── name_lint.py           Deterministic naming checks (alias drift, collisions).
│   ├── asset_registry.py      Builds auditor_assets: groups copies by hash/name,
│   │                          counts reuse across projects/customers, reuse_score.
│   ├── semantic_dupes.py      Bridge to era_indexer pgvector embeddings; clusters
│   │                          near-identical files, suppresses working-set and
│   │                          temporal siblings.
│   ├── placement.py           Placement Intelligence Engine (Librarian training):
│   │                          learns placement patterns from the vault, hybrid
│   │                          predict(), simulation accuracy, inbox plans. No moves.
│   ├── findings.py            FindingsGenerator: orchestrates all finding types and
│   │                          the steward suppression/false-positive filters.
│   ├── scoring.py             Per-folder health scoring written to auditor_scores.
│   ├── reports.py             Renders the Markdown report (priority order +
│   │                          reuse leaderboard + suppressed-noise summary).
│   ├── registry_bootstrap.py  Derives customer/project registry YAML from the scan.
│   │
│   ├── prompts/
│   │   ├── classify_folder.md     LLM prompt for folder classification.
│   │   └── generate_findings.md   LLM prompt carrying the Steward identity + the
│   │                              three audit-question gates.
│   │
│   └── rules/                 Human-editable YAML knowledge base:
│       ├── customer_registry.yaml     Known customers (single source of truth).
│       ├── project_registry.yaml      Known projects + lifecycle + initiative_type.
│       ├── initiative_types.yaml      Archetypes that decide which template applies.
│       ├── project_templates.yaml     Canonical A/B/C stage tree.
│       ├── naming_standards.yaml      container_names, numbering_policy, lint rules.
│       ├── organization_rules.yaml    Root-level placement rules.
│       ├── allowed_empty_folders.yaml Inbox/staging folders allowed to be empty.
│       └── decision_history.yaml      Recorded architecture decisions to honor.
│
├── tests/                     Unit tests (run with pytest):
│   ├── test_constitution.py       Deterministic classification + false-positive filter.
│   ├── test_folder_roles.py       Role resolution + the 9-role directive set.
│   ├── test_template_diff.py      Stage-tree validation + renumbering.
│   ├── test_initiative_types.py   Archetype-aware completeness + asset advisories.
│   ├── test_asset_registry.py     Asset grouping + reuse scoring + asset families.
│   ├── test_steward.py            Promotion gate, semantic clustering, working-set
│   │                              and temporal suppression (the Steward behaviour).
│   └── test_placement.py          Placement engine: pattern extraction, hybrid
│                                  prediction, simulation scoring, inbox plans.
│
└── reports/                   Timestamped Markdown reports, one per run (gitignored
                               output; not knowledge, skipped by the scanner).
```

## Setup

```bash
cd era_auditor
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp config.yaml.example config.yaml
```

Edit `config.yaml` with your source folder. Secrets are read from the root
`../.env` file, so keep `OPENAI_API_KEY`, `OPENAI_MODEL`, and the Postgres
connection values there.

Initialize the standalone auditor tables:

```bash
python -m auditor.cli init-db
```

## First Test Pass

Start small before auditing the full vault.

```bash
python -m auditor.cli scan --dry-run --limit 50
python -m auditor.cli scan --write-db --limit 50
python -m auditor.cli classify --limit 50
python -m auditor.cli audit --limit 50
python -m auditor.cli report latest
```

## Recurring Activation

Use this whenever you want to activate the cleanup assistant:

```bash
python -m auditor.cli run
```

Useful options:

```bash
python -m auditor.cli run --limit 50
python -m auditor.cli run --full
python -m auditor.cli run --no-ai
```

Default behavior is conservative:

- Unchanged folders reuse prior classifications.
- Changed and new folders are classified again.
- Findings are written to Postgres.
- A timestamped Markdown report is written to `reports/`.
- No file operations are performed on the knowledge vault.

## Registry Bootstrap

Instead of hand-editing registry YAML, derive it from the scanned tree:

```bash
python -m auditor.cli bootstrap-registry            # writes reports/registry_patch_<ts>.yaml
python -m auditor.cli bootstrap-registry --apply    # review first, then merge
```

Projects get a `lifecycle` (`lead | active_presales | delivery | archived`).
Template completeness is only enforced from `active_presales` onward; leads
are informational.

## Initiative Archetypes

Not every initiative is a sales opportunity. Archetypes live in
`auditor/rules/initiative_types.yaml` and decide WHICH template applies:

| Archetype | Stage tree (A/B/C)? | Expected folders |
| --- | --- | --- |
| `sales_opportunity` | yes | canonical stage tree |
| `delivery_project` | yes | canonical stage tree |
| `workshop` | no | Materials, Slides, Meeting Notes |
| `training_engagement` | no (unless staged) | Curriculum, Materials, Slides |
| `strategic_initiative` | no | Discussions, Planning, Deliverables |
| `architecture_artifact` | no | the artifact itself |
| `research_activity` | no | Research, References |
| `support_activity` | no | Tickets, Meeting Notes |

Resolution is registry-first: `initiative_type` in
`auditor/rules/project_registry.yaml` wins; otherwise the type is inferred
deterministically from the initiative name and child folders. A workshop or
strategic initiative is never asked for `A. PreSales` / `B. Delivery` /
`C. Post Sales`.

## Template Validation

The canonical stage tree lives in `auditor/rules/project_templates.yaml`
(`canonical_stage_tree`). Validation is "required core + open extension" and
only applies to archetypes that use the stage tree:

- Core stages (`A.1. RFI_RFP_RFQ`, `A.2. Proposal` and children) must use
  canonical names and indices.
- Extension folders are allowed if their letter prefix matches the ancestor
  stage (a `B.x` folder belongs under `B. Delivery`, not inside `A.1.`).
- Sibling index collisions get concrete renumbering suggestions.
- Stage-prefixed folders inside non-sales archetypes still get structural
  linting (collisions, alias drift), but never completeness demands.

## Folder Roles

Every folder gets a deterministic role before any auditing logic runs
(`auditor/folder_roles.py`):

- `CONTAINER` (Resources, Templates, Version 1, drafts, Slides, ...) and
  `TEMPORAL` (2026, Jan, 202510_Oct, Sprint 7, Q1) folders organize
  knowledge; they are never compared by name and never generate
  duplication findings.
- Structural roles (root, customer, initiative, stage) map from the
  existing classification.
- `RESOURCE_LIBRARY` (shared, reusable knowledge such as `04 Resources`)
  and `ADMINISTRATIVE` (ops/admin folders that organize work) are the
  remaining content roles. The full directive set is nine roles: ROOT,
  PROJECT, CUSTOMER, INITIATIVE, STAGE, CONTAINER, TEMPORAL,
  RESOURCE_LIBRARY, ADMINISTRATIVE.

The container-name list lives in `auditor/rules/naming_standards.yaml`
(`container_names`).

## Numbering Policy

Numeric prefixes (`01`, `09`, ...) are ordering and grouping aids, NOT
unique identifiers (`numbering_policy: ordering_not_identity`). Sibling
folders may intentionally share a prefix and never generate findings.
Stage indices (`A.2.5.`) remain identifiers validated by the template
differ.

## Asset Registry

After each scan, `auditor/asset_registry.py` rebuilds `auditor_assets`:
one row per distinct knowledge asset (by content hash, or normalized name
for unhashed files), with copy count, project/customer reuse counts, a
0-100 `reuse_score`, and a `canonical_location` (the `04 Resources` copy
when one exists).

```bash
python -m auditor.cli assets refresh   # rebuild from the latest scan
python -m auditor.cli assets list --top 20
```

## Duplication: Three Separate Systems

1. **Physical duplicates** - byte-identical files by SHA256
   (`knowledge_duplication`, medium severity, highest confidence).
2. **Semantic duplicates** - near-identical content via era_indexer's
   pgvector embeddings (`semantic_duplication`). Mean chunk embedding per
   file, pairwise cosine similarity above `semantic.similarity_threshold`
   (default 0.92). Gracefully no-ops when the indexer has not embedded the
   scan roots. Configured in `config.yaml` under `semantic:`.
3. **Architecture review** - the same meaningful topic under 2+ top-level
   roots (e.g. `FDE` in both `02 Ops` and `04 Resources`) produces ONE
   `architecture_review` finding framed as a question with action
   `document_decision`. Folder-name similarity alone is never duplication.

## Knowledge Steward Principles

The auditor is a Knowledge Steward, not a knowledge architect. It preserves
clarity, consistency, context, and the human's workflows; it never
restructures or centralizes the vault to fit a theory of perfect
organization. The filesystem is the human-owned navigation layer - a future
AI Librarian must learn from it, not the other way around.

Every finding must pass at least one gate, or it is suppressed:

1. Will this improve future human understanding?
2. Will a human struggle to find this later?
3. Will this create duplicate maintenance effort?

### Reusable Asset Advisory (not relocation)

Asset reuse is ADVISORY only. The auditor never recommends moving files out
of a project - project copies preserve archive self-containment so an
engagement can be exported or reviewed in isolation. A `reusable_asset`
advisory (low severity, no suggested destination) is raised only when an
asset crosses MULTIPLE CUSTOMERS AND shows active maintenance (multiple
diverging copies). Even then the suggested action is to COPY one canonical
version into `04 Resources` while keeping the project copies - never to
relocate. A deck copied into two folders for a single customer does not
qualify, and `Resources`/`Templates` folders inside a project are project
self-containment, never leakage findings.

## Review Findings

```bash
python -m auditor.cli findings list
python -m auditor.cli findings accept FINDING_ID
python -m auditor.cli findings reject FINDING_ID --reason "Not actually duplicate"
```

Accepted and rejected findings remain in the database so future versions can
learn from your review history.

## What's Been Built (evolution)

The agent grew through three directives, each tightening it toward a human-first
steward rather than a filesystem optimizer:

1. **Folder auditor -> archetype-aware auditor.** Deterministic constitution,
   initiative archetypes (`initiative_types.yaml`), and template-diff validation
   so a workshop is never asked for `A. PreSales` / `B. Delivery` / `C. Post Sales`.
   Numbering treated as ordering, not identity.

2. **Folder-centric -> asset-centric.** Introduced the **nine folder roles**
   (`folder_roles.py`), the **asset registry** (`auditor_assets`, reuse scoring),
   and split duplication into three systems: physical (SHA256), semantic
   (`era_indexer` pgvector bridge with clustering), and architecture review for
   genuinely ambiguous ownership. Removed folder-name similarity and numeric-prefix
   findings as noise.

3. **Human-First Knowledge Steward.** Every finding must pass one of three gates
   (improves understanding? hard to find later? duplicate maintenance?). Asset
   reuse became **advisory, copy-not-move, multi-customer + actively-maintained
   only**. `Resources`/`Templates` inside a project are self-containment, never
   leakage. Semantic detection now suppresses working-set siblings (PageN exports,
   version stems), temporal time-series (distinct daily todos / monthly reports),
   and dependency/code paths (`.venv`, `site-packages`, `node_modules`).

4. **Librarian Training System (current).** The auditor's job is now to *teach a
   future Librarian where the user would file a new file*. It learns placement
   patterns from the existing vault (the ground truth), measures how accurately a
   Librarian could replicate the user's filing, and plans inbox placements -
   **read-only, no moves**. See the section below.

Verification at the close of the steward work: **81 unit tests passing**. The
Librarian-training layer adds **14 more** (placement + asset families), for
**95 passing**.

## Librarian Training System

The long-term goal is an **AI Librarian** that places new files exactly where the
user would. The auditor's role is to extract the organizational intelligence that
trains it. **Phase 1 (this build) is learn + simulate + plan only - no file is
ever moved.**

### Placement Intelligence Engine (`auditor/placement.py`)

Treats the existing vault as labeled training data: every placed file is an
example of where *this* user puts files like it. It predicts a destination with a
**hybrid, deterministic-first** strategy:

1. **Deterministic** - learned patterns keyed by
   `(customer, initiative_type, stage, file_kind)` plus filename signals
   (`proposal`, `poc`, `demo`, `workshop`...), and the project registry's
   canonical paths. A mismatch on a known customer disqualifies a pattern.
2. **Embedding** - when deterministic confidence is weak, a nearest-neighbour
   vote over `era_indexer` embeddings: the destination folders of the most
   semantically similar placed files. No-ops gracefully if the indexer is empty.
3. **LLM** - reserved as a Phase-2 hook for genuinely ambiguous cases.

Confidence bands follow the directive: `>95%` auto-place (Phase 2),
`75-95%` suggest, `<75%` leave in inbox / needs review.

### Commands

```bash
python -m auditor.cli placement learn       # extract patterns -> auditor_placement_patterns
python -m auditor.cli placement simulate    # blind-predict placed files, score accuracy
python -m auditor.cli placement simulate --sample 500 --no-embeddings
python -m auditor.cli placement plan        # predict destinations for 00 Inbox files (no moves)
```

`placement learn` also runs automatically at the end of every `auditor run`.

### Placement Simulation = the success metric

`simulate` hides each placed file's location, rebuilds patterns *without it*, and
predicts blind, then scores: **exact** (same folder), **initiative** (same
customer+initiative), **customer** (same customer), or **wrong**. The accuracy
report (`reports/placement_simulation_run_*.md`) is the primary measure of
Librarian readiness - more important than folder audit scores.

### Supporting data

- **Asset families** (`auditor_assets.family_key`) group working-set derivations
  (`Page6`/`Page8`/`V3` of one deck) under a single logical asset via the shared
  stem helper, so the Librarian reasons about the family, not each variant.
- **Project registry enrichment** adds `initiative_type` and `canonical_path` to
  `auditor_projects` so the engine knows each project's archetype and home.
- **`missing_initiative_metadata` finding** flags initiatives with no registered
  archetype - a Librarian-training signal, since unregistered initiatives are
  exactly where placement confidence collapses. Surfaced under the report's
  *Librarian Training Signals* section.

### Tables

`auditor_placement_patterns` (learned rules), `auditor_placement_simulations`
(blind-prediction scores per run), and `auditor_placement_plans` (predicted inbox
destinations, `status = 'planned'` - the Phase-2 executor will consume these).

## Safety Rules

- All commands are read-only against source folders.
- Reports contain recommendations only.
- A future move/rename/archive executor must be built separately with dry-run
  output, backups, and explicit human confirmation.
