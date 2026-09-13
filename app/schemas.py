from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class GoalCreate(BaseModel):
    title: str = Field(min_length=2, max_length=120)
    current_level: str = Field(min_length=2, max_length=500)
    desired_outcome: str = Field(min_length=5, max_length=1000)
    deadline: date
    weekly_hours: int = Field(ge=1, le=80)
    learning_preferences: str = Field(default="", max_length=500)


class TaskStatusUpdate(BaseModel):
    status: Literal["TODO", "IN_PROGRESS"]


class SubmissionCreate(BaseModel):
    evidence_text: str = Field(min_length=10, max_length=10000)
    repository_url: HttpUrl | None = None
    actual_minutes: int = Field(ge=1, le=1440)


class ReviewDecision(BaseModel):
    decision: Literal["ACCEPT", "REJECT"]
