"""Add ingestion reliability state and idempotency fields.

Revision ID: 20260914_0002
"""
from alembic import op
import sqlalchemy as sa


revision = "20260914_0002"
down_revision = "20260914_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("ingestion_jobs")}
    added_idempotency = "idempotency_key" not in columns
    if "idempotency_key" not in columns:
        op.add_column("ingestion_jobs", sa.Column("idempotency_key", sa.String(100)))
        op.execute(sa.text("UPDATE ingestion_jobs SET idempotency_key=id"))
        op.alter_column("ingestion_jobs", "idempotency_key", nullable=False)
    if "attempt_count" not in columns:
        op.add_column(
            "ingestion_jobs",
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        )
    if "max_attempts" not in columns:
        op.add_column(
            "ingestion_jobs",
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        )
    if added_idempotency:
        op.create_index(
            "uq_ingestion_goal_idempotency",
            "ingestion_jobs",
            ["goal_id", "idempotency_key"],
            unique=True,
        )
    if bind.dialect.name == "postgresql":
        op.create_check_constraint(
            "ck_ingestion_status",
            "ingestion_jobs",
            "status IN ('PENDING','QUEUED','RUNNING','SUCCEEDED','FAILED')",
        )
        op.create_check_constraint(
            "ck_ingestion_attempts",
            "ingestion_jobs",
            "attempt_count BETWEEN 0 AND max_attempts",
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_constraint("ck_ingestion_attempts", "ingestion_jobs", type_="check")
        op.drop_constraint("ck_ingestion_status", "ingestion_jobs", type_="check")
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("ingestion_jobs")}
    if "uq_ingestion_goal_idempotency" in indexes:
        op.drop_index("uq_ingestion_goal_idempotency", table_name="ingestion_jobs")
    op.drop_column("ingestion_jobs", "max_attempts")
    op.drop_column("ingestion_jobs", "attempt_count")
    op.drop_column("ingestion_jobs", "idempotency_key")
