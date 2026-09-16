"""Frozen pre-release initial schema.

Revision ID: 20260914_0001
This one-time stabilization freezes the original schema. Revisions 0001-0006 are immutable from here.
"""
from datetime import datetime, timezone
from alembic import op
import sqlalchemy as sa

revision = "20260914_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('content_items',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('source_type', sa.String(length=20), nullable=False),
    sa.Column('external_id', sa.Text(), nullable=False),
    sa.Column('source_name', sa.Text(), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('summary', sa.Text(), server_default='', nullable=False),
    sa.Column('topics', sa.Text(), server_default='[]', nullable=False),
    sa.Column('quality_score', sa.Integer(), server_default='50', nullable=False),
    sa.Column('trend_score', sa.Integer(), server_default='50', nullable=False),
    sa.Column('published_at', sa.String(length=40), nullable=True),
    sa.Column('discovered_at', sa.String(length=40), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source_type', 'external_id')
    )
    op.create_table('users',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('password_hash', sa.Text(), nullable=False),
    sa.Column('display_name', sa.String(length=80), nullable=False),
    sa.Column('is_active', sa.Integer(), server_default='1', nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email')
    )
    op.create_table('ai_runs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('run_type', sa.String(length=30), nullable=False),
    sa.Column('entity_id', sa.String(length=36), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('model', sa.Text(), nullable=False),
    sa.Column('prompt_version', sa.Text(), nullable=False),
    sa.Column('latency_ms', sa.Integer(), server_default='0', nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('learning_goals',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('title', sa.String(length=120), nullable=False),
    sa.Column('current_level', sa.Text(), nullable=False),
    sa.Column('desired_outcome', sa.Text(), nullable=False),
    sa.Column('deadline', sa.String(length=10), nullable=False),
    sa.Column('weekly_hours', sa.Integer(), nullable=False),
    sa.Column('learning_preferences', sa.Text(), server_default='', nullable=False),
    sa.Column('status', sa.String(length=20), server_default='ACTIVE', nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.CheckConstraint('weekly_hours BETWEEN 0.5 AND 84'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_goals_user', 'learning_goals', ['user_id', 'status'], unique=False)
    op.create_table('ingestion_jobs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('goal_id', sa.String(length=36), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('items_found', sa.Integer(), server_default='0', nullable=False),
    sa.Column('recommendations_created', sa.Integer(), server_default='0', nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.Column('finished_at', sa.String(length=40), nullable=True),
    sa.CheckConstraint("status IN ('PENDING','QUEUED','RUNNING','SUCCEEDED','FAILED')"),
    sa.ForeignKeyConstraint(['goal_id'], ['learning_goals.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('knowledge_nodes',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('goal_id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('category', sa.Text(), nullable=False),
    sa.Column('description', sa.Text(), server_default='', nullable=False),
    sa.Column('mastery', sa.Integer(), server_default='0', nullable=False),
    sa.Column('confidence', sa.Integer(), server_default='20', nullable=False),
    sa.Column('priority', sa.Integer(), server_default='50', nullable=False),
    sa.Column('status', sa.String(length=20), server_default='DISCOVERED', nullable=False),
    sa.Column('source', sa.Text(), server_default='USER', nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.Column('updated_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['goal_id'], ['learning_goals.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('goal_id', 'name')
    )
    op.create_index('idx_knowledge_goal', 'knowledge_nodes', ['goal_id', 'status'], unique=False)
    op.create_table('plan_versions',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('goal_id', sa.String(length=36), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('rationale', sa.Text(), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.CheckConstraint("status IN ('DRAFT','ACTIVE','ARCHIVED')"),
    sa.ForeignKeyConstraint(['goal_id'], ['learning_goals.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('goal_id', 'version')
    )
    op.create_index('idx_plan_goal_status', 'plan_versions', ['goal_id', 'status'], unique=False)
    op.create_table('recommendations',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('goal_id', sa.String(length=36), nullable=False),
    sa.Column('content_item_id', sa.String(length=36), nullable=False),
    sa.Column('status', sa.String(length=20), server_default='CANDIDATE', nullable=False),
    sa.Column('score', sa.Integer(), nullable=False),
    sa.Column('score_breakdown', sa.Text(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('created_module_id', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.Column('decided_at', sa.String(length=40), nullable=True),
    sa.ForeignKeyConstraint(['content_item_id'], ['content_items.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['goal_id'], ['learning_goals.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('goal_id', 'content_item_id')
    )
    op.create_index('idx_recommendations_goal', 'recommendations', ['goal_id', 'status', 'score'], unique=False)
    op.create_table('knowledge_edges',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('goal_id', sa.String(length=36), nullable=False),
    sa.Column('source_node_id', sa.String(length=36), nullable=False),
    sa.Column('target_node_id', sa.String(length=36), nullable=False),
    sa.Column('relation_type', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['goal_id'], ['learning_goals.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_node_id'], ['knowledge_nodes.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['target_node_id'], ['knowledge_nodes.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source_node_id', 'target_node_id', 'relation_type')
    )
    op.create_table('learning_modules',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('goal_id', sa.String(length=36), nullable=False),
    sa.Column('recommendation_id', sa.String(length=36), nullable=True),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('rationale', sa.Text(), nullable=False),
    sa.Column('estimated_minutes', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), server_default='ACTIVE', nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['goal_id'], ['learning_goals.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['recommendation_id'], ['recommendations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('learning_tasks',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('plan_version_id', sa.String(length=36), nullable=False),
    sa.Column('week_number', sa.Integer(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('estimated_minutes', sa.Integer(), nullable=False),
    sa.Column('deliverable', sa.Text(), nullable=False),
    sa.Column('acceptance_criteria', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=24), server_default='TODO', nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.CheckConstraint("status IN ('TODO','IN_PROGRESS','SUBMITTED','PASSED','NEEDS_REVISION')"),
    sa.CheckConstraint('estimated_minutes > 0'),
    sa.CheckConstraint('week_number BETWEEN 1 AND 4'),
    sa.ForeignKeyConstraint(['plan_version_id'], ['plan_versions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_tasks_plan_week', 'learning_tasks', ['plan_version_id', 'week_number', 'position'], unique=False)
    op.create_table('weekly_reviews',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('goal_id', sa.String(length=36), nullable=False),
    sa.Column('week_number', sa.Integer(), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('proposed_changes', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=20), server_default='PENDING', nullable=False),
    sa.Column('created_plan_version_id', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['created_plan_version_id'], ['plan_versions.id'], ),
    sa.ForeignKeyConstraint(['goal_id'], ['learning_goals.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('module_tasks',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('module_id', sa.String(length=36), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('estimated_minutes', sa.Integer(), nullable=False),
    sa.Column('deliverable', sa.Text(), nullable=False),
    sa.Column('acceptance_criteria', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['module_id'], ['learning_modules.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('task_attempts',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('task_id', sa.String(length=36), nullable=False),
    sa.Column('evidence_text', sa.Text(), nullable=False),
    sa.Column('repository_url', sa.Text(), nullable=True),
    sa.Column('actual_minutes', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.CheckConstraint('actual_minutes > 0'),
    sa.ForeignKeyConstraint(['task_id'], ['learning_tasks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('teaching_sessions',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('task_id', sa.String(length=36), nullable=False),
    sa.Column('status', sa.String(length=24), server_default='ACTIVE', nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.CheckConstraint("status IN ('ACTIVE','WAITING_USER','WAITING_CHOICE','COMPLETED')"),
    sa.ForeignKeyConstraint(['task_id'], ['learning_tasks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('assessments',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('attempt_id', sa.String(length=36), nullable=False),
    sa.Column('result', sa.String(length=24), nullable=False),
    sa.Column('score', sa.Integer(), nullable=False),
    sa.Column('feedback', sa.Text(), nullable=False),
    sa.Column('criterion_results', sa.Text(), nullable=False),
    sa.Column('evaluator', sa.Text(), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.CheckConstraint("result IN ('PASSED','NEEDS_REVISION')"),
    sa.CheckConstraint('score BETWEEN 0 AND 100'),
    sa.ForeignKeyConstraint(['attempt_id'], ['task_attempts.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('attempt_id')
    )
    op.create_table('teaching_messages',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('session_id', sa.String(length=36), nullable=False),
    sa.Column('role', sa.String(length=10), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('created_at', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['teaching_sessions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    # ### end Alembic commands ###
    op.bulk_insert(sa.table("users",sa.column("id",sa.String),sa.column("email",sa.String),sa.column("password_hash",sa.Text),sa.column("display_name",sa.String),sa.column("is_active",sa.Integer),sa.column("created_at",sa.String)), [{"id":"00000000-0000-0000-0000-000000000001","email":"local@mission-control.invalid","password_hash":"!","display_name":"Local User","is_active":1,"created_at":datetime.now(timezone.utc).isoformat(timespec="microseconds")}])


def downgrade() -> None:
    op.drop_table('teaching_messages')
    op.drop_table('assessments')
    op.drop_table('teaching_sessions')
    op.drop_table('task_attempts')
    op.drop_table('module_tasks')
    op.drop_table('weekly_reviews')
    op.drop_index('idx_tasks_plan_week', table_name='learning_tasks')
    op.drop_table('learning_tasks')
    op.drop_table('learning_modules')
    op.drop_table('knowledge_edges')
    op.drop_index('idx_recommendations_goal', table_name='recommendations')
    op.drop_table('recommendations')
    op.drop_index('idx_plan_goal_status', table_name='plan_versions')
    op.drop_table('plan_versions')
    op.drop_index('idx_knowledge_goal', table_name='knowledge_nodes')
    op.drop_table('knowledge_nodes')
    op.drop_table('ingestion_jobs')
    op.drop_index('idx_goals_user', table_name='learning_goals')
    op.drop_table('learning_goals')
    op.drop_table('ai_runs')
    op.drop_table('users')
    op.drop_table('content_items')
    # ### end Alembic commands ###
