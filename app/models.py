from sqlalchemy import (
    CheckConstraint, Column, ForeignKey, Index, Integer, MetaData, Numeric, String, Table, Text,
    UniqueConstraint,
)


metadata = MetaData()

users = Table(
    "users", metadata,
    Column("id", String(36), primary_key=True),
    Column("email", String(254), nullable=False, unique=True),
    Column("password_hash", Text, nullable=False),
    Column("display_name", String(80), nullable=False),
    Column("is_active", Integer, nullable=False, server_default="1"),
    Column("created_at", String(40), nullable=False),
)

learning_goals = Table(
    "learning_goals", metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", String(36), ForeignKey("users.id"), nullable=False),
    Column("title", String(120), nullable=False),
    Column("current_level", Text, nullable=False),
    Column("desired_outcome", Text, nullable=False),
    Column("deadline", String(10), nullable=False),
    Column("weekly_hours", Numeric(12, 6), nullable=False),
    Column("daily_hours", Numeric(12, 6), nullable=False),
    Column("study_weekdays", Text, nullable=False),
    Column("timezone", String(64), nullable=False, server_default="Asia/Shanghai"),
    Column("budget_derivation", String(80), nullable=False),
    Column("learning_preferences", Text, nullable=False, server_default=""),
    Column("status", String(20), nullable=False, server_default="ACTIVE"),
    Column("created_at", String(40), nullable=False),
    CheckConstraint("weekly_hours BETWEEN 0.5 AND 84"),
    CheckConstraint("daily_hours BETWEEN 0.5 AND 12"),
)

plan_versions = Table(
    "plan_versions", metadata,
    Column("id", String(36), primary_key=True),
    Column("goal_id", String(36), ForeignKey("learning_goals.id", ondelete="CASCADE"), nullable=False),
    Column("version", Integer, nullable=False),
    Column("status", String(20), nullable=False),
    Column("rationale", Text, nullable=False), Column("planning_risks", Text, nullable=False, server_default="[]"),
    Column("adjustment_suggestions", Text, nullable=False, server_default="[]"),
    Column("created_at", String(40), nullable=False),
    UniqueConstraint("goal_id", "version"),
    CheckConstraint("status IN ('DRAFT','ACTIVE','ARCHIVED')"),
)

learning_tasks = Table(
    "learning_tasks", metadata,
    Column("id", String(36), primary_key=True),
    Column("plan_version_id", String(36), ForeignKey("plan_versions.id", ondelete="CASCADE"), nullable=False),
    Column("week_number", Integer, nullable=False), Column("position", Integer, nullable=False),
    Column("title", Text, nullable=False), Column("description", Text, nullable=False),
    Column("estimated_minutes", Integer, nullable=False), Column("deliverable", Text, nullable=False),
    Column("acceptance_criteria", Text, nullable=False),
    Column("status", String(24), nullable=False, server_default="TODO"),
    Column("scheduled_date", String(10), nullable=False),
    Column("created_at", String(40), nullable=False),
    CheckConstraint("week_number BETWEEN 1 AND 4"), CheckConstraint("estimated_minutes > 0"),
    CheckConstraint("status IN ('TODO','IN_PROGRESS','SUBMITTED','PASSED','NEEDS_REVISION')"),
)

task_attempts = Table(
    "task_attempts", metadata, Column("id", String(36), primary_key=True),
    Column("task_id", String(36), ForeignKey("learning_tasks.id", ondelete="CASCADE"), nullable=False),
    Column("evidence_text", Text, nullable=False), Column("repository_url", Text),
    Column("actual_minutes", Integer, nullable=False), Column("status", String(20), nullable=False),
    Column("created_at", String(40), nullable=False), CheckConstraint("actual_minutes > 0"),
)

assessments = Table(
    "assessments", metadata, Column("id", String(36), primary_key=True),
    Column("attempt_id", String(36), ForeignKey("task_attempts.id", ondelete="CASCADE"), nullable=False, unique=True),
    Column("result", String(24), nullable=False), Column("score", Integer, nullable=False),
    Column("feedback", Text, nullable=False), Column("criterion_results", Text, nullable=False),
    Column("evaluator", Text, nullable=False), Column("created_at", String(40), nullable=False),
    CheckConstraint("result IN ('PASSED','NEEDS_REVISION')"), CheckConstraint("score BETWEEN 0 AND 100"),
)

teaching_sessions = Table(
    "teaching_sessions", metadata, Column("id", String(36), primary_key=True),
    Column("task_id", String(36), ForeignKey("learning_tasks.id", ondelete="CASCADE"), nullable=False),
    Column("current_section_id", String(36)),
    Column("lesson_progress", Integer, nullable=False, server_default="0"),
    Column("last_user_action", String(30), nullable=False, server_default="INIT"),
    Column("retry_count", Integer, nullable=False, server_default="0"),
    Column("mastery", Integer, nullable=False, server_default="0"),
    Column("status", String(24), nullable=False, server_default="ACTIVE"),
    Column("created_at", String(40), nullable=False), Column("updated_at", String(40), nullable=False),
    CheckConstraint("status IN ('ACTIVE','WAITING_USER','WAITING_CHOICE','COMPLETED')"),
    CheckConstraint("mastery BETWEEN 0 AND 100"),
)

