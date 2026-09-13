from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import ai, db
from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    test_settings = SimpleNamespace(
        database_path=tmp_path / "test.db", openai_api_key=None, openai_model="test-model"
    )
    monkeypatch.setattr(db, "settings", test_settings)
    monkeypatch.setattr(ai, "settings", test_settings)
    db.init_db()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def goal_payload():
    return {
        "title": "掌握 LangGraph 工程实践",
        "current_level": "会 Python 和基础 LLM API",
        "desired_outcome": "完成支持暂停恢复和测试的学习助手",
        "deadline": "2026-10-31",
        "weekly_hours": 6,
        "learning_preferences": "官方文档和动手项目",
    }
