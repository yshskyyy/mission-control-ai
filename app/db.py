import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, text

from app.config import settings


_engines = {}
LOCAL_USER_ID = "00000000-0000-0000-0000-000000000001"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def new_id() -> str:
    return str(uuid4())


def database_url() -> str:
    configured = getattr(settings, "database_url", None)
    if configured:
        return configured
    return f"sqlite:///{Path(settings.database_path)}"


class DbRow:
    def __init__(self, row):
        self._values = tuple(row)
        self._mapping = dict(row._mapping)

    def __getitem__(self, key):
        return self._values[key] if isinstance(key, int) else self._mapping[key]

    def __iter__(self):
        return iter(self._mapping)

    def __len__(self):
        return len(self._mapping)

    def keys(self):
        return self._mapping.keys()

    def get(self, key, default=None):
        return self._mapping.get(key, default)


class ResultAdapter:
    def __init__(self, result):
        self._result = result

    def fetchone(self):
        row = self._result.fetchone()
        return DbRow(row) if row is not None else None

    def fetchall(self):
        return [DbRow(row) for row in self._result.fetchall()]

    @property
    def rowcount(self):
        return self._result.rowcount


class ConnectionAdapter:
    def __init__(self, connection, dialect: str):
        self._connection = connection
        self._dialect = dialect

    def execute(self, statement: str, params=()):
        if self._dialect == "postgresql":
            statement = statement.replace("ORDER BY rowid", "ORDER BY created_at,id")
            statement = statement.replace(
                "MAX(knowledge_nodes.priority,excluded.priority)",
                "GREATEST(knowledge_nodes.priority,excluded.priority)",
            )
        if isinstance(params, dict):
            return ResultAdapter(self._connection.execute(text(statement), params))
        bindings = {}
        parts = statement.split("?")
        if len(parts) - 1 != len(params):
            raise ValueError("SQL placeholder count does not match parameters")
        converted = parts[0]
        for index, value in enumerate(params):
            key = f"p{index}"
            converted += f":{key}" + parts[index + 1]
            bindings[key] = value
        return ResultAdapter(self._connection.execute(text(converted), bindings))


def engine():
    url = database_url()
    if url not in _engines:
        options = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            path = Path(url.removeprefix("sqlite:///"))
            path.parent.mkdir(parents=True, exist_ok=True)
            options["connect_args"] = {"check_same_thread": False, "timeout": 5}
        _engines[url] = create_engine(url, **options)
    return _engines[url]


@contextmanager
def connection():
    current_engine = engine()
    with current_engine.begin() as conn:
        if current_engine.dialect.name == "sqlite":
            conn.exec_driver_sql("PRAGMA foreign_keys = ON")
            conn.exec_driver_sql("PRAGMA busy_timeout = 5000")
        yield ConnectionAdapter(conn, current_engine.dialect.name)