teaching_messages = Table(
    "teaching_messages", metadata, Column("id", String(36), primary_key=True),
    Column("session_id", String(36), ForeignKey("teaching_sessions.id", ondelete="CASCADE"), nullable=False),
    Column("section_id", String(36)), Column("role", String(10), nullable=False),
    Column("message_type", String(24), nullable=False, server_default="QUESTION"),
    Column("content", Text, nullable=False), Column("idempotency_key", String(100)),
    Column("teaching_strategy", String(24)), Column("provider", String(30)),
    Column("model", String(100)), Column("prompt_version", String(80)),
    Column("created_at", String(40), nullable=False),
)

lesson_sections = Table(
    "lesson_sections", metadata, Column("id", String(36), primary_key=True),
    Column("session_id", String(36), ForeignKey("teaching_sessions.id", ondelete="CASCADE"), nullable=False),
    Column("position", Integer, nullable=False), Column("title", Text, nullable=False),
    Column("objective", Text, nullable=False), Column("content", Text, nullable=False),
    Column("example", Text, nullable=False), Column("check_question", Text, nullable=False),
    Column("status", String(20), nullable=False, server_default="LOCKED"),
    Column("mastery", Integer, nullable=False, server_default="0"),
    Column("created_at", String(40), nullable=False),
    UniqueConstraint("session_id", "position"),
)

quizzes = Table(
    "quizzes", metadata, Column("id", String(36), primary_key=True),
    Column("session_id", String(36), ForeignKey("teaching_sessions.id", ondelete="CASCADE"), nullable=False),
    Column("section_id", String(36), ForeignKey("lesson_sections.id", ondelete="CASCADE"), nullable=False),
    Column("version", Integer, nullable=False), Column("question", Text, nullable=False),
    Column("expected_answer", Text, nullable=False), Column("rubric", Text, nullable=False),
    Column("status", String(20), nullable=False, server_default="ACTIVE"),
    Column("created_at", String(40), nullable=False),
    UniqueConstraint("section_id", "version"),
)

quiz_attempts = Table(
    "quiz_attempts", metadata, Column("id", String(36), primary_key=True),
    Column("quiz_id", String(36), ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False),
    Column("idempotency_key", String(100), nullable=False), Column("answer", Text, nullable=False),
    Column("score", Integer, nullable=False), Column("passed", Integer, nullable=False),
    Column("feedback", Text, nullable=False), Column("weak_points", Text, nullable=False),
    Column("created_at", String(40), nullable=False), UniqueConstraint("quiz_id", "idempotency_key"),
)

mastery_records = Table(
    "mastery_records", metadata, Column("id", String(36), primary_key=True),
    Column("session_id", String(36), ForeignKey("teaching_sessions.id", ondelete="CASCADE"), nullable=False),
    Column("section_id", String(36), ForeignKey("lesson_sections.id", ondelete="CASCADE"), nullable=False),
    Column("source_attempt_id", String(36), ForeignKey("quiz_attempts.id"), nullable=False, unique=True),
    Column("previous_mastery", Integer, nullable=False), Column("new_mastery", Integer, nullable=False),
    Column("reason", Text, nullable=False), Column("created_at", String(40), nullable=False),
)

knowledge_nodes = Table(
    "knowledge_nodes", metadata, Column("id", String(36), primary_key=True),
    Column("goal_id", String(36), ForeignKey("learning_goals.id", ondelete="CASCADE"), nullable=False),
    Column("name", Text, nullable=False), Column("category", Text, nullable=False),
    Column("description", Text, nullable=False, server_default=""), Column("mastery", Integer, nullable=False, server_default="0"),
    Column("confidence", Integer, nullable=False, server_default="20"), Column("priority", Integer, nullable=False, server_default="50"),
    Column("status", String(20), nullable=False, server_default="DISCOVERED"), Column("source", Text, nullable=False, server_default="USER"),
    Column("created_at", String(40), nullable=False), Column("updated_at", String(40), nullable=False),
    UniqueConstraint("goal_id", "name"),
)

knowledge_edges = Table(
    "knowledge_edges", metadata, Column("id", String(36), primary_key=True),
    Column("goal_id", String(36), ForeignKey("learning_goals.id", ondelete="CASCADE"), nullable=False),
    Column("source_node_id", String(36), ForeignKey("knowledge_nodes.id", ondelete="CASCADE"), nullable=False),
    Column("target_node_id", String(36), ForeignKey("knowledge_nodes.id", ondelete="CASCADE"), nullable=False),
    Column("relation_type", String(20), nullable=False), Column("created_at", String(40), nullable=False),
    UniqueConstraint("source_node_id", "target_node_id", "relation_type"),
)

