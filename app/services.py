import json
from uuid import uuid4

from app import repository
from app.ai import assess, generate_learning_module, generate_plan
from app.scheduling import SchedulingError, current_plan_week, local_today, schedule_tasks


class NotFoundError(Exception):
    pass


class PlanningError(Exception):
    def __init__(self, code: str, message: str, task: dict | None = None):
        super().__init__(message)
        self.code = code
        self.task = task


def _planner_split_oversized(tasks: list[dict], daily_minutes: int) -> list[dict]:
    """Planner-layer compatibility splitter; the date scheduler never changes task semantics."""
    stages = ("范围与准备", "核心实现", "验证与修正", "交付与复盘")
    result = []
    for task in tasks:
        if task["estimated_minutes"] <= daily_minutes:
            result.append(task)
            continue
        parts = (task["estimated_minutes"] + daily_minutes - 1) // daily_minutes
        remaining = task["estimated_minutes"]
        for index in range(parts):
            minutes = min(daily_minutes, remaining)
            stage = stages[min(index, len(stages) - 1)]
            child = dict(task)
            child.update({
                "title": f"{task['title']} · {stage} {index + 1}/{parts}",
                "description": f"{task['description']} 本子任务仅完成可独立验收的“{stage}”部分。",
                "estimated_minutes": minutes,
                "deliverable": f"{task['deliverable']} · {stage}成果",
                "acceptance_criteria": [
                    f"已提交“{stage}”独立产出",
                    "产出无需依赖未完成子任务即可复查",
                    *(task["acceptance_criteria"][:2]),
                ],
            })
            result.append(child)
            remaining -= minutes
    return result


def create_plan(goal_id: str) -> dict:
    goal = repository.get_goal(goal_id)
    if not goal:
        raise NotFoundError("Goal not found")
    for planner_attempt in range(2):
        rationale, tasks, evaluator = generate_plan(goal)
        oversized = next((task for task in tasks
                           if task["estimated_minutes"] > int(float(goal["daily_hours"]) * 60)), None)
        if not oversized:
            break
        goal = dict(goal)
        goal["planning_feedback"] = (
            f"上次任务“{oversized['title']}”过大。必须将它重新设计为多个可独立验收的小任务，"
            "每项都有不同的产出和 acceptance criteria。"
        )
    else:
        raise PlanningError("TASK_TOO_LARGE", "Planner 两次尝试后仍产生超过每日预算的任务", oversized)
    max_minutes = goal["weekly_hours"] * 60
    for week in range(1, 5):
        week_tasks = [task for task in tasks if task["week_number"] == week]
        total = sum(task["estimated_minutes"] for task in week_tasks)
        if total > max_minutes and total:
            ratio = max_minutes / total
            for task in week_tasks:
                task["estimated_minutes"] = max(20, int(task["estimated_minutes"] * ratio))
    try:
        tasks, risks, suggestions = schedule_tasks(tasks, goal)
    except SchedulingError as exc:
        raise PlanningError(exc.code, str(exc), exc.task) from exc
    plan = repository.save_plan(
        goal_id, f"{rationale}（生成器：{evaluator}）", tasks,
        planning_risks=risks, adjustment_suggestions=suggestions,
    )
    repository.upsert_knowledge_node(
        goal_id, goal["title"], "长期目标", goal["desired_outcome"], 100, "GOAL"
    )
    return decode_plan(plan)


def decode_plan(plan: dict | None) -> dict | None:
    if not plan:
        return None
    for task in plan["tasks"]:
        task["acceptance_criteria"] = json.loads(task["acceptance_criteria"])
    for key in ("planning_risks", "adjustment_suggestions"):
        if isinstance(plan.get(key), str):
            plan[key] = json.loads(plan[key])
    return plan


def submit_evidence(task_id: str, submission: dict) -> dict:
    task = repository.get_task_context(task_id)
    if not task:
        raise NotFoundError("Task not found")
    repository.update_task_status(task_id, "SUBMITTED")
    result, evaluator = assess(task, submission)
    saved = repository.save_assessment(task_id, submission, result, evaluator)
    node = repository.upsert_knowledge_node(
        task["goal_id"], task["title"], "计划任务", task["description"], 60, "PLAN"
    )
    root = repository.upsert_knowledge_node(
        task["goal_id"], repository.get_goal(task["goal_id"])["title"], "长期目标", source="GOAL"
    )
    repository.upsert_knowledge_edge(task["goal_id"], node["id"], root["id"], "PART_OF")
    repository.update_knowledge_mastery(task["goal_id"], task["title"], result["score"])
    return saved