def init_db() -> None:
    if not database_url().startswith("sqlite"):
        with engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return
    path = Path(settings.database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                display_name TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS learning_goals (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'
                    REFERENCES users(id),
                title TEXT NOT NULL,
                current_level TEXT NOT NULL,
                desired_outcome TEXT NOT NULL,
                deadline TEXT NOT NULL,
                weekly_hours REAL NOT NULL CHECK (weekly_hours BETWEEN 0.5 AND 84),
                daily_hours REAL NOT NULL CHECK (daily_hours BETWEEN 0.5 AND 12),
                study_weekdays TEXT NOT NULL,
                timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
                budget_derivation TEXT NOT NULL,
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
                planning_risks TEXT NOT NULL DEFAULT '[]',
                adjustment_suggestions TEXT NOT NULL DEFAULT '[]',
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
                scheduled_date TEXT NOT NULL,
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
                created_at TEXT NOT NULL,
                user_id TEXT REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS teaching_sessions (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL REFERENCES learning_tasks(id) ON DELETE CASCADE,
                current_section_id TEXT,
                lesson_progress INTEGER NOT NULL DEFAULT 0,
                last_user_action TEXT NOT NULL DEFAULT 'INIT',
                retry_count INTEGER NOT NULL DEFAULT 0,
                mastery INTEGER NOT NULL DEFAULT 0 CHECK (mastery BETWEEN 0 AND 100),
                status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK
                    (status IN ('ACTIVE','WAITING_USER','WAITING_CHOICE','COMPLETED')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS teaching_messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES teaching_sessions(id) ON DELETE CASCADE,
                section_id TEXT,
                role TEXT NOT NULL CHECK (role IN ('USER','TEACHER')),
                message_type TEXT NOT NULL DEFAULT 'QUESTION',
                content TEXT NOT NULL,
                idempotency_key TEXT,
                teaching_strategy TEXT,
                provider TEXT,
                model TEXT,
                prompt_version TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS lesson_sections (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES teaching_sessions(id) ON DELETE CASCADE,
                position INTEGER NOT NULL,
                title TEXT NOT NULL,
                objective TEXT NOT NULL,
                content TEXT NOT NULL,
                example TEXT NOT NULL,
                check_question TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'LOCKED'
                    CHECK (status IN ('LOCKED','CURRENT','COMPLETED')),
                mastery INTEGER NOT NULL DEFAULT 0 CHECK (mastery BETWEEN 0 AND 100),
                created_at TEXT NOT NULL,
                UNIQUE(session_id,position)
            );

            CREATE TABLE IF NOT EXISTS quizzes (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES teaching_sessions(id) ON DELETE CASCADE,
                section_id TEXT NOT NULL REFERENCES lesson_sections(id) ON DELETE CASCADE,
                version INTEGER NOT NULL,
                question TEXT NOT NULL,
                expected_answer TEXT NOT NULL,
                rubric TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ACTIVE'
                    CHECK (status IN ('ACTIVE','GRADED')),
                created_at TEXT NOT NULL,
                UNIQUE(section_id,version)
            );

            CREATE TABLE IF NOT EXISTS quiz_attempts (
                id TEXT PRIMARY KEY,
                quiz_id TEXT NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
                idempotency_key TEXT NOT NULL,
                answer TEXT NOT NULL,
                score INTEGER NOT NULL CHECK (score BETWEEN 0 AND 100),
                passed INTEGER NOT NULL,
                feedback TEXT NOT NULL,
                weak_points TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(quiz_id,idempotency_key)
            );

            CREATE TABLE IF NOT EXISTS mastery_records (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES teaching_sessions(id) ON DELETE CASCADE,
                section_id TEXT NOT NULL REFERENCES lesson_sections(id) ON DELETE CASCADE,
                source_attempt_id TEXT NOT NULL UNIQUE REFERENCES quiz_attempts(id),
                previous_mastery INTEGER NOT NULL,
                new_mastery INTEGER NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS knowledge_nodes (
                id TEXT PRIMARY KEY,
                goal_id TEXT NOT NULL REFERENCES learning_goals(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                mastery INTEGER NOT NULL DEFAULT 0 CHECK (mastery BETWEEN 0 AND 100),
                confidence INTEGER NOT NULL DEFAULT 20 CHECK (confidence BETWEEN 0 AND 100),
                priority INTEGER NOT NULL DEFAULT 50 CHECK (priority BETWEEN 0 AND 100),
                status TEXT NOT NULL DEFAULT 'DISCOVERED'
                    CHECK (status IN ('DISCOVERED','LEARNING','MASTERED','REVIEW')),
                source TEXT NOT NULL DEFAULT 'USER',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(goal_id, name)
            );

            CREATE TABLE IF NOT EXISTS knowledge_edges (
                id TEXT PRIMARY KEY,
                goal_id TEXT NOT NULL REFERENCES learning_goals(id) ON DELETE CASCADE,
                source_node_id TEXT NOT NULL REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
                target_node_id TEXT NOT NULL REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
                relation_type TEXT NOT NULL
                    CHECK (relation_type IN ('REQUIRES','PART_OF','RELATED_TO','APPLIED_BY')),
                created_at TEXT NOT NULL,
                UNIQUE(source_node_id, target_node_id, relation_type)
            );

            CREATE TABLE IF NOT EXISTS content_items (
                id TEXT PRIMARY KEY,
                source_type TEXT NOT NULL CHECK (source_type IN ('GITHUB','NEWS')),
                external_id TEXT NOT NULL,
                source_name TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                topics TEXT NOT NULL DEFAULT '[]',
                quality_score INTEGER NOT NULL DEFAULT 50 CHECK (quality_score BETWEEN 0 AND 100),
                trend_score INTEGER NOT NULL DEFAULT 50 CHECK (trend_score BETWEEN 0 AND 100),
                published_at TEXT,
                discovered_at TEXT NOT NULL,
                UNIQUE(source_type, external_id)
            );

            CREATE TABLE IF NOT EXISTS recommendations (
                id TEXT PRIMARY KEY,
                goal_id TEXT NOT NULL REFERENCES learning_goals(id) ON DELETE CASCADE,
                content_item_id TEXT NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
                status TEXT NOT NULL DEFAULT 'CANDIDATE'
                    CHECK (status IN ('CANDIDATE','RECOMMENDED','ACCEPTED','DISMISSED')),
                score INTEGER NOT NULL CHECK (score BETWEEN 0 AND 100),
                score_breakdown TEXT NOT NULL,
                reason TEXT NOT NULL,
                created_module_id TEXT,
                created_at TEXT NOT NULL,
                decided_at TEXT,
                UNIQUE(goal_id, content_item_id)
            );

            CREATE TABLE IF NOT EXISTS learning_modules (
                id TEXT PRIMARY KEY,
                goal_id TEXT NOT NULL REFERENCES learning_goals(id) ON DELETE CASCADE,
                recommendation_id TEXT REFERENCES recommendations(id),
                title TEXT NOT NULL,
                rationale TEXT NOT NULL,
                estimated_minutes INTEGER NOT NULL CHECK (estimated_minutes > 0),
                status TEXT NOT NULL DEFAULT 'ACTIVE'
                    CHECK (status IN ('DRAFT','ACTIVE','COMPLETED','ARCHIVED')),
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS module_tasks (
                id TEXT PRIMARY KEY,
                module_id TEXT NOT NULL REFERENCES learning_modules(id) ON DELETE CASCADE,
                position INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                estimated_minutes INTEGER NOT NULL CHECK (estimated_minutes > 0),
                deliverable TEXT NOT NULL,
                acceptance_criteria TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS ingestion_jobs (
                id TEXT PRIMARY KEY,
                goal_id TEXT NOT NULL REFERENCES learning_goals(id) ON DELETE CASCADE,
                status TEXT NOT NULL CHECK (status IN ('PENDING','QUEUED','RUNNING','SUCCEEDED','FAILED')),
                idempotency_key TEXT NOT NULL,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 3,
                items_found INTEGER NOT NULL DEFAULT 0,
                recommendations_created INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                created_at TEXT NOT NULL,
                finished_at TEXT,
                UNIQUE(goal_id,idempotency_key),
                CHECK (attempt_count BETWEEN 0 AND max_attempts)
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_plan_week
                ON learning_tasks(plan_version_id, week_number, position);
            CREATE INDEX IF NOT EXISTS idx_plan_goal_status
                ON plan_versions(goal_id, status);
            CREATE INDEX IF NOT EXISTS idx_teaching_messages_session
                ON teaching_messages(session_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_knowledge_goal ON knowledge_nodes(goal_id, status);
            CREATE INDEX IF NOT EXISTS idx_recommendations_goal ON recommendations(goal_id, status, score);
            CREATE INDEX IF NOT EXISTS idx_content_discovered ON content_items(discovered_at);
            """
        )
        ingestion_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='ingestion_jobs'"
        ).fetchone()[0]
        ingestion_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(ingestion_jobs)")
        }
        if "QUEUED" not in ingestion_sql or "idempotency_key" not in ingestion_columns:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.executescript(
                """
                ALTER TABLE ingestion_jobs RENAME TO ingestion_jobs_legacy;
                CREATE TABLE ingestion_jobs (
                    id TEXT PRIMARY KEY,
                    goal_id TEXT NOT NULL REFERENCES learning_goals(id) ON DELETE CASCADE,
                    status TEXT NOT NULL CHECK (
                        status IN ('PENDING','QUEUED','RUNNING','SUCCEEDED','FAILED')
                    ),
                    idempotency_key TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    items_found INTEGER NOT NULL DEFAULT 0,
                    recommendations_created INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    finished_at TEXT,
                    UNIQUE(goal_id,idempotency_key),
                    CHECK (attempt_count BETWEEN 0 AND max_attempts)
                );
                INSERT INTO ingestion_jobs (
                    id,goal_id,status,idempotency_key,attempt_count,max_attempts,
                    items_found,recommendations_created,error,created_at,finished_at
                )
                SELECT id,goal_id,status,id,CASE WHEN status IN ('RUNNING','FAILED','SUCCEEDED')
                    THEN 1 ELSE 0 END,3,items_found,recommendations_created,error,
                    created_at,finished_at FROM ingestion_jobs_legacy;
                DROP TABLE ingestion_jobs_legacy;
                """
            )
            conn.execute("PRAGMA foreign_keys = ON")
        teaching_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='teaching_sessions'"
        ).fetchone()[0]
        teaching_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(teaching_sessions)")
        }
        if "current_section_id" not in teaching_columns or "WAITING_CHOICE" not in teaching_sql:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute("PRAGMA legacy_alter_table = ON")
            conn.executescript(
                """
                ALTER TABLE teaching_sessions RENAME TO teaching_sessions_legacy;
                CREATE TABLE teaching_sessions (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES learning_tasks(id) ON DELETE CASCADE,
                    current_section_id TEXT,
                    lesson_progress INTEGER NOT NULL DEFAULT 0,
                    last_user_action TEXT NOT NULL DEFAULT 'INIT',
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    mastery INTEGER NOT NULL DEFAULT 0 CHECK (mastery BETWEEN 0 AND 100),
                    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK
                        (status IN ('ACTIVE','WAITING_USER','WAITING_CHOICE','COMPLETED')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                INSERT INTO teaching_sessions (
                    id,task_id,status,created_at,updated_at
                ) SELECT id,task_id,status,created_at,created_at FROM teaching_sessions_legacy;
                DROP TABLE teaching_sessions_legacy;
                """
            )
            conn.execute("PRAGMA legacy_alter_table = OFF")
            conn.execute("PRAGMA foreign_keys = ON")
        message_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(teaching_messages)")
        }
        if "section_id" not in message_columns:
            conn.execute("ALTER TABLE teaching_messages ADD COLUMN section_id TEXT")
        if "message_type" not in message_columns:
            conn.execute(
                "ALTER TABLE teaching_messages ADD COLUMN message_type TEXT NOT NULL DEFAULT 'QUESTION'"
            )
        if "idempotency_key" not in message_columns:
            conn.execute("ALTER TABLE teaching_messages ADD COLUMN idempotency_key TEXT")
        for column in ("teaching_strategy", "provider", "model", "prompt_version"):
            if column not in message_columns:
                conn.execute(f"ALTER TABLE teaching_messages ADD COLUMN {column} TEXT")
        columns = {row[1] for row in conn.execute("PRAGMA table_info(learning_goals)")}
        if "user_id" not in columns:
            conn.execute(
                "ALTER TABLE learning_goals ADD COLUMN user_id TEXT NOT NULL "
                f"DEFAULT '{LOCAL_USER_ID}'"
            )
        if "daily_hours" not in columns:
            conn.execute("ALTER TABLE learning_goals ADD COLUMN daily_hours REAL")
            conn.execute("ALTER TABLE learning_goals ADD COLUMN study_weekdays TEXT")
            conn.execute("ALTER TABLE learning_goals ADD COLUMN timezone TEXT DEFAULT 'Asia/Shanghai'")
            conn.execute("ALTER TABLE learning_goals ADD COLUMN budget_derivation TEXT")
            goals = conn.execute("SELECT id,weekly_hours FROM learning_goals").fetchall()
            for goal in goals:
                valid = [day for day in range(1, 8) if 0.5 <= goal["weekly_hours"] / day <= 12]
                days = min(valid, key=lambda day: (abs(day - 5), -day))
                conn.execute(
                    "UPDATE learning_goals SET daily_hours=?,study_weekdays=?,timezone=?,budget_derivation=? WHERE id=?",
                    (goal["weekly_hours"] / days, json.dumps(list(range(1, days + 1))),
                     "Asia/Shanghai", "LEGACY_WEEKLY_PREFER_FIVE_WEEKDAYS_EXACT_BUDGET", goal["id"]),
                )
        plan_columns = {row[1] for row in conn.execute("PRAGMA table_info(plan_versions)")}
        if "planning_risks" not in plan_columns:
            conn.execute("ALTER TABLE plan_versions ADD COLUMN planning_risks TEXT NOT NULL DEFAULT '[]'")
            conn.execute("ALTER TABLE plan_versions ADD COLUMN adjustment_suggestions TEXT NOT NULL DEFAULT '[]'")
        task_columns = {row[1] for row in conn.execute("PRAGMA table_info(learning_tasks)")}
        if "scheduled_date" not in task_columns:
            conn.execute("ALTER TABLE learning_tasks ADD COLUMN scheduled_date TEXT")
        ai_columns = {row[1] for row in conn.execute("PRAGMA table_info(ai_runs)")}
        if "user_id" not in ai_columns:
            conn.execute("ALTER TABLE ai_runs ADD COLUMN user_id TEXT REFERENCES users(id)")
        conn.execute(
            """INSERT INTO users (id,email,password_hash,display_name,is_active,created_at)
            VALUES (?,?,?,?,1,?) ON CONFLICT(id) DO NOTHING""",
            (LOCAL_USER_ID, "local@mission-control.invalid", "!", "Local User", utc_now()),
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_goals_user ON learning_goals(user_id,status)")
        conn.commit()
    finally:
        conn.close()
