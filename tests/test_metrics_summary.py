import json
from prometheus_client import REGISTRY
from types import SimpleNamespace
import pytest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from app import ai, auth, db, repository
from app.config import Settings
from app.observability import record_ai_request
from app.observability import AI_LOGICAL_REQUESTS, TELEMETRY_WRITE_FAILURES


def test_ai_metrics_use_only_bounded_non_sensitive_labels():
    record_ai_request("TEACHING", "openai", "SUCCEEDED", .2, 10, 5, .001)
    forbidden = {"user_id", "session_id", "question", "error", "prompt"}
    for metric in REGISTRY.collect():
        if metric.name.startswith(("teaching_", "workflow_", "quiz_", "plan_", "deadline_", "ai_", "estimated_ai_")):
            for sample in metric.samples:
                assert forbidden.isdisjoint(sample.labels)


def test_metrics_summary_is_authenticated_and_user_scoped(client, monkeypatch):
    monkeypatch.setattr(auth, "settings", SimpleNamespace(
        auth_disabled=False, jwt_secret="test-secret-with-at-least-32-characters",
        jwt_expire_minutes=60,
    ))
    assert client.get("/api/internal/metrics-summary").status_code == 401
    registered = client.post("/auth/register", json={"email": "metrics@example.com",
        "password": "secure-password-123", "display_name": "Metrics"}).json()
    response = client.get("/api/internal/metrics-summary",
                          headers={"Authorization": f"Bearer {registered['access_token']}"})
    assert response.status_code == 200
    body = response.json()
    assert {"logical_requests","provider_attempts","fallback_rate","schema_failure_rate",
            "retry_rate","cost_estimate_available","usage_available","latency_ms",
            "completed_count","incomplete_count","stale_incomplete_count",
            "usage_coverage_rate","pricing_coverage_rate"}.issubset(body)
    assert "unowned_historical_data_excluded" not in body
    assert body["latency_ms"]=={"p50":None,"p95":None,"sample_count":0}
    assert body["estimated_cost"] is None and not body["cost_estimate_available"]
    assert "tokens" not in body and "error" not in body and "prompt" not in body


def _counter_value(metric):
    return sum(sample.value for sample in metric.collect()[0].samples if sample.name.endswith("_total"))


def test_model_and_fallback_survive_telemetry_storage_failure(tmp_path,monkeypatch,caplog):
    class Responses:
        def create(self,**kwargs):
            payload={"rationale":"valid","tasks":[{"week_number":index//3+1,"title":f"任务{index}",
                "description":"完整说明","estimated_minutes":30,"deliverable":"成果",
                "acceptance_criteria":["可运行","可复查"]} for index in range(12)]}
            return SimpleNamespace(output_text=json.dumps(payload),usage=None)
    goal={"id":"goal","title":"目标","current_level":"初级","desired_outcome":"完成成果","deadline":"2027-01-01",
          "daily_hours":1,"study_weekdays":[1,2,3],"timezone":"Asia/Shanghai","learning_preferences":"实践"}
    settings=SimpleNamespace(openai_api_key="key",openai_model="model",openai_temperature=0,
        ai_input_cost_per_million=0,ai_output_cost_per_million=0)
    monkeypatch.setattr(ai,"settings",settings); monkeypatch.setattr(ai,"_client",lambda:SimpleNamespace(responses=Responses()) if settings.openai_api_key else None)
    def fail(*args,**kwargs): raise RuntimeError("database unavailable secret-content-must-not-log")
    monkeypatch.setattr(repository,"start_ai_logical_request",fail)
    monkeypatch.setattr(repository,"save_ai_run",fail)
    monkeypatch.setattr(repository,"get_ai_logical_request",fail)
    monkeypatch.setattr(repository,"finalize_ai_logical_request",fail)
    before=_counter_value(TELEMETRY_WRITE_FAILURES)
    rationale,tasks,model=ai.generate_plan(goal)
    assert model=="model" and rationale=="valid" and len(tasks)==12
    assert _counter_value(TELEMETRY_WRITE_FAILURES)>before
    assert "secret-content-must-not-log" not in caplog.text
    settings.openai_api_key=None
    _,fallback_tasks,fallback_model=ai.generate_plan(goal)
    assert fallback_model=="local-fallback" and fallback_tasks


