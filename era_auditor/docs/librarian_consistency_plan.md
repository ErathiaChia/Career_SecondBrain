# Librarian Consistency Plan

Goal: make all `auditor/rules/*.yaml` internally consistent and aligned with the
code, so the Librarian/Auditor reads coherent signals when deciding where a file
belongs. Then start fresh (drop DB, re-init from YAML) and re-measure placement.

Strategy decisions (locked):
- **registry_path_only** for classification: rely on `project_registry` exact
  `folder_path` matches (initiatives classify at confidence 1.0).
- **folder-derived customer codes**: codes must equal what
  `FolderConstitution.customer_code()` derives from the folder name.
- **Drop DB + start fresh**: `init-db` runs `schema.sql` then
  `sync_registries_from_yaml()`, so YAML is the single source of truth.
- **flatten_letter** numbering: keep letter prefixes, running numbers within a
  stage (`A.1`, `A.2`, `A.3`), max depth `Letter.N`. No engine rewrite.
- Iterate with `run --full --no-ai` first (fast/free), then one AI pass.

---

## Verified mechanics (from reading the code)

- `init-db` (cli.py:54-59) -> `schema.sql` (idempotent) + `sync_registries_from_yaml()` (db.py:27-32).
- `run` (cli.py:122-172) does NOT sync YAML and skips already-classified folders
  unless `--full` (content_signature gating, db.py:259-282). Fresh DB avoids both.
- Classification: deterministic-first (constitution.py), only unmatched folders
  hit OpenAI (classifier.py:53-70). `project_match` uses in-memory YAML.
- Placement engine reads `projects_registry()` from the DB and `customer_code`
  from the latest classification (db.py:801-844). So registry + classification
  must agree.
- Embeddings are a no-op until `era_indexer` is populated (config.py:83 default
  `indexer_database_url = None`). Use `--no-embeddings`.
- schema.sql has NO DROP statements; "start fresh" needs explicit DROP.

---

## Test constraints (from tests/test_constitution.py)

- Line 76: already expects `02_Bank_Negara`-sibling `09_SG-MOH C3 (DEROM)` ->
  `customer_code == "SG_MOH_C3_DEROM"`. (Confirms Workstream A.)
- Lines 58-59: `MY_MOH` -> `"Malaysia Ministry of Health"` is TEST-PINNED. Keep
  this exact `full_name` in customer_registry.yaml.
- Lines 147-190: use `02_Bank_Negara` as the deliberate UNKNOWN-customer fixture
  (`unknown_customer` + `enrich_registry`). Adding `BANK_NEGARA` to the registry
  makes it KNOWN and breaks these 2 tests -> Workstream F swaps the fixture.

---

## Registry modeling decision (added during execution)

The generated registry had 18 entries whose `folder_path` pointed at the
*customer* folder itself (e.g. `01 Project/2026/07_MY_MOH`). The constitution
matches those as `initiative` (project match, conf 1.0), which broke two tests
that assert customer-named year-children must classify as `customer`.

FINAL decision (user, corrected against the real tree): **two shapes.**
- Multi-initiative customers (01_IBF): one registry row per sub-folder initiative
  (`01_IBF/1 AI Staff Training` ...). Parent `01_IBF` stays `customer`.
- Single-initiative customers: the stage tree sits DIRECTLY under the customer
  folder (e.g. `02_Bank_Negara/A.1. RFI_RFP_RFQ`), so the customer folder IS the
  initiative. `folder_path` points at the customer folder; it classifies as
  `folder_type=initiative` (project_registry, conf 1.0).

24 initiatives total (6 IBF sub-folders + 18 customer-folder initiatives). Tests
updated: registered customer-folder -> initiative; an UNregistered customer-named
year child still -> customer (container rule). 96 tests pass.

### Deterministic coverage snapshot (no AI, 625 folders)
- matched 251/625 (40%): stage 205, initiative 32, temporal 6, root 6, customer 1
- unmatched 374 are NOT project initiatives: `04 Resources` (template/asset lib),
  `02 Ops` (Daily_Todo, Internal_Meeting_Notes, Events), `03 Product`, and deep
  content folders (Resources, Data, Version N, named working folders) + a few new
  stage variants (A.1.4 Additional Resources, A.2.7 Internal Discussion, A.3 DEMO,
  Meetings). These are the real "needs a rule or AI" backlog.

## Workstream A - project_registry.yaml customer_code fixes

Make `customer_code` folder-derived (matches `customer_code()` / `relaxed_customer_code()`).

| folder_path | from | to |
|---|---|---|
| `02_Bank_Negara` | `BNM` | `BANK_NEGARA` |
| `09_SG-MOH C3 (DEROM)` | `SG_MOH_C3` | `SG_MOH_C3_DEROM` |
| `11_Thailand - True Telecom` | `TRUE_TELECOM` | `THAILAND_TRUE_TELECOM` |
| `12_TTSH - Eye Clinic` | `TTSH` | `TTSH_EYE_CLINIC` |
| `20_TemasekPoly_SmartContract` | `TEMASEKPOLY` | `TEMASEKPOLY_SMARTCONTRACT` |

The other ~19 entries (incl. all IBF initiatives) already match.

---

## Workstream B - customer_registry.yaml full rewrite

One entry per customer folder, key = folder-derived code. Test-pinned name
(`MY_MOH`) preserved exactly. Codes:

`IBF, BANK_NEGARA, HONGLEONG, DBS, ITE_AMK, MUSIMMAS, MY_MOH, NUHS,
SG_MOH_C3_DEROM, SPH, THAILAND_TRUE_TELECOM, TTSH_EYE_CLINIC, HCLTECH, SENTOSA,
HC3, HSA, VANGUARDHEALTH, TAIYOYUDEN, TEMASEKPOLY_SMARTCONTRACT`