def build_weekly_review(goal_id: str, week_number: int | None = None) -> dict:
    goal = repository.get_goal(goal_id)
    plan = repository.active_plan(goal_id)
    if not goal or not plan:
        raise NotFoundError("Goal or active plan not found")
    if week_number is None:
        week_number = current_plan_week(plan["tasks"], goal["timezone"])
    tasks = [task for task in plan["tasks"] if task["week_number"] == week_number]
    attempts = repository.task_attempts_for_goal(goal_id)
    completed = sum(task["status"] == "PASSED" for task in tasks)
    estimated = sum(task["estimated_minutes"] for task in tasks)
    actual = sum(attempt["actual_minutes"] for attempt in attempts if attempt["task_id"] in {t["id"] for t in tasks})
    incomplete = [task["title"] for task in tasks if task["status"] != "PASSED"]
    completion_rate = round(completed / len(tasks) * 100) if tasks else 0
    pace = round(actual / estimated * 100) if estimated else 0
    summary = (
        f"第{week_number}周完成 {completed}/{len(tasks)} 个任务（{completion_rate}%）；"
        f"预计 {estimated} 分钟，实际已记录 {actual} 分钟（{pace}%）。"
    )
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
    goal = repository.get_goal(review["goal_id"])
    remaining_source = [task for task in current["tasks"] if task["status"] != "PASSED"]
    remaining_weeks = max(1, 4 - review["week_number"])
    weekly_capacity = goal["weekly_hours"] * 60
    total_minutes = sum(task["estimated_minutes"] for task in remaining_source)
    available_minutes = weekly_capacity * remaining_weeks
    scale = min(1, available_minutes / total_minutes) if total_minutes else 1
    remaining = []
    target_week = 1
    used = 0
    for task in remaining_source:
        minutes = max(1, int(task["estimated_minutes"] * scale))
        if used and used + minutes > weekly_capacity and target_week < remaining_weeks:
            target_week += 1
            used = 0
        remaining.append({
                "week_number": target_week,
                "title": task["title"], "description": task["description"],
                "estimated_minutes": minutes, "deliverable": task["deliverable"],
                "acceptance_criteria": json.loads(task["acceptance_criteria"]),
                "status": task["status"],
            })
        used += minutes
    rationale = (
        f"动态调整自第 {review['week_number']} 周复盘：{review['proposed_changes']} "
        f"剩余 {len(remaining)} 项任务按每周 {weekly_capacity} 分钟容量重新排期。"
    )
    try:
        remaining, risks, suggestions = schedule_tasks(remaining, goal)
    except SchedulingError as exc:
        raise PlanningError(exc.code, str(exc), exc.task) from exc
    plan = repository.save_plan(
        review["goal_id"], rationale, remaining,
        planning_risks=risks, adjustment_suggestions=suggestions,
    )
    repository.set_review_decision(review_id, "ACCEPTED", plan["id"])
    return repository.get_weekly_review(review_id)


def start_teaching(task_id: str, user_id: str = "00000000-0000-0000-0000-000000000001") -> dict:
    task = repository.get_task(task_id)
    if not task:
        raise NotFoundError("Task not found")
    session = repository.create_teaching_session(task_id)
    from app.teaching_workflow import run_teaching_action
    return run_teaching_action(session["id"], user_id, "INIT")


def teaching_reply(session_id: str, content: str,
                   user_id: str = "00000000-0000-0000-0000-000000000001") -> dict:
    session = repository.get_teaching_session(session_id)
    if not session:
        raise NotFoundError("Teaching session not found")
    from app.teaching_workflow import run_teaching_action
    return run_teaching_action(
        session_id, user_id, "QUESTION", content=content, idempotency_key=str(uuid4())
    )


def reteach(session_id: str, user_id: str) -> dict:
    from app.teaching_workflow import run_teaching_action
    return run_teaching_action(session_id, user_id, "RETEACH")


def start_quiz(session_id: str, user_id: str) -> dict:
    from app.teaching_workflow import run_teaching_action
    return run_teaching_action(session_id, user_id, "START_QUIZ")


def submit_quiz_answer(session_id: str, quiz_id: str, answer: str,
                       idempotency_key: str, user_id: str) -> dict:
    from app.teaching_workflow import run_teaching_action
    return run_teaching_action(
        session_id, user_id, "ANSWER", content=answer, quiz_id=quiz_id,
        idempotency_key=idempotency_key,
    )


def continue_teaching(session_id: str, user_id: str) -> dict:
    from app.teaching_workflow import run_teaching_action
    return run_teaching_action(session_id, user_id, "CONTINUE")


