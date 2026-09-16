"""Add explicit learning availability and scheduled task dates.

Revision ID: 20260915_0005
"""
import json
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from alembic import op
import sqlalchemy as sa


revision = "20260915_0005"
down_revision = "20260915_0004"
branch_labels = None
depends_on = None


def _batch(table_name: str):
    # copy_from retains even unnamed CHECK constraints during SQLite table rebuilds.
    table = sa.Table(table_name, sa.MetaData(), autoload_with=op.get_bind())
    return op.batch_alter_table(table_name, copy_from=table)


def _legacy_schedule(weekly: Decimal) -> tuple[Decimal, list[int]]:
    valid = [day for day in range(1, 8) if Decimal("0.5") <= weekly / day <= 12]
    days = min(valid, key=lambda day: (abs(day - 5), -day))
    return weekly / days, list(range(1, days + 1))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    goal_columns = {column["name"]: column for column in inspector.get_columns("learning_goals")}
    checks = inspector.get_check_constraints("learning_goals")
    with _batch("learning_goals") as batch:
        for constraint in checks:
            sqltext = constraint.get("sqltext") or ""
            if "weekly_hours" in sqltext and "84" not in sqltext and constraint.get("name"):
                batch.drop_constraint(constraint["name"], type_="check")
        if isinstance(goal_columns["weekly_hours"]["type"], sa.Integer):
            batch.alter_column("weekly_hours", existing_type=sa.Integer(), type_=sa.Numeric(12, 6), nullable=False)
        if "daily_hours" not in goal_columns:
            batch.add_column(sa.Column("daily_hours", sa.Numeric(12, 6)))
        if "study_weekdays" not in goal_columns:
            batch.add_column(sa.Column("study_weekdays", sa.Text()))
        if "timezone" not in goal_columns:
            batch.add_column(sa.Column("timezone", sa.String(64), server_default="Asia/Shanghai"))
        if "budget_derivation" not in goal_columns:
            batch.add_column(sa.Column("budget_derivation", sa.String(80)))
        if not any("weekly_hours BETWEEN 0.5 AND 84" in (check.get("sqltext") or "") for check in checks):
            batch.create_check_constraint("ck_goal_weekly_hours_v2", "weekly_hours BETWEEN 0.5 AND 84")
        if not any("daily_hours" in (check.get("sqltext") or "") for check in checks):
            batch.create_check_constraint("ck_goal_daily_hours", "daily_hours BETWEEN 0.5 AND 12")
    goals = sa.Table("learning_goals", sa.MetaData(), autoload_with=bind)
    for row in bind.execute(sa.select(goals.c.id, goals.c.weekly_hours, goals.c.daily_hours)).mappings():
        if row["daily_hours"] is not None:
            continue
        daily, weekdays = _legacy_schedule(Decimal(str(row["weekly_hours"])))
        bind.execute(goals.update().where(goals.c.id == row["id"]).values(
            daily_hours=daily, study_weekdays=json.dumps(weekdays), timezone="Asia/Shanghai",
            budget_derivation="LEGACY_WEEKLY_PREFER_FIVE_WEEKDAYS_EXACT_BUDGET",
        ))
    if "daily_hours" not in goal_columns:
        with _batch("learning_goals") as batch:
            batch.alter_column("daily_hours", nullable=False)
            batch.alter_column("study_weekdays", nullable=False)
            batch.alter_column("timezone", nullable=False)
            batch.alter_column("budget_derivation", nullable=False)
    plan_columns = {column["name"] for column in sa.inspect(bind).get_columns("plan_versions")}
    with _batch("plan_versions") as batch:
        if "planning_risks" not in plan_columns:
            batch.add_column(sa.Column("planning_risks", sa.Text(), nullable=False, server_default="[]"))
        if "adjustment_suggestions" not in plan_columns:
            batch.add_column(sa.Column("adjustment_suggestions", sa.Text(), nullable=False, server_default="[]"))
    task_columns = {column["name"] for column in sa.inspect(bind).get_columns("learning_tasks")}
    with _batch("learning_tasks") as batch:
        if "scheduled_date" not in task_columns:
            batch.add_column(sa.Column("scheduled_date", sa.String(10)))
    tasks = sa.Table("learning_tasks", sa.MetaData(), autoload_with=bind)
    plans = sa.Table("plan_versions", sa.MetaData(), autoload_with=bind)
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    for plan in bind.execute(sa.select(plans.c.id, plans.c.goal_id)).mappings():
        goal = bind.execute(sa.select(goals).where(goals.c.id == plan["goal_id"])).mappings().one()
        weekdays = set(json.loads(goal["study_weekdays"]))
        capacity = int(Decimal(str(goal["daily_hours"])) * 60)
        cursor, used = today, 0
        legacy_risks = []
        plan_tasks = bind.execute(sa.select(tasks).where(tasks.c.plan_version_id == plan["id"])
                                  .order_by(tasks.c.week_number, tasks.c.position)).mappings()
        for task in plan_tasks:
            minutes = task["estimated_minutes"]
            if minutes > capacity:
                legacy_risks.append({"code": "TASK_TOO_LARGE", "task_id": task["id"]})
            while cursor.isoweekday() not in weekdays or (used and used + minutes > capacity):
                cursor += timedelta(days=1)
                used = 0
            bind.execute(tasks.update().where(tasks.c.id == task["id"]).values(scheduled_date=cursor.isoformat()))
            used += minutes
        if legacy_risks:
            bind.execute(plans.update().where(plans.c.id == plan["id"]).values(
                planning_risks=json.dumps(legacy_risks),
                adjustment_suggestions=json.dumps(["请让 Planner 将旧超长任务重新拆分"]),
            ))
    if "scheduled_date" not in task_columns:
        with _batch("learning_tasks") as batch:
            batch.alter_column("scheduled_date", nullable=False)


def downgrade() -> None:
    with _batch("learning_tasks") as batch:
        batch.drop_column("scheduled_date")
    with _batch("plan_versions") as batch:
        batch.drop_column("adjustment_suggestions")
        batch.drop_column("planning_risks")
    with _batch("learning_goals") as batch:
        batch.drop_constraint("ck_goal_daily_hours", type_="check")
        batch.drop_column("budget_derivation")
        batch.drop_column("timezone")
        batch.drop_column("study_weekdays")
        batch.drop_column("daily_hours")
        batch.alter_column("weekly_hours", existing_type=sa.Numeric(12, 6), type_=sa.Integer(), nullable=False)
