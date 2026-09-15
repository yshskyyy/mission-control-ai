from pathlib import Path
from contextlib import asynccontextmanager
import json

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from app import repository, services
from app.auth import (
    create_access_token, current_user, ensure_goal_owner, ensure_task_owner,
    hash_password, verify_password,
)
from app.db import init_db, new_id
from app.jobs import run_ingestion_locally
from app.observability import configure_observability
from app.queueing import enqueue_ingestion, QueueUnavailableError
from app.schemas import (
    GoalCreate, LoginRequest, RecommendationDecision, RegisterRequest, ReviewDecision, SubmissionCreate,
    QuizAnswerCreate, TaskStatusUpdate, TeachingMessageCreate,
)


static_dir = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Mission Control AI", version="2.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=static_dir), name="static")
app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")
configure_observability(app)


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(static_dir / "index.html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/auth/register", status_code=201)
def register(payload: RegisterRequest):
    if repository.get_user_by_email(payload.email):
        raise HTTPException(409, "Email already registered")
    user = repository.create_user(payload.email, hash_password(payload.password), payload.display_name)
    return {"access_token": create_access_token(user["id"]), "token_type": "bearer",
            "user": {k: user[k] for k in ("id", "email", "display_name")}}


@app.post("/auth/login")
def login(payload: LoginRequest):
    user = repository.get_user_by_email(payload.email)
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(401, "Invalid email or password")
    return {"access_token": create_access_token(user["id"]), "token_type": "bearer",
            "user": {k: user[k] for k in ("id", "email", "display_name")}}


@app.get("/auth/me")
def me(user: dict = Depends(current_user)):
    return {k: user[k] for k in ("id", "email", "display_name")}


@app.get("/api/goals")
def list_goals(user: dict = Depends(current_user)):
    return repository.list_goals(user["id"])


@app.post("/api/goals", status_code=201)
def create_goal(payload: GoalCreate, user: dict = Depends(current_user)):
    return repository.create_goal(payload.model_dump(), user["id"])


@app.post("/api/goals/{goal_id}/generate-plan")
async def generate_goal_plan(goal_id: str, user: dict = Depends(current_user)):
    ensure_goal_owner(goal_id, user)
    try:
        return await run_in_threadpool(services.create_plan, goal_id)
    except services.NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except services.PlanningError as exc:
        raise HTTPException(422, {"code": exc.code, "message": str(exc), "task": exc.task}) from exc


@app.get("/api/goals/{goal_id}/plan")
def get_goal_plan(goal_id: str, user: dict = Depends(current_user)):
    ensure_goal_owner(goal_id, user)
    plan = services.decode_plan(repository.active_plan(goal_id))
    if not plan:
        raise HTTPException(404, "Active plan not found")
    return plan


@app.get("/api/today")
def today(goal_id: str = Query(...), user: dict = Depends(current_user)):
    ensure_goal_owner(goal_id, user)
    plan = services.decode_plan(repository.active_plan(goal_id))
    if not plan:
        raise HTTPException(404, "Active plan not found")
    goal = repository.get_goal(goal_id)
    today_value = services.local_today(goal["timezone"]).isoformat()
    current = [task for task in plan["tasks"]
               if task["status"] != "PASSED" and task.get("scheduled_date") == today_value]
    scheduled_minutes = sum(task["estimated_minutes"] for task in current)
    return {"goal": goal, "plan_version": plan["version"], "tasks": current,
            "date": today_value, "scheduled_hours": round(scheduled_minutes / 60, 2),
            "daily_hours": goal["daily_hours"]}


@app.patch("/api/tasks/{task_id}/status")
def update_task(task_id: str, payload: TaskStatusUpdate, user: dict = Depends(current_user)):
    ensure_task_owner(task_id, user)
    task = repository.update_task_status(task_id, payload.status)
    if not task:
        raise HTTPException(404, "Task not found")
    return task


@app.post("/api/tasks/{task_id}/submissions", status_code=201)
async def submit(task_id: str, payload: SubmissionCreate, user: dict = Depends(current_user)):
    ensure_task_owner(task_id, user)
    try:
        data = payload.model_dump(mode="json")
        return await run_in_threadpool(services.submit_evidence, task_id, data)
    except services.NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/goals/{goal_id}/weekly-reviews", status_code=201)
