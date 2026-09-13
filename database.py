import sqlite3
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
MEMORY_DIR = BASE_DIR / "memory_data"
DATABASE_PATH = MEMORY_DIR / "mission_control.db"


def get_connection():
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database():
    with get_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS daily_briefs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                brief_date TEXT NOT NULL UNIQUE,
                available_hours INTEGER,
                news TEXT NOT NULL DEFAULT '',
                news_analysis TEXT NOT NULL DEFAULT '',
                github_analysis TEXT NOT NULL DEFAULT '',
                tree_update_result TEXT NOT NULL DEFAULT '',
                plan TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS daily_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                review_date TEXT NOT NULL UNIQUE,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_daily_briefs_date
            ON daily_briefs(brief_date DESC);

            CREATE INDEX IF NOT EXISTS idx_daily_reviews_date
            ON daily_reviews(review_date DESC);
            """
        )


def upsert_daily_brief(
    content,
    brief_date=None,
    available_hours=None,
    news="",
    news_analysis="",
    github_analysis="",
    tree_update_result="",
    plan="",
):
    initialize_database()
    brief_date = brief_date or datetime.now().strftime("%Y-%m-%d")
    now = datetime.now().isoformat(timespec="seconds")

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO daily_briefs (
                brief_date, available_hours, news, news_analysis,
                github_analysis, tree_update_result, plan, content,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(brief_date) DO UPDATE SET
                available_hours = excluded.available_hours,
                news = excluded.news,
                news_analysis = excluded.news_analysis,
                github_analysis = excluded.github_analysis,
                tree_update_result = excluded.tree_update_result,
                plan = excluded.plan,
                content = excluded.content,
                updated_at = excluded.updated_at
            """,
            (
                brief_date,
                available_hours,
                news,
                news_analysis,
                github_analysis,
                tree_update_result,
                plan,
                content,
                now,
                now,
            ),
        )


def upsert_daily_review(content, review_date=None):
    initialize_database()
    review_date = review_date or datetime.now().strftime("%Y-%m-%d")
    now = datetime.now().isoformat(timespec="seconds")

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO daily_reviews (
                review_date, content, created_at, updated_at
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(review_date) DO UPDATE SET
                content = excluded.content,
                updated_at = excluded.updated_at
            """,
            (review_date, content, now, now),
        )


def load_latest_content(table_name):
    if table_name not in {"daily_briefs", "daily_reviews"}:
        raise ValueError("Unsupported table name")

    initialize_database()
    date_column = "brief_date" if table_name == "daily_briefs" else "review_date"
    with get_connection() as connection:
        row = connection.execute(
            f"SELECT content FROM {table_name} ORDER BY {date_column} DESC LIMIT 1"
        ).fetchone()
    return row["content"] if row else ""


def list_recent_briefs(limit=7):
    initialize_database()
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT brief_date, available_hours, updated_at
            FROM daily_briefs
            ORDER BY brief_date DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()


def import_markdown_history():
    initialize_database()
    imported_briefs = 0
    imported_reviews = 0

    for path in sorted((MEMORY_DIR / "daily_briefs").glob("*.md")):
        now = datetime.now().isoformat(timespec="seconds")
        with get_connection() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO daily_briefs (
                    brief_date, content, created_at, updated_at
                ) VALUES (?, ?, ?, ?)
                """,
                (path.stem, path.read_text(encoding="utf-8"), now, now),
            )
        imported_briefs += cursor.rowcount

    for path in sorted((MEMORY_DIR / "daily_reviews").glob("*.md")):
        now = datetime.now().isoformat(timespec="seconds")
        with get_connection() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO daily_reviews (
                    review_date, content, created_at, updated_at
                ) VALUES (?, ?, ?, ?)
                """,
                (path.stem, path.read_text(encoding="utf-8"), now, now),
            )
        imported_reviews += cursor.rowcount

    return imported_briefs, imported_reviews
