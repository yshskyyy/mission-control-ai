from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash

from app import repository
from app.config import settings
from app.db import LOCAL_USER_ID


password_hash = PasswordHash.recommended()
bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    try:
        return password_hash.verify(password, encoded)
    except Exception:
        return False


def create_access_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id, "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
        "iss": "mission-control-ai",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> dict:
    if getattr(settings, "auth_disabled", False):
        return repository.get_user(LOCAL_USER_ID)
    if not credentials:
        raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = jwt.decode(
            credentials.credentials, settings.jwt_secret,
            algorithms=["HS256"], issuer="mission-control-ai",
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(401, "Invalid or expired token") from exc
    user = repository.get_user(payload.get("sub", ""))
    if not user or not user["is_active"]:
        raise HTTPException(401, "User is inactive or missing")
    return user


def ensure_goal_owner(goal_id: str, user: dict) -> dict:
    goal = repository.get_goal(goal_id, user["id"])
    if not goal:
        raise HTTPException(404, "Goal not found")
    return goal


def ensure_task_owner(task_id: str, user: dict) -> dict:
    task = repository.get_task_context(task_id)
    if not task or not repository.get_goal(task["goal_id"], user["id"]):
        raise HTTPException(404, "Task not found")
    return task
