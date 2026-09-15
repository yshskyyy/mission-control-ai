from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


class SchedulingError(ValueError):
    def __init__(self, code: str, message: str, task: dict | None = None):
        super().__init__(message)
        self.code = code
        self.task = task


def local_today(timezone: str, now: datetime | None = None) -> date:
    current = now or datetime.now(ZoneInfo(timezone))
    if current.tzinfo is None:
        current = current.replace(tzinfo=ZoneInfo(timezone))
    return current.astimezone(ZoneInfo(timezone)).date()


def schedule_tasks(tasks: list[dict], goal: dict, now: datetime | None = None) -> tuple[list[dict], list[dict], list[str]]:
    daily_minutes = int(float(goal["daily_hours"]) * 60)
    weekdays = set(goal["study_weekdays"] if isinstance(goal["study_weekdays"], list)
                   else __import__("json").loads(goal["study_weekdays"]))
    oversized = next((task for task in tasks if task["estimated_minutes"] > daily_minutes), None)
    if oversized:
        raise SchedulingError(
            "TASK_TOO_LARGE",
            f"任务“{oversized['title']}”预计 {oversized['estimated_minutes']} 分钟，超过每日 {daily_minutes} 分钟预算",
            oversized,
        )
    cursor = local_today(goal["timezone"], now)
    deadline = date.fromisoformat(str(goal["deadline"]))
    used_by_date: dict[date, int] = {}
    scheduled: list[dict] = []
    for original in tasks:
        task = dict(original)
        while True:
            if cursor.isoweekday() in weekdays:
                used = used_by_date.get(cursor, 0)
                if used + task["estimated_minutes"] <= daily_minutes:
                    used_by_date[cursor] = used + task["estimated_minutes"]
                    task["scheduled_date"] = cursor.isoformat()
                    scheduled.append(task)
                    break
            cursor += timedelta(days=1)
    overflow = [task for task in scheduled if date.fromisoformat(task["scheduled_date"]) > deadline]
    risks = []
    suggestions = []
    if overflow:
        risks.append({
            "code": "DEADLINE_RISK",
            "message": f"现有预算下有 {len(overflow)} 项任务将在截止日期后完成",
            "first_overflow_date": overflow[0]["scheduled_date"],
        })
        suggestions = ["延长截止日期", "增加每周学习日", "增加每天可用小时", "缩小目标范围"]
    return scheduled, risks, suggestions


def current_plan_week(tasks: list[dict], timezone: str, now: datetime | None = None) -> int:
    dates = sorted(date.fromisoformat(task["scheduled_date"]) for task in tasks if task.get("scheduled_date"))
    if not dates:
        return 1
    return max(1, (local_today(timezone, now) - dates[0]).days // 7 + 1)