content_items = Table(
    "content_items", metadata, Column("id", String(36), primary_key=True),
    Column("source_type", String(20), nullable=False), Column("external_id", Text, nullable=False),
    Column("source_name", Text, nullable=False), Column("title", Text, nullable=False), Column("url", Text, nullable=False),
    Column("summary", Text, nullable=False, server_default=""), Column("topics", Text, nullable=False, server_default="[]"),
    Column("quality_score", Integer, nullable=False, server_default="50"), Column("trend_score", Integer, nullable=False, server_default="50"),
    Column("published_at", String(40)), Column("discovered_at", String(40), nullable=False),
    UniqueConstraint("source_type", "external_id"),
)

recommendations = Table(
    "recommendations", metadata, Column("id", String(36), primary_key=True),
    Column("goal_id", String(36), ForeignKey("learning_goals.id", ondelete="CASCADE"), nullable=False),
    Column("content_item_id", String(36), ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False),
    Column("status", String(20), nullable=False, server_default="CANDIDATE"), Column("score", Integer, nullable=False),
    Column("score_breakdown", Text, nullable=False), Column("reason", Text, nullable=False),
    Column("created_module_id", String(36)), Column("created_at", String(40), nullable=False), Column("decided_at", String(40)),
    UniqueConstraint("goal_id", "content_item_id"),
)

learning_modules = Table(
    "learning_modules", metadata, Column("id", String(36), primary_key=True),
    Column("goal_id", String(36), ForeignKey("learning_goals.id", ondelete="CASCADE"), nullable=False),
    Column("recommendation_id", String(36), ForeignKey("recommendations.id")), Column("title", Text, nullable=False),
    Column("rationale", Text, nullable=False), Column("estimated_minutes", Integer, nullable=False),
    Column("status", String(20), nullable=False, server_default="ACTIVE"), Column("created_at", String(40), nullable=False),
)

module_tasks = Table(
    "module_tasks", metadata, Column("id", String(36), primary_key=True),
    Column("module_id", String(36), ForeignKey("learning_modules.id", ondelete="CASCADE"), nullable=False),
    Column("position", Integer, nullable=False), Column("title", Text, nullable=False), Column("description", Text, nullable=False),
    Column("estimated_minutes", Integer, nullable=False), Column("deliverable", Text, nullable=False),
    Column("acceptance_criteria", Text, nullable=False),
)

weekly_reviews = Table(
    "weekly_reviews", metadata, Column("id", String(36), primary_key=True),
    Column("goal_id", String(36), ForeignKey("learning_goals.id", ondelete="CASCADE"), nullable=False),
    Column("week_number", Integer, nullable=False), Column("summary", Text, nullable=False),
    Column("proposed_changes", Text, nullable=False), Column("status", String(20), nullable=False, server_default="PENDING"),
    Column("created_plan_version_id", String(36), ForeignKey("plan_versions.id")), Column("created_at", String(40), nullable=False),
)

ingestion_jobs = Table(
    "ingestion_jobs", metadata, Column("id", String(36), primary_key=True),
    Column("goal_id", String(36), ForeignKey("learning_goals.id", ondelete="CASCADE"), nullable=False),
    Column("status", String(20), nullable=False),
    Column("idempotency_key", String(100), nullable=False),
    Column("attempt_count", Integer, nullable=False, server_default="0"),
    Column("max_attempts", Integer, nullable=False, server_default="3"),
    Column("items_found", Integer, nullable=False, server_default="0"),
    Column("recommendations_created", Integer, nullable=False, server_default="0"), Column("error", Text),
    Column("created_at", String(40), nullable=False), Column("finished_at", String(40)),
    UniqueConstraint("goal_id", "idempotency_key"),
    CheckConstraint("status IN ('PENDING','QUEUED','RUNNING','SUCCEEDED','FAILED')"),
    CheckConstraint("attempt_count BETWEEN 0 AND max_attempts"),
)

ai_runs = Table(
    "ai_runs", metadata, Column("id", String(36), primary_key=True), Column("run_type", String(30), nullable=False),
    Column("entity_id", String(36), nullable=False), Column("status", String(20), nullable=False),
    Column("model", Text, nullable=False), Column("prompt_version", Text, nullable=False),
    Column("latency_ms", Integer, nullable=False, server_default="0"), Column("error", Text),
    Column("created_at", String(40), nullable=False), Column("user_id", String(36), ForeignKey("users.id")),
)

Index("idx_goals_user", learning_goals.c.user_id, learning_goals.c.status)
Index("idx_tasks_plan_week", learning_tasks.c.plan_version_id, learning_tasks.c.week_number, learning_tasks.c.position)
Index("idx_plan_goal_status", plan_versions.c.goal_id, plan_versions.c.status)
Index("idx_knowledge_goal", knowledge_nodes.c.goal_id, knowledge_nodes.c.status)
Index("idx_recommendations_goal", recommendations.c.goal_id, recommendations.c.status, recommendations.c.score)
