"""Exercise the frozen Alembic chain, never runtime init_db/create_all."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest
import sqlalchemy as sa


ROOT = Path(__file__).resolve().parents[1]


def migrate(path, direction="upgrade", revision="head"):
    result = subprocess.run(
        [sys.executable, "-m", "alembic", direction, revision], cwd=ROOT,
        env={**os.environ, "DATABASE_URL": f"sqlite:///{path}"},
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def seed(path):
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("""INSERT INTO learning_goals
            (id,user_id,title,current_level,desired_outcome,deadline,weekly_hours,created_at)
            VALUES ('goal','00000000-0000-0000-0000-000000000001','Goal','beginner','demo','2030-01-01',5,'2026-01-01')""")
        conn.execute("""INSERT INTO ingestion_jobs
            (id,goal_id,status,items_found,recommendations_created,error,created_at)
            VALUES ('legacy','goal','FAILED',7,2,'preserve me','2026-01-01')""")
        conn.execute("""INSERT INTO ai_runs
            (id,run_type,entity_id,status,model,prompt_version,created_at)
            VALUES ('old-ai','TEACHING','task','SUCCEEDED','old-model','v1','2026-01-01')""")


def check_head(path):
    engine = sa.create_engine(f"sqlite:///{path}")
    try:
        inspector = sa.inspect(engine)
        columns = {c["name"]: c for c in inspector.get_columns("ingestion_jobs")}
        assert not columns["idempotency_key"]["nullable"]
        indexes = {i["name"]: i for i in inspector.get_indexes("ingestion_jobs")}
        assert indexes["uq_ingestion_goal_idempotency"]["unique"]
        assert any(f["referred_table"] == "learning_goals" for f in inspector.get_foreign_keys("ingestion_jobs"))
        assert {c["name"] for c in inspector.get_check_constraints("ingestion_jobs")} >= {
            "ck_ingestion_attempts", "ck_ingestion_status"}
        assert any("weekly_hours" in c["sqltext"] for c in inspector.get_check_constraints("learning_goals"))
        assert len(inspector.get_check_constraints("learning_tasks")) == 3
        assert any("status" in c["sqltext"] for c in inspector.get_check_constraints("teaching_sessions"))
        assert {i["name"] for i in inspector.get_indexes("ai_runs")} >= {
            "idx_ai_runs_correlation", "idx_ai_runs_user_created", "uq_ai_runs_attempt_id"}
        assert any(f["referred_table"] == "ai_logical_requests" for f in inspector.get_foreign_keys("ai_runs"))
        assert len(inspector.get_check_constraints("ai_runs")) == 4
    finally:
        engine.dispose()


def test_fresh_sqlite_complete_alembic_chain(tmp_path):
    path = tmp_path / "fresh.db"
    migrate(path)
    check_head(path)


@pytest.mark.parametrize("existing_nullable_key", [False, True])
def test_sqlite_history_constraints_and_roundtrip(tmp_path, existing_nullable_key):
    path = tmp_path / "historical.db"
    migrate(path, revision="20260914_0001")
    seed(path)
    if existing_nullable_key:
        # Exercise an interrupted/legacy add-column with NULLs and a pre-existing index.
        with sqlite3.connect(path) as conn:
            conn.execute("ALTER TABLE ingestion_jobs ADD COLUMN idempotency_key VARCHAR(100)")
            conn.execute("CREATE UNIQUE INDEX uq_ingestion_goal_idempotency ON ingestion_jobs(goal_id,idempotency_key)")
    migrate(path)
    check_head(path)
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("SELECT idempotency_key,items_found,recommendations_created,error FROM ingestion_jobs WHERE id='legacy'").fetchone() == ("legacy",7,2,"preserve me")
        assert conn.execute("SELECT model FROM ai_runs WHERE id='old-ai'").fetchone() == ("old-model",)
        statement = "INSERT INTO ingestion_jobs(id,goal_id,status,idempotency_key,attempt_count,created_at) VALUES (?,?,?,?,?,?)"
        conn.execute(statement, ("valid","goal","PENDING","valid-key",0,"2026-01-01"))
        for values in (
            ("null","goal","PENDING",None,0,"2026-01-01"),
            ("duplicate","goal","PENDING","valid-key",0,"2026-01-01"),
            ("bad-status","goal","INVALID","bad-status",0,"2026-01-01"),
            ("bad-attempt","goal","RUNNING","bad-attempt",4,"2026-01-01"),
            ("orphan","missing","PENDING","orphan",0,"2026-01-01"),
        ):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(statement, values)
    migrate(path, "downgrade", "20260915_0005")
    migrate(path)
    check_head(path)
    # Also exercise every earlier downgrade's batch constraint handling.
    migrate(path, "downgrade", "20260914_0001")
    migrate(path)
    check_head(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT items_found,error FROM ingestion_jobs WHERE id='legacy'").fetchone() == (7,"preserve me")
        assert conn.execute("SELECT model FROM ai_runs WHERE id='old-ai'").fetchone() == ("old-model",)
