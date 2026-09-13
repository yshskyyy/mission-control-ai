from datetime import datetime
from pathlib import Path

from database import load_latest_content, upsert_daily_brief, upsert_daily_review


BASE_DIR = Path(__file__).resolve().parent
MEMORY_DIR = BASE_DIR / "memory_data"


def save_daily_brief(brief, **metadata):
    folder = MEMORY_DIR / "daily_briefs"
    folder.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    (folder / f"{today}.md").write_text(brief, encoding="utf-8")
    upsert_daily_brief(brief, brief_date=today, **metadata)


def save_daily_review(review):
    folder = MEMORY_DIR / "daily_reviews"
    folder.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    (folder / f"{today}.md").write_text(review, encoding="utf-8")
    upsert_daily_review(review, review_date=today)


def load_latest_review():
    database_content = load_latest_content("daily_reviews")
    if database_content:
        return database_content
    return _load_latest_markdown(MEMORY_DIR / "daily_reviews")


def load_latest_brief():
    database_content = load_latest_content("daily_briefs")
    if database_content:
        return database_content
    return _load_latest_markdown(MEMORY_DIR / "daily_briefs")


def _load_latest_markdown(folder):
    files = sorted(folder.glob("*.md")) if folder.exists() else []
    return files[-1].read_text(encoding="utf-8") if files else ""
