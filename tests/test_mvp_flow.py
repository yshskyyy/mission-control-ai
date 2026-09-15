def create_goal_and_plan(client, goal_payload):
    goal_response = client.post("/api/goals", json=goal_payload)
    assert goal_response.status_code == 201
    goal = goal_response.json()
    plan_response = client.post(f"/api/goals/{goal['id']}/generate-plan")
    assert plan_response.status_code == 200
    return goal, plan_response.json()


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_create_goal_and_budgeted_plan(client, goal_payload):
    goal, plan = create_goal_and_plan(client, goal_payload)
    assert plan["goal_id"] == goal["id"]
    assert plan["version"] == 1
    assert len(plan["tasks"]) == 12
    for week in range(1, 5):
        total = sum(t["estimated_minutes"] for t in plan["tasks"] if t["week_number"] == week)
        assert total <= goal_payload["weekly_hours"] * 60
    runs = client.get("/api/internal/ai-runs").json()
    assert runs[0]["status"] == "FALLBACK"


def test_submit_evidence_updates_task(client, goal_payload):
    goal, plan = create_goal_and_plan(client, goal_payload)
    task = plan["tasks"][0]
    client.patch(f"/api/tasks/{task['id']}/status", json={"status": "IN_PROGRESS"})
    evidence = (
        "我已经实现目标拆解，并写了测试验证结果。测试命令为 pytest，全部通过。"
        "清单包含前置知识、当前差距和下一步，每一项都在 README 中给出说明。" * 2
    )
    response = client.post(
        f"/api/tasks/{task['id']}/submissions",
        json={"evidence_text": evidence, "actual_minutes": 55, "repository_url": None},
    )
    assert response.status_code == 201
    assert response.json()["result"] == "PASSED"
    today = client.get("/api/today", params={"goal_id": goal["id"]}).json()
    assert all(item["id"] != task["id"] for item in today["tasks"])


def test_review_acceptance_creates_new_plan_version(client, goal_payload):
    goal, _ = create_goal_and_plan(client, goal_payload)
    review_response = client.post(f"/api/goals/{goal['id']}/weekly-reviews", params={"week": 1})
    assert review_response.status_code == 201
    review = review_response.json()
    decision = client.post(
        f"/api/weekly-reviews/{review['id']}/decision", json={"decision": "ACCEPT"}
    )
    assert decision.status_code == 200
    assert decision.json()["status"] == "ACCEPTED"
    plan = client.get(f"/api/goals/{goal['id']}/plan").json()
    assert plan["version"] == 2
    assert "动态调整" in plan["rationale"]
    for week in range(1, 5):
        total = sum(t["estimated_minutes"] for t in plan["tasks"] if t["week_number"] == week)
        assert total <= goal_payload["weekly_hours"] * 60


def test_teaching_session_keeps_conversation_and_ai_runs(client, goal_payload):
    _, plan = create_goal_and_plan(client, goal_payload)
    task = plan["tasks"][0]
    started = client.post(f"/api/tasks/{task['id']}/teaching-sessions")
    assert started.status_code == 201
    session = started.json()
    assert session["task_id"] == task["id"]
    assert session["messages"][0]["role"] == "TEACHER"

    reply = client.post(
        f"/api/teaching-sessions/{session['id']}/messages",
        json={"content": "最小结果是运行示例并得到预期输出。"},
    )
    assert reply.status_code == 201
    messages = reply.json()["messages"]
    assert [item["role"] for item in messages] == ["TEACHER", "USER", "TEACHER"]
    runs = client.get("/api/internal/ai-runs").json()
    assert sum(run["run_type"] == "TEACHING" for run in runs) == 2


def test_teaching_rejects_missing_entities(client):
    assert client.post("/api/tasks/missing/teaching-sessions").status_code == 404
    response = client.post(
        "/api/teaching-sessions/missing/messages", json={"content": "请解释"}
    )
    assert response.status_code == 404


def test_trend_recommendation_creates_module_tree_and_plan(client, goal_payload, monkeypatch):
    from app import intelligence

    goal, _ = create_goal_and_plan(client, goal_payload)
    signal = {
        "source_type": "GITHUB", "external_id": "repo-42", "source_name": "GitHub",
        "title": "example/langgraph-checkpoint", "url": "https://github.com/example/repo",
        "summary": "Python agent checkpoint and durable workflow example",
        "topics": ["python", "agent", "langgraph"], "quality_score": 88,
        "trend_score": 82, "published_at": "2026-09-01T00:00:00Z",
    }
    monkeypatch.setattr(intelligence, "collect_signals", lambda: ([signal], []))

    response = client.post(f"/api/goals/{goal['id']}/recommendations/refresh")
    assert response.status_code == 202
    job = client.get(f"/api/ingestion-jobs/{response.json()['id']}").json()
    assert job["status"] == "SUCCEEDED"
    assert job["recommendations_created"] == 1

    recommendations = client.get(f"/api/goals/{goal['id']}/recommendations").json()
    assert recommendations[0]["status"] == "RECOMMENDED"
    assert "goal_relevance" in recommendations[0]["score_breakdown"]
    accepted = client.post(
        f"/api/recommendations/{recommendations[0]['id']}/decision",
        json={"decision": "ACCEPT"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "ACCEPTED"
    modules = client.get(f"/api/goals/{goal['id']}/learning-modules").json()
    assert len(modules) == 1
    assert len(modules[0]["tasks"]) >= 2
    tree = client.get(f"/api/goals/{goal['id']}/knowledge-tree").json()
    assert any(node["source"] == "GITHUB" for node in tree["nodes"])
    assert any(edge["relation_type"] == "PART_OF" for edge in tree["edges"])
    assert client.get(f"/api/goals/{goal['id']}/plan").json()["version"] == 2

    repeated = client.post(
        f"/api/recommendations/{recommendations[0]['id']}/decision",
        json={"decision": "ACCEPT"},
    )
    assert repeated.status_code == 200
    assert len(client.get(f"/api/goals/{goal['id']}/learning-modules").json()) == 1
    assert client.get(f"/api/goals/{goal['id']}/plan").json()["version"] == 2


def test_failed_ingestion_job_is_observable(client, goal_payload, monkeypatch):
    from app import intelligence

    goal, _ = create_goal_and_plan(client, goal_payload)
    monkeypatch.setattr(intelligence, "collect_signals", lambda: ([], ["GitHub: timeout"]))
    response = client.post(f"/api/goals/{goal['id']}/recommendations/refresh")
    job = client.get(f"/api/ingestion-jobs/{response.json()['id']}").json()
    assert job["status"] == "FAILED"
    assert "timeout" in job["error"]
    recovered_signal = {
        "source_type": "NEWS", "external_id": "news-1", "source_name": "Test",
        "title": "LangGraph durable execution", "url": "https://example.com/langgraph",
        "summary": "agent workflow recovery", "topics": ["langgraph", "agent"],
        "quality_score": 75, "trend_score": 70, "published_at": None,
    }
    monkeypatch.setattr(intelligence, "collect_signals", lambda: ([recovered_signal], []))
    retried = client.post(f"/api/ingestion-jobs/{job['id']}/retry")
    assert retried.status_code == 202
    recovered = client.get(f"/api/ingestion-jobs/{job['id']}").json()
    assert recovered["status"] == "SUCCEEDED"
    assert recovered["recommendations_created"] == 1


def test_reject_invalid_goal(client, goal_payload):
    goal_payload["weekly_hours"] = 0
    response = client.post("/api/goals", json=goal_payload)
    assert response.status_code == 422
