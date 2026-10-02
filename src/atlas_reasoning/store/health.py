"""Database health for Reasoning V3: reachable, migrated, untampered."""

from __future__ import annotations

from typing import Any

from atlas_reasoning.store.db import SCHEMA, Database, DatabaseError
from atlas_reasoning.store.migrate import applied_migrations, available_migrations, check_applied

REQUIRED_TABLES = ("reasoning_runs", "reasoning_cases", "reasoning_case_evidence", "reasoning_case_observations", "reasoning_work_items",
                   "reasoning_results", "reasoning_result_versions", "reasoning_evidence_links", "manager_notes", "manager_note_revisions",
                   "atlas_questions", "atlas_answers", "teachings", "teaching_revisions", "llm_calls", "memory_sync_log", "schema_migrations",
                   # Chat 2 (migrations 0100-0199)
                   "reasoning_result_diffs", "reasoning_lifecycle_transitions",
                   # Chat 3 (migrations 0200-0299)
                   "memory_injections", "atlas_question_asks", "engineering_review_flags",
                   # Phase 15 (migrations 0300-0399)
                   "reasoning_failed_candidates",
                   # Phase 17 (migrations 0500-0599)
                   "executive_briefs", "executive_brief_versions", "executive_brief_inputs", "executive_statement_refs", "executive_brief_runs")


def database_health(db: Database) -> dict[str, Any]:
    """``ok`` is true only when the database answers, every migration is applied unchanged and every required table exists."""
    report: dict[str, Any] = {"ok": False, "database": db.display_url, "schema": SCHEMA}
    try:
        with db.transaction() as conn:
            row = conn.execute("SELECT current_setting('server_version') AS version, now() AS now").fetchone() or {}
            report["server_version"], report["checked_at"] = row.get("version"), row["now"].isoformat() if row.get("now") else None
            tables = {r["table_name"] for r in conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = %s", (SCHEMA,))}
        migrations = available_migrations()
        applied = applied_migrations(db)
    except DatabaseError as error:
        report["error"] = str(error)
        return report
    except Exception as error:  # noqa: BLE001 - a health check reports every failure instead of raising
        report["error"] = f"{type(error).__name__}: {error}"
        return report
    report["applied"] = sorted(row["name"] for row in applied.values())
    report["pending"] = [migration.name for migration in migrations if migration.version not in applied]
    report["problems"] = check_applied(applied, migrations)
    report["missing_tables"] = [name for name in REQUIRED_TABLES if name not in tables]
    report["ok"] = not report["pending"] and not report["problems"] and not report["missing_tables"]
    return report
