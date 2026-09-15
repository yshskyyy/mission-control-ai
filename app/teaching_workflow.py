import os
import sqlite3
from pathlib import Path
from typing import Literal, TypedDict

os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from app import ai, db, repository


MAX_RETEACH_COUNT = 3


class TeachingState(TypedDict, total=False):
    user_id: str
    task_id: str
    teaching_session_id: str
    current_section_id: str
    lesson_progress: int
    last_user_action: str
    user_content: str
    quiz_id: str
    idempotency_key: str
    quiz_score: int
    weak_points: list[str]
    mastery: int
    retry_count: int
    status: str
    duplicate_submission: bool


def _task(state: TeachingState) -> dict:
    task = repository.get_task_context(state["task_id"])
    if not task:
        raise RuntimeError("Teaching task no longer exists")
    return task


def _teaching_context(session: dict, section_id: str) -> tuple[list[str], list[str]]:
    weak_points: list[str] = []
    for attempt in reversed(session.get("quiz_attempts", [])):
        quiz = next((item for item in session.get("quizzes", [])
                     if item["id"] == attempt["quiz_id"]), None)
        if quiz and quiz["section_id"] == section_id and not attempt["passed"]:
            weak_points = attempt["weak_points"]
            break
    strategies = [message["teaching_strategy"] for message in session.get("messages", [])
                  if message.get("section_id") == section_id and message.get("teaching_strategy")]
    return weak_points, strategies


def _runtime(task_id: str) -> dict:
    run = repository.latest_ai_run("TEACHING", task_id) or {}
    return {key: run.get(key) for key in ("provider", "model", "prompt_version", "fallback")}


def generate_lesson(state: TeachingState) -> dict:
    proposal, _ = ai.generate_lesson(_task(state))
    sections = repository.save_lesson_sections(
        state["teaching_session_id"], proposal["sections"]
    )
    return {"current_section_id": sections[0]["id"], "lesson_progress": 0,
            "status": "WAITING_USER"}


def teach_section(state: TeachingState) -> dict:
    if state.get("last_user_action") == "QUESTION":
        return {}
    section = repository.get_lesson_section(state["current_section_id"])
    content = (
        f"## {section['title']}\n\n目标：{section['objective']}\n\n{section['content']}"
        f"\n\n例子：{section['example']}\n\n理解检查：{section['check_question']}"
    )
    repository.add_teaching_message(
        state["teaching_session_id"], "TEACHER", content, section["id"], "TEACHING",
        teaching_strategy="step_by_step", runtime=_runtime(state["task_id"]),
    )
    reset_retry = 0 if state.get("last_user_action") == "CONTINUE" and state.get("status") == "WAITING_CHOICE" else None
    repository.update_teaching_state(
        state["teaching_session_id"], action=state.get("last_user_action", "INIT"),
        status="WAITING_USER", current_section_id=section["id"], retry_count=reset_retry,
    )
    return {"status": "WAITING_USER", **({"retry_count": 0} if reset_retry == 0 else {})}


def handle_question(state: TeachingState) -> dict:
    session = repository.get_teaching_session(state["teaching_session_id"])
    section = repository.get_lesson_section(state["current_section_id"])
    repository.add_teaching_message(
        state["teaching_session_id"], "USER", state["user_content"], section["id"], "QUESTION",
        state.get("idempotency_key"),
    )
    weak_points, used_strategies = _teaching_context(session, section["id"])
    reply, _, strategy = ai.answer_teaching_question(
        _task(state), section, session["messages"], state["user_content"],
        weak_points, session["mastery"], used_strategies,
    )
    repository.add_teaching_message(
        state["teaching_session_id"], "TEACHER", reply, section["id"], "ANSWER",
        teaching_strategy=strategy, runtime=_runtime(state["task_id"]),
    )
    repository.update_teaching_state(
        state["teaching_session_id"], action="QUESTION", status="WAITING_USER"
    )
    return {"status": "WAITING_USER"}


def generate_quiz(state: TeachingState) -> dict:
    section = repository.get_lesson_section(state["current_section_id"])
    session = repository.get_teaching_session(state["teaching_session_id"])
    version = 1 + sum(q["section_id"] == section["id"] for q in session["quizzes"])
    proposal, _ = ai.generate_section_quiz(_task(state), section, version)
    quiz = repository.create_quiz(
        state["teaching_session_id"], section["id"], proposal
    )
    repository.update_teaching_state(
        state["teaching_session_id"], action="START_QUIZ", status="WAITING_USER"
    )
    return {"quiz_id": quiz["id"], "status": "WAITING_USER"}


