import json
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo
from pathlib import Path

from app import ai, db, intelligence, repository, services, workflows
from app.db import LOCAL_USER_ID
from app.schemas import GoalCreate
from evals.schemas import EvalCase, RAW_OUTPUT_SCHEMAS


PASSING_QUIZ_ANSWER = "输入是固定样例，操作是运行实现，结果是可观察输出，最后用测试验证。"

def _execution(suite: str, raw: dict, observation: dict, errors: list[str] | None = None) -> dict:
    try:
        RAW_OUTPUT_SCHEMAS[suite].model_validate(raw)
        validation = {"passed": True, "detail": f"valid raw {suite} production output"}
    except Exception as exc:
        validation = {"passed": False, "detail": f"{type(exc).__name__}: {str(exc)[:500]}"}
    return {"raw_production_output": raw, "raw_schema_validation": validation,
            "normalized_observation": observation if validation["passed"] else {},
            "normalization_errors": errors or []}

def _goal_payload(data: dict) -> dict:
    payload = dict(data)
    offset = payload.pop("deadline_offset_days", 120)
    reference = payload.pop("reference_date", "2026-01-15")
    if reference == "runtime":
        reference = "2026-01-15"
    payload["deadline"] = (date.fromisoformat(reference) + timedelta(days=offset)).isoformat()
    return GoalCreate.model_validate(payload).model_dump(mode="json")

def _reference_now(case: EvalCase) -> datetime:
    goal = case.input["goal"]
    reference = goal.get("reference_date", "2026-01-15")
    if reference == "runtime":
        reference = "2026-01-15"
    return datetime.combine(date.fromisoformat(reference), time(12), ZoneInfo(goal["timezone"]))

def _create_course(case: EvalCase) -> tuple[dict, dict, dict]:
    goal = repository.create_goal(_goal_payload(case.input["goal"]))
    with ai.logical_ai_request("planning:create-course"):
        plan = services.create_plan(goal["id"], now=_reference_now(case))
    with ai.logical_ai_request("teaching:generate-lesson"):
        session = services.start_teaching(plan["tasks"][0]["id"], LOCAL_USER_ID)
    return goal, plan, session

def run_teaching(case: EvalCase) -> dict:
    _, _, session = _create_course(case)
    previous = session["messages"][-1]["content"]
    with ai.logical_ai_request("teaching:specific-question"):
        session = services.teaching_reply(session["id"], case.input["specific_question"], LOCAL_USER_ID)
    specific = session["messages"][-1]["content"]
    ambiguous_previous = specific
    with ai.logical_ai_request("teaching:reference-question"):
        session = services.teaching_reply(session["id"], "什么意思", LOCAL_USER_ID)
    ambiguous = session["messages"][-1]["content"]
    mastery_before = session["mastery"]
    with ai.logical_ai_request("teaching:quiz-1"):
        session = services.start_quiz(session["id"], LOCAL_USER_ID)
    quiz = [q for q in session["quizzes"] if q["status"] == "ACTIVE"][-1]
    with ai.logical_ai_request("teaching:evaluate-wrong"):
        session = services.submit_quiz_answer(session["id"], quiz["id"], "我不知道",
                                               f"{case.id}-wrong", LOCAL_USER_ID)
    weak = session["quiz_attempts"][-1]["weak_points"]
    retry_quiz = [q for q in session["quizzes"] if q["status"] == "ACTIVE"][-1]
    with ai.logical_ai_request("teaching:evaluate-pass"):
        session = services.submit_quiz_answer(session["id"], retry_quiz["id"], PASSING_QUIZ_ANSWER,
                                               f"{case.id}-pass", LOCAL_USER_ID)
    reteach_messages = []
    for index in range(2):
        before = len(session["messages"])
        with ai.logical_ai_request(f"teaching:reteach-{index+1}"):
            session = services.reteach(session["id"], LOCAL_USER_ID)
        reteach_messages.extend(m for m in session["messages"][before:] if m["message_type"] == "RETEACH")
    observation={"section_count": len(session["sections"]), "specific_answer": specific,
            "ambiguous_answer": ambiguous, "previous_teacher_message": ambiguous_previous,
            "reteach_strategies": [m["teaching_strategy"] for m in reteach_messages],
            "weak_points": weak, "quiz_versions": [q["version"] for q in session["quizzes"]],
            "mastery_before": mastery_before, "mastery_after": session["mastery"],
            "final_status": session["status"], "attempt_count": len(session["quiz_attempts"]),
            "mastery_record_count": len(session["mastery_records"])}
    return _execution("teaching", observation, observation)

