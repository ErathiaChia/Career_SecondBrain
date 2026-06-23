"""Guarded reset entry point for Era Vault index data.

Run from ``era_indexer``:

    python -m truncate_all_career_history --confirm TRUNCATE_ERA_VAULT_DATA
"""
from __future__ import annotations

import argparse
import json

from career_history import config, db, envfile


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Truncate Era Vault indexed data while preserving schema, indexes, "
            "pgvector, and schema_migrations."
        )
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config.yaml. Defaults to ./config.yaml.",
    )
    parser.add_argument(
        "--expected-database",
        default="era_vault",
        help="Refuse to run unless current_database() matches this value.",
    )
    parser.add_argument(
        "--confirm",
        required=True,
        help="Must be exactly TRUNCATE_ERA_VAULT_DATA.",
    )
    args = parser.parse_args()

    envfile.load()
    config.load(args.config)
    result = db.truncate_index_data(
        confirm=args.confirm,
        expected_database=args.expected_database,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
