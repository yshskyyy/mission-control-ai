import json

from app import repository
from app.ai import assess, generate_plan


class NotFoundError(Exception):
    pass


def create_plan(goal_id: str) -> dict:
    goal = repository.get_goal(goal_id)
    if not goal:
        raise NotFoundError("Goal not found")
    rationale, tasks, evaluator = generate_plan(goal)
    max_minutes = goal["weekly_hours"] * 60
    for week in range(1, 5):
        week_tasks = [task for task in tasks if task["week_number"] == week]
        total = sum(task["estimated_minutes"] for task in week_tasks)
        if total > max_minutes and total:
            ratio = max_minutes / total
            for task in week_tasks:
                task["estimated_minutes"] = max(20, int(task["estimated_minutes"] * ratio))
    plan = repository.save_plan(goal_id, f"{rationale}（生成器：{evaluator}）", tasks)
    return decode_plan(plan)


def decode_plan(plan: dict | None) -> dict | None:
    if not plan:
        return None
    for task in plan["tasks"]:
        task["acceptance_criteria"] = json.loads(task["acceptance_criteria"])
    return plan


def submit_evidence(task_id: str, submission: dict) -> dict:
    task = repository.get_task(task_id)
    if not task:
        raise NotFoundError("Task not found")
    repository.update_task_status(task_id, "SUBMITTED")
    result, evaluator = assess(task, submission)
    return repository.save_assessment(task_id, submission, result, evaluator)


def build_weekly_review(goal_id: str, week_number: int = 1) -> dict:
    goal = repository.get_goal(goal_id)
    plan = repository.active_plan(goal_id)
    if not goal or not plan:
        raise NotFoundError("Goal or active plan not found")
    tasks = [task for task in plan["tasks"] if task["week_number"] == week_number]
    attempts = repository.task_attempts_for_goal(goal_id)
    completed = sum(task["status"] == "PASSED" for task in tasks)
    estimated = sum(task["estimated_minutes"] for task in tasks)
    actual = sum(attempt["actual_minutes"] for attempt in attempts if attempt["task_id"] in {t["id"] for t in tasks})
    incomplete = [task["title"] for task in tasks if task["status"] != "PASSED"]
    summary = f"第{week_number}周完成 {completed}/{len(tasks)} 个任务；预计 {estimated} 分钟，实际已记录 {actual} 分钟。"
    changes = (
        "保留未完成任务并降低下周新增内容，优先补齐：" + "、".join(incomplete)
        if incomplete else "本周任务全部通过，下一周按原计划推进。"
    )
    return repository.save_weekly_review(goal_id, week_number, summary, changes)


def decide_review(review_id: str, decision: str) -> dict:
    review = repository.get_weekly_review(review_id)
    if not review:
        raise NotFoundError("Review not found")
    if decision == "REJECT":
        return repository.set_review_decision(review_id, "REJECTED")
    current = repository.active_plan(review["goal_id"])
    remaining = []
    for task in current["tasks"]:
        if task["status"] != "PASSED":
            remaining.append({
                "week_number": max(1, task["week_number"] - review["week_number"]),
                "title": task["title"], "description": task["description"],
                "estimated_minutes": task["estimated_minutes"], "deliverable": task["deliverable"],
                "acceptance_criteria": json.loads(task["acceptance_criteria"]),
            })
    plan = repository.save_plan(review["goal_id"], review["proposed_changes"], remaining)
    repository.set_review_decision(review_id, "ACCEPTED", plan["id"])
    return repository.get_weekly_review(review_id)
