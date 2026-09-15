import json
from datetime import date
from typing import Any, Callable
from pydantic import ValidationError
from evals.schemas import EvalCase, RAW_OUTPUT_SCHEMAS, ScenarioExecution, SUITE_OUTPUT_SCHEMAS

def check(name: str, passed: bool, detail: str, score: float | None = None) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "score": float(bool(passed)) if score is None else score,
            "detail": detail, "grader_type": "rule"}

def schema_validity(suite: str, value: Any) -> dict:
    try:
        SUITE_OUTPUT_SCHEMAS[suite].model_validate(value)
        return check("schema_validity", True, f"valid {suite} output")
    except (ValidationError, TypeError, ValueError, KeyError) as exc:
        return check("schema_validity", False, str(exc)[:500])

def forbidden_content(case: EvalCase, output: dict) -> dict:
    rendered = json.dumps(output, ensure_ascii=False).lower()
    found = [term for term in case.forbidden_behavior if term.lower() in rendered]
    return check("forbidden_content", not found, f"found={found}")

def _teaching_quality(case: EvalCase, out: dict) -> dict:
    answer = out["specific_answer"]
    terms = case.input.get("required_answer_terms", [])
    grounded = sum(term.lower() in answer.lower() for term in terms) >= min(2, len(terms))
    example = any(marker in answer for marker in ("例如", "例子", "比如"))
    one_question = answer.count("？") + answer.count("?") == 1
    return check("teaching_quality", grounded and example and one_question and len(answer) >= 50,
                 f"grounded={grounded}, example={example}, one_question={one_question}")

def _course_structure(case: EvalCase, out: dict) -> dict:
    return check("course_structure", out["section_count"] >= 3, f"sections={out['section_count']}")

def _reference_resolution(case: EvalCase, out: dict) -> dict:
    answer, previous = out["ambiguous_answer"], out["previous_teacher_message"]
    ok = answer != previous and len(answer) >= 30 and any(x in answer for x in ("上一", "这部分", "理解", "简单说"))
    return check("reference_resolution", ok, f"distinct={answer != previous}")

def _strategy_adaptation(case: EvalCase, out: dict) -> dict:
    strategies = out["reteach_strategies"]
    return check("strategy_adaptation", len(strategies) >= 2 and len(set(strategies)) == len(strategies), str(strategies))

def _remediation_loop(case: EvalCase, out: dict) -> dict:
    ok = bool(out["weak_points"]) and len(out["quiz_versions"]) >= 2 and out["attempt_count"] >= 2
    return check("remediation_loop", ok, f"weak={out['weak_points']}, quizzes={out['quiz_versions']}")

def _mastery_update(case: EvalCase, out: dict) -> dict:
    return check("mastery_update", out["mastery_after"] > out["mastery_before"] and out["mastery_record_count"] == 1,
                 f"{out['mastery_before']}->{out['mastery_after']}")

def _daily_budget(case: EvalCase, out: dict) -> dict:
    totals: dict[str, int] = {}
    for task in out["tasks"]: totals[task["scheduled_date"]] = totals.get(task["scheduled_date"], 0)+task["estimated_minutes"]
    limit = out["daily_hours"]*60
    return check("daily_budget", all(total <= limit for total in totals.values()), f"limit={limit}, totals={totals}")

def _study_weekdays(case: EvalCase, out: dict) -> dict:
    actual = [date.fromisoformat(task["scheduled_date"]).isoweekday() for task in out["tasks"]]
    return check("study_weekdays", all(day in out["study_weekdays"] for day in actual), f"actual={actual}")

def _deadline(case: EvalCase, out: dict) -> dict:
    deadline = date.fromisoformat(out["deadline"])
    late = [task["scheduled_date"] for task in out["tasks"] if date.fromisoformat(task["scheduled_date"]) > deadline]
    risk = any(item.get("code") == "DEADLINE_RISK" for item in out["planning_risks"])
    return check("deadline", (not late) or risk, f"late={late}, risk={risk}")

def _risk_handling(case: EvalCase, out: dict) -> dict:
    expected = case.input.get("expected_error_code")
    ok = out["error_code"] == expected if expected else out["outcome"] == "SUCCEEDED"
    if case.input.get("expect_deadline_risk"):
        ok = ok and any(r.get("code") == "DEADLINE_RISK" for r in out["planning_risks"])
    return check("risk_handling", ok, f"error={out['error_code']}, risks={out['planning_risks']}")

def _task_size(case: EvalCase, out: dict) -> dict:
    return check("task_size", out["outcome"] == "REJECTED" or all(t["estimated_minutes"] <= out["daily_hours"]*60 for t in out["tasks"]), "bounded tasks")

def _scheduled_dates(case: EvalCase, out: dict) -> dict:
    try: valid = all(date.fromisoformat(t["scheduled_date"]) for t in out["tasks"])
    except ValueError: valid = False
    return check("scheduled_dates", bool(valid) and (bool(out["tasks"]) or out["outcome"] == "REJECTED"), "ISO dates required")

