from types import SimpleNamespace

from app import auth
from app import ai


PASSING_ANSWER = "输入是固定样例，操作是运行实现，结果是可观察输出，最后用测试验证。"


def _course(client, goal_payload):
    goal = client.post("/api/goals", json=goal_payload).json()
    plan = client.post(f"/api/goals/{goal['id']}/generate-plan").json()
    session = client.post(f"/api/tasks/{plan['tasks'][0]['id']}/teaching-sessions").json()
    return goal, plan, session


def _active_quiz(session):
    return [quiz for quiz in session["quizzes"] if quiz["status"] == "ACTIVE"][-1]


def test_structured_course_questions_reteach_quiz_and_mastery(client, goal_payload):
    goal, _, session = _course(client, goal_payload)
    assert len(session["sections"]) == 3
    assert [section["status"] for section in session["sections"]] == ["CURRENT", "LOCKED", "LOCKED"]
    assert session["current_section_id"] == session["sections"][0]["id"]
    assert session["messages"][0]["message_type"] == "TEACHING"

    for question in ("输入具体指什么？", "这个结果应该如何观察？"):
        response = client.post(
            f"/api/teaching-sessions/{session['id']}/messages", json={"content": question}
        )
        assert response.status_code == 201
        session = response.json()
    persisted = client.get(f"/api/teaching-sessions/{session['id']}").json()
    assert all(any(question in message["content"] for message in persisted["messages"])
               for question in ("输入具体指什么？", "这个结果应该如何观察？"))

    session = client.post(f"/api/teaching-sessions/{session['id']}/reteach").json()
    assert session["retry_count"] == 1
    assert session["messages"][-1]["message_type"] == "RETEACH"

    session = client.post(f"/api/teaching-sessions/{session['id']}/quizzes").json()
    first_quiz = _active_quiz(session)
    assert "expected_answer" not in first_quiz
    session = client.post(
        f"/api/teaching-sessions/{session['id']}/quizzes/{first_quiz['id']}/attempts",
        json={"answer": "我不知道"}, headers={"Idempotency-Key": "wrong-once"},
    ).json()
    assert session["quiz_attempts"][-1]["passed"] == 0
    assert session["quiz_attempts"][-1]["weak_points"]
    assert session["messages"][-1]["message_type"] == "RETEACH"

    retry_quiz = _active_quiz(session)
    passed = client.post(
        f"/api/teaching-sessions/{session['id']}/quizzes/{retry_quiz['id']}/attempts",
        json={"answer": PASSING_ANSWER}, headers={"Idempotency-Key": "pass-on-retry"},
    )
    assert passed.status_code == 201
    session = passed.json()
    assert session["quiz_attempts"][-1]["passed"] == 1
    assert len(session["mastery_records"]) == 1
    assert session["mastery"] > 0
    assert session["sections"][0]["status"] == "COMPLETED"
    assert session["sections"][1]["status"] == "CURRENT"
    tree = client.get(f"/api/goals/{goal['id']}/knowledge-tree").json()
    assert any(node["source"] == "TEACHING" and node["mastery"] > 0 for node in tree["nodes"])

    duplicate = client.post(
        f"/api/teaching-sessions/{session['id']}/quizzes/{retry_quiz['id']}/attempts",
        json={"answer": PASSING_ANSWER}, headers={"Idempotency-Key": "pass-on-retry"},
    ).json()
    assert len(duplicate["quiz_attempts"]) == 2
    assert len(duplicate["mastery_records"]) == 1
    assert duplicate["sections"][1]["status"] == "CURRENT"


def test_three_failed_quizzes_pause_for_user_choice(client, goal_payload):
    _, _, session = _course(client, goal_payload)
    for attempt in range(1, 4):
        if not session["quizzes"] or not any(q["status"] == "ACTIVE" for q in session["quizzes"]):
            session = client.post(f"/api/teaching-sessions/{session['id']}/quizzes").json()
        quiz = _active_quiz(session)
        session = client.post(
            f"/api/teaching-sessions/{session['id']}/quizzes/{quiz['id']}/attempts",
            json={"answer": "不知道"}, headers={"Idempotency-Key": f"wrong-{attempt}"},
        ).json()
    assert session["retry_count"] == 3
    assert session["status"] == "WAITING_CHOICE"
    assert session["messages"][-1]["message_type"] == "SYSTEM"
    continued = client.post(f"/api/teaching-sessions/{session['id']}/continue").json()
    assert continued["status"] == "WAITING_USER"
    assert continued["retry_count"] == 0