def test_schema_failure_has_one_logical_outcome_and_one_attempt(tmp_path,monkeypatch):
    settings=SimpleNamespace(database_path=tmp_path/"telemetry.db",database_url=None,openai_api_key="key",
        openai_model="model",openai_temperature=0,ai_input_cost_per_million=0,ai_output_cost_per_million=0)
    monkeypatch.setattr(db,"settings",settings); monkeypatch.setattr(ai,"settings",settings); db.init_db()
    response=SimpleNamespace(output_text=json.dumps({"reply":"x"}),usage=None)
    monkeypatch.setattr(ai,"_client",lambda:SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs:response)))
    with ai.ai_run_context("correlation","logical"):
        assert ai._pydantic_call("TEACHING","missing","v","prompt",ai.TeachingOutput) is None
        ai._run_fallback("TEACHING", lambda: "fallback")
    logical=repository.list_ai_logical_requests_for_correlation("correlation")
    attempts=repository.list_ai_runs_for_correlation("correlation")
    assert len(logical)==1 and logical[0]["final_outcome"]=="FALLBACK_SUCCESS" and logical[0]["schema_failure"]
    assert logical[0]["attempt_count"]==1 and len(attempts)==1 and attempts[0]["status"]=="SCHEMA_FAILURE"


def test_atomic_finalize_is_idempotent_and_rejects_conflict(tmp_path, monkeypatch):
    settings=SimpleNamespace(database_path=tmp_path/"atomic.db",database_url=None)
    monkeypatch.setattr(db,"settings",settings); monkeypatch.setattr(repository,"settings",settings); db.init_db()
    repository.start_ai_logical_request("logical","correlation","TEACHING","missing","v")
    assert repository.finalize_ai_logical_request("logical","MODEL_SUCCESS")=="FINALIZED"
    assert repository.finalize_ai_logical_request("logical","MODEL_SUCCESS")=="ALREADY_FINALIZED"
    assert repository.finalize_ai_logical_request("logical","FALLBACK_SUCCESS")=="CONFLICT"
    assert repository.get_ai_logical_request("logical")["final_outcome"]=="MODEL_SUCCESS"


def test_concurrent_finalize_has_one_winner(tmp_path, monkeypatch):
    settings=SimpleNamespace(database_path=tmp_path/"concurrent.db",database_url=None)
    monkeypatch.setattr(db,"settings",settings); monkeypatch.setattr(repository,"settings",settings); db.init_db()
    repository.start_ai_logical_request("logical","correlation","TEACHING","missing","v")
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses=list(pool.map(lambda outcome: repository.finalize_ai_logical_request("logical",outcome),
                               ["MODEL_SUCCESS","FALLBACK_SUCCESS"]))
    assert statuses.count("FINALIZED")==1 and statuses.count("CONFLICT")==1


def test_incomplete_and_stale_are_excluded_from_completed_denominator(tmp_path, monkeypatch):
    settings=SimpleNamespace(database_path=tmp_path/"stale.db",database_url=None,
                             ai_logical_request_stale_seconds=60)
    monkeypatch.setattr(db,"settings",settings)
    monkeypatch.setattr(repository,"settings",settings)
    db.init_db()
    user=repository.create_user("stale@example.com","!","Stale")
    repository.start_ai_logical_request("logical","correlation","OTHER",user["id"],"v")
    old=(datetime.now(timezone.utc)-timedelta(minutes=2)).isoformat()
    with db.connection() as conn:
        conn.execute("UPDATE ai_logical_requests SET started_at=?,user_id=? WHERE logical_request_id=?",
                     (old,user["id"],"logical"))
    summary=repository.metrics_summary(user["id"])
    assert summary["completed_count"]==0 and summary["incomplete_count"]==1
    assert summary["stale_incomplete_count"]==1 and summary["fallback_rate"] is None


