CREATE TABLE IF NOT EXISTS auditor_runs (
    id BIGSERIAL PRIMARY KEY,
    run_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    config_path TEXT,
    report_path TEXT,
    total_folders INTEGER NOT NULL DEFAULT 0,
    changed_folders INTEGER NOT NULL DEFAULT 0,
    new_folders INTEGER NOT NULL DEFAULT 0,
    removed_folders INTEGER NOT NULL DEFAULT 0,
    total_findings INTEGER NOT NULL DEFAULT 0,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_cost_usd NUMERIC(12, 6),
    error_message TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS auditor_folders (
    id BIGSERIAL PRIMARY KEY,
    root_path TEXT NOT NULL,
    path TEXT NOT NULL,
    absolute_path TEXT NOT NULL,
    parent_path TEXT,
    depth INTEGER NOT NULL,
    file_count INTEGER NOT NULL DEFAULT 0,
    child_folder_count INTEGER NOT NULL DEFAULT 0,
    total_size_bytes BIGINT NOT NULL DEFAULT 0,
    latest_modified_at TIMESTAMPTZ,
    sample_filenames JSONB NOT NULL DEFAULT '[]'::jsonb,
    file_extension_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
    file_category_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata_signals JSONB NOT NULL DEFAULT '{}'::jsonb,
    content_signature TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    first_seen_run_id BIGINT REFERENCES auditor_runs(id),
    last_seen_run_id BIGINT REFERENCES auditor_runs(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (root_path, path)
);

ALTER TABLE auditor_folders
    ADD COLUMN IF NOT EXISTS file_extension_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS file_category_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS metadata_signals JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS auditor_files (
    id BIGSERIAL PRIMARY KEY,
    root_path TEXT NOT NULL,
    folder_path TEXT NOT NULL,
    path TEXT NOT NULL,
    absolute_path TEXT NOT NULL,
    extension TEXT NOT NULL DEFAULT '',
    size_bytes BIGINT NOT NULL DEFAULT 0,
    modified_at TIMESTAMPTZ,
    content_hash TEXT,
    first_seen_run_id BIGINT REFERENCES auditor_runs(id),
    last_seen_run_id BIGINT REFERENCES auditor_runs(id),
    status TEXT NOT NULL DEFAULT 'active',
    UNIQUE (root_path, path)
);

ALTER TABLE auditor_files
    ADD COLUMN IF NOT EXISTS content_hash TEXT;

CREATE INDEX IF NOT EXISTS idx_auditor_files_content_hash
    ON auditor_files (content_hash) WHERE content_hash IS NOT NULL;

CREATE TABLE IF NOT EXISTS auditor_folder_classifications (
    id BIGSERIAL PRIMARY KEY,
    folder_id BIGINT NOT NULL REFERENCES auditor_folders(id) ON DELETE CASCADE,
    run_id BIGINT NOT NULL REFERENCES auditor_runs(id),
    content_signature TEXT NOT NULL,
    folder_type TEXT NOT NULL,
    customer TEXT,
    initiative TEXT,
    initiative_type TEXT,
    root_category TEXT,
    customer_code TEXT,
    customer_name TEXT,
    stage TEXT,
    is_intentional_empty BOOLEAN NOT NULL DEFAULT FALSE,
    template_status TEXT,
    matched_rule TEXT,
    registry_project_id TEXT,
    registry_customer_id TEXT,
    classification_source TEXT,
    classification_role TEXT,
    confidence_reason TEXT,
    confidence NUMERIC(5, 4) NOT NULL,
    reasoning TEXT NOT NULL,
    raw_response JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE auditor_folder_classifications
    ADD COLUMN IF NOT EXISTS initiative_type TEXT,
    ADD COLUMN IF NOT EXISTS root_category TEXT,
    ADD COLUMN IF NOT EXISTS customer_code TEXT,
    ADD COLUMN IF NOT EXISTS customer_name TEXT,
    ADD COLUMN IF NOT EXISTS stage TEXT,
    ADD COLUMN IF NOT EXISTS is_intentional_empty BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS template_status TEXT,
    ADD COLUMN IF NOT EXISTS matched_rule TEXT,
    ADD COLUMN IF NOT EXISTS registry_project_id TEXT,
    ADD COLUMN IF NOT EXISTS registry_customer_id TEXT,
    ADD COLUMN IF NOT EXISTS classification_source TEXT,
    ADD COLUMN IF NOT EXISTS classification_role TEXT,
    ADD COLUMN IF NOT EXISTS confidence_reason TEXT;

CREATE INDEX IF NOT EXISTS idx_auditor_classifications_folder_signature
    ON auditor_folder_classifications (folder_id, content_signature, created_at DESC);

CREATE TABLE IF NOT EXISTS auditor_findings (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES auditor_runs(id),
    folder_id BIGINT REFERENCES auditor_folders(id) ON DELETE SET NULL,
    folder_path TEXT NOT NULL,
    issue_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    confidence NUMERIC(5, 4) NOT NULL,
    suggested_action TEXT NOT NULL,
    suggested_destination TEXT,
    reasoning TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    reviewer_reason TEXT,
    raw_response JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_auditor_findings_status
    ON auditor_findings (status, confidence DESC, severity);

CREATE TABLE IF NOT EXISTS auditor_customers (
    id BIGSERIAL PRIMARY KEY,
    customer_code TEXT NOT NULL UNIQUE,
    full_name TEXT,
    industry TEXT,
    country TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    source TEXT NOT NULL DEFAULT 'yaml',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS auditor_projects (
    id BIGSERIAL PRIMARY KEY,
    project_id TEXT NOT NULL UNIQUE,
    customer_code TEXT,
    customer_name TEXT,
    initiative_name TEXT,
    status TEXT,
    year INTEGER,
    folder_path TEXT NOT NULL,
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    source TEXT NOT NULL DEFAULT 'yaml',
    last_updated DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Librarian training: the project registry is consulted by the Placement
-- Engine, so it needs the archetype and the canonical destination root.
ALTER TABLE auditor_projects
    ADD COLUMN IF NOT EXISTS initiative_type TEXT,
    ADD COLUMN IF NOT EXISTS canonical_path TEXT;

CREATE TABLE IF NOT EXISTS auditor_decisions (
    id BIGSERIAL PRIMARY KEY,
    finding_id BIGINT REFERENCES auditor_findings(id) ON DELETE SET NULL,
    decision TEXT NOT NULL,
    decision_note TEXT,
    issue_type TEXT,
    folder_path TEXT,
    pattern_key TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS auditor_recommendation_patterns (
    id BIGSERIAL PRIMARY KEY,
    pattern_key TEXT NOT NULL UNIQUE,
    issue_type TEXT NOT NULL,
    folder_pattern TEXT,
    decision TEXT NOT NULL,
    rationale TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Asset registry: track knowledge rather than folders. One row per distinct
-- knowledge asset (identified by content hash, or normalized name for files
-- that were not hashed). Reuse counts and scores feed asset-centric findings
-- and the report leaderboard.
CREATE TABLE IF NOT EXISTS auditor_assets (
    id BIGSERIAL PRIMARY KEY,
    asset_key TEXT NOT NULL UNIQUE,
    asset_name TEXT NOT NULL,
    file_hash TEXT,
    file_type TEXT NOT NULL DEFAULT 'other',
    size_bytes BIGINT NOT NULL DEFAULT 0,
    copy_count INTEGER NOT NULL DEFAULT 1,
    paths JSONB NOT NULL DEFAULT '[]'::jsonb,
    customer_count INTEGER NOT NULL DEFAULT 0,
    customers JSONB NOT NULL DEFAULT '[]'::jsonb,
    project_count INTEGER NOT NULL DEFAULT 0,
    projects JSONB NOT NULL DEFAULT '[]'::jsonb,
    root_count INTEGER NOT NULL DEFAULT 1,
    reuse_score INTEGER NOT NULL DEFAULT 0,
    canonical_location TEXT,
    in_resources BOOLEAN NOT NULL DEFAULT FALSE,
    first_seen_run_id BIGINT REFERENCES auditor_runs(id),
    last_seen_run_id BIGINT REFERENCES auditor_runs(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Asset families group working-set derivations (Page6/Page8/V3 of the same
-- logical asset) under one family_key so the Librarian reasons about the
-- family, not each variant.
ALTER TABLE auditor_assets
    ADD COLUMN IF NOT EXISTS family_key TEXT;

CREATE INDEX IF NOT EXISTS idx_auditor_assets_reuse
    ON auditor_assets (reuse_score DESC);
CREATE INDEX IF NOT EXISTS idx_auditor_assets_hash
    ON auditor_assets (file_hash) WHERE file_hash IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_auditor_assets_family
    ON auditor_assets (family_key) WHERE family_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS auditor_scores (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES auditor_runs(id),
    folder_id BIGINT NOT NULL REFERENCES auditor_folders(id) ON DELETE CASCADE,
    naming_consistency INTEGER NOT NULL,
    duplicate_risk INTEGER NOT NULL,
    placement_confidence INTEGER NOT NULL,
    structure_clarity INTEGER NOT NULL,
    rules_compliance INTEGER NOT NULL,
    total_score INTEGER NOT NULL,
    explanation TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, folder_id)
);

-- =====================================================================
-- Librarian training subsystem (Placement Intelligence Engine)
-- =====================================================================

-- Placement patterns: learned "files like X live under destination Y" rules
-- extracted from the existing repository (the ground-truth training data).
-- One row per observed (destination, file_kind) combination, with the
-- contextual signals and how many placed files support it.
CREATE TABLE IF NOT EXISTS auditor_placement_patterns (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT REFERENCES auditor_runs(id) ON DELETE CASCADE,
    pattern_key TEXT NOT NULL,
    destination_path TEXT NOT NULL,
    customer_code TEXT,
    initiative_type TEXT,
    stage TEXT,
    file_kind TEXT,
    name_signals JSONB NOT NULL DEFAULT '[]'::jsonb,
    support_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, pattern_key)
);

CREATE INDEX IF NOT EXISTS idx_placement_patterns_keys
    ON auditor_placement_patterns (customer_code, initiative_type, stage, file_kind);

-- Placement simulations: blind predictions on already-placed files used to
-- measure Librarian readiness (placement accuracy).
CREATE TABLE IF NOT EXISTS auditor_placement_simulations (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT REFERENCES auditor_runs(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    actual_path TEXT NOT NULL,
    predicted_path TEXT,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
    match_level TEXT NOT NULL DEFAULT 'wrong',
    method TEXT,
    rationale TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_placement_sim_run
    ON auditor_placement_simulations (run_id, match_level);

-- Placement plans: predicted destinations for files currently sitting in the
-- inbox / staging folders. Phase 1 only PLANS (status 'planned'); the Phase 2
-- executor will consume these rows to move files.
CREATE TABLE IF NOT EXISTS auditor_placement_plans (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT REFERENCES auditor_runs(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    predicted_path TEXT,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
    confidence_band TEXT NOT NULL DEFAULT 'needs_review',
    method TEXT,
    rationale TEXT,
    status TEXT NOT NULL DEFAULT 'planned',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_placement_plans_run
    ON auditor_placement_plans (run_id, confidence_band);