def weekly_review(goal_id: str, week: int | None = Query(default=None, ge=1),
                  user: dict = Depends(current_user)):
    ensure_goal_owner(goal_id, user)
    try:
        return services.build_weekly_review(goal_id, week)
    except services.NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/weekly-reviews/{review_id}/decision")
def review_decision(review_id: str, payload: ReviewDecision, user: dict = Depends(current_user)):
    review = repository.get_weekly_review(review_id)
    if not review:
        raise HTTPException(404, "Review not found")
    ensure_goal_owner(review["goal_id"], user)
    try:
        return services.decide_review(review_id, payload.decision)
    except services.NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except services.PlanningError as exc:
        raise HTTPException(422, {"code": exc.code, "message": str(exc), "task": exc.task}) from exc


@app.post("/api/tasks/{task_id}/teaching-sessions", status_code=201)
async def start_teaching(task_id: str, user: dict = Depends(current_user)):
    ensure_task_owner(task_id, user)
    try:
        session = await run_in_threadpool(services.start_teaching, task_id, user["id"])
        return services.public_teaching_session(session)
    except services.NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/teaching-sessions/{session_id}")
def get_teaching(session_id: str, user: dict = Depends(current_user)):
    session = repository.get_teaching_session(session_id)
    if not session or not repository.get_goal(session["goal_id"], user["id"]):
        raise HTTPException(404, "Teaching session not found")
    return services.public_teaching_session(session)


@app.post("/api/teaching-sessions/{session_id}/messages", status_code=201)
async def teaching_message(session_id: str, payload: TeachingMessageCreate,
                     user: dict = Depends(current_user)):
    session = repository.get_teaching_session(session_id)
    if not session or not repository.get_goal(session["goal_id"], user["id"]):
        raise HTTPException(404, "Teaching session not found")
    try:
        session = await run_in_threadpool(
            services.teaching_reply, session_id, payload.content, user["id"]
        )
        return services.public_teaching_session(session)
    except services.NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


def _owned_teaching_session(session_id: str, user: dict) -> dict:
    session = repository.get_teaching_session(session_id)
    if not session or not repository.get_goal(session["goal_id"], user["id"]):
        raise HTTPException(404, "Teaching session not found")
    return session


@app.post("/api/teaching-sessions/{session_id}/reteach")
async def reteach_session(session_id: str, user: dict = Depends(current_user)):
    _owned_teaching_session(session_id, user)
    session = await run_in_threadpool(services.reteach, session_id, user["id"])
    return services.public_teaching_session(session)


@app.post("/api/teaching-sessions/{session_id}/quizzes", status_code=201)
async def create_teaching_quiz(session_id: str, user: dict = Depends(current_user)):
    _owned_teaching_session(session_id, user)
    session = await run_in_threadpool(services.start_quiz, session_id, user["id"])
    return services.public_teaching_session(session)


@app.post("/api/teaching-sessions/{session_id}/quizzes/{quiz_id}/attempts", status_code=201)
async def answer_teaching_quiz(
    session_id: str, quiz_id: str, payload: QuizAnswerCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=100),
    user: dict = Depends(current_user),
):
    _owned_teaching_session(session_id, user)
    session = await run_in_threadpool(
        services.submit_quiz_answer, session_id, quiz_id, payload.answer,
        idempotency_key or new_id(), user["id"],
    )
    return services.public_teaching_session(session)


@app.post("/api/teaching-sessions/{session_id}/continue")
async def continue_teaching_session(session_id: str, user: dict = Depends(current_user)):
    _owned_teaching_session(session_id, user)
    session = await run_in_threadpool(services.continue_teaching, session_id, user["id"])
    return services.public_teaching_session(session)


