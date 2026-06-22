from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, RowMapping
import yaml

from .config import AppConfig
from .models import (
    AuditFinding,
    FolderClassification,
    FolderRecord,
    FolderScore,
    KnowledgeAsset,
    ScanResult,
)


class AuditorDatabase:
    def __init__(self, config: AppConfig):
        self.config = config
        self.engine = create_engine(config.database.connection_string, future=True)

    def init_db(self) -> None:
        schema_path = self.config.base_dir / "schema.sql"
        sql = schema_path.read_text(encoding="utf-8")
        with self.engine.begin() as conn:
            conn.exec_driver_sql(sql)
        self.sync_registries_from_yaml()

    def sync_registries_from_yaml(self) -> None:
        rules_dir = self.config.base_dir / "auditor" / "rules"
        customer_registry_path = rules_dir / "customer_registry.yaml"
        project_registry_path = rules_dir / "project_registry.yaml"
        if customer_registry_path.exists():
            data = yaml.safe_load(customer_registry_path.read_text(encoding="utf-8")) or {}
            for code, customer in data.get("customers", {}).items():
                self.add_customer(
                    customer_code=code,
                    full_name=customer.get("full_name"),
                    industry=customer.get("industry"),
                    country=customer.get("country"),
                    metadata={key: value for key, value in customer.items() if key not in {"full_name", "industry", "country"}},
                    source="yaml",
                )
        if project_registry_path.exists():
            data = yaml.safe_load(project_registry_path.read_text(encoding="utf-8")) or {}
            for project in data.get("projects", []):
                self.add_project(
                    project_id=project["project_id"],
                    folder_path=project["folder_path"],
                    customer_code=project.get("customer_code"),
                    customer_name=project.get("customer_name"),
                    initiative_name=project.get("initiative_name"),
                    status=project.get("status"),
                    year=project.get("year"),
                    tags=project.get("tags", []),
                    initiative_type=project.get("initiative_type"),
                    canonical_path=project.get("canonical_path"),
                    metadata={
                        key: value
                        for key, value in project.items()
                        if key
                        not in {
                            "project_id",
                            "folder_path",
                            "customer_code",
                            "customer_name",
                            "initiative_name",
                            "status",
                            "year",
                            "tags",
                            "initiative_type",
                            "canonical_path",
                        }
                    },
                    source="yaml",
                )

    def create_run(self, run_type: str) -> int:
        with self.engine.begin() as conn:
            result = conn.execute(
                text(
                    """
                    INSERT INTO auditor_runs (run_type, config_path)
                    VALUES (:run_type, :config_path)
                    RETURNING id
                    """
                ),
                {"run_type": run_type, "config_path": str(self.config.config_path)},
            )
            return int(result.scalar_one())

    def finish_run(
        self,
        run_id: int,
        status: str = "completed",
        report_path: str | None = None,
        counts: dict[str, int] | None = None,
        error_message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        counts = counts or {}
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE auditor_runs
                    SET status = :status,
                        finished_at = NOW(),
                        report_path = COALESCE(:report_path, report_path),
                        total_folders = COALESCE(:total_folders, total_folders),
                        changed_folders = COALESCE(:changed_folders, changed_folders),
                        new_folders = COALESCE(:new_folders, new_folders),
                        removed_folders = COALESCE(:removed_folders, removed_folders),
                        total_findings = COALESCE(:total_findings, total_findings),
                        error_message = :error_message,
                        metadata = COALESCE(CAST(:metadata AS JSONB), metadata)
                    WHERE id = :run_id
                    """
                ),
                {
                    "run_id": run_id,
                    "status": status,
                    "report_path": report_path,
                    "total_folders": counts.get("total_folders"),
                    "changed_folders": counts.get("changed_folders"),
                    "new_folders": counts.get("new_folders"),
                    "removed_folders": counts.get("removed_folders"),
                    "total_findings": counts.get("total_findings"),
                    "error_message": error_message,
                    "metadata": json.dumps(metadata or {}),
                },
            )

    def upsert_scan_result(self, run_id: int, scan_result: ScanResult) -> dict[str, int]:
        active_before = self._active_folder_signatures()
        seen_keys: set[tuple[str, str]] = set()
        new_count = 0
        changed_count = 0

        with self.engine.begin() as conn:
            for folder in scan_result.folders:
                key = (folder.root_path, folder.path)
                seen_keys.add(key)
                previous = active_before.get(key)
                if previous is None:
                    new_count += 1
                elif previous != folder.content_signature:
                    changed_count += 1

                conn.execute(
                    text(
                        """
                        INSERT INTO auditor_folders (
                            root_path, path, absolute_path, parent_path, depth,
                            file_count, child_folder_count, total_size_bytes,
                            latest_modified_at, sample_filenames, file_extension_counts,
                            file_category_counts, metadata_signals, content_signature,
                            status, first_seen_run_id, last_seen_run_id, updated_at
                        )
                        VALUES (
                            :root_path, :path, :absolute_path, :parent_path, :depth,
                            :file_count, :child_folder_count, :total_size_bytes,
                            :latest_modified_at, CAST(:sample_filenames AS JSONB),
                            CAST(:file_extension_counts AS JSONB),
                            CAST(:file_category_counts AS JSONB),
                            CAST(:metadata_signals AS JSONB), :content_signature,
                            'active', :run_id, :run_id, NOW()
                        )
                        ON CONFLICT (root_path, path)
                        DO UPDATE SET
                            absolute_path = EXCLUDED.absolute_path,
                            parent_path = EXCLUDED.parent_path,
                            depth = EXCLUDED.depth,
                            file_count = EXCLUDED.file_count,
                            child_folder_count = EXCLUDED.child_folder_count,
                            total_size_bytes = EXCLUDED.total_size_bytes,
                            latest_modified_at = EXCLUDED.latest_modified_at,
                            sample_filenames = EXCLUDED.sample_filenames,
                            file_extension_counts = EXCLUDED.file_extension_counts,
                            file_category_counts = EXCLUDED.file_category_counts,
                            metadata_signals = EXCLUDED.metadata_signals,
                            content_signature = EXCLUDED.content_signature,
                            status = 'active',
                            last_seen_run_id = EXCLUDED.last_seen_run_id,
                            updated_at = NOW()
                        """
                    ),
                    {
                        **folder.model_dump(),
                        "sample_filenames": json.dumps(folder.sample_filenames),
                        "file_extension_counts": json.dumps(folder.file_extension_counts),
                        "file_category_counts": json.dumps(folder.file_category_counts),
                        "metadata_signals": json.dumps(folder.metadata_signals),
                        "run_id": run_id,
                    },
                )

            for file in scan_result.files:
                conn.execute(
                    text(
                        """
                        INSERT INTO auditor_files (
                            root_path, folder_path, path, absolute_path, extension,
                            size_bytes, modified_at, content_hash,
                            first_seen_run_id, last_seen_run_id, status
                        )
                        VALUES (
                            :root_path, :folder_path, :path, :absolute_path, :extension,
                            :size_bytes, :modified_at, :content_hash, :run_id, :run_id, 'active'
                        )
                        ON CONFLICT (root_path, path)
                        DO UPDATE SET
                            folder_path = EXCLUDED.folder_path,
                            absolute_path = EXCLUDED.absolute_path,
                            extension = EXCLUDED.extension,
                            size_bytes = EXCLUDED.size_bytes,
                            modified_at = EXCLUDED.modified_at,
                            content_hash = COALESCE(EXCLUDED.content_hash, auditor_files.content_hash),
                            last_seen_run_id = EXCLUDED.last_seen_run_id,
                            status = 'active'
                        """
                    ),
                    {**file.model_dump(), "run_id": run_id},
                )

            removed_result = conn.execute(
                text(
                    """
                    UPDATE auditor_folders
                    SET status = 'removed', updated_at = NOW()
                    WHERE status = 'active' AND last_seen_run_id != :run_id
                    """
                ),
                {"run_id": run_id},
            )
            conn.execute(
                text(
                    """
                    UPDATE auditor_files
                    SET status = 'removed'
                    WHERE status = 'active' AND last_seen_run_id != :run_id
                    """
                ),
                {"run_id": run_id},
            )

        return {
            "total_folders": len(scan_result.folders),
            "new_folders": new_count,
            "changed_folders": changed_count,
            "removed_folders": int(removed_result.rowcount or 0),
        }

    def folders_for_classification(self, limit: int | None, full: bool = False) -> list[FolderRecord]:
        clause = ""
        if not full:
            clause = """
            AND NOT EXISTS (
                SELECT 1
                FROM auditor_folder_classifications c
                WHERE c.folder_id = f.id
                  AND c.content_signature = f.content_signature
            )
            """
        query = f"""
            SELECT *
            FROM auditor_folders f
            WHERE f.status = 'active'
            {clause}
            ORDER BY f.depth ASC, f.path ASC
        """
        if limit is not None:
            query += " LIMIT :limit"

        with self.engine.begin() as conn:
            rows = conn.execute(text(query), {"limit": limit}).mappings().all()
        return [folder_record_from_row(row) for row in rows]

    def active_folders(self, limit: int | None = None) -> list[FolderRecord]:
        query = "SELECT * FROM auditor_folders WHERE status = 'active' ORDER BY depth ASC, path ASC"
        if limit is not None:
            query += " LIMIT :limit"
        with self.engine.begin() as conn:
            rows = conn.execute(text(query), {"limit": limit}).mappings().all()
        return [folder_record_from_row(row) for row in rows]

    def latest_classifications(self) -> dict[int, FolderClassification]:
        with self.engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT DISTINCT ON (folder_id)
                        folder_id, folder_type, customer, initiative,
                        initiative_type,
                        root_category, customer_code, customer_name, stage,
                        is_intentional_empty, template_status, matched_rule,
                        registry_project_id, registry_customer_id,
                        classification_source, classification_role, confidence_reason,
                        confidence, reasoning
                    FROM auditor_folder_classifications
                    ORDER BY folder_id, created_at DESC
                    """
                )
            ).mappings().all()
        return {
            int(row["folder_id"]): FolderClassification(
                folder_type=row["folder_type"],
                customer=row["customer"],
                initiative=row["initiative"],
                initiative_type=row["initiative_type"],
                root_category=row["root_category"],
                customer_code=row["customer_code"],
                customer_name=row["customer_name"],
                stage=row["stage"],
                is_intentional_empty=bool(row["is_intentional_empty"]),
                template_status=row["template_status"],
                matched_rule=row["matched_rule"],
                registry_project_id=row["registry_project_id"],
                registry_customer_id=row["registry_customer_id"],
                classification_source=row["classification_source"],
                classification_role=row["classification_role"],
                confidence_reason=row["confidence_reason"],
                confidence=float(row["confidence"]),
                reasoning=row["reasoning"],
            )
            for row in rows
        }

    def save_classification(
        self,
        run_id: int,
        folder: FolderRecord,
        classification: FolderClassification,
        raw_response: dict[str, Any] | None = None,
    ) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO auditor_folder_classifications (
                        folder_id, run_id, content_signature, folder_type,
                        customer, initiative, initiative_type, root_category, customer_code,
                        customer_name, stage, is_intentional_empty, template_status,
                        matched_rule, registry_project_id, registry_customer_id,
                        classification_source, classification_role, confidence_reason,
                        confidence, reasoning, raw_response
                    )
                    VALUES (
                        :folder_id, :run_id, :content_signature, :folder_type,
                        :customer, :initiative, :initiative_type, :root_category, :customer_code,
                        :customer_name, :stage, :is_intentional_empty,
                        :template_status, :matched_rule, :registry_project_id,
                        :registry_customer_id, :classification_source,
                        :classification_role, :confidence_reason, :confidence, :reasoning,
                        CAST(:raw_response AS JSONB)
                    )
                    """
                ),
                {
                    "folder_id": folder.id,
                    "run_id": run_id,
                    "content_signature": folder.content_signature,
                    **classification.model_dump(),
                    "raw_response": json.dumps(raw_response or classification.model_dump()),
                },
            )

    def save_findings(self, run_id: int, findings: list[AuditFinding]) -> int:
        folders = {folder.path: folder.id for folder in self.active_folders()}
        with self.engine.begin() as conn:
            for finding in findings:
                conn.execute(
                    text(
                        """
                        INSERT INTO auditor_findings (
                            run_id, folder_id, folder_path, issue_type, severity,
                            confidence, suggested_action, suggested_destination,
                            reasoning, raw_response
                        )
                        VALUES (
                            :run_id, :folder_id, :folder_path, :issue_type, :severity,
                            :confidence, :suggested_action, :suggested_destination,
                            :reasoning, CAST(:raw_response AS JSONB)
                        )
                        """
                    ),
                    {
                        "run_id": run_id,
                        "folder_id": folders.get(finding.folder_path),
                        **finding.model_dump(),
                        "raw_response": json.dumps(finding.model_dump()),
                    },
                )
        return len(findings)

    def findings_for_run(self, run_id: int) -> list[dict[str, Any]]:
        with self.engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT *
                    FROM auditor_findings
                    WHERE run_id = :run_id
                    ORDER BY confidence DESC, severity DESC, folder_path ASC
                    """
                ),
                {"run_id": run_id},
            ).mappings().all()
        return [dict(row) for row in rows]

    def open_findings(self) -> list[dict[str, Any]]:
        with self.engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT *
                    FROM auditor_findings
                    WHERE status = 'open'
                    ORDER BY confidence DESC, severity DESC, created_at DESC
                    """
                )
            ).mappings().all()
        return [dict(row) for row in rows]

    def rejected_patterns(self) -> set[tuple[str, str]]:
        with self.engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT issue_type, folder_pattern
                    FROM auditor_recommendation_patterns
                    WHERE decision = 'rejected'
                    """
                )
            ).mappings().all()
        return {(row["issue_type"], row["folder_pattern"]) for row in rows}

    def review_finding(self, finding_id: int, status: str, reason: str | None = None) -> bool:
        with self.engine.begin() as conn:
            finding = conn.execute(
                text("SELECT id, issue_type, folder_path FROM auditor_findings WHERE id = :finding_id"),
                {"finding_id": finding_id},
            ).mappings().first()
            result = conn.execute(
                text(
                    """
                    UPDATE auditor_findings
                    SET status = :status,
                        reviewer_reason = :reason,
                        reviewed_at = NOW()
                    WHERE id = :finding_id
                    """
                ),
                {"finding_id": finding_id, "status": status, "reason": reason},
            )
            if finding and result.rowcount:
                pattern_key = f"{status}:{finding['issue_type']}:{finding['folder_path']}"
                conn.execute(
                    text(
                        """
                        INSERT INTO auditor_decisions (
                            finding_id, decision, decision_note, issue_type, folder_path, pattern_key
                        )
                        VALUES (
                            :finding_id, :decision, :decision_note, :issue_type, :folder_path, :pattern_key
                        )
                        """
                    ),
                    {
                        "finding_id": finding_id,
                        "decision": status,
                        "decision_note": reason,
                        "issue_type": finding["issue_type"],
                        "folder_path": finding["folder_path"],
                        "pattern_key": pattern_key,
                    },
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO auditor_recommendation_patterns (
                            pattern_key, issue_type, folder_pattern, decision, rationale
                        )
                        VALUES (
                            :pattern_key, :issue_type, :folder_pattern, :decision, :rationale
                        )
                        ON CONFLICT (pattern_key)
                        DO UPDATE SET
                            decision = EXCLUDED.decision,
                            rationale = EXCLUDED.rationale,
                            updated_at = NOW()
                        """
                    ),
                    {
                        "pattern_key": pattern_key,
                        "issue_type": finding["issue_type"],
                        "folder_pattern": finding["folder_path"],
                        "decision": status,
                        "rationale": reason,
                    },
                )
        return bool(result.rowcount)

    def add_customer(
        self,
        customer_code: str,
        full_name: str | None = None,
        industry: str | None = None,
        country: str | None = None,
        metadata: dict[str, Any] | None = None,
        source: str = "cli",
    ) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO auditor_customers (
                        customer_code, full_name, industry, country, metadata, source, updated_at
                    )
                    VALUES (
                        :customer_code, :full_name, :industry, :country,
                        CAST(:metadata AS JSONB), :source, NOW()
                    )
                    ON CONFLICT (customer_code)
                    DO UPDATE SET
                        full_name = COALESCE(EXCLUDED.full_name, auditor_customers.full_name),
                        industry = COALESCE(EXCLUDED.industry, auditor_customers.industry),
                        country = COALESCE(EXCLUDED.country, auditor_customers.country),
                        metadata = auditor_customers.metadata || EXCLUDED.metadata,
                        source = EXCLUDED.source,
                        updated_at = NOW()
                    """
                ),
                {
                    "customer_code": customer_code,
                    "full_name": full_name,
                    "industry": industry,
                    "country": country,
                    "metadata": json.dumps(metadata or {}),
                    "source": source,
                },
            )

    def add_project(
        self,
        project_id: str,
        folder_path: str,
        customer_code: str | None = None,
        customer_name: str | None = None,
        initiative_name: str | None = None,
        status: str | None = None,
        year: int | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        source: str = "cli",
        initiative_type: str | None = None,
        canonical_path: str | None = None,
    ) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO auditor_projects (
                        project_id, customer_code, customer_name, initiative_name,
                        status, year, folder_path, tags, metadata, source,
                        initiative_type, canonical_path, last_updated, updated_at
                    )
                    VALUES (
                        :project_id, :customer_code, :customer_name, :initiative_name,
                        :status, :year, :folder_path, CAST(:tags AS JSONB),
                        CAST(:metadata AS JSONB), :source,
                        :initiative_type, :canonical_path, CURRENT_DATE, NOW()
                    )
                    ON CONFLICT (project_id)
                    DO UPDATE SET
                        customer_code = COALESCE(EXCLUDED.customer_code, auditor_projects.customer_code),
                        customer_name = COALESCE(EXCLUDED.customer_name, auditor_projects.customer_name),
                        initiative_name = COALESCE(EXCLUDED.initiative_name, auditor_projects.initiative_name),
                        status = COALESCE(EXCLUDED.status, auditor_projects.status),
                        year = COALESCE(EXCLUDED.year, auditor_projects.year),
                        folder_path = EXCLUDED.folder_path,
                        tags = EXCLUDED.tags,
                        metadata = auditor_projects.metadata || EXCLUDED.metadata,
                        source = EXCLUDED.source,
                        initiative_type = COALESCE(EXCLUDED.initiative_type, auditor_projects.initiative_type),
                        canonical_path = COALESCE(EXCLUDED.canonical_path, auditor_projects.canonical_path),
                        last_updated = CURRENT_DATE,
                        updated_at = NOW()
                    """
                ),
                {
                    "project_id": project_id,
                    "customer_code": customer_code,
                    "customer_name": customer_name,
                    "initiative_name": initiative_name,
                    "status": status,
                    "year": year,
                    "folder_path": folder_path,
                    "tags": json.dumps(tags or []),
                    "metadata": json.dumps(metadata or {}),
                    "source": source,
                    "initiative_type": initiative_type,
                    "canonical_path": canonical_path,
                },
            )

    def save_scores(self, run_id: int, scores: list[FolderScore]) -> None:
        with self.engine.begin() as conn:
            for score in scores:
                conn.execute(
                    text(
                        """
                        INSERT INTO auditor_scores (
                            run_id, folder_id, naming_consistency, duplicate_risk,
                            placement_confidence, structure_clarity, rules_compliance,
                            total_score, explanation
                        )
                        VALUES (
                            :run_id, :folder_id, :naming_consistency, :duplicate_risk,
                            :placement_confidence, :structure_clarity, :rules_compliance,
                            :total_score, :explanation
                        )
                        ON CONFLICT (run_id, folder_id)
                        DO UPDATE SET
                            naming_consistency = EXCLUDED.naming_consistency,
                            duplicate_risk = EXCLUDED.duplicate_risk,
                            placement_confidence = EXCLUDED.placement_confidence,
                            structure_clarity = EXCLUDED.structure_clarity,
                            rules_compliance = EXCLUDED.rules_compliance,
                            total_score = EXCLUDED.total_score,
                            explanation = EXCLUDED.explanation
                        """
                    ),
                    {"run_id": run_id, **score.model_dump()},
                )

    def scores_for_run(self, run_id: int) -> list[dict[str, Any]]:
        with self.engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT s.*, f.path AS folder_path
                    FROM auditor_scores s
                    JOIN auditor_folders f ON f.id = s.folder_id
                    WHERE s.run_id = :run_id
                    ORDER BY s.total_score ASC, f.path ASC
                    """
                ),
                {"run_id": run_id},
            ).mappings().all()
        return [dict(row) for row in rows]

    def findings_status_summary(self) -> dict[str, int]:
        """Counts of findings by status, plus open counts by severity."""
        with self.engine.begin() as conn:
            status_rows = conn.execute(
                text("SELECT status, COUNT(*) AS n FROM auditor_findings GROUP BY status")
            ).mappings().all()
            severity_rows = conn.execute(
                text(
                    """
                    SELECT severity, COUNT(*) AS n
                    FROM auditor_findings
                    WHERE status = 'open'
                    GROUP BY severity
                    """
                )
            ).mappings().all()
        summary = {f"status_{row['status']}": int(row["n"]) for row in status_rows}
        summary.update({f"open_{row['severity']}": int(row["n"]) for row in severity_rows})
        return summary

    def duplicate_file_groups(self, min_size_bytes: int = 1) -> list[dict[str, Any]]:
        """Groups of active files sharing the same content hash."""
        with self.engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT content_hash,
                           COUNT(*) AS copy_count,
                           MAX(size_bytes) AS size_bytes,
                           ARRAY_AGG(path ORDER BY path) AS paths,
                           ARRAY_AGG(DISTINCT folder_path) AS folder_paths
                    FROM auditor_files
                    WHERE status = 'active'
                      AND content_hash IS NOT NULL
                      AND size_bytes >= :min_size
                    GROUP BY content_hash
                    HAVING COUNT(*) > 1
                    ORDER BY MAX(size_bytes) DESC
                    """
                ),
                {"min_size": min_size_bytes},
            ).mappings().all()
        return [dict(row) for row in rows]

    def active_files(self, min_size_bytes: int = 0) -> list[dict[str, Any]]:
        """All active files with hash/extension metadata for asset building."""
        with self.engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT root_path, folder_path, path, extension,
                           size_bytes, content_hash
                    FROM auditor_files
                    WHERE status = 'active'
                      AND size_bytes >= :min_size
                    ORDER BY path
                    """
                ),
                {"min_size": min_size_bytes},
            ).mappings().all()
        return [dict(row) for row in rows]

    def replace_assets(self, run_id: int, assets: list[KnowledgeAsset]) -> int:
        """Upsert the asset registry from a fresh scan.

        Assets not seen in this refresh are removed (the registry mirrors the
        current state of the vault, history lives in auditor_runs).
        """
        with self.engine.begin() as conn:
            for asset in assets:
                conn.execute(
                    text(
                        """
                        INSERT INTO auditor_assets (
                            asset_key, asset_name, file_hash, file_type, size_bytes,
                            copy_count, paths, customer_count, customers,
                            project_count, projects, root_count, reuse_score,
                            canonical_location, in_resources, family_key,
                            first_seen_run_id, last_seen_run_id, updated_at
                        )
                        VALUES (
                            :asset_key, :asset_name, :file_hash, :file_type, :size_bytes,
                            :copy_count, CAST(:paths AS JSONB), :customer_count,
                            CAST(:customers AS JSONB), :project_count,
                            CAST(:projects AS JSONB), :root_count, :reuse_score,
                            :canonical_location, :in_resources, :family_key,
                            :run_id, :run_id, NOW()
                        )
                        ON CONFLICT (asset_key)
                        DO UPDATE SET
                            asset_name = EXCLUDED.asset_name,
                            file_hash = EXCLUDED.file_hash,
                            file_type = EXCLUDED.file_type,
                            size_bytes = EXCLUDED.size_bytes,
                            copy_count = EXCLUDED.copy_count,
                            paths = EXCLUDED.paths,
                            customer_count = EXCLUDED.customer_count,
                            customers = EXCLUDED.customers,
                            project_count = EXCLUDED.project_count,
                            projects = EXCLUDED.projects,
                            root_count = EXCLUDED.root_count,
                            reuse_score = EXCLUDED.reuse_score,
                            canonical_location = EXCLUDED.canonical_location,
                            in_resources = EXCLUDED.in_resources,
                            family_key = EXCLUDED.family_key,
                            last_seen_run_id = EXCLUDED.last_seen_run_id,
                            updated_at = NOW()
                        """
                    ),
                    {
                        **asset.model_dump(),
                        "paths": json.dumps(asset.paths),
                        "customers": json.dumps(asset.customers),
                        "projects": json.dumps(asset.projects),
                        "run_id": run_id,
                    },
                )
            conn.execute(
                text("DELETE FROM auditor_assets WHERE last_seen_run_id != :run_id"),
                {"run_id": run_id},
            )
        return len(assets)

    def top_assets(self, limit: int = 20, min_reuse_score: int = 0) -> list[dict[str, Any]]:
        with self.engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT *
                    FROM auditor_assets
                    WHERE reuse_score >= :min_score
                    ORDER BY reuse_score DESC, copy_count DESC, asset_name ASC
                    LIMIT :limit
                    """
                ),
                {"limit": limit, "min_score": min_reuse_score},
            ).mappings().all()
        return [_asset_row_to_dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Placement Intelligence Engine (Librarian training)
    # ------------------------------------------------------------------

    def placed_files_with_context(self, min_size_bytes: int = 0) -> list[dict[str, Any]]:
        """Active files joined to their folder's latest classification.

        This is the ground-truth training set: each row is a file the user has
        already placed, annotated with the customer/initiative/stage context of
        its folder. Used both for pattern extraction and placement simulation.
        """
        with self.engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT
                        fi.root_path,
                        fi.folder_path,
                        fi.path,
                        fi.extension,
                        fi.size_bytes,
                        fi.content_hash,
                        c.folder_type,
                        c.customer_code,
                        c.customer_name,
                        c.initiative,
                        c.initiative_type,
                        c.stage,
                        c.root_category
                    FROM auditor_files fi
                    JOIN auditor_folders fo
                      ON fo.root_path = fi.root_path AND fo.path = fi.folder_path
                    LEFT JOIN LATERAL (
                        SELECT *
                        FROM auditor_folder_classifications c
                        WHERE c.folder_id = fo.id
                        ORDER BY c.created_at DESC
                        LIMIT 1
                    ) c ON TRUE
                    WHERE fi.status = 'active'
                      AND fo.status = 'active'
                      AND fi.size_bytes >= :min_size
                    ORDER BY fi.path
                    """
                ),
                {"min_size": min_size_bytes},
            ).mappings().all()
        return [dict(row) for row in rows]

    def projects_registry(self) -> list[dict[str, Any]]:
        """All known projects, for the placement engine to consult."""
        with self.engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT project_id, customer_code, customer_name, initiative_name,
                           initiative_type, status, year, folder_path, canonical_path
                    FROM auditor_projects
                    """
                )
            ).mappings().all()
        return [dict(row) for row in rows]

    def replace_placement_patterns(
        self, run_id: int, patterns: list[dict[str, Any]]
    ) -> int:
        """Replace this run's learned placement patterns."""
        with self.engine.begin() as conn:
            conn.execute(
                text("DELETE FROM auditor_placement_patterns WHERE run_id = :run_id"),
                {"run_id": run_id},
            )
            for p in patterns:
                conn.execute(
                    text(
                        """
                        INSERT INTO auditor_placement_patterns (
                            run_id, pattern_key, destination_path, customer_code,
                            initiative_type, stage, file_kind, name_signals, support_count
                        )
                        VALUES (
                            :run_id, :pattern_key, :destination_path, :customer_code,
                            :initiative_type, :stage, :file_kind,
                            CAST(:name_signals AS JSONB), :support_count
                        )
                        ON CONFLICT (run_id, pattern_key) DO UPDATE SET
                            destination_path = EXCLUDED.destination_path,
                            support_count = EXCLUDED.support_count,
                            name_signals = EXCLUDED.name_signals
                        """
                    ),
                    {
                        "run_id": run_id,
                        "pattern_key": p["pattern_key"],
                        "destination_path": p["destination_path"],
                        "customer_code": p.get("customer_code"),
                        "initiative_type": p.get("initiative_type"),
                        "stage": p.get("stage"),
                        "file_kind": p.get("file_kind"),
                        "name_signals": json.dumps(p.get("name_signals", [])),
                        "support_count": p.get("support_count", 0),
                    },
                )
        return len(patterns)

    def save_placement_simulations(
        self, run_id: int, rows: list[dict[str, Any]]
    ) -> int:
        with self.engine.begin() as conn:
            for r in rows:
                conn.execute(
                    text(
                        """
                        INSERT INTO auditor_placement_simulations (
                            run_id, file_path, actual_path, predicted_path,
                            confidence, match_level, method, rationale
                        )
                        VALUES (
                            :run_id, :file_path, :actual_path, :predicted_path,
                            :confidence, :match_level, :method, :rationale
                        )
                        """
                    ),
                    {"run_id": run_id, **r},
                )
        return len(rows)

    def save_placement_plans(self, run_id: int, rows: list[dict[str, Any]]) -> int:
        with self.engine.begin() as conn:
            for r in rows:
                conn.execute(
                    text(
                        """
                        INSERT INTO auditor_placement_plans (
                            run_id, file_path, predicted_path, confidence,
                            confidence_band, method, rationale, status
                        )
                        VALUES (
                            :run_id, :file_path, :predicted_path, :confidence,
                            :confidence_band, :method, :rationale, 'planned'
                        )
                        """
                    ),
                    {"run_id": run_id, **r},
                )
        return len(rows)

    def latest_run_id(self) -> int | None:
        with self.engine.begin() as conn:
            return conn.execute(
                text("SELECT id FROM auditor_runs ORDER BY started_at DESC LIMIT 1")
            ).scalar_one_or_none()

    def _active_folder_signatures(self) -> dict[tuple[str, str], str]:
        with self.engine.begin() as conn:
            rows = conn.execute(
                text("SELECT root_path, path, content_signature FROM auditor_folders WHERE status = 'active'")
            ).mappings().all()
        return {(row["root_path"], row["path"]): row["content_signature"] for row in rows}


