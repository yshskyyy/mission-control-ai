# Architecture: production modular monolith

## System view

```text
React 19 + TypeScript + Vite + React Flow
                  │ HTTPS / JWT
                  ▼
FastAPI API ── services ── AI gateway (OpenAI + deterministic fallback)
    │              │                 │
    │              └──── LangGraph resumable recommendation workflow
    │                                │
    ├── SQLAlchemy Core ── PostgreSQL (business state, users, audit runs)
    ├── RQ ─────────────── Redis AOF (durable ingestion queue)
    ├── Prometheus /metrics, OpenTelemetry OTLP, Sentry
    └── static React production bundle

Scheduler ── RQ ── Queue worker ── LangGraph ── PostgreSQL
                                   └── checkpoint store
```

SQLite remains supported only as a zero-dependency local/test profile. Hosted
deployments use PostgreSQL and apply the Alembic migration before the API starts.

## Quality and observability loop

Versioned synthetic cases feed separate deterministic rule graders and an optional strict-schema LLM judge. The runner records experiment metadata and compares regression results with the committed baseline. Pull requests never call a paid model; the repository's public test split is not a secret holdout, and real-model evaluation is manual.

AI runs carry nullable `correlation_id`, `logical_request_id`, and `attempt_id`. Evaluation authenticity
queries only the current correlation rather than scanning historical runs. Workflow evidence comes from
checkpoint snapshots/history plus persisted job state and side effects. The SQLite test demonstrates
same-process checkpoint reconnection only, not operating-system process restart recovery.

`ai_logical_requests` owns one business operation and its single final outcome. The compatibility
`ai_runs` table now represents provider-attempt detail; it owns provider/model latency, optional usage,
optional cost, and schema/provider failure status. User summaries aggregate outcomes from the former
and attempt measurements from the latter, preventing fallback chains from becoming multiple requests.

At runtime, `ai_runs` stores user-scoped provider/model/Prompt version, latency, token accounting, configured cost estimate, fallback/failure state and retry count. Prometheus receives bounded operational labels only. The authenticated metrics-summary API computes privacy-safe aggregates. Engineering regression, sampled model quality, operational telemetry and user outcomes remain intentionally separate.

Logical outcomes use an atomic, terminal-only database transition. A completed fallback is recorded
only after the deterministic implementation returns; a failed fallback becomes `TOTAL_FAILURE`.
Requests left without a terminal outcome are reported as incomplete and, after
`AI_LOGICAL_REQUEST_STALE_SECONDS` (default 900 seconds), stale. Stale requests are detected only;
there is currently no background reconciliation or reaper.

Prometheus counters describe events observed by the current process and reset when that process is
restarted. The authenticated database summary describes persisted, user-owned history. A telemetry
storage failure can therefore make the views differ without changing the product response.
`plan_ai_operations_total` measures completed planning AI operations, not plan persistence.
Legacy rows without an owner are silently excluded from ordinary user summaries.

## Boundaries

- `frontend/`: authenticated React SPA and interactive knowledge graph.
- `app/main.py`: HTTP transport, authorization and ownership checks.
- `app/services.py`: use cases and deterministic business constraints.
- `app/ai.py`: structured model calls, prompt versions and local fallback.
- `app/intelligence.py`: untrusted GitHub/news collection and scoring.
- `app/workflows.py`: resumable LangGraph recommendation workflow.
- `app/queueing.py`, `app/jobs.py`, `app/worker.py`: Redis/RQ dispatch, jobs and scheduler.
- `app/repository.py`: persistence through the SQLAlchemy connection boundary.
- `app/models.py`, `migrations/`: portable schema and versioned migrations.
- `app/observability.py`: request IDs, metrics, traces and error reporting.

## Security and tenancy

Passwords are Argon2 hashes. Short-lived HS256 bearer tokens identify a user;
every goal-scoped route verifies ownership before reading or mutating state.
`AUTH_DISABLED=true` is restricted to local demos/tests and maps requests to the
seeded local user.

## AI and workflow policy

Interactive plan, assessment and tutor endpoints are async FastAPI handlers and
move blocking SDK work to the thread pool so the event loop remains available.
Long-running trend ingestion is persisted as a database job and dispatched to RQ
with retries. LangGraph owns workflow control/checkpoints, not business entities.
Model output is schema-validated; application code owns budgets, permissions,
status transitions and plan versioning.

## Data and failure behavior

- PostgreSQL is the source of truth; Redis is transport, never the business record.
- Recommendation writes are idempotent and external content is untrusted.
- Only an accepted recommendation may create a module and update the graph.
- Redis failure falls back to an in-process task for local availability.
- SQLite LangGraph checkpoints use the shared worker volume. A future multi-host
  deployment should move checkpoints to a PostgreSQL checkpointer.

## Deployment units

`compose.yaml` runs PostgreSQL, Redis, the API, an RQ worker and the periodic
intelligence scheduler. The API applies `alembic upgrade head` at startup. The
Docker image builds the React bundle in a Node stage and serves it from FastAPI.
