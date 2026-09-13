from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import repository, services
from app.db import init_db
from app.schemas import GoalCreate, ReviewDecision, SubmissionCreate, TaskStatusUpdate


static_dir = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Mission Control AI", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(static_dir / "index.html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/goals")
def list_goals():
    return repository.list_goals()


@app.post("/api/goals", status_code=201)
def create_goal(payload: GoalCreate):
    return repository.create_goal(payload.model_dump())


@app.post("/api/goals/{goal_id}/generate-plan")
def generate_goal_plan(goal_id: str):
    try:
        return services.create_plan(goal_id)
    except services.NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/goals/{goal_id}/plan")
def get_goal_plan(goal_id: str):
    plan = services.decode_plan(repository.active_plan(goal_id))
    if not plan:
        raise HTTPException(404, "Active plan not found")
    return plan


@app.get("/api/today")
def today(goal_id: str = Query(...)):
    plan = services.decode_plan(repository.active_plan(goal_id))
    if not plan:
        raise HTTPException(404, "Active plan not found")
    current = [task for task in plan["tasks"] if task["status"] != "PASSED"][:3]
    return {"goal": repository.get_goal(goal_id), "plan_version": plan["version"], "tasks": current}


@app.patch("/api/tasks/{task_id}/status")
def update_task(task_id: str, payload: TaskStatusUpdate):
    task = repository.update_task_status(task_id, payload.status)
    if not task:
        raise HTTPException(404, "Task not found")
    return task


@app.post("/api/tasks/{task_id}/submissions", status_code=201)
def submit(task_id: str, payload: SubmissionCreate):
    try:
        data = payload.model_dump(mode="json")
        return services.submit_evidence(task_id, data)
    except services.NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/goals/{goal_id}/weekly-reviews", status_code=201)
def weekly_review(goal_id: str, week: int = Query(default=1, ge=1, le=4)):
    try:
        return services.build_weekly_review(goal_id, week)
    except services.NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/weekly-reviews/{review_id}/decision")
def review_decision(review_id: str, payload: ReviewDecision):
    try:
        return services.decide_review(review_id, payload.decision)
    except services.NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/internal/ai-runs")
def ai_runs():
    return repository.list_ai_runs()
