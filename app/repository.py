import json

from app.db import LOCAL_USER_ID, connection, new_id, utc_now


def rows(items):
    return [dict(item) for item in items]


def decode_goal(row) -> dict | None:
    if not row:
        return None
    result = dict(row)
    if result.get("study_weekdays") and isinstance(result["study_weekdays"], str):
        result["study_weekdays"] = json.loads(result["study_weekdays"])
    if result.get("daily_hours") is not None:
        result["daily_hours"] = float(result["daily_hours"])
    if result.get("weekly_hours") is not None:
        result["weekly_hours"] = float(result["weekly_hours"])
    result["study_days_per_week"] = len(result.get("study_weekdays") or [])
    result["weekly_budget_hours"] = (
        result.get("daily_hours", 0) * result["study_days_per_week"]
    )
    return result


def create_goal(data: dict, user_id: str = LOCAL_USER_ID) -> dict:
    goal_id = new_id()
    with connection() as conn:
        conn.execute(
            """INSERT INTO learning_goals
            (id,user_id,title,current_level,desired_outcome,deadline,weekly_hours,daily_hours,
             study_weekdays,timezone,budget_derivation,learning_preferences,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                goal_id, user_id, data["title"], data["current_level"], data["desired_outcome"],
                str(data["deadline"]), data["weekly_hours"], data["daily_hours"],
                json.dumps(data["study_weekdays"]), data["timezone"], data["budget_derivation"],
                data["learning_preferences"], utc_now(),
            ),
        )
    return get_goal(goal_id)


def get_goal(goal_id: str, user_id: str | None = None) -> dict | None:
    with connection() as conn:
        if user_id:
            row = conn.execute(
                "SELECT * FROM learning_goals WHERE id=? AND user_id=?", (goal_id, user_id)
            ).fetchone()
        else:
            row = conn.execute("SELECT * FROM learning_goals WHERE id=?", (goal_id,)).fetchone()
    return decode_goal(row)


def list_goals(user_id: str | None = None) -> list[dict]:
    with connection() as conn:
        if user_id:
            result = conn.execute(
                "SELECT * FROM learning_goals WHERE user_id=? ORDER BY created_at DESC", (user_id,)
            ).fetchall()
        else:
            result = conn.execute("SELECT * FROM learning_goals ORDER BY created_at DESC").fetchall()
        return [decode_goal(row) for row in result]


def create_user(email: str, password_hash: str, display_name: str) -> dict:
    user_id = new_id()
    with connection() as conn:
        conn.execute(
            "INSERT INTO users VALUES (?,?,?,?,1,?)",
            (user_id, email.lower(), password_hash, display_name, utc_now()),
        )
    return get_user(user_id)


def get_user(user_id: str) -> dict | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_user_by_email(email: str) -> dict | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE email=?", (email.lower(),)).fetchone()
    return dict(row) if row else None


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


def save_plan(goal_id: str, rationale: str, tasks: list[dict], activate: bool = True,
              planning_risks: list[dict] | None = None,
              adjustment_suggestions: list[str] | None = None) -> dict:
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
            """INSERT INTO plan_versions
            (id,goal_id,version,status,rationale,planning_risks,adjustment_suggestions,created_at)
            VALUES (?,?,?,?,?,?,?,?)""",
            (plan_id, goal_id, version, "ACTIVE" if activate else "DRAFT", rationale,
             json.dumps(planning_risks or [], ensure_ascii=False),
             json.dumps(adjustment_suggestions or [], ensure_ascii=False), utc_now()),
        )
        for position, task in enumerate(tasks, start=1):
            conn.execute(
                """INSERT INTO learning_tasks
                (id,plan_version_id,week_number,position,title,description,estimated_minutes,
                deliverable,acceptance_criteria,status,scheduled_date,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    new_id(), plan_id, task["week_number"], position, task["title"],
                    task["description"], task["estimated_minutes"], task["deliverable"],
                    json.dumps(task["acceptance_criteria"], ensure_ascii=False),
                    task.get("status", "TODO"), task["scheduled_date"], utc_now(),
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


def get_task_context(task_id: str) -> dict | None:
    with connection() as conn:
        row = conn.execute(
            """SELECT lt.*,pv.goal_id,lg.title AS goal_title,
            lg.current_level,lg.desired_outcome,lg.learning_preferences
            FROM learning_tasks lt JOIN plan_versions pv ON pv.id=lt.plan_version_id
            JOIN learning_goals lg ON lg.id=pv.goal_id WHERE lt.id=?""", (task_id,)
        ).fetchone()
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


def create_teaching_session(task_id: str) -> dict:
    session_id = new_id()
    now = utc_now()
    with connection() as conn:
        conn.execute(
            """INSERT INTO teaching_sessions
            (id,task_id,current_section_id,lesson_progress,last_user_action,retry_count,
             mastery,status,created_at,updated_at)
            VALUES (?,?,NULL,0,'INIT',0,0,'ACTIVE',?,?)""",
            (session_id, task_id, now, now),
        )
    return get_teaching_session(session_id)


def add_teaching_message(session_id: str, role: str, content: str,
                         section_id: str | None = None, message_type: str = "QUESTION",
                         idempotency_key: str | None = None,
                         teaching_strategy: str | None = None,
                         runtime: dict | None = None) -> dict:
    message_id = new_id()
    with connection() as conn:
        conn.execute(
            """INSERT INTO teaching_messages
            (id,session_id,section_id,role,message_type,content,idempotency_key,
             teaching_strategy,provider,model,prompt_version,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (message_id, session_id, section_id, role, message_type, content,
             idempotency_key, teaching_strategy,
             (runtime or {}).get("provider"), (runtime or {}).get("model"),
             (runtime or {}).get("prompt_version"), utc_now()),
        )
        row = conn.execute("SELECT * FROM teaching_messages WHERE id=?", (message_id,)).fetchone()
    return dict(row)


def get_teaching_session(session_id: str) -> dict | None:
    with connection() as conn:
        session = conn.execute(
            """SELECT ts.*,lt.title AS task_title,lt.description AS task_description,
            lt.deliverable,lt.acceptance_criteria,pv.goal_id
            FROM teaching_sessions ts JOIN learning_tasks lt ON lt.id=ts.task_id
            JOIN plan_versions pv ON pv.id=lt.plan_version_id
            WHERE ts.id=?""", (session_id,),
        ).fetchone()
        if not session:
            return None
        messages = conn.execute(
            "SELECT * FROM teaching_messages WHERE session_id=? ORDER BY rowid",
            (session_id,),
        ).fetchall()
        sections = conn.execute(
            "SELECT * FROM lesson_sections WHERE session_id=? ORDER BY position", (session_id,)
        ).fetchall()
        quizzes = conn.execute(
            "SELECT * FROM quizzes WHERE session_id=? ORDER BY created_at", (session_id,)
        ).fetchall()
        attempts = conn.execute(
            """SELECT qa.* FROM quiz_attempts qa JOIN quizzes q ON q.id=qa.quiz_id
            WHERE q.session_id=? ORDER BY qa.created_at""", (session_id,)
        ).fetchall()
        mastery = conn.execute(
            "SELECT * FROM mastery_records WHERE session_id=? ORDER BY created_at", (session_id,)
        ).fetchall()
    result = dict(session)
    result["messages"] = rows(messages)
    result["sections"] = rows(sections)
    result["quizzes"] = rows(quizzes)
    result["quiz_attempts"] = rows(attempts)
    result["mastery_records"] = rows(mastery)
    for quiz in result["quizzes"]:
        quiz["rubric"] = json.loads(quiz["rubric"])
    for attempt in result["quiz_attempts"]:
        attempt["weak_points"] = json.loads(attempt["weak_points"])
    return result


def save_lesson_sections(session_id: str, sections: list[dict]) -> list[dict]:
    with connection() as conn:
        existing = conn.execute(
            "SELECT id FROM lesson_sections WHERE session_id=? LIMIT 1", (session_id,)
        ).fetchone()
        if not existing:
            first_id = None
            for position, section in enumerate(sections, start=1):
                section_id = new_id()
                first_id = first_id or section_id
                conn.execute(
                    """INSERT INTO lesson_sections
                    (id,session_id,position,title,objective,content,example,check_question,
                     status,mastery,created_at) VALUES (?,?,?,?,?,?,?,?,?,0,?)""",
                    (section_id, session_id, position, section["title"], section["objective"],
                     section["content"], section["example"], section["check_question"],
                     "CURRENT" if position == 1 else "LOCKED", utc_now()),
                )
            conn.execute(
                """UPDATE teaching_sessions SET current_section_id=?,lesson_progress=0,
                status='WAITING_USER',updated_at=? WHERE id=?""",
                (first_id, utc_now(), session_id),
            )
    return list_lesson_sections(session_id)


def list_lesson_sections(session_id: str) -> list[dict]:
    with connection() as conn:
        return rows(conn.execute(
            "SELECT * FROM lesson_sections WHERE session_id=? ORDER BY position", (session_id,)
        ).fetchall())


def get_lesson_section(section_id: str) -> dict | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM lesson_sections WHERE id=?", (section_id,)).fetchone()
    return dict(row) if row else None


def update_teaching_state(session_id: str, *, action: str, status: str | None = None,
                          retry_count: int | None = None, mastery: int | None = None,
                          current_section_id: str | None = None,
                          lesson_progress: int | None = None) -> dict:
    fields, values = ["last_user_action=?", "updated_at=?"], [action, utc_now()]
    for name, value in (("status", status), ("retry_count", retry_count),
                        ("mastery", mastery), ("current_section_id", current_section_id),
                        ("lesson_progress", lesson_progress)):
        if value is not None:
            fields.append(f"{name}=?")
            values.append(value)
    values.append(session_id)
    with connection() as conn:
        conn.execute(f"UPDATE teaching_sessions SET {','.join(fields)} WHERE id=?", tuple(values))
    return get_teaching_session(session_id)


def create_quiz(session_id: str, section_id: str, proposal: dict) -> dict:
    quiz_id = new_id()
    with connection() as conn:
        version = conn.execute(
            "SELECT COALESCE(MAX(version),0)+1 FROM quizzes WHERE section_id=?", (section_id,)
        ).fetchone()[0]
        conn.execute("UPDATE quizzes SET status='GRADED' WHERE section_id=? AND status='ACTIVE'", (section_id,))
        conn.execute(
            """INSERT INTO quizzes
            (id,session_id,section_id,version,question,expected_answer,rubric,status,created_at)
            VALUES (?,?,?,?,?,?,?,'ACTIVE',?)""",
            (quiz_id, session_id, section_id, version, proposal["question"],
             proposal["expected_answer"], json.dumps(proposal["rubric"], ensure_ascii=False), utc_now()),
        )
    return get_quiz(quiz_id)


def get_quiz(quiz_id: str) -> dict | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM quizzes WHERE id=?", (quiz_id,)).fetchone()
    result = dict(row) if row else None
    if result:
        result["rubric"] = json.loads(result["rubric"])
    return result


def save_quiz_attempt(quiz_id: str, idempotency_key: str, answer: str,
                      evaluation: dict) -> tuple[dict, bool]:
    attempt_id = new_id()
    with connection() as conn:
        conn.execute(
            """INSERT INTO quiz_attempts
            (id,quiz_id,idempotency_key,answer,score,passed,feedback,weak_points,created_at)
            VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(quiz_id,idempotency_key) DO NOTHING""",
            (attempt_id, quiz_id, idempotency_key, answer, evaluation["score"],
             1 if evaluation["passed"] else 0, evaluation["feedback"],
             json.dumps(evaluation["weak_points"], ensure_ascii=False), utc_now()),
        )
        row = conn.execute(
            "SELECT * FROM quiz_attempts WHERE quiz_id=? AND idempotency_key=?",
            (quiz_id, idempotency_key),
        ).fetchone()
        if row["id"] == attempt_id:
            conn.execute("UPDATE quizzes SET status='GRADED' WHERE id=?", (quiz_id,))
    result = dict(row)
    result["weak_points"] = json.loads(result["weak_points"])
    return result, result["id"] == attempt_id


def get_quiz_attempt_by_key(quiz_id: str, idempotency_key: str) -> dict | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM quiz_attempts WHERE quiz_id=? AND idempotency_key=?",
            (quiz_id, idempotency_key),
        ).fetchone()
    if not row:
        return None
    result = dict(row)
    result["weak_points"] = json.loads(result["weak_points"])
    return result


def record_quiz_mastery(session_id: str, section_id: str, attempt: dict) -> dict:
    record_id = new_id()
    with connection() as conn:
        existing = conn.execute(
            "SELECT * FROM mastery_records WHERE source_attempt_id=?", (attempt["id"],)
        ).fetchone()
        if existing:
            return dict(existing)
        section = conn.execute("SELECT * FROM lesson_sections WHERE id=?", (section_id,)).fetchone()
        previous = section["mastery"]
        updated = max(previous, attempt["score"])
        conn.execute(
            """INSERT INTO mastery_records
            (id,session_id,section_id,source_attempt_id,previous_mastery,new_mastery,reason,created_at)
            VALUES (?,?,?,?,?,?,?,?)""",
            (record_id, session_id, section_id, attempt["id"], previous, updated,
             "Quiz passed" if attempt["passed"] else "Quiz evidence", utc_now()),
        )
        conn.execute("UPDATE lesson_sections SET mastery=? WHERE id=?", (updated, section_id))
        average = conn.execute(
            "SELECT COALESCE(AVG(mastery),0) FROM lesson_sections WHERE session_id=?", (session_id,)
        ).fetchone()[0]
        conn.execute(
            "UPDATE teaching_sessions SET mastery=?,updated_at=? WHERE id=?",
            (round(average), utc_now(), session_id),
        )
    return {"id": record_id, "session_id": session_id, "section_id": section_id,
            "source_attempt_id": attempt["id"], "previous_mastery": previous,
            "new_mastery": updated}


def complete_current_section(session_id: str) -> dict:
    with connection() as conn:
        session = conn.execute("SELECT * FROM teaching_sessions WHERE id=?", (session_id,)).fetchone()
        current = conn.execute(
            "SELECT * FROM lesson_sections WHERE id=?", (session["current_section_id"],)
        ).fetchone()
        conn.execute("UPDATE lesson_sections SET status='COMPLETED' WHERE id=?", (current["id"],))
        following = conn.execute(
            "SELECT * FROM lesson_sections WHERE session_id=? AND position>? ORDER BY position LIMIT 1",
            (session_id, current["position"]),
        ).fetchone()
        if following:
            conn.execute("UPDATE lesson_sections SET status='CURRENT' WHERE id=?", (following["id"],))
            conn.execute(
                """UPDATE teaching_sessions SET current_section_id=?,lesson_progress=?,retry_count=0,
                last_user_action='SECTION_COMPLETED',status='WAITING_USER',updated_at=? WHERE id=?""",
                (following["id"], current["position"], utc_now(), session_id),
            )
        else:
            conn.execute(
                """UPDATE teaching_sessions SET lesson_progress=?,retry_count=0,
                last_user_action='COURSE_COMPLETED',status='COMPLETED',updated_at=? WHERE id=?""",
                (current["position"], utc_now(), session_id),
            )
    return get_teaching_session(session_id)


def upsert_knowledge_node(goal_id: str, name: str, category: str, description: str = "",
                          priority: int = 50, source: str = "USER") -> dict:
    now = utc_now()
    with connection() as conn:
        conn.execute(
            """INSERT INTO knowledge_nodes
            (id,goal_id,name,category,description,mastery,confidence,priority,status,source,created_at,updated_at)
            VALUES (?,?,?,?,?,0,20,?,'DISCOVERED',?,?,?)
            ON CONFLICT(goal_id,name) DO UPDATE SET
              category=excluded.category,
              description=CASE WHEN excluded.description='' THEN knowledge_nodes.description ELSE excluded.description END,
              priority=MAX(knowledge_nodes.priority,excluded.priority),updated_at=excluded.updated_at""",
            (new_id(), goal_id, name, category, description, priority, source, now, now),
        )
        row = conn.execute(
            "SELECT * FROM knowledge_nodes WHERE goal_id=? AND name=?", (goal_id, name)
        ).fetchone()
    return dict(row)


def list_knowledge_nodes(goal_id: str) -> list[dict]:
    with connection() as conn:
        return rows(conn.execute(
            "SELECT * FROM knowledge_nodes WHERE goal_id=? ORDER BY priority DESC,name", (goal_id,)
        ).fetchall())


def list_knowledge_edges(goal_id: str) -> list[dict]:
    with connection() as conn:
        return rows(conn.execute(
            "SELECT * FROM knowledge_edges WHERE goal_id=? ORDER BY created_at", (goal_id,)
        ).fetchall())


def upsert_knowledge_edge(goal_id: str, source_node_id: str, target_node_id: str,
                          relation_type: str) -> dict:
    with connection() as conn:
        conn.execute(
            """INSERT INTO knowledge_edges VALUES (?,?,?,?,?,?)
            ON CONFLICT(source_node_id,target_node_id,relation_type) DO NOTHING""",
            (new_id(), goal_id, source_node_id, target_node_id, relation_type, utc_now()),
        )
        row = conn.execute(
            """SELECT * FROM knowledge_edges
            WHERE source_node_id=? AND target_node_id=? AND relation_type=?""",
            (source_node_id, target_node_id, relation_type),
        ).fetchone()
    return dict(row)


def update_knowledge_mastery(goal_id: str, name: str, score: int) -> dict | None:
    with connection() as conn:
        node = conn.execute(
            "SELECT * FROM knowledge_nodes WHERE goal_id=? AND name=?", (goal_id, name)
        ).fetchone()
        if not node:
            return None
        mastery = round(node["mastery"] * .6 + score * .4)
        confidence = min(100, node["confidence"] + 20)
        status = "MASTERED" if mastery >= 80 else "LEARNING" if mastery >= 30 else "REVIEW"
        conn.execute(
            "UPDATE knowledge_nodes SET mastery=?,confidence=?,status=?,updated_at=? WHERE id=?",
            (mastery, confidence, status, utc_now(), node["id"]),
        )
    return upsert_knowledge_node(goal_id, name, node["category"])


def upsert_content_item(item: dict) -> dict:
    with connection() as conn:
        conn.execute(
            """INSERT INTO content_items
            (id,source_type,external_id,source_name,title,url,summary,topics,quality_score,
             trend_score,published_at,discovered_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(source_type,external_id) DO UPDATE SET
              title=excluded.title,url=excluded.url,summary=excluded.summary,topics=excluded.topics,
              quality_score=excluded.quality_score,trend_score=excluded.trend_score,
              published_at=excluded.published_at""",
            (new_id(), item["source_type"], item["external_id"], item["source_name"],
             item["title"], item["url"], item.get("summary", ""),
             json.dumps(item.get("topics", []), ensure_ascii=False), item["quality_score"],
             item["trend_score"], item.get("published_at"), utc_now()),
        )
        row = conn.execute(
            "SELECT * FROM content_items WHERE source_type=? AND external_id=?",
            (item["source_type"], item["external_id"]),
        ).fetchone()
    return dict(row)


def save_recommendation(goal_id: str, content_item_id: str, score: int,
                        breakdown: dict, reason: str) -> dict:
    with connection() as conn:
        conn.execute(
            """INSERT INTO recommendations
            (id,goal_id,content_item_id,status,score,score_breakdown,reason,created_at)
            VALUES (?,?,?,'RECOMMENDED',?,?,?,?)
            ON CONFLICT(goal_id,content_item_id) DO UPDATE SET
              score=excluded.score,score_breakdown=excluded.score_breakdown,
              reason=excluded.reason,
              status=CASE WHEN recommendations.status IN ('ACCEPTED','DISMISSED')
                          THEN recommendations.status ELSE 'RECOMMENDED' END""",
            (new_id(), goal_id, content_item_id, score,
             json.dumps(breakdown, ensure_ascii=False), reason, utc_now()),
        )
        row = conn.execute(
            "SELECT * FROM recommendations WHERE goal_id=? AND content_item_id=?",
            (goal_id, content_item_id),
        ).fetchone()
    return dict(row)


def get_recommendation(recommendation_id: str) -> dict | None:
    with connection() as conn:
        row = conn.execute(
            """SELECT r.*,c.source_type,c.source_name,c.title AS content_title,c.url,
            c.summary,c.topics,c.quality_score,c.trend_score
            FROM recommendations r JOIN content_items c ON c.id=r.content_item_id
            WHERE r.id=?""", (recommendation_id,),
        ).fetchone()
    return dict(row) if row else None


def list_recommendations(goal_id: str) -> list[dict]:
    with connection() as conn:
        return rows(conn.execute(
            """SELECT r.*,c.source_type,c.source_name,c.title AS content_title,c.url,
            c.summary,c.topics,c.quality_score,c.trend_score
            FROM recommendations r JOIN content_items c ON c.id=r.content_item_id
            WHERE r.goal_id=? ORDER BY r.score DESC,r.created_at DESC""", (goal_id,),
        ).fetchall())


def set_recommendation_decision(recommendation_id: str, status: str,
                                module_id: str | None = None) -> dict | None:
    with connection() as conn:
        conn.execute(
            "UPDATE recommendations SET status=?,created_module_id=?,decided_at=? WHERE id=?",
            (status, module_id, utc_now(), recommendation_id),
        )
    return get_recommendation(recommendation_id)


def save_learning_module(goal_id: str, recommendation_id: str, title: str, rationale: str,
                         tasks: list[dict]) -> dict:
    module_id = new_id()
    with connection() as conn:
        conn.execute(
            "INSERT INTO learning_modules VALUES (?,?,?,?,?,?,'ACTIVE',?)",
            (module_id, goal_id, recommendation_id, title, rationale,
             sum(task["estimated_minutes"] for task in tasks), utc_now()),
        )
        for position, task in enumerate(tasks, start=1):
            conn.execute(
                "INSERT INTO module_tasks VALUES (?,?,?,?,?,?,?,?)",
                (new_id(), module_id, position, task["title"], task["description"],
                 task["estimated_minutes"], task["deliverable"],
                 json.dumps(task["acceptance_criteria"], ensure_ascii=False)),
            )
    return get_learning_module(module_id)


def get_learning_module(module_id: str) -> dict | None:
    with connection() as conn:
        module = conn.execute("SELECT * FROM learning_modules WHERE id=?", (module_id,)).fetchone()
        if not module:
            return None
        tasks = conn.execute(
            "SELECT * FROM module_tasks WHERE module_id=? ORDER BY position", (module_id,)
        ).fetchall()
    result = dict(module)
    result["tasks"] = rows(tasks)
    return result


def list_learning_modules(goal_id: str) -> list[dict]:
    with connection() as conn:
        ids = [row[0] for row in conn.execute(
            "SELECT id FROM learning_modules WHERE goal_id=? ORDER BY created_at DESC", (goal_id,)
        ).fetchall()]
    return [get_learning_module(module_id) for module_id in ids]


def create_ingestion_job(goal_id: str, idempotency_key: str) -> dict:
    candidate_id = new_id()
    with connection() as conn:
        conn.execute(
            """INSERT INTO ingestion_jobs
            (id,goal_id,status,idempotency_key,attempt_count,max_attempts,items_found,
             recommendations_created,error,created_at,finished_at)
            VALUES (?,?,'PENDING',?,0,3,0,0,NULL,?,NULL)
            ON CONFLICT(goal_id,idempotency_key) DO NOTHING""",
            (candidate_id, goal_id, idempotency_key, utc_now()),
        )
        existing = conn.execute(
            "SELECT id FROM ingestion_jobs WHERE goal_id=? AND idempotency_key=?",
            (goal_id, idempotency_key),
        ).fetchone()
        job_id = existing["id"]
    return get_ingestion_job(job_id)


def _transition_ingestion_job(job_id: str, expected: tuple[str, ...], status: str,
                              assignments: str = "", params: tuple = ()) -> dict | None:
    placeholders = ",".join("?" for _ in expected)
    suffix = f",{assignments}" if assignments else ""
    with connection() as conn:
        result = conn.execute(
            f"UPDATE ingestion_jobs SET status=?{suffix} WHERE id=? AND status IN ({placeholders})",
            (status, *params, job_id, *expected),
        )
    return get_ingestion_job(job_id) if result.rowcount == 1 else None


def mark_ingestion_queued(job_id: str) -> dict | None:
    return _transition_ingestion_job(
        job_id, ("PENDING",), "QUEUED", "error=NULL,finished_at=NULL"
    )


def start_ingestion_attempt(job_id: str) -> dict | None:
    return _transition_ingestion_job(
        job_id, ("QUEUED",), "RUNNING",
        "attempt_count=attempt_count+1,error=NULL,finished_at=NULL",
    )


def mark_ingestion_retryable(job_id: str, error: str) -> dict | None:
    with connection() as conn:
        result = conn.execute(
            """UPDATE ingestion_jobs SET status='QUEUED',error=?
            WHERE id=? AND status='RUNNING' AND attempt_count < max_attempts""",
            (error, job_id),
        )
    return get_ingestion_job(job_id) if result.rowcount == 1 else None


def mark_ingestion_failed(job_id: str, error: str) -> dict | None:
    with connection() as conn:
        result = conn.execute(
            """UPDATE ingestion_jobs SET status='FAILED',error=?,finished_at=?
            WHERE id=? AND status IN ('PENDING','QUEUED','RUNNING') AND
            (status!='RUNNING' OR attempt_count >= max_attempts)""",
            (error, utc_now(), job_id),
        )
    return get_ingestion_job(job_id) if result.rowcount == 1 else None


def mark_ingestion_succeeded(job_id: str, items_found: int,
                             recommendations_created: int, warning: str | None = None) -> dict | None:
    return _transition_ingestion_job(
        job_id, ("RUNNING",), "SUCCEEDED",
        "items_found=?,recommendations_created=?,error=?,finished_at=?",
        (items_found, recommendations_created, warning, utc_now()),
    )


def reset_ingestion_for_manual_retry(job_id: str) -> dict | None:
    return _transition_ingestion_job(
        job_id, ("FAILED",), "PENDING",
        "attempt_count=0,error=NULL,finished_at=NULL",
    )


def get_ingestion_job(job_id: str) -> dict | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM ingestion_jobs WHERE id=?", (job_id,)).fetchone()
    return dict(row) if row else None


def list_unfinished_ingestion_jobs() -> list[dict]:
    with connection() as conn:
        return rows(conn.execute(
            "SELECT * FROM ingestion_jobs WHERE status='PENDING' ORDER BY created_at"
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
    user_id = ai_run_user_id(run_type, entity_id)
    with connection() as conn:
        conn.execute(
            """INSERT INTO ai_runs
            (id,run_type,entity_id,status,model,prompt_version,latency_ms,error,created_at,user_id)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (new_id(), run_type, entity_id, status, model, prompt_version, latency_ms, error,
             utc_now(), user_id),
        )


def latest_ai_run(run_type: str, entity_id: str) -> dict | None:
    with connection() as conn:
        row = conn.execute(
            """SELECT status,model,prompt_version,latency_ms,error,created_at
            FROM ai_runs WHERE run_type=? AND entity_id=? ORDER BY created_at DESC,id DESC LIMIT 1""",
            (run_type, entity_id),
        ).fetchone()
    if not row:
        return None
    result = dict(row)
    result["provider"] = "local" if result["status"] == "FALLBACK" else "openai"
    result["fallback"] = result["status"] == "FALLBACK"
    return result


def ai_run_user_id(run_type: str, entity_id: str) -> str | None:
    with connection() as conn:
        if run_type == "PLAN_GENERATION":
            row = conn.execute("SELECT user_id FROM learning_goals WHERE id=?", (entity_id,)).fetchone()
        elif run_type in ("ASSESSMENT", "TEACHING", "QUIZ_GENERATION", "QUIZ_EVALUATION"):
            row = conn.execute(
                """SELECT lg.user_id FROM learning_tasks lt
                JOIN plan_versions pv ON pv.id=lt.plan_version_id
                JOIN learning_goals lg ON lg.id=pv.goal_id WHERE lt.id=?""", (entity_id,)
            ).fetchone()
        elif run_type == "MODULE_GENERATION":
            row = conn.execute(
                """SELECT lg.user_id FROM recommendations r
                JOIN learning_goals lg ON lg.id=r.goal_id WHERE r.id=?""", (entity_id,)
            ).fetchone()
        else:
            row = None
    return row["user_id"] if row else None


def list_ai_runs(limit: int = 50, user_id: str | None = None) -> list[dict]:
    with connection() as conn:
        if user_id:
            result = conn.execute(
                "SELECT * FROM ai_runs WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        else:
            result = conn.execute(
                "SELECT * FROM ai_runs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return rows(result)
