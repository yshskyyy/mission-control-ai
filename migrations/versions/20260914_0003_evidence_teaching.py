"""Add evidence-driven teaching course entities.

Revision ID: 20260914_0003
"""
from alembic import op
import sqlalchemy as sa

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
        table = sa.Table("teaching_sessions", sa.MetaData(), autoload_with=bind)
        with op.batch_alter_table("teaching_sessions", copy_from=table) as batch:
            batch.alter_column("updated_at", existing_type=sa.String(40), nullable=False)

    message_columns = {column["name"] for column in inspector.get_columns("teaching_messages")}
    _add_column("teaching_messages", message_columns, sa.Column("section_id", sa.String(36)))
    _add_column("teaching_messages", message_columns, sa.Column("message_type", sa.String(24), nullable=False, server_default="QUESTION"))
    _add_column("teaching_messages", message_columns, sa.Column("idempotency_key", sa.String(100)))

    op.create_table("lesson_sections",
        sa.Column("id",sa.String(36),primary_key=True),
        sa.Column("session_id",sa.String(36),sa.ForeignKey("teaching_sessions.id",ondelete="CASCADE"),nullable=False),
        sa.Column("position",sa.Integer(),nullable=False),sa.Column("title",sa.Text(),nullable=False),
        sa.Column("objective",sa.Text(),nullable=False),sa.Column("content",sa.Text(),nullable=False),
        sa.Column("example",sa.Text(),nullable=False),sa.Column("check_question",sa.Text(),nullable=False),
        sa.Column("status",sa.String(20),nullable=False,server_default="LOCKED"),
        sa.Column("mastery",sa.Integer(),nullable=False,server_default="0"),
        sa.Column("created_at",sa.String(40),nullable=False),sa.UniqueConstraint("session_id","position"))
    op.create_table("quizzes",
        sa.Column("id",sa.String(36),primary_key=True),
        sa.Column("session_id",sa.String(36),sa.ForeignKey("teaching_sessions.id",ondelete="CASCADE"),nullable=False),
        sa.Column("section_id",sa.String(36),sa.ForeignKey("lesson_sections.id",ondelete="CASCADE"),nullable=False),
        sa.Column("version",sa.Integer(),nullable=False),sa.Column("question",sa.Text(),nullable=False),
        sa.Column("expected_answer",sa.Text(),nullable=False),sa.Column("rubric",sa.Text(),nullable=False),
        sa.Column("status",sa.String(20),nullable=False,server_default="ACTIVE"),
        sa.Column("created_at",sa.String(40),nullable=False),sa.UniqueConstraint("section_id","version"))
    op.create_table("quiz_attempts",
        sa.Column("id",sa.String(36),primary_key=True),
        sa.Column("quiz_id",sa.String(36),sa.ForeignKey("quizzes.id",ondelete="CASCADE"),nullable=False),
        sa.Column("idempotency_key",sa.String(100),nullable=False),sa.Column("answer",sa.Text(),nullable=False),
        sa.Column("score",sa.Integer(),nullable=False),sa.Column("passed",sa.Integer(),nullable=False),
        sa.Column("feedback",sa.Text(),nullable=False),sa.Column("weak_points",sa.Text(),nullable=False),
        sa.Column("created_at",sa.String(40),nullable=False),sa.UniqueConstraint("quiz_id","idempotency_key"))
    op.create_table("mastery_records",
        sa.Column("id",sa.String(36),primary_key=True),
        sa.Column("session_id",sa.String(36),sa.ForeignKey("teaching_sessions.id",ondelete="CASCADE"),nullable=False),
        sa.Column("section_id",sa.String(36),sa.ForeignKey("lesson_sections.id",ondelete="CASCADE"),nullable=False),
        sa.Column("source_attempt_id",sa.String(36),sa.ForeignKey("quiz_attempts.id"),nullable=False,unique=True),
        sa.Column("previous_mastery",sa.Integer(),nullable=False),sa.Column("new_mastery",sa.Integer(),nullable=False),
        sa.Column("reason",sa.Text(),nullable=False),sa.Column("created_at",sa.String(40),nullable=False))


def downgrade() -> None:
    op.drop_table("mastery_records")
    op.drop_table("quiz_attempts")
    op.drop_table("quizzes")
    op.drop_table("lesson_sections")
    for name, columns in (
        ("teaching_messages", ("idempotency_key", "message_type", "section_id")),
        ("teaching_sessions", ("updated_at", "mastery", "retry_count", "last_user_action",
                               "lesson_progress", "current_section_id")),
    ):
        table = sa.Table(name, sa.MetaData(), autoload_with=op.get_bind())
        with op.batch_alter_table(name, copy_from=table) as batch:
            for column in columns:
                batch.drop_column(column)