def _asset_row_to_dict(row: RowMapping) -> dict[str, Any]:
    record = dict(row)
    for key in ("paths", "customers", "projects"):
        value = record.get(key)
        if isinstance(value, str):
            record[key] = json.loads(value)
    return record


def folder_record_from_row(row: RowMapping) -> FolderRecord:
    sample_filenames = row["sample_filenames"]
    if isinstance(sample_filenames, str):
        sample_filenames = json.loads(sample_filenames)
    file_extension_counts = row.get("file_extension_counts") or {}
    if isinstance(file_extension_counts, str):
        file_extension_counts = json.loads(file_extension_counts)
    file_category_counts = row.get("file_category_counts") or {}
    if isinstance(file_category_counts, str):
        file_category_counts = json.loads(file_category_counts)
    metadata_signals = row.get("metadata_signals") or {}
    if isinstance(metadata_signals, str):
        metadata_signals = json.loads(metadata_signals)
    return FolderRecord(
        id=int(row["id"]),
        root_path=row["root_path"],
        path=row["path"],
        absolute_path=row["absolute_path"],
        parent_path=row["parent_path"],
        depth=int(row["depth"]),
        file_count=int(row["file_count"]),
        child_folder_count=int(row["child_folder_count"]),
        total_size_bytes=int(row["total_size_bytes"]),
        latest_modified_at=row["latest_modified_at"],
        sample_filenames=sample_filenames or [],
        file_extension_counts=file_extension_counts,
        file_category_counts=file_category_counts,
        metadata_signals=metadata_signals,
        content_signature=row["content_signature"],
    )


def create_database(config: AppConfig) -> AuditorDatabase:
    return AuditorDatabase(config)
