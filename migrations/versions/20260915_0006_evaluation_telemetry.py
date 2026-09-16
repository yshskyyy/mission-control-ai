"""add evaluation telemetry to ai runs

Revision ID: 20260915_0006
Revises: 20260915_0005
"""
from alembic import op
import sqlalchemy as sa


revision = "20260915_0006"
down_revision = "20260915_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("ai_runs")}
    columns = (
        sa.Column("provider", sa.String(30), nullable=False, server_default="local"),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("estimated_cost", sa.Numeric(14, 8), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("correlation_id", sa.String(64), nullable=True),
        sa.Column("logical_request_id", sa.String(100), nullable=True),
        sa.Column("attempt_id", sa.String(64), nullable=True),
    )
    for column in columns:
        if column.name not in existing:
            op.add_column("ai_runs", column)
    op.execute("UPDATE ai_runs SET provider='openai' WHERE status!='FALLBACK' AND model!='local'")
    op.create_index("idx_ai_runs_correlation", "ai_runs", ["correlation_id", "logical_request_id", "created_at"], unique=False, if_not_exists=True)
    op.create_index("uq_ai_runs_attempt_id", "ai_runs", ["attempt_id"], unique=True, if_not_exists=True,
                    postgresql_where=sa.text("attempt_id IS NOT NULL"))
    inspector=sa.inspect(op.get_bind())
    if "ai_logical_requests" not in inspector.get_table_names():
        op.create_table("ai_logical_requests",
            sa.Column("logical_request_id",sa.String(100),primary_key=True),
            sa.Column("correlation_id",sa.String(64),nullable=False),
            sa.Column("run_type",sa.String(30),nullable=False),sa.Column("prompt_version",sa.Text(),nullable=False),
            sa.Column("entity_id",sa.String(36),nullable=False),
            sa.Column("user_id",sa.String(36),sa.ForeignKey("users.id"),nullable=True),
            sa.Column("final_outcome",sa.String(30),nullable=True),
            sa.Column("provider_backed",sa.Boolean(),nullable=False,server_default=sa.false()),
            sa.Column("schema_failure",sa.Boolean(),nullable=False,server_default=sa.false()),
            sa.Column("attempt_count",sa.Integer(),nullable=False,server_default="0"),
            sa.Column("final_provider",sa.String(30)),sa.Column("final_model",sa.Text()),
            sa.Column("created_at",sa.String(40),nullable=False),sa.Column("completed_at",sa.String(40)),
            sa.Column("started_at",sa.String(40),nullable=False),sa.Column("finalized_at",sa.String(40)),
            sa.CheckConstraint("final_outcome IS NULL OR final_outcome IN ('MODEL_SUCCESS','FALLBACK_SUCCESS','TOTAL_FAILURE')",name="ck_ai_logical_final_outcome"),
            sa.CheckConstraint("attempt_count >= 0",name="ck_ai_logical_attempt_count"))
    else:
        logical_columns={column["name"] for column in sa.inspect(op.get_bind()).get_columns("ai_logical_requests")}
        if "started_at" not in logical_columns:
            op.add_column("ai_logical_requests",sa.Column("started_at",sa.String(40),nullable=True))
            op.execute("UPDATE ai_logical_requests SET started_at=created_at WHERE started_at IS NULL")
            table=sa.Table("ai_logical_requests",sa.MetaData(),autoload_with=op.get_bind())
            with op.batch_alter_table("ai_logical_requests",copy_from=table) as batch:
                batch.alter_column("started_at",existing_type=sa.String(40),nullable=False)
        if "finalized_at" not in logical_columns:
            op.add_column("ai_logical_requests",sa.Column("finalized_at",sa.String(40),nullable=True))
            op.execute("UPDATE ai_logical_requests SET finalized_at=completed_at WHERE completed_at IS NOT NULL")
    op.create_index("idx_ai_logical_user_created","ai_logical_requests",["user_id","created_at"],if_not_exists=True)
    op.create_index("idx_ai_logical_correlation","ai_logical_requests",["correlation_id","logical_request_id"],if_not_exists=True)
    op.create_index("idx_ai_runs_user_created","ai_runs",["user_id","created_at"],if_not_exists=True)
    foreign_keys={item.get("name") for item in sa.inspect(op.get_bind()).get_foreign_keys("ai_runs")}
    checks={item["name"] for item in sa.inspect(op.get_bind()).get_check_constraints("ai_runs")}
    table=sa.Table("ai_runs",sa.MetaData(),autoload_with=op.get_bind())
    with op.batch_alter_table("ai_runs",copy_from=table) as batch:
        if "fk_ai_runs_logical_request" not in foreign_keys:
            batch.create_foreign_key("fk_ai_runs_logical_request","ai_logical_requests",
                                     ["logical_request_id"],["logical_request_id"])
        for name,condition in (("ck_ai_runs_input_tokens","input_tokens IS NULL OR input_tokens >= 0"),
                           ("ck_ai_runs_output_tokens","output_tokens IS NULL OR output_tokens >= 0"),
                           ("ck_ai_runs_estimated_cost","estimated_cost IS NULL OR estimated_cost >= 0"),
                           ("ck_ai_runs_retry_count","retry_count >= 0")):
            if name not in checks: batch.create_check_constraint(name,condition)


def downgrade() -> None:
    op.drop_index("idx_ai_runs_user_created", table_name="ai_runs", if_exists=True)
    op.drop_index("uq_ai_runs_attempt_id", table_name="ai_runs", if_exists=True)
    op.drop_index("idx_ai_runs_correlation", table_name="ai_runs", if_exists=True)
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("ai_runs")}
    table=sa.Table("ai_runs",sa.MetaData(),autoload_with=op.get_bind())
    with op.batch_alter_table("ai_runs",copy_from=table) as batch:
        batch.drop_constraint("fk_ai_runs_logical_request",type_="foreignkey")
        for name in ("ck_ai_runs_retry_count","ck_ai_runs_estimated_cost","ck_ai_runs_output_tokens","ck_ai_runs_input_tokens"):
            batch.drop_constraint(name,type_="check")
        for name in ("attempt_id", "logical_request_id", "correlation_id", "retry_count", "estimated_cost", "output_tokens", "input_tokens", "provider"):
            if name in existing:
                batch.drop_column(name)
    op.drop_table("ai_logical_requests", if_exists=True)
