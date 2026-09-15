from datetime import date
from math import ceil, floor
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, HttpUrl, model_validator


class GoalCreate(BaseModel):
    title: str = Field(min_length=2, max_length=120)
    current_level: str = Field(min_length=2, max_length=500)
    desired_outcome: str = Field(min_length=5, max_length=1000)
    deadline: date
    daily_hours: float | None = Field(default=None, ge=0.5, le=12)
    study_weekdays: list[int] | None = Field(default=None, min_length=1, max_length=7)
    study_days_per_week: int | None = Field(default=None, ge=1, le=7)
    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=64)
    weekly_hours: float | None = Field(default=None, ge=1, le=80)
    budget_derivation: str | None = None
    learning_preferences: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def normalize_schedule(self):
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
        if self.study_weekdays is not None:
            if any(day < 1 or day > 7 for day in self.study_weekdays):
                raise ValueError("study_weekdays must use ISO weekdays 1 (Monday) through 7 (Sunday)")
            if len(set(self.study_weekdays)) != len(self.study_weekdays):
                raise ValueError("study_weekdays cannot contain duplicates")
            self.study_weekdays = sorted(self.study_weekdays)
            if self.study_days_per_week is not None and self.study_days_per_week != len(self.study_weekdays):
                raise ValueError("study_days_per_week must match study_weekdays")
            self.study_days_per_week = len(self.study_weekdays)
        elif self.study_days_per_week is not None:
            self.study_weekdays = list(range(1, self.study_days_per_week + 1))
        if self.daily_hours is not None:
            if not self.study_weekdays:
                raise ValueError("study_weekdays or study_days_per_week is required with daily_hours")
            self.weekly_hours = self.daily_hours * len(self.study_weekdays)
            self.budget_derivation = "DAILY_HOURS_X_EXPLICIT_WEEKDAYS"
            return self
        if self.weekly_hours is None:
            raise ValueError("daily_hours or legacy weekly_hours is required")
        valid_days = [day for day in range(1, 8) if 0.5 <= self.weekly_hours / day <= 12]
        days = min(valid_days, key=lambda day: (abs(day - 5), -day))
        self.study_weekdays = list(range(1, days + 1))
        self.study_days_per_week = days
        self.daily_hours = self.weekly_hours / days
        self.budget_derivation = "LEGACY_WEEKLY_PREFER_FIVE_WEEKDAYS_EXACT_BUDGET"
        return self


class TaskStatusUpdate(BaseModel):
    status: Literal["TODO", "IN_PROGRESS"]


class SubmissionCreate(BaseModel):
    evidence_text: str = Field(min_length=10, max_length=10000)
    repository_url: HttpUrl | None = None
    actual_minutes: int = Field(ge=1, le=1440)


class ReviewDecision(BaseModel):
    decision: Literal["ACCEPT", "REJECT"]


class TeachingMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class QuizAnswerCreate(BaseModel):
    answer: str = Field(min_length=1, max_length=4000)


class RecommendationDecision(BaseModel):
    decision: Literal["ACCEPT", "DISMISS"]


class RegisterRequest(BaseModel):
    email: str = Field(min_length=5, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    password: str = Field(min_length=10, max_length=128)
    display_name: str = Field(min_length=2, max_length=80)


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=1, max_length=128)