def evaluate_answer(state: TeachingState) -> dict:
    quiz = repository.get_quiz(state["quiz_id"])
    if not quiz or quiz["session_id"] != state["teaching_session_id"]:
        raise RuntimeError("Quiz does not belong to teaching session")
    existing = repository.get_quiz_attempt_by_key(quiz["id"], state["idempotency_key"])
    if existing:
        return {"quiz_score": existing["score"], "weak_points": existing["weak_points"],
                "duplicate_submission": True}
    section = repository.get_lesson_section(quiz["section_id"])
    evaluation, _ = ai.evaluate_quiz_answer(
        _task(state), section, quiz, state["user_content"]
    )
    attempt, created = repository.save_quiz_attempt(
        quiz["id"], state["idempotency_key"], state["user_content"], evaluation
    )
    if not created:
        return {"quiz_score": attempt["score"], "weak_points": attempt["weak_points"],
                "duplicate_submission": True}
    retry_count = 0 if attempt["passed"] else state.get("retry_count", 0) + 1
    repository.add_teaching_message(
        state["teaching_session_id"], "USER", state["user_content"], section["id"], "QUIZ_ANSWER",
        state["idempotency_key"],
    )
    repository.add_teaching_message(
        state["teaching_session_id"], "TEACHER", attempt["feedback"], section["id"], "QUIZ_FEEDBACK"
    )
    repository.update_teaching_state(
        state["teaching_session_id"], action="ANSWER", retry_count=retry_count,
        status="ACTIVE",
    )
    return {"quiz_score": attempt["score"], "weak_points": attempt["weak_points"],
            "retry_count": retry_count, "current_section_id": section["id"],
            "duplicate_submission": False}


def reteach_weak_point(state: TeachingState) -> dict:
    section = repository.get_lesson_section(state["current_section_id"])
    session = repository.get_teaching_session(state["teaching_session_id"])
    persisted_weak, used_strategies = _teaching_context(session, section["id"])
    weak_points = state.get("weak_points") or persisted_weak
    retry_count = state.get("retry_count", 0)
    if state.get("last_user_action") == "RETEACH":
        retry_count += 1
    reply, _, strategy = ai.reteach_section(
        _task(state), section, weak_points, session["mastery"],
        used_strategies, session["messages"],
    )
    repository.add_teaching_message(
        state["teaching_session_id"], "TEACHER", reply, section["id"], "RETEACH",
        teaching_strategy=strategy, runtime=_runtime(state["task_id"]),
    )
    repository.update_teaching_state(
        state["teaching_session_id"], action="RETEACH", retry_count=retry_count,
        status="ACTIVE",
    )
    return {"retry_count": retry_count, "status": "ACTIVE"}


def pause_for_choice(state: TeachingState) -> dict:
    repository.add_teaching_message(
        state["teaching_session_id"], "TEACHER",
        "本节已经连续重讲三次。你可以继续再学一次，或暂时返回任务补充实践证据。",
        state["current_section_id"], "SYSTEM",
    )
    repository.update_teaching_state(
        state["teaching_session_id"], action="MAX_RETRIES", status="WAITING_CHOICE",
        retry_count=state.get("retry_count", MAX_RETEACH_COUNT),
    )
    return {"status": "WAITING_CHOICE"}


def update_mastery(state: TeachingState) -> dict:
    session = repository.get_teaching_session(state["teaching_session_id"])
    attempt = session["quiz_attempts"][-1]
    repository.record_quiz_mastery(
        state["teaching_session_id"], state["current_section_id"], attempt
    )
    task = _task(state)
    repository.upsert_knowledge_node(
        task["goal_id"], task["title"], "计划任务", task["description"], 60, "TEACHING"
    )
    repository.update_knowledge_mastery(task["goal_id"], task["title"], attempt["score"])
    refreshed = repository.get_teaching_session(state["teaching_session_id"])
    return {"mastery": refreshed["mastery"], "retry_count": 0}


