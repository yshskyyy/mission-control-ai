import pytest

from app import intelligence, jobs, queueing, repository, services


def _goal(client, goal_payload):
    response = client.post("/api/goals", json=goal_payload)
    assert response.status_code == 201
    return response.json()


def _signal(external_id: str = "reliable-1") -> dict:
    return {
        "source_type": "GITHUB",
        "external_id": external_id,
        "source_name": "GitHub",
        "title": "langgraph/reliable-agent",
        "url": f"https://github.com/example/{external_id}",
        "summary": "LangGraph agent workflow checkpoint and recovery",
        "topics": ["langgraph", "agent", "workflow"],
        "quality_score": 90,
        "trend_score": 85,
        "published_at": "2026-09-01T00:00:00Z",
    }


def _queued_job(goal_id: str, key: str) -> dict:
    job = services.start_recommendation_refresh(goal_id, key)
    assert repository.mark_ingestion_queued(job["id"])["status"] == "QUEUED"
    return job


def test_first_two_attempts_fail_and_third_succeeds(client, goal_payload, monkeypatch):
    goal = _goal(client, goal_payload)
    calls = 0

    def flaky_collection():
        nonlocal calls
        calls += 1
        return (([], [f"temporary failure {calls}"]) if calls < 3 else ([_signal()], []))

    monkeypatch.setattr(intelligence, "collect_signals", flaky_collection)
    job = _queued_job(goal["id"], "three-attempt-success")

    for expected_attempt in (1, 2):
        with pytest.raises(RuntimeError):
            jobs.run_ingestion(job["id"])
        state = repository.get_ingestion_job(job["id"])
        assert state["status"] == "QUEUED"
        assert state["attempt_count"] == expected_attempt
        assert "temporary failure" in state["error"]

    jobs.run_ingestion(job["id"])
    state = repository.get_ingestion_job(job["id"])
    assert state["status"] == "SUCCEEDED"
    assert state["attempt_count"] == 3
    assert state["recommendations_created"] == 1


def test_three_failures_are_final_and_cannot_run_again(client, goal_payload, monkeypatch):
    goal = _goal(client, goal_payload)
    monkeypatch.setattr(intelligence, "collect_signals", lambda: ([], ["permanent failure"]))
    job = _queued_job(goal["id"], "three-attempt-failure")

    for _ in range(3):
        with pytest.raises(RuntimeError):
            jobs.run_ingestion(job["id"])

    state = repository.get_ingestion_job(job["id"])
    assert state["status"] == "FAILED"
    assert state["attempt_count"] == state["max_attempts"] == 3
    with pytest.raises(RuntimeError, match="not QUEUED"):
        jobs.run_ingestion(job["id"])
    assert repository.get_ingestion_job(job["id"])["attempt_count"] == 3


def test_retry_endpoint_cannot_overwrite_success(client, goal_payload, monkeypatch):
    goal = _goal(client, goal_payload)
    monkeypatch.setattr(intelligence, "collect_signals", lambda: ([_signal("success")], []))
    job = _queued_job(goal["id"], "already-successful")
    jobs.run_ingestion(job["id"])

    response = client.post(f"/api/ingestion-jobs/{job['id']}/retry")
    assert response.status_code == 409
    assert repository.get_ingestion_job(job["id"])["status"] == "SUCCEEDED"


def test_idempotency_key_and_duplicate_worker_execution(client, goal_payload, monkeypatch):
    goal = _goal(client, goal_payload)
    assert client.post(f"/api/goals/{goal['id']}/generate-plan").status_code == 200
    monkeypatch.setattr(intelligence, "collect_signals", lambda: ([_signal("idempotent")], []))
    first = services.start_recommendation_refresh(goal["id"], "same-request")
    second = services.start_recommendation_refresh(goal["id"], "same-request")
    assert first["id"] == second["id"]
    repository.mark_ingestion_queued(first["id"])

    jobs.run_ingestion(first["id"])
    recommendation = repository.list_recommendations(goal["id"])[0]
    assert client.post(
        f"/api/recommendations/{recommendation['id']}/decision",
        json={"decision": "ACCEPT"},
    ).status_code == 200

    jobs.run_ingestion(first["id"])
    assert len(repository.list_recommendations(goal["id"])) == 1
    assert len(repository.list_learning_modules(goal["id"])) == 1
    assert repository.active_plan(goal["id"])["version"] == 2


def test_production_redis_failure_is_explicit(client, goal_payload, monkeypatch):
    goal = _goal(client, goal_payload)
    monkeypatch.setattr(
        queueing,
        "settings",
        type("ProductionSettings", (), {
            "redis_url": "redis://127.0.0.1:1/0?socket_connect_timeout=0.1",
            "environment": "production",
        })(),
    )
    response = client.post(
        f"/api/goals/{goal['id']}/recommendations/refresh",
        headers={"Idempotency-Key": "redis-down"},
    )
    assert response.status_code == 503
    repeated = services.start_recommendation_refresh(goal["id"], "redis-down")
    assert repeated["status"] == "FAILED"
    assert repeated["attempt_count"] == 0


def test_invalid_backward_state_transitions_are_rejected(client, goal_payload):
    goal = _goal(client, goal_payload)
    job = _queued_job(goal["id"], "no-backward-transition")
    assert repository.reset_ingestion_for_manual_retry(job["id"]) is None
    assert repository.mark_ingestion_succeeded(job["id"], 0, 0) is None
    assert repository.get_ingestion_job(job["id"])["status"] == "QUEUED"


def test_rq_is_configured_for_three_total_attempts(monkeypatch):
    captured = {}

    class FakeRedis:
        def ping(self):
            return True

    class FakeQueue:
        def __init__(self, name, connection):
            captured["name"] = name

        def enqueue(self, *args, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(
        queueing,
        "settings",
        type("DevelopmentSettings", (), {
            "redis_url": "redis://example.invalid/0", "environment": "development"
        })(),
    )
    monkeypatch.setattr(queueing.Redis, "from_url", lambda _: FakeRedis())
    monkeypatch.setattr(queueing, "Queue", FakeQueue)

    assert queueing.enqueue_ingestion("job-1") is True
    assert captured["job_id"] == "ingestion-job-1"
    assert captured["retry"].max == 2
