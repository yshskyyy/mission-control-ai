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
    # Preserve existing keys, and give every historical NULL its unique job ID.
    op.execute(sa.text("UPDATE ingestion_jobs SET idempotency_key=id WHERE idempotency_key IS NULL"))
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
    table = sa.Table("ingestion_jobs", sa.MetaData(), autoload_with=bind)
    with op.batch_alter_table("ingestion_jobs", copy_from=table) as batch:
        batch.alter_column("idempotency_key", existing_type=sa.String(100), nullable=False)
        batch.create_check_constraint(
            "ck_ingestion_status",
            "status IN ('PENDING','QUEUED','RUNNING','SUCCEEDED','FAILED')",
        )
        batch.create_check_constraint(
            "ck_ingestion_attempts",
            "attempt_count BETWEEN 0 AND max_attempts",
        )


def downgrade() -> None:
    bind = op.get_bind()
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("ingestion_jobs")}
    if "uq_ingestion_goal_idempotency" in indexes:
        op.drop_index("uq_ingestion_goal_idempotency", table_name="ingestion_jobs")
    table = sa.Table("ingestion_jobs", sa.MetaData(), autoload_with=bind)
    with op.batch_alter_table("ingestion_jobs", copy_from=table) as batch:
        batch.drop_constraint("ck_ingestion_attempts", type_="check")
        batch.drop_constraint("ck_ingestion_status", type_="check")
        batch.drop_column("max_attempts")
        batch.drop_column("attempt_count")
        batch.drop_column("idempotency_key")
