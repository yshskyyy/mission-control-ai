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


def test_reject_invalid_goal(client, goal_payload):
    goal_payload["weekly_hours"] = 0
    response = client.post("/api/goals", json=goal_payload)
    assert response.status_code == 422