def run_planning(case: EvalCase) -> dict:
    goal = repository.create_goal(_goal_payload(case.input["goal"]))
    original = services.generate_plan
    if case.scenario == "task_too_large":
        oversized = [{"week_number": 1, "title": "不可分割的大任务", "description": "超过每日预算",
            "estimated_minutes": int(float(goal["daily_hours"])*60)+30, "deliverable": "完整成果",
            "acceptance_criteria": ["可运行", "可复查"]}]
        services.generate_plan = lambda current: ("injected oversized task", oversized, "injected")
    try:
        try:
            with ai.logical_ai_request("planning:create-plan"):
                plan = services.create_plan(goal["id"], now=_reference_now(case))
            observation={"outcome": "SUCCEEDED", "daily_hours": float(goal["daily_hours"]),
                "study_weekdays": goal["study_weekdays"], "deadline": str(goal["deadline"]),
                "tasks": plan["tasks"], "planning_risks": plan["planning_risks"],
                "adjustment_suggestions": plan["adjustment_suggestions"], "error_code": None}
            return _execution("planning", observation, observation)
        except services.PlanningError as exc:
            observation={"outcome": "REJECTED", "daily_hours": float(goal["daily_hours"]),
                "study_weekdays": goal["study_weekdays"], "deadline": str(goal["deadline"]),
                "tasks": [], "planning_risks": [], "adjustment_suggestions": [str(exc)],
                "error_code": exc.code}
            return _execution("planning", observation, observation)
    finally:
        services.generate_plan = original

def run_assessment(case: EvalCase) -> dict:
    task = dict(case.input["task"])
    task["acceptance_criteria"] = json.dumps(task["acceptance_criteria"], ensure_ascii=False)
    with ai.logical_ai_request("assessment:evaluate"):
        result, _ = ai.assess(task, case.input["submission"])
    return _execution("assessment", result, result)

def _signal() -> dict:
    return {"source_type":"GITHUB", "external_id":"checkpoint-real", "source_name":"GitHub",
        "title":"langgraph/reliable-agent", "url":"https://example.invalid/checkpoint",
        "summary":"checkpoint recovery", "topics":["langgraph"], "quality_score":90,
        "trend_score":80, "published_at":"2026-09-01T00:00:00Z"}

def run_workflow(case: EvalCase) -> dict:
    goal = repository.create_goal(_goal_payload(case.input["goal"]))
    job = services.start_recommendation_refresh(goal["id"], case.id)
    repository.mark_ingestion_queued(job["id"]); repository.start_ingestion_attempt(job["id"])
    collect_calls = 0; failure_calls = 0
    original_collect, original_save = intelligence.collect_signals, repository.save_recommendation
    def collect():
        nonlocal collect_calls; collect_calls += 1; return [_signal()], []
    def fail_once(*args, **kwargs):
        nonlocal failure_calls; failure_calls += 1
        if failure_calls == 1: raise TimeoutError(case.injected_failure or "injected failure")
        return original_save(*args, **kwargs)
    intelligence.collect_signals, repository.save_recommendation = collect, fail_once
    try:
        before=workflows.recommendation_checkpoint_evidence(job["id"])
        statuses=[repository.get_ingestion_job(job["id"])["status"]]
        side_effects=[len(repository.list_recommendations(goal["id"]))]
        try: workflows.run_recommendation_workflow(job["id"])
        except TimeoutError: pass
        after_failure=workflows.recommendation_checkpoint_evidence(job["id"])
        statuses.append(repository.get_ingestion_job(job["id"])["status"]); side_effects.append(len(repository.list_recommendations(goal["id"])))
        if case.input.get("simulate_checkpoint_loss"):
            Path(db.settings.database_path).with_suffix(".workflows.db").unlink(missing_ok=True)
        workflows.run_recommendation_workflow(job["id"])
        after_recovery=workflows.recommendation_checkpoint_evidence(job["id"])
        statuses.append(repository.get_ingestion_job(job["id"])["status"])
        first_count = len(repository.list_recommendations(goal["id"]))
        side_effects.append(first_count)
        workflows.run_recommendation_workflow(job["id"])
        after_duplicate=workflows.recommendation_checkpoint_evidence(job["id"])
        statuses.append(repository.get_ingestion_job(job["id"])["status"])
        second_count = len(repository.list_recommendations(goal["id"]))
        side_effects.append(second_count)
    finally:
        intelligence.collect_signals, repository.save_recommendation = original_collect, original_save
    raw={"before_failure":before,"after_failure":after_failure,"after_recovery":after_recovery,
         "after_duplicate_resume":after_duplicate,"job_statuses":statuses,
         "collect_calls":collect_calls,"side_effect_counts":side_effects}
    events=[{"sequence":index+1,"event":name,"job_status":status,"side_effect_count":count}
            for index,(name,status,count) in enumerate(zip(
                ["CHECKPOINT_ABSENT","CHECKPOINT_INTERRUPTED","CHECKPOINT_RECOVERED","DUPLICATE_RESUME_NOOP"],statuses,side_effects))]
    observation={"events":events, "collect_calls":collect_calls,
        "final_status":repository.get_ingestion_job(job["id"])["status"],
        "side_effect_count":second_count, "duplicate_side_effect_count":second_count-first_count}
    return _execution("workflow",raw,observation)

def run_recommendation(case: EvalCase) -> dict:
    ranked = []
    for candidate in case.input["candidates"]:
        raw = {**candidate, "source_type":"GITHUB", "source_name":"eval", "url":"https://example.invalid"}
        score, breakdown, reason = intelligence.score_for_goal(raw, case.input["goal"], case.input["nodes"])
        ranked.append({**candidate, "score":score, "breakdown":breakdown, "reason":reason})
    observation={"items":sorted(ranked, key=lambda item:item["score"], reverse=True)}
    return _execution("recommendation",observation,observation)

RUNNERS = {"teaching":run_teaching, "planning":run_planning, "assessment":run_assessment,
           "workflow":run_workflow, "recommendation":run_recommendation}
