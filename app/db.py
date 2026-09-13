import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.config import settings


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return str(uuid4())


@contextmanager
def connection():
    path = Path(settings.database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS learning_goals (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                current_level TEXT NOT NULL,
                desired_outcome TEXT NOT NULL,
                deadline TEXT NOT NULL,
                weekly_hours INTEGER NOT NULL CHECK (weekly_hours BETWEEN 1 AND 80),
                learning_preferences TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'ACTIVE',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS plan_versions (
                id TEXT PRIMARY KEY,
                goal_id TEXT NOT NULL REFERENCES learning_goals(id) ON DELETE CASCADE,
                version INTEGER NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('DRAFT', 'ACTIVE', 'ARCHIVED')),
                rationale TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(goal_id, version)
            );

            CREATE TABLE IF NOT EXISTS learning_tasks (
                id TEXT PRIMARY KEY,
                plan_version_id TEXT NOT NULL REFERENCES plan_versions(id) ON DELETE CASCADE,
                week_number INTEGER NOT NULL CHECK (week_number BETWEEN 1 AND 4),
                position INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                estimated_minutes INTEGER NOT NULL CHECK (estimated_minutes > 0),
                deliverable TEXT NOT NULL,
                acceptance_criteria TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'TODO'
                    CHECK (status IN ('TODO','IN_PROGRESS','SUBMITTED','PASSED','NEEDS_REVISION')),
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS task_attempts (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL REFERENCES learning_tasks(id) ON DELETE CASCADE,
                evidence_text TEXT NOT NULL,
                repository_url TEXT,
                actual_minutes INTEGER NOT NULL CHECK (actual_minutes > 0),
                status TEXT NOT NULL DEFAULT 'SUBMITTED',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS assessments (
                id TEXT PRIMARY KEY,
                attempt_id TEXT NOT NULL UNIQUE REFERENCES task_attempts(id) ON DELETE CASCADE,
                result TEXT NOT NULL CHECK (result IN ('PASSED','NEEDS_REVISION')),
                score INTEGER NOT NULL CHECK (score BETWEEN 0 AND 100),
                feedback TEXT NOT NULL,
                criterion_results TEXT NOT NULL,
                evaluator TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS weekly_reviews (
                id TEXT PRIMARY KEY,
                goal_id TEXT NOT NULL REFERENCES learning_goals(id) ON DELETE CASCADE,
                week_number INTEGER NOT NULL,
                summary TEXT NOT NULL,
                proposed_changes TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING'
                    CHECK (status IN ('PENDING','ACCEPTED','REJECTED')),
                created_plan_version_id TEXT REFERENCES plan_versions(id),
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS ai_runs (
                id TEXT PRIMARY KEY,
                run_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                status TEXT NOT NULL,
                model TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                latency_ms INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_plan_week
                ON learning_tasks(plan_version_id, week_number, position);
            CREATE INDEX IF NOT EXISTS idx_plan_goal_status
                ON plan_versions(goal_id, status);
            """
        )