def test_ambiguous_question_is_grounded_and_not_repeated(client, goal_payload):
    _, _, session = _course(client, goal_payload)
    previous = session["messages"][-1]["content"]
    response = client.post(
        f"/api/teaching-sessions/{session['id']}/messages", json={"content": "什么意思"}
    )
    assert response.status_code == 201
    payload = response.json()
    answer = payload["messages"][-1]
    assert answer["content"] != previous
    assert answer["teaching_strategy"]
    assert payload["runtime"] == {
        "provider": "local", "model": "local",
        "prompt_version": "teaching-question-v2", "fallback": True,
    }


def test_consecutive_reteach_changes_strategy_and_content(client, goal_payload):
    _, _, session = _course(client, goal_payload)
    first = client.post(f"/api/teaching-sessions/{session['id']}/reteach").json()
    second = client.post(f"/api/teaching-sessions/{session['id']}/reteach").json()
    first_message, second_message = first["messages"][-1], second["messages"][-1]
    assert first_message["teaching_strategy"] != second_message["teaching_strategy"]
    assert first_message["content"] != second_message["content"]


def test_specific_question_selects_targeted_strategy(client, goal_payload):
    _, _, session = _course(client, goal_payload)
    payload = client.post(
        f"/api/teaching-sessions/{session['id']}/messages",
        json={"content": "请用一段代码说明这个概念如何验证"},
    ).json()
    answer = payload["messages"][-1]
    assert answer["teaching_strategy"] == "code"
    assert "assert" in answer["content"]


def test_prompt_contains_history_weak_points_mastery_and_goal(monkeypatch):
    captured = {}
    def capture_prompt(*args):
        captured["prompt"] = args[3]
        return None
    monkeypatch.setattr(ai, "_pydantic_call", capture_prompt)
    task = {"id": "task", "title": "任务", "description": "说明", "goal_title": "长期目标",
            "desired_outcome": "上线产品", "current_level": "初级"}
    section = {"title": "缓存", "objective": "理解一致性", "content": "缓存正文", "example": "缓存例子"}
    reply, _, _ = ai.answer_teaching_question(
        task, section, [{"role": "TEACHER", "content": "上一条导师消息"}],
        "缓存和数据库有什么区别", ["失效策略"], 42, ["simple"],
    )
    prompt = captured["prompt"]
    assert reply
    for expected in ("长期目标", "上线产品", "上一条导师消息", "失效策略", "42", "simple"):
        assert expected in prompt


def test_public_teaching_api_does_not_expose_internal_secrets(client, goal_payload):
    _, _, session = _course(client, goal_payload)
    payload = client.get(f"/api/teaching-sessions/{session['id']}").json()
    serialized = str(payload).lower()
    assert "api_key" not in serialized
    assert "system prompt" not in serialized
    assert "rubric" not in serialized
    assert "expected_answer" not in serialized


def test_no_key_fallback_can_complete_entire_course(client, goal_payload):
    _, _, session = _course(client, goal_payload)
    for section_number in range(3):
        session = client.post(f"/api/teaching-sessions/{session['id']}/quizzes").json()
        quiz = _active_quiz(session)
        session = client.post(
            f"/api/teaching-sessions/{session['id']}/quizzes/{quiz['id']}/attempts",
            json={"answer": PASSING_ANSWER},
            headers={"Idempotency-Key": f"complete-{section_number}"},
        ).json()
    assert session["status"] == "COMPLETED"
    assert session["lesson_progress"] == 3
    assert session["mastery"] == 100
    assert len(session["mastery_records"]) == 3
    assert session["messages"][-1]["message_type"] == "SYSTEM"


def test_other_user_cannot_read_or_continue_session(client, goal_payload, monkeypatch):
    monkeypatch.setattr(auth, "settings", SimpleNamespace(
        auth_disabled=False, jwt_secret="test-secret-with-at-least-32-characters",
        jwt_expire_minutes=60,
    ))
    alice = client.post("/auth/register", json={
        "email": "teacher-alice@example.com", "password": "secure-password-123",
        "display_name": "Alice",
    }).json()
    bob = client.post("/auth/register", json={
        "email": "teacher-bob@example.com", "password": "secure-password-123",
        "display_name": "Bob",
    }).json()
    alice_headers = {"Authorization": f"Bearer {alice['access_token']}"}
    bob_headers = {"Authorization": f"Bearer {bob['access_token']}"}
    goal = client.post("/api/goals", json=goal_payload, headers=alice_headers).json()
    plan = client.post(
        f"/api/goals/{goal['id']}/generate-plan", headers=alice_headers
    ).json()
    session = client.post(
        f"/api/tasks/{plan['tasks'][0]['id']}/teaching-sessions", headers=alice_headers
    ).json()
    assert client.get(
        f"/api/teaching-sessions/{session['id']}", headers=bob_headers
    ).status_code == 404
    assert client.post(
        f"/api/teaching-sessions/{session['id']}/continue", headers=bob_headers
    ).status_code == 404
