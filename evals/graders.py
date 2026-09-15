from typing import Any


def check(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": detail}


def grade_plan(goal: dict, plan: dict) -> list[dict]:
    tasks = plan["tasks"]
    budget = goal["weekly_hours"] * 60
    weekly = {
        week: sum(task["estimated_minutes"] for task in tasks if task["week_number"] == week)
        for week in range(1, 5)
    }
    return [
        check("task_count", 8 <= len(tasks) <= 12, f"count={len(tasks)}"),
        check("valid_weeks", all(1 <= task["week_number"] <= 4 for task in tasks),
              "all tasks must be in weeks 1-4"),
        check("weekly_budget", all(total <= budget for total in weekly.values()),
              f"budget={budget}, weekly={weekly}"),
        check("deliverables", all(task.get("deliverable", "").strip() for task in tasks),
              "every task needs a deliverable"),
        check("acceptance_criteria", all(len(task.get("acceptance_criteria", [])) >= 2 for task in tasks),
              "every task needs at least two criteria"),
    ]


def grade_teaching(case: dict, reply: str) -> list[dict]:
    forbidden = case.get("forbidden", [])
    return [
        check("non_empty", len(reply.strip()) >= 30, f"length={len(reply.strip())}"),
        check("has_example", any(word in reply for word in ("例子", "例如", "示例")),
              "reply should contain a concrete example"),
        check("asks_question", reply.count("？") + reply.count("?") == 1,
              "reply should ask exactly one check question"),
        check("task_grounded", any(term.lower() in reply.lower() for term in case["grounding_terms"]),
              f"expected one of {case['grounding_terms']}"),
        check("avoids_forbidden", not any(term.lower() in reply.lower() for term in forbidden),
              f"forbidden={forbidden}"),
    ]


def grade_assessment(case: dict, result: dict) -> list[dict]:
    return [
        check("expected_result", result["result"] == case["expected_result"],
              f"expected={case['expected_result']}, actual={result['result']}"),
        check("score_consistency",
              (result["result"] == "PASSED" and result["score"] >= 60) or
              (result["result"] == "NEEDS_REVISION" and result["score"] < 60),
              f"result={result['result']}, score={result['score']}"),
        check("criterion_coverage",
              len(result.get("criterion_results", [])) == len(case["task"]["acceptance_criteria"]),
              "each acceptance criterion must be graded"),
        check("feedback", bool(result.get("feedback", "").strip()), "feedback is required"),
    ]


def grade_recommendation(case: dict, ranked: list[dict]) -> list[dict]:
    top = ranked[0]
    scores = {item["external_id"]: item["score"] for item in ranked}
    return [
        check("expected_top", top["external_id"] == case["expected_top_external_id"],
              f"expected={case['expected_top_external_id']}, actual={top['external_id']}"),
        check("score_range", all(0 <= item["score"] <= 100 for item in ranked), str(scores)),
        check("breakdown", all(set(item["breakdown"]) == {
            "goal_relevance", "knowledge_gap", "practical_value", "trend_strength"
        } for item in ranked), "all four score components must be present"),
        check("explainable", all(item["reason"].strip() for item in ranked),
              "each candidate needs a reason"),
    ]