def public_teaching_session(session: dict) -> dict:
    result = dict(session)
    result["quizzes"] = [
        {key: value for key, value in quiz.items() if key not in ("expected_answer", "rubric")}
        for quiz in session.get("quizzes", [])
    ]
    latest_runtime = next(({
        "provider": message.get("provider"), "model": message.get("model"),
        "prompt_version": message.get("prompt_version"),
        "fallback": message.get("provider") == "local",
    } for message in reversed(result.get("messages", [])) if message.get("provider")), None)
    result["runtime"] = latest_runtime or {
        "provider": "local", "model": "local", "prompt_version": None, "fallback": True,
    }
    return result


def decode_recommendation(item: dict) -> dict:
    result = dict(item)
    result["topics"] = json.loads(result["topics"])
    result["score_breakdown"] = json.loads(result["score_breakdown"])
    return result


def list_recommendations(goal_id: str) -> list[dict]:
    if not repository.get_goal(goal_id):
        raise NotFoundError("Goal not found")
    return [decode_recommendation(item) for item in repository.list_recommendations(goal_id)]


def refresh_recommendations(job_id: str) -> None:
    from app.workflows import run_recommendation_workflow
    run_recommendation_workflow(job_id)


def start_recommendation_refresh(goal_id: str, idempotency_key: str) -> dict:
    if not repository.get_goal(goal_id):
        raise NotFoundError("Goal not found")
    return repository.create_ingestion_job(goal_id, idempotency_key)


def decide_recommendation(recommendation_id: str, decision: str) -> dict:
    recommendation = repository.get_recommendation(recommendation_id)
    if not recommendation:
        raise NotFoundError("Recommendation not found")
    if recommendation["status"] in ("ACCEPTED", "DISMISSED"):
        return decode_recommendation(recommendation)
    if decision == "DISMISS":
        return decode_recommendation(
            repository.set_recommendation_decision(recommendation_id, "DISMISSED")
        )
    goal = repository.get_goal(recommendation["goal_id"])
    proposal, evaluator = generate_learning_module(goal, recommendation)
    module = repository.save_learning_module(
        goal["id"], recommendation_id, proposal["title"],
        f"{proposal['rationale']}（生成器：{evaluator}）", proposal["tasks"],
    )
    root = repository.upsert_knowledge_node(
        goal["id"], goal["title"], "长期目标", goal["desired_outcome"], 100, "GOAL"
    )
    for name in proposal["knowledge_nodes"]:
        node = repository.upsert_knowledge_node(
            goal["id"], name, "趋势学习", recommendation["summary"], 70, recommendation["source_type"]
        )
        repository.upsert_knowledge_edge(goal["id"], node["id"], root["id"], "PART_OF")
    _merge_module_into_plan(goal, module)
    return decode_recommendation(
        repository.set_recommendation_decision(recommendation_id, "ACCEPTED", module["id"])
    )


def _merge_module_into_plan(goal: dict, module: dict) -> dict:
    current = repository.active_plan(goal["id"])
    tasks = []
    if current:
        for task in current["tasks"]:
            if task["status"] == "PASSED":
                continue
            tasks.append({
                "title": task["title"], "description": task["description"],
                "estimated_minutes": task["estimated_minutes"], "deliverable": task["deliverable"],
                "acceptance_criteria": json.loads(task["acceptance_criteria"]), "status": task["status"],
            })
    for task in module["tasks"]:
        tasks.append({
            "title": task["title"], "description": task["description"],
            "estimated_minutes": task["estimated_minutes"], "deliverable": task["deliverable"],
            "acceptance_criteria": json.loads(task["acceptance_criteria"]), "status": "TODO",
        })
    weekly_capacity = goal["weekly_hours"] * 60
    total_capacity = weekly_capacity * 4
    total = sum(task["estimated_minutes"] for task in tasks)
    scale = min(1, total_capacity / total) if total else 1
    week, used = 1, 0
    for task in tasks:
        task["estimated_minutes"] = max(1, int(task["estimated_minutes"] * scale))
        if used and used + task["estimated_minutes"] > weekly_capacity and week < 4:
            week += 1
            used = 0
        task["week_number"] = week
        used += task["estimated_minutes"]
    tasks = _planner_split_oversized(tasks, int(float(goal["daily_hours"]) * 60))
    try:
        tasks, risks, suggestions = schedule_tasks(tasks, goal)
    except SchedulingError as exc:
        raise PlanningError(exc.code, str(exc), exc.task) from exc
    return repository.save_plan(
        goal["id"], f"接受趋势学习模块“{module['title']}”后按容量生成的新计划。", tasks,
        planning_risks=risks, adjustment_suggestions=suggestions,
    )


def knowledge_tree(goal_id: str) -> dict:
    if not repository.get_goal(goal_id):
        raise NotFoundError("Goal not found")
    return {"nodes": repository.list_knowledge_nodes(goal_id),
            "edges": repository.list_knowledge_edges(goal_id)}
