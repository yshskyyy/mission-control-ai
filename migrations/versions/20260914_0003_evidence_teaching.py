"""Add evidence-driven teaching course entities.

Revision ID: 20260914_0003
"""
from alembic import op
import sqlalchemy as sa

from app.models import lesson_sections, mastery_records, quiz_attempts, quizzes


revision = "20260914_0003"
down_revision = "20260914_0002"
branch_labels = None
depends_on = None


def _add_column(table: str, columns: set[str], column: sa.Column) -> None:
    if column.name not in columns:
        op.add_column(table, column)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    session_columns = {column["name"] for column in inspector.get_columns("teaching_sessions")}
    _add_column("teaching_sessions", session_columns, sa.Column("current_section_id", sa.String(36)))
    _add_column("teaching_sessions", session_columns, sa.Column("lesson_progress", sa.Integer(), nullable=False, server_default="0"))
    _add_column("teaching_sessions", session_columns, sa.Column("last_user_action", sa.String(30), nullable=False, server_default="INIT"))
    _add_column("teaching_sessions", session_columns, sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"))
    _add_column("teaching_sessions", session_columns, sa.Column("mastery", sa.Integer(), nullable=False, server_default="0"))
    _add_column("teaching_sessions", session_columns, sa.Column("updated_at", sa.String(40)))
    if "updated_at" not in session_columns:
        op.execute(sa.text("UPDATE teaching_sessions SET updated_at=created_at"))
        op.alter_column("teaching_sessions", "updated_at", nullable=False)

    message_columns = {column["name"] for column in inspector.get_columns("teaching_messages")}
    _add_column("teaching_messages", message_columns, sa.Column("section_id", sa.String(36)))
    _add_column("teaching_messages", message_columns, sa.Column("message_type", sa.String(24), nullable=False, server_default="QUESTION"))
    _add_column("teaching_messages", message_columns, sa.Column("idempotency_key", sa.String(100)))

    lesson_sections.create(bind, checkfirst=True)
    quizzes.create(bind, checkfirst=True)
    quiz_attempts.create(bind, checkfirst=True)
    mastery_records.create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    mastery_records.drop(bind, checkfirst=True)
    quiz_attempts.drop(bind, checkfirst=True)
    quizzes.drop(bind, checkfirst=True)
    lesson_sections.drop(bind, checkfirst=True)
    for column in ("idempotency_key", "message_type", "section_id"):
        op.drop_column("teaching_messages", column)
    for column in ("updated_at", "mastery", "retry_count", "last_user_action",
                   "lesson_progress", "current_section_id"):
        op.drop_column("teaching_sessions", column)
