from collections import defaultdict
from datetime import datetime, timezone

from app import services
from app.scheduling import current_plan_week, local_today


def _payload(goal_payload, **updates):
    payload = dict(goal_payload)
    payload.pop("weekly_hours", None)
    payload.update({
        "daily_hours": 1.5,
        "study_weekdays": [1, 2, 3, 4, 5],
        "timezone": "Asia/Shanghai",
    })
    payload.update(updates)
    return payload


def test_daily_availability_validation_and_weekday_normalization(client, goal_payload):
    assert client.post("/api/goals", json=_payload(goal_payload, daily_hours=0.4)).status_code == 422
    assert client.post("/api/goals", json=_payload(goal_payload, study_weekdays=[1, 1])).status_code == 422
    response = client.post("/api/goals", json=_payload(goal_payload, study_weekdays=None,
                                                        study_days_per_week=3))
    assert response.status_code == 201
    assert response.json()["study_weekdays"] == [1, 2, 3]


def test_legacy_weekly_budget_is_preserved_and_explained(client, goal_payload):
    goal = client.post("/api/goals", json=goal_payload).json()
    assert goal["weekly_hours"] == goal_payload["weekly_hours"]
    assert abs(goal["weekly_budget_hours"] - goal_payload["weekly_hours"]) < 0.00001
    assert goal["budget_derivation"] == "LEGACY_WEEKLY_PREFER_FIVE_WEEKDAYS_EXACT_BUDGET"
    assert len(goal["study_weekdays"]) == goal["study_days_per_week"]


def test_plan_has_dates_and_never_exceeds_daily_budget(client, goal_payload):
    goal = client.post("/api/goals", json=_payload(goal_payload)).json()
    plan = client.post(f"/api/goals/{goal['id']}/generate-plan").json()
    totals = defaultdict(int)
    for task in plan["tasks"]:
        assert task["scheduled_date"]
        totals[task["scheduled_date"]] += task["estimated_minutes"]
    assert max(totals.values()) <= goal["daily_hours"] * 60


def test_insufficient_deadline_returns_risk_and_suggestions(client, goal_payload):
    payload = _payload(goal_payload, daily_hours=0.5, study_weekdays=[1], deadline="2026-09-16")
    goal = client.post("/api/goals", json=payload).json()
    plan = client.post(f"/api/goals/{goal['id']}/generate-plan").json()
    assert any(risk["code"] == "DEADLINE_RISK" for risk in plan["planning_risks"])
    assert "延长截止日期" in plan["adjustment_suggestions"]


def test_planner_reports_task_too_large_after_bounded_retries(client, goal_payload, monkeypatch):
    goal = client.post("/api/goals", json=_payload(goal_payload, daily_hours=0.5,
                                                    study_weekdays=[1, 2, 3])).json()
    oversized = [{"week_number": 1, "title": "过大任务", "description": "不能一天完成",
                  "estimated_minutes": 90, "deliverable": "完整成果",
                  "acceptance_criteria": ["可运行", "可复查"]}]
    calls = []
    monkeypatch.setattr(services, "generate_plan",
                        lambda current: (calls.append(current) or ("test", oversized, "test")))
    response = client.post(f"/api/goals/{goal['id']}/generate-plan")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "TASK_TOO_LARGE"
    assert len(calls) == 2
    assert "独立验收" in calls[1]["planning_feedback"]


def test_timezone_controls_today_and_current_week():
    instant = datetime(2026, 9, 13, 16, 30, tzinfo=timezone.utc)
    assert local_today("Asia/Shanghai", instant).isoformat() == "2026-09-14"
    assert local_today("America/Los_Angeles", instant).isoformat() == "2026-09-13"
    tasks = [{"scheduled_date": "2026-09-01"}]
    later = datetime(2026, 9, 15, 12, tzinfo=timezone.utc)
    assert current_plan_week(tasks, "Asia/Shanghai", later) == 3
