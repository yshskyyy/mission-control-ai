# Architecture Decision: MVP modular monolith

## Context

The product needs a complete evidence-driven learning loop before it needs distributed scale. The current user count is one, while model calls and plan evaluation remain the main sources of uncertainty.

## Decision

Use a FastAPI modular monolith backed by SQLite. Keep API validation, application services, AI integration and persistence in separate modules. Provide a deterministic local AI fallback so development and demonstrations do not depend on an external service.

## Boundaries

- `app/main.py`: HTTP transport only
- `app/services.py`: use-case orchestration and deterministic constraints
- `app/ai.py`: structured model calls, prompt versions and fallback behavior
- `app/repository.py`: persistence operations
- `app/db.py`: schema and transaction boundary
- `app/static/`: dependency-free browser client

The AI layer proposes plans and assessments. Application code enforces time budgets, statuses and plan activation.

## Evolution triggers

Introduce PostgreSQL when concurrent writes, hosted deployment or richer querying make SQLite limiting.

Introduce a queue when plan generation and assessment need durable background execution rather than request-response calls.

Introduce LangGraph for a weekly replanning workflow when it requires multiple model/tool steps, checkpoint recovery and an approval pause. It should not own core business entities.

## Known MVP limitations

- External repository links are stored but not fetched or verified.
- AI operations execute synchronously.
- Authentication is omitted because the first deployment is personal/local.
- Weekly replanning carries incomplete tasks forward; it does not yet optimize a new dependency graph.