def complete_section(state: TeachingState) -> dict:
    session = repository.complete_current_section(state["teaching_session_id"])
    return {"current_section_id": session["current_section_id"],
            "lesson_progress": session["lesson_progress"], "status": session["status"],
            "retry_count": session["retry_count"], "mastery": session["mastery"]}


def complete_course(state: TeachingState) -> dict:
    repository.add_teaching_message(
        state["teaching_session_id"], "TEACHER",
        "课程已完成。现在可以返回任务页面，用提交证据完成最终验收。",
        state.get("current_section_id"), "SYSTEM",
    )
    repository.update_teaching_state(
        state["teaching_session_id"], action="COURSE_COMPLETED", status="COMPLETED"
    )
    return {"status": "COMPLETED"}


def _route_action(state: TeachingState) -> str:
    return {
        "INIT": "generate_lesson", "QUESTION": "handle_question",
        "RETEACH": "reteach_weak_point", "START_QUIZ": "generate_quiz",
        "ANSWER": "evaluate_answer", "CONTINUE": "teach_section",
    }[state["last_user_action"]]


def _after_evaluation(state: TeachingState) -> str:
    if state.get("duplicate_submission"):
        return "end"
    if state.get("quiz_score", 0) >= 75:
        return "update_mastery"
    if state.get("retry_count", 0) >= MAX_RETEACH_COUNT:
        return "pause_for_choice"
    return "reteach_weak_point"


def _after_reteach(state: TeachingState) -> str:
    if state.get("retry_count", 0) >= MAX_RETEACH_COUNT:
        return "pause_for_choice"
    return "generate_quiz" if state.get("last_user_action") == "ANSWER" else "end"


def _after_section(state: TeachingState) -> Literal["teach_section", "complete_course"]:
    return "complete_course" if state.get("status") == "COMPLETED" else "teach_section"


def _build_graph(checkpointer: SqliteSaver):
    graph = StateGraph(TeachingState)
    for name, node in (
        ("generate_lesson", generate_lesson), ("teach_section", teach_section),
        ("handle_question", handle_question), ("generate_quiz", generate_quiz),
        ("evaluate_answer", evaluate_answer), ("reteach_weak_point", reteach_weak_point),
        ("pause_for_choice", pause_for_choice), ("update_mastery", update_mastery),
        ("complete_section", complete_section), ("complete_course", complete_course),
    ):
        graph.add_node(name, node)
    graph.add_conditional_edges(START, _route_action)
    graph.add_edge("generate_lesson", "teach_section")
    graph.add_edge("handle_question", "teach_section")
    graph.add_conditional_edges("evaluate_answer", _after_evaluation, {
        "end": END, "update_mastery": "update_mastery",
        "pause_for_choice": "pause_for_choice", "reteach_weak_point": "reteach_weak_point",
    })
    graph.add_conditional_edges("reteach_weak_point", _after_reteach, {
        "end": END, "generate_quiz": "generate_quiz", "pause_for_choice": "pause_for_choice",
    })
    graph.add_edge("update_mastery", "complete_section")
    graph.add_conditional_edges("complete_section", _after_section)
    for node in ("teach_section", "generate_quiz", "pause_for_choice", "complete_course"):
        graph.add_edge(node, END)
    return graph.compile(checkpointer=checkpointer)


def run_teaching_action(session_id: str, user_id: str, action: str, *,
                        content: str = "", quiz_id: str = "",
                        idempotency_key: str = "") -> dict:
    session = repository.get_teaching_session(session_id)
    if not session:
        raise RuntimeError("Teaching session not found")
    state: TeachingState = {
        "user_id": user_id, "task_id": session["task_id"],
        "teaching_session_id": session_id,
        "current_section_id": session.get("current_section_id") or "",
        "lesson_progress": session["lesson_progress"], "last_user_action": action,
        "user_content": content, "quiz_id": quiz_id,
        "idempotency_key": idempotency_key, "quiz_score": 0,
        "weak_points": [], "mastery": session["mastery"],
        "retry_count": session["retry_count"], "status": session["status"],
        "duplicate_submission": False,
    }
    checkpoint_path = Path(db.settings.database_path).with_suffix(".teaching.workflows.db")
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(checkpoint_path, check_same_thread=False)
    try:
        graph = _build_graph(SqliteSaver(connection))
        graph.invoke(state, config={"configurable": {"thread_id": session_id}})
    finally:
        connection.close()
    return repository.get_teaching_session(session_id)