def test_attempt_requires_matching_logical_request(tmp_path, monkeypatch):
    settings=SimpleNamespace(database_path=tmp_path/"relations.db",database_url=None)
    monkeypatch.setattr(db,"settings",settings); db.init_db()
    with pytest.raises(ValueError,match="does not exist"):
        repository.save_ai_run("TEACHING","missing","FAILED","m","v",correlation_id="c",logical_request_id="none")
    repository.start_ai_logical_request("logical","c","TEACHING","missing","v")
    with pytest.raises(ValueError,match="correlation"):
        repository.save_ai_run("TEACHING","missing","FAILED","m","v",correlation_id="other",logical_request_id="logical")
    legacy=repository.save_ai_run("TEACHING","missing","FAILED","m","v")
    assert repository.latest_ai_run("TEACHING","missing")["attempt_id"]==legacy
    with pytest.raises(Exception):
        repository.save_ai_run("TEACHING","missing","FAILED","m","v",attempt_id=legacy)


def test_fallback_failure_finalizes_total_failure(tmp_path, monkeypatch):
    settings=SimpleNamespace(database_path=tmp_path/"fallback-failure.db",database_url=None,
        openai_api_key=None,openai_model="model")
    monkeypatch.setattr(db,"settings",settings); monkeypatch.setattr(ai,"settings",settings); db.init_db()
    with ai.ai_run_context("correlation","operation"):
        ai._start_request("TEACHING","missing","v")
        with pytest.raises(RuntimeError,match="fallback broke"):
            ai._run_fallback("TEACHING",lambda: (_ for _ in ()).throw(RuntimeError("fallback broke")))
    row=repository.list_ai_logical_requests_for_correlation("correlation")[0]
    assert row["final_outcome"]=="TOTAL_FAILURE"


def test_logical_metric_increments_only_for_first_finalize(tmp_path, monkeypatch):
    settings=SimpleNamespace(database_path=tmp_path/"metric-once.db",database_url=None)
    monkeypatch.setattr(db,"settings",settings); db.init_db()
    repository.start_ai_logical_request("logical","correlation","TEACHING","missing","v")
    before=AI_LOGICAL_REQUESTS.labels("TEACHING","MODEL_SUCCESS")._value.get()
    assert ai._finalize_request("logical","TEACHING","MODEL_SUCCESS")=="FINALIZED"
    assert ai._finalize_request("logical","TEACHING","MODEL_SUCCESS")=="ALREADY_FINALIZED"
    assert ai._finalize_request("logical","TEACHING","FALLBACK_SUCCESS")=="CONFLICT"
    after=AI_LOGICAL_REQUESTS.labels("TEACHING","MODEL_SUCCESS")._value.get()
    assert after-before==1


def test_attempt_user_isolation_and_summary_coverage(tmp_path, monkeypatch):
    settings=SimpleNamespace(database_path=tmp_path/"coverage.db",database_url=None,
                             ai_logical_request_stale_seconds=900)
    monkeypatch.setattr(db,"settings",settings); monkeypatch.setattr(repository,"settings",settings); db.init_db()
    alice=repository.create_user("alice-coverage@example.com","!","Alice")
    bob=repository.create_user("bob-coverage@example.com","!","Bob")
    def goal(user,title):
        return repository.create_goal({"title":title,"current_level":"beginner","desired_outcome":"demo",
            "deadline":"2027-01-01","weekly_hours":5,"daily_hours":1,"study_weekdays":[1,2,3,4,5],
            "timezone":"Asia/Shanghai","budget_derivation":"EXPLICIT_DAILY_WEEKDAYS","learning_preferences":""},user["id"])
    alice_goal,bob_goal=goal(alice,"Alice goal"),goal(bob,"Bob goal")
    repository.start_ai_logical_request("alice-op","alice-c","PLAN_GENERATION",alice_goal["id"],"v")
    repository.start_ai_logical_request("bob-op","bob-c","PLAN_GENERATION",bob_goal["id"],"v")
    repository.save_ai_run("PLAN_GENERATION",alice_goal["id"],"SUCCEEDED","a-model","v",latency_ms=11,
        provider="openai",input_tokens=10,output_tokens=5,estimated_cost=.001,
        correlation_id="alice-c",logical_request_id="alice-op")
    repository.save_ai_run("PLAN_GENERATION",bob_goal["id"],"FAILED","b-model","v",latency_ms=99,
        provider="openai",input_tokens=None,output_tokens=None,estimated_cost=None,
        correlation_id="bob-c",logical_request_id="bob-op")
    repository.finalize_ai_logical_request("alice-op","MODEL_SUCCESS",provider="openai",model="a-model")
    repository.finalize_ai_logical_request("bob-op","FALLBACK_SUCCESS",provider="local",model="local")
    with pytest.raises(ValueError,match="user"):
        repository.save_ai_run("PLAN_GENERATION",bob_goal["id"],"FAILED","bad","v",
            correlation_id="alice-c",logical_request_id="alice-op")
    a=repository.metrics_summary(alice["id"]); b=repository.metrics_summary(bob["id"])
    assert a["latency_ms"]["p50"]==11 and a["estimated_cost"]==.001
    assert a["usage_coverage_rate"]==1 and a["pricing_coverage_rate"]==1
    assert b["latency_ms"]["p50"]==99 and b["fallback_successes"]==1
    assert b["usage_coverage_rate"]==0 and b["pricing_coverage_rate"]==0


