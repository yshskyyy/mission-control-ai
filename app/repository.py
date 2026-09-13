import json

from app.db import connection, new_id, utc_now


def rows(items):
    return [dict(item) for item in items]


def create_goal(data: dict) -> dict:
    goal_id = new_id()
    with connection() as conn:
        conn.execute(
            """INSERT INTO learning_goals
            (id,title,current_level,desired_outcome,deadline,weekly_hours,learning_preferences,created_at)
            VALUES (?,?,?,?,?,?,?,?)""",
            (
                goal_id, data["title"], data["current_level"], data["desired_outcome"],
                str(data["deadline"]), data["weekly_hours"], data["learning_preferences"], utc_now(),
            ),
        )
    return get_goal(goal_id)


def get_goal(goal_id: str) -> dict | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM learning_goals WHERE id=?", (goal_id,)).fetchone()
    return dict(row) if row else None


def list_goals() -> list[dict]:
    with connection() as conn:
        return rows(conn.execute("SELECT * FROM learning_goals ORDER BY created_at DESC").fetchall())


def active_plan(goal_id: str) -> dict | None:
    with connection() as conn:
        plan = conn.execute(
            "SELECT * FROM plan_versions WHERE goal_id=? AND status='ACTIVE'", (goal_id,)
        ).fetchone()
        if not plan:
            return None
        tasks = conn.execute(
            "SELECT * FROM learning_tasks WHERE plan_version_id=? ORDER BY week_number,position",
            (plan["id"],),
        ).fetchall()
    result = dict(plan)
    result["tasks"] = rows(tasks)
    return result


def save_plan(goal_id: str, rationale: str, tasks: list[dict], activate: bool = True) -> dict:
    plan_id = new_id()
    with connection() as conn:
        version = conn.execute(
            "SELECT COALESCE(MAX(version),0)+1 FROM plan_versions WHERE goal_id=?", (goal_id,)
        ).fetchone()[0]
        if activate:
            conn.execute(
                "UPDATE plan_versions SET status='ARCHIVED' WHERE goal_id=? AND status='ACTIVE'",
                (goal_id,),
            )
        conn.execute(
            "INSERT INTO plan_versions VALUES (?,?,?,?,?,?)",
            (plan_id, goal_id, version, "ACTIVE" if activate else "DRAFT", rationale, utc_now()),
        )
        for position, task in enumerate(tasks, start=1):
            conn.execute(
                """INSERT INTO learning_tasks
                (id,plan_version_id,week_number,position,title,description,estimated_minutes,
                 deliverable,acceptance_criteria,status,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,'TODO',?)""",
                (
                    new_id(), plan_id, task["week_number"], position, task["title"],
                    task["description"], task["estimated_minutes"], task["deliverable"],
                    json.dumps(task["acceptance_criteria"], ensure_ascii=False), utc_now(),
                ),
            )
    return active_plan(goal_id) if activate else get_plan(plan_id)


def get_plan(plan_id: str) -> dict | None:
    with connection() as conn:
        plan = conn.execute("SELECT * FROM plan_versions WHERE id=?", (plan_id,)).fetchone()
        if not plan:
            return None
        tasks = conn.execute(
            "SELECT * FROM learning_tasks WHERE plan_version_id=? ORDER BY week_number,position",
            (plan_id,),
        ).fetchall()
    result = dict(plan)
    result["tasks"] = rows(tasks)
    return result


def get_task(task_id: str) -> dict | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM learning_tasks WHERE id=?", (task_id,)).fetchone()
    return dict(row) if row else None


def update_task_status(task_id: str, status: str) -> dict | None:
    with connection() as conn:
        conn.execute("UPDATE learning_tasks SET status=? WHERE id=?", (status, task_id))
    return get_task(task_id)


def save_assessment(task_id: str, submission: dict, assessment: dict, evaluator: str) -> dict:
    attempt_id, assessment_id = new_id(), new_id()
    with connection() as conn:
        conn.execute(
            """INSERT INTO task_attempts
            (id,task_id,evidence_text,repository_url,actual_minutes,status,created_at)
            VALUES (?,?,?,?,?,'ASSESSED',?)""",
            (
                attempt_id, task_id, submission["evidence_text"], submission.get("repository_url"),
                submission["actual_minutes"], utc_now(),
            ),
        )
        conn.execute(
            """INSERT INTO assessments
            (id,attempt_id,result,score,feedback,criterion_results,evaluator,created_at)
            VALUES (?,?,?,?,?,?,?,?)""",
            (
                assessment_id, attempt_id, assessment["result"], assessment["score"],
                assessment["feedback"], json.dumps(assessment["criterion_results"], ensure_ascii=False),
                evaluator, utc_now(),
            ),
        )
        conn.execute(
            "UPDATE learning_tasks SET status=? WHERE id=?", (assessment["result"], task_id)
        )
    return {"assessment_id": assessment_id, "attempt_id": attempt_id, **assessment}


def task_attempts_for_goal(goal_id: str) -> list[dict]:
    with connection() as conn:
        return rows(conn.execute(
            """SELECT ta.*, lt.title, lt.status AS task_status, lt.estimated_minutes
            FROM task_attempts ta JOIN learning_tasks lt ON lt.id=ta.task_id
            JOIN plan_versions pv ON pv.id=lt.plan_version_id WHERE pv.goal_id=?""",
            (goal_id,),
        ).fetchall())


def save_weekly_review(goal_id: str, week_number: int, summary: str, changes: str) -> dict:
    review_id = new_id()
    with connection() as conn:
        conn.execute(
            "INSERT INTO weekly_reviews VALUES (?,?,?,?,?,'PENDING',NULL,?)",
            (review_id, goal_id, week_number, summary, changes, utc_now()),
        )
    return get_weekly_review(review_id)


def get_weekly_review(review_id: str) -> dict | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM weekly_reviews WHERE id=?", (review_id,)).fetchone()
    return dict(row) if row else None


def set_review_decision(review_id: str, status: str, plan_id: str | None = None) -> dict:
    with connection() as conn:
        conn.execute(
            "UPDATE weekly_reviews SET status=?,created_plan_version_id=? WHERE id=?",
            (status, plan_id, review_id),
        )
    return get_weekly_review(review_id)


def save_ai_run(run_type: str, entity_id: str, status: str, model: str, prompt_version: str,
                latency_ms: int = 0, error: str | None = None) -> None:
    with connection() as conn:
        conn.execute(
            "INSERT INTO ai_runs VALUES (?,?,?,?,?,?,?,?,?)",
            (new_id(), run_type, entity_id, status, model, prompt_version, latency_ms, error, utc_now()),
        )


def list_ai_runs(limit: int = 50) -> list[dict]:
    with connection() as conn:
        return rows(conn.execute(
            "SELECT * FROM ai_runs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall())
