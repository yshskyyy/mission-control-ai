"""Create production schema.

Revision ID: 20260914_0001
"""
from alembic import op

from app.db import LOCAL_USER_ID, utc_now
from app.models import metadata


revision = "20260914_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    metadata.create_all(bind=op.get_bind())
    users = metadata.tables["users"]
    op.bulk_insert(users, [{
        "id": LOCAL_USER_ID, "email": "local@mission-control.invalid",
        "password_hash": "!", "display_name": "Local User", "is_active": 1,
        "created_at": utc_now(),
    }])


def downgrade() -> None:
    metadata.drop_all(bind=op.get_bind())