@app.post("/api/goals/{goal_id}/recommendations/refresh", status_code=202)
def refresh_recommendations(goal_id: str, background_tasks: BackgroundTasks,
                            idempotency_key: str | None = Header(
                                default=None, alias="Idempotency-Key", max_length=100
                            ),
                            user: dict = Depends(current_user)):
    ensure_goal_owner(goal_id, user)
    try:
        job = services.start_recommendation_refresh(goal_id, idempotency_key or new_id())
        if job["status"] != "PENDING":
            return job
        queued = repository.mark_ingestion_queued(job["id"])
        if not queued:
            return repository.get_ingestion_job(job["id"])
        try:
            if not enqueue_ingestion(job["id"]):
                background_tasks.add_task(run_ingestion_locally, job["id"])
        except QueueUnavailableError as exc:
            repository.mark_ingestion_failed(job["id"], str(exc))
            raise HTTPException(503, str(exc)) from exc
        return repository.get_ingestion_job(job["id"])
    except services.NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/ingestion-jobs/{job_id}")
def ingestion_job(job_id: str, user: dict = Depends(current_user)):
    job = repository.get_ingestion_job(job_id)
    if not job or not repository.get_goal(job["goal_id"], user["id"]):
        raise HTTPException(404, "Ingestion job not found")
    return job


@app.post("/api/ingestion-jobs/{job_id}/retry", status_code=202)
def retry_ingestion_job(job_id: str, background_tasks: BackgroundTasks,
                        user: dict = Depends(current_user)):
    job = repository.get_ingestion_job(job_id)
    if not job or not repository.get_goal(job["goal_id"], user["id"]):
        raise HTTPException(404, "Ingestion job not found")
    if job["status"] != "FAILED":
        raise HTTPException(409, "Only failed jobs can be retried")
    pending = repository.reset_ingestion_for_manual_retry(job_id)
    if not pending:
        raise HTTPException(409, "Job state changed; retry was not applied")
    queued = repository.mark_ingestion_queued(job_id)
    if not queued:
        raise HTTPException(409, "Job could not transition to QUEUED")
    try:
        if not enqueue_ingestion(job_id):
            background_tasks.add_task(run_ingestion_locally, job_id)
    except QueueUnavailableError as exc:
        repository.mark_ingestion_failed(job_id, str(exc))
        raise HTTPException(503, str(exc)) from exc
    return repository.get_ingestion_job(job_id)


@app.get("/api/goals/{goal_id}/recommendations")
def recommendations(goal_id: str, user: dict = Depends(current_user)):
    ensure_goal_owner(goal_id, user)
    try:
        return services.list_recommendations(goal_id)
    except services.NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/recommendations/{recommendation_id}/decision")
async def recommendation_decision(recommendation_id: str, payload: RecommendationDecision,
                            user: dict = Depends(current_user)):
    recommendation = repository.get_recommendation(recommendation_id)
    if not recommendation:
        raise HTTPException(404, "Recommendation not found")
    ensure_goal_owner(recommendation["goal_id"], user)
    try:
        return await run_in_threadpool(
            services.decide_recommendation, recommendation_id, payload.decision
        )
    except services.NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except services.PlanningError as exc:
        raise HTTPException(422, {"code": exc.code, "message": str(exc), "task": exc.task}) from exc


@app.get("/api/goals/{goal_id}/knowledge-tree")
def knowledge_tree(goal_id: str, user: dict = Depends(current_user)):
    ensure_goal_owner(goal_id, user)
    try:
        return services.knowledge_tree(goal_id)
    except services.NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/goals/{goal_id}/learning-modules")
def learning_modules(goal_id: str, user: dict = Depends(current_user)):
    ensure_goal_owner(goal_id, user)
    result = repository.list_learning_modules(goal_id)
    for module in result:
        for task in module["tasks"]:
            task["acceptance_criteria"] = json.loads(task["acceptance_criteria"])
    return result


@app.get("/api/internal/ai-runs")
def ai_runs(user: dict = Depends(current_user)):
    return repository.list_ai_runs(user_id=user["id"])


@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str):
    reserved = ("api", "auth", "docs", "redoc", "openapi.json", "health", "metrics", "assets", "static")
    first_segment = full_path.split("/", 1)[0]
    if first_segment in reserved:
        raise HTTPException(404, "Not found")
    return FileResponse(static_dir / "index.html")