def test_summary_distinguishes_unavailable_retry_usage_cost_and_empty_latency(tmp_path,monkeypatch):
    settings=SimpleNamespace(database_path=tmp_path/"summary.db",database_url=None)
    monkeypatch.setattr(db,"settings",settings); db.init_db()
    summary=repository.metrics_summary("nobody")
    assert summary["retry_rate"] is None and not summary["retry_measurement_available"]
    assert summary["estimated_cost"] is None and not summary["cost_estimate_available"]
    assert not summary["usage_available"] and summary["latency_ms"]["sample_count"]==0
    assert summary["latency_ms"]["p50"] is None and summary["latency_ms"]["p95"] is None


def test_production_rejects_disabled_authentication():
    with pytest.raises(ValueError,match="AUTH_DISABLED"):
        Settings(environment="production",auth_disabled=True)


def test_metrics_summary_two_users_are_fully_isolated(client,goal_payload,monkeypatch):
    monkeypatch.setattr(auth,"settings",SimpleNamespace(auth_disabled=False,
        jwt_secret="test-secret-with-at-least-32-characters",jwt_expire_minutes=60))
    def register(name):
        data=client.post("/auth/register",json={"email":f"{name}@example.com","password":"secure-password-123",
            "display_name":name}).json()
        return {"Authorization":f"Bearer {data['access_token']}"}
    alice,bob=register("alice-metrics"),register("bob-metrics")
    alice_goal=client.post("/api/goals",json=goal_payload,headers=alice).json()
    client.post(f"/api/goals/{alice_goal['id']}/generate-plan",headers=alice)
    before=client.get("/api/internal/metrics-summary",headers=alice).json()
    bob_goal=client.post("/api/goals",json=goal_payload,headers=bob).json()
    plan=client.post(f"/api/goals/{bob_goal['id']}/generate-plan",headers=bob).json()
    session=client.post(f"/api/tasks/{plan['tasks'][0]['id']}/teaching-sessions",headers=bob).json()
    session=client.post(f"/api/teaching-sessions/{session['id']}/quizzes",headers=bob).json()
    quiz=next(item for item in session["quizzes"] if item["status"]=="ACTIVE")
    client.post(f"/api/teaching-sessions/{session['id']}/quizzes/{quiz['id']}/attempts",
        json={"answer":"不知道"},headers={**bob,"Idempotency-Key":"bob-attempt"})
    after=client.get("/api/internal/metrics-summary",headers=alice).json()
    bob_summary=client.get("/api/internal/metrics-summary",headers=bob).json()
    assert after==before and after["logical_requests"]==1 and after["quiz_attempts"]==0
    assert bob_summary["logical_requests"]>after["logical_requests"] and bob_summary["quiz_attempts"]==1
