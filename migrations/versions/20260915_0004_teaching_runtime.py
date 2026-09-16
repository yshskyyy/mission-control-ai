"""Persist adaptive teaching strategy and safe runtime metadata.

Revision ID: 20260915_0004
"""
from alembic import op
import sqlalchemy as sa


revision = "20260915_0004"
down_revision = "20260914_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("teaching_messages")}
    for name, length in (
        ("teaching_strategy", 24), ("provider", 30),
        ("model", 100), ("prompt_version", 80),
    ):
        if name not in columns:
            op.add_column("teaching_messages", sa.Column(name, sa.String(length)))


def downgrade() -> None:
    table = sa.Table("teaching_messages", sa.MetaData(), autoload_with=op.get_bind())
    with op.batch_alter_table("teaching_messages", copy_from=table) as batch:
        for name in ("prompt_version", "model", "provider", "teaching_strategy"):
            batch.drop_column(name)