---

## Workstream C - remove customer_dictionary.yaml

Delete the file and update the 6 references so customer_registry is the single
source of truth:
1. constitution.py:25 - remove `self.customer_dictionary = ...`
2. constitution.py:43 (`as_prompt_payload`) - remove `"customer_dictionary"` key
3. constitution.py:254 (`customer_code`) - drop dictionary membership check
4. constitution.py:264-266 (`known_customer`) - read only customer_registry
5. registry_bootstrap.py:42 - remove dictionary from merged known_customers
6. naming_standards.yaml:97 - reword the dictionary-lookup comment

---

## Workstream D - flatten + enrich presales stage tree

Proposed canonical PreSales tree (letter prefixes, running numbers, max `Letter.N`):

```
A. PreSales (optional wrapper)
A.1. RFI_RFP_RFQ  [core]   -> A.1.1 Logo, A.1.2 Requirements, A.1.3 Meeting Notes, A.1.4 Sample Data
A.2. Proposal     [core]   -> A.2.1 Clarification, A.2.2 Effort Estimation, A.2.3 Timeline,
                              A.2.4 Presentation Slide, A.2.5 Contract
A.3. Engagement   [opt]    -> A.3.1 Sharing Session, A.3.2 Internal Discussion, A.3.3 Demo, A.3.4 Workshop
B. Delivery
C. Post Sales
```

Update `project_templates.yaml` (`canonical_stage_tree` + `stage_template`) and
`naming_standards.yaml` (`stage_names`) together. Add aliases for A.1.4, A.2.2,
A.3.x. Note: existing `A.2.6.` folders will (intentionally) raise template_drift.

---

## Workstream E - resolve sharing_session

`sharing_session` is allowed by models.py InitiativeType (lines 78-88) and
classify_folder.md:16, but has no archetype in initiative_types.yaml. Since it is
now a presales activity (A.3.1), remove it from both the model Literal and the
prompt enum list.

---

## Workstream F - swap test fixtures

In tests/test_constitution.py, `test_unknown_customer_is_registry_enrichment`
(147-167) and `test_rejected_finding_pattern_is_suppressed` (169-190) use
`02_Bank_Negara`. Since BANK_NEGARA becomes known, swap to a path that is in no
registry (e.g. `01 Project/2026/99_FakeCorp`) so the unknown-customer path is
still exercised.

---

## Verification sequence (fresh start)

```bash
pytest

# Drop all auditor tables, then re-init from YAML
psql "$AUDITOR_DATABASE_URL" -c "DROP TABLE IF EXISTS \
  auditor_runs, auditor_folders, auditor_files, auditor_folder_classifications, \
  auditor_findings, auditor_customers, auditor_projects, auditor_decisions, \
  auditor_recommendation_patterns, auditor_assets, auditor_scores, \
  auditor_placement_patterns, auditor_placement_simulations, \
  auditor_placement_plans CASCADE;"

python -m auditor.cli init-db                              # schema + YAML sync
python -m auditor.cli run --full --no-ai                   # fast deterministic pass; iterate
python -m auditor.cli run --full                           # AI pass when deterministic looks right
python -m auditor.cli placement simulate --sample 300 --no-embeddings
# compare vs placement_simulation_run_3
```

## Coverage uplift plan (deterministic, no AI)

Goal: raise the 40% deterministic coverage by classifying the unmatched 374 with
rules instead of LLM calls. Three additive rules, all in constitution.py +
organization_rules.yaml/naming_standards.yaml (no breaking changes; the new
folder_type values already exist in models.FolderType):

1. **Category inheritance** - tag each non-project top-level root in
   organization_rules.yaml with `category_type` (02 Ops -> operations,
   03 Product -> product, 04 Resources -> resource, 05 Administrative ->
   administration). New constitution fallback: a folder whose root_category is a
   category root and matched nothing more specific inherits that folder_type
   (matched_rule `category:<root>`, confidence ~0.6, source `organization_rules`).
2. **Month temporal** - extend is_temporal() to also accept month_pattern and
   common month-name folders (01_Jan, 202601_Jan, 10Oct) so YYYY/MM sub-trees
   under Ops classify as temporal.
3. **Container folders** - a folder whose normalized name is in
   naming_standards.container_names (Resources, Data, Demo, Images, ...) classifies
   as folder_type=knowledge_asset/resource container (matched_rule
   `container:<name>`), so deep working folders stop falling through.

Ordering in classify_deterministic: keep current specific rules first
(registry, temporal, archive, stage, customer/initiative); add month-temporal
into the temporal check; then container; then category-inheritance as the final
catch-all before `return None`.

## Coverage uplift RESULT

After the 3 rules: **deterministic coverage 251 -> 577 / 625 (40% -> 92%)**,
zero AI cost, 96 tests still pass.

By type: stage 205, resource 127, product 57, administration 48, operations 46,
temporal 37, initiative 32, knowledge_asset 17, root 6, inbox 1, customer 1.
By rule: category 278, stage 205, temporal 37, project_registry 24, container 17.

Remaining 48 unmatched are ALL under `01 Project` - deep working sub-folders
below the stage tree (version folders, named working folders like
`HL Bank - POC`, meeting sub-folders) + a few stage variants not yet in the tree
(`A.2.7 Internal Discussion`, `A.1.4 Additional Resources`, `Meetings`,
`D. New Requirements`). These are the legitimate AI / stage-tree-extension cases.

## Risk notes

- Embeddings no-op until era_indexer populated.
- New stage tree intentionally raises template_drift on legacy `A.2.6.` folders.
- `--no-ai` covers registered/stage/temporal/customer folders deterministically.
