import sqlite3
import os
from pathlib import Path
from typing import TypedDict

os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from app import db, intelligence, repository
from app.observability import WORKFLOW_FAILURES, WORKFLOW_RESUME


class RecommendationState(TypedDict, total=False):
    job_id: str
    goal_id: str
    items: list[dict]
    source_errors: list[str]
    recommendations_created: int


def _collect(state: RecommendationState) -> dict:
    items, errors = intelligence.collect_signals()
    if not items and errors:
        raise RuntimeError("；".join(errors))
    return {"items": items, "source_errors": errors}


def _score_and_persist(state: RecommendationState) -> dict:
    goal = repository.get_goal(state["goal_id"])
    nodes = repository.list_knowledge_nodes(state["goal_id"])
    created = 0
    for raw_item in state.get("items", []):
        item = repository.upsert_content_item(raw_item)
        score, breakdown, reason = intelligence.score_for_goal(raw_item, goal, nodes)
        if score < 45:
            continue
        repository.save_recommendation(goal["id"], item["id"], score, breakdown, reason)
        created += 1
    return {"recommendations_created": created}


def _finish(state: RecommendationState) -> dict:
    transitioned = repository.mark_ingestion_succeeded(
        state["job_id"], len(state.get("items", [])),
        state.get("recommendations_created", 0), "；".join(state.get("source_errors", [])) or None,
    )
    if not transitioned:
        raise RuntimeError("Ingestion job could not transition RUNNING -> SUCCEEDED")
    return {}


def _build_graph(checkpointer: SqliteSaver):
    builder = StateGraph(RecommendationState)
    builder.add_node("collect_signals", _collect)
    builder.add_node("score_and_persist", _score_and_persist)
    builder.add_node("finish", _finish)
    builder.add_edge(START, "collect_signals")
    builder.add_edge("collect_signals", "score_and_persist")
    builder.add_edge("score_and_persist", "finish")
    builder.add_edge("finish", END)
    return builder.compile(checkpointer=checkpointer)


def run_recommendation_workflow(job_id: str) -> None:
    job = repository.get_ingestion_job(job_id)
    if not job or job["status"] == "SUCCEEDED":
        return
    checkpoint_path = Path(db.settings.database_path).with_suffix(".workflows.db")
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(checkpoint_path, check_same_thread=False)
    try:
        graph = _build_graph(SqliteSaver(connection))
        config = {"configurable": {"thread_id": job_id}}
        snapshot = graph.get_state(config)
        if snapshot.next:
            WORKFLOW_RESUME.labels("recommendation").inc()
            graph.invoke(None, config=config)
        else:
            graph.invoke({"job_id": job_id, "goal_id": job["goal_id"]}, config=config)
    except Exception:
        WORKFLOW_FAILURES.labels("recommendation").inc()
        raise
    finally:
        connection.close()


def recommendation_checkpoint_evidence(job_id: str) -> dict:
    """Read persisted LangGraph checkpoint evidence without executing the graph."""
    checkpoint_path = Path(db.settings.database_path).with_suffix(".workflows.db")
    if not checkpoint_path.exists():
        return {"checkpoint_exists": False, "snapshot_next": [], "history": [],
                "limitation": "No checkpoint database exists."}
    connection = sqlite3.connect(checkpoint_path, check_same_thread=False)
    try:
        graph = _build_graph(SqliteSaver(connection))
        config = {"configurable": {"thread_id": job_id}}
        snapshot = graph.get_state(config)
        history = []
        for item in graph.get_state_history(config):
            history.append({"next": list(item.next), "values": dict(item.values),
                            "created_at": item.created_at})
        return {"checkpoint_exists": True, "snapshot_next": list(snapshot.next),
                "history": history,
                "limitation": "Same-process checkpoint reconnection; process restart is not exercised."}
    finally:
        connection.close()