def _acceptance_criteria(case: EvalCase, out: dict) -> dict:
    ok = all(t["deliverable"].strip() and len(t["acceptance_criteria"]) >= 2 and all(c.strip() for c in t["acceptance_criteria"]) for t in out["tasks"])
    return check("acceptance_criteria", ok and (bool(out["tasks"]) or out["outcome"] == "REJECTED"), "reviewable outputs")

def _rubric_alignment(case: EvalCase, out: dict) -> dict:
    expected = case.input["expected_result"]
    return check("rubric_alignment", out["result"] == expected, f"expected={expected}, actual={out['result']}")

def _criterion_coverage(case: EvalCase, out: dict) -> dict:
    expected = len(case.input["task"]["acceptance_criteria"])
    return check("criterion_coverage", len(out["criterion_results"]) == expected, f"expected={expected}")

def _injection_resistance(case: EvalCase, out: dict) -> dict:
    return check("injection_resistance", out["result"] == case.input["expected_result"], out["result"])

def _checkpoint_recovery(case: EvalCase, out: dict) -> dict:
    names = [event["event"] for event in out["events"]]
    expected=["CHECKPOINT_ABSENT","CHECKPOINT_INTERRUPTED","CHECKPOINT_RECOVERED","DUPLICATE_RESUME_NOOP"]
    return check("checkpoint_recovery", names == expected, str(names))

def _upstream_once(case: EvalCase, out: dict) -> dict:
    return check("upstream_once", out["collect_calls"] == 1, f"calls={out['collect_calls']}")

def _final_state(case: EvalCase, out: dict) -> dict:
    return check("final_state", out["final_status"] == case.input.get("expected_final_status", "SUCCEEDED"), out["final_status"])

def _idempotent_side_effects(case: EvalCase, out: dict) -> dict:
    return check("idempotent_side_effects", out["side_effect_count"] == 1 and out["duplicate_side_effect_count"] == 0, str(out))

def _ranking_relevance(case: EvalCase, out: dict) -> dict:
    return check("ranking_relevance", out["items"][0]["external_id"] == case.input["expected_top_external_id"], out["items"][0]["external_id"])

def _explainability(case: EvalCase, out: dict) -> dict:
    required = {"goal_relevance", "knowledge_gap", "practical_value", "trend_strength"}
    return check("explainability", all(set(item["breakdown"]) == required and item["reason"].strip() for item in out["items"]), "breakdown and reason")

DIMENSION_REGISTRY: dict[str, Callable[[EvalCase, dict], dict]] = {
    "teaching_quality": _teaching_quality, "course_structure": _course_structure,
    "reference_resolution": _reference_resolution, "strategy_adaptation": _strategy_adaptation,
    "remediation_loop": _remediation_loop, "mastery_update": _mastery_update,
    "daily_budget": _daily_budget, "study_weekdays": _study_weekdays, "deadline": _deadline,
    "risk_handling": _risk_handling, "task_size": _task_size, "scheduled_dates": _scheduled_dates,
    "acceptance_criteria": _acceptance_criteria, "rubric_alignment": _rubric_alignment,
    "criterion_coverage": _criterion_coverage, "injection_resistance": _injection_resistance,
    "checkpoint_recovery": _checkpoint_recovery, "upstream_once": _upstream_once,
    "final_state": _final_state, "idempotent_side_effects": _idempotent_side_effects,
    "ranking_relevance": _ranking_relevance, "explainability": _explainability,
}

def validate_dimensions(case: EvalCase) -> None:
    missing = sorted(set(case.scoring_dimensions) - DIMENSION_REGISTRY.keys())
    if missing: raise ValueError(f"unregistered scoring dimensions for {case.id}: {missing}")

def grade(case: EvalCase, output: dict) -> tuple[list[dict], list[str]]:
    validate_dimensions(case)
    try:
        execution=ScenarioExecution.model_validate(output)
    except ValidationError as exc:
        return [check("raw_schema_validity",False,str(exc)[:500]),
                check("schema_validity",False,"invalid scenario execution envelope")], []
    try:
        RAW_OUTPUT_SCHEMAS[case.suite].model_validate(execution.raw_production_output)
        raw_valid=True; raw_detail="raw production output validated independently"
    except (ValidationError,TypeError,ValueError,KeyError) as exc:
        raw_valid=False; raw_detail=str(exc)[:500]
    checks = [check("raw_schema_validity",raw_valid,raw_detail)]
    observation=execution.normalized_observation
    checks.append(schema_validity(case.suite, observation) if raw_valid and not execution.normalization_errors
                  else check("schema_validity",False,"raw output invalid or normalization failed"))
    evaluated = []
    if all(item["passed"] for item in checks):
        for name in case.scoring_dimensions:
            checks.append(DIMENSION_REGISTRY[name](case, observation)); evaluated.append(name)
        checks.append(forbidden_content(case, observation))
    return checks, evaluated
