# Evaluation harness

## Telemetry accounting contract

- A **logical AI request** is one business-level AI operation such as `generate_lesson`,
  `answer_question`, or `generate_quiz`. It has exactly one final outcome:
  `MODEL_SUCCESS`, `FALLBACK_SUCCESS`, or `TOTAL_FAILURE`.
- A **provider attempt** is one actual provider/model call. Attempts own latency and, when
  supplied by the provider, token usage and estimated cost. Deterministic fallback is a logical
  outcome, not an OpenAI attempt.
- A **schema failure** means provider content failed its target Pydantic schema. The attempt is
  `SCHEMA_FAILURE`; the logical request then ends as fallback success or total failure.
- A **retry** is the second or later provider attempt sharing a logical request ID. Provider retry
  is not implemented, so retry rate is unavailable rather than zero.

Fallback rate uses completed logical requests as its denominator. Schema and retry rates use
provider-backed logical requests. Latency, tokens, and cost aggregate provider attempts. Missing
usage differs from zero usage; missing pricing produces `estimated_cost=null` and
`cost_estimate_available=false`; empty latency samples return null P50/P95.

Telemetry writes are best-effort. Failures log only operation and exception type, increment
`telemetry_write_failures_total`, and never replace a successful model or fallback result.
The authenticated `/api/internal/metrics-summary` is a user-scoped persistent DB aggregate and
excludes `user_id=NULL` history. `/metrics` represents only the current API process; RQ worker
counters are not automatically present and are not cluster-wide totals.

The harness closes the development → evaluation → release → observation loop. Dataset `2.1.0` lives in `evals/datasets/v2/`; every privacy-safe case declares a production scenario, input, injected failure, expected and forbidden behavior, scoring dimensions, tags, required status, and a `dev`, `regression`, or `public_test` split.

## Modes

Deterministic, free regression:

```bash
python -m evals.run --suite all --split regression
```

This validates schemas, schedules, workflow transitions, fallback behavior and evidence rules. It reports `engineering_regression_only` and does not claim real semantic quality.

Explicit real-model sampling:

```bash
OPENAI_API_KEY=... EVAL_JUDGE_MODEL=gpt-4.1-mini \
  python -m evals.run --suite all --split public_test --live --repetitions 3
```

The tested model and judge are recorded separately. Every live case records its actual provider, model, final status, fallback use, model-call success, and schema failures. A fallback or Judge failure fails the run and prevents a real-model quality claim. Judge output uses a strict Pydantic schema, must return exactly the declared dimensions, and receives the candidate as JSON-encoded untrusted data. Repeated cases report mean and variance.

Each run writes UUID-named JSON and Markdown plus `latest.*` under ignored `evals/reports/`. Reports include Git state, dataset/model/Prompt versions, P50/P95 latency, tokens, configured cost, fallback/schema/retry rates, baseline differences and failed cases. Only the small baseline and report Schema are committed.

## Gates and maintenance

CI builds/tests the frontend, runs Python tests, and then evaluates the regression split. A required-case failure, missing dimension, missing Schema grader, schema failure, empty suite, or excessive baseline regression fails CI. Real-model public testing is manual `workflow_dispatch` and reads the API key from GitHub Secrets.

Develop new cases in `dev` and promote stable cases to `regression`. `public_test` is public and must not be described as a blind holdout. A future private dataset can be supplied with `--dataset-root /controlled/path --split private_holdout` without adding a storage service. Never add production conversations, secrets, personal data, exact prose matching, or judge instructions inside candidate input.

Generate a baseline candidate explicitly:

```bash
python -m evals.run --suite all --split regression \
  --write-baseline-candidate /tmp/baseline-candidate.json
```

Generation does not approve a baseline and refuses to overwrite an approved file. A candidate, rejected,
stale, missing, or malformed baseline makes the regression command exit non-zero. Only an `APPROVED`
baseline whose dataset version/hash match and whose source commit is an ancestor of `HEAD` participates
in comparison. Offline candidates always use `quality_claim=engineering_regression_only`.

After reviewing the candidate and its failed cases, promote it explicitly:

```bash
python -m evals.baseline approve \
  --candidate /tmp/baseline-candidate.json \
  --output evals/baseline.json \
  --reviewer "reviewer name" \
  --approval-source "PR URL or review reference"
```

Approval records the reviewer, time, and review source. Generating a candidate never performs this step.

Workflow regression reads LangGraph checkpoint snapshots/history, persisted job state, and database side
effects. It verifies same-process reconnection to the SQLite checkpoint. It does **not** claim process-restart
recovery; that remains an integration limitation.

Cases marked `integration_pending` are listed in reports and excluded from pass counts. They must not be presented as covered. The current Assessment submission idempotency case is pending because the product endpoint has no Idempotency-Key contract; live Redis/RQ retry is likewise pending outside a real worker environment.

## Production telemetry

Prometheus exports bounded labels only: teaching requests/fallback/schema failures, workflow resumes/failures, quiz attempts/passes, plan generation/deadline risk, AI duration, tokens and configured cost estimates. IDs, questions, prompts and full errors are never labels.

Authenticated users can read their own privacy-safe aggregate at `GET /api/internal/metrics-summary`. It omits content, identifiers, token counts, credentials, prompts, rubrics and error text. Offline regression, real-model quality evaluation, production telemetry and user product outcomes are distinct signals.
## Telemetry authenticity and migration boundary

Live model authenticity is evaluated per declared logical operation inside the case correlation.
Missing, duplicate, or unexpected operations fail the live check; one successful step cannot hide a
fallback or missing provider call in another step.

Migration history was frozen once while the project was pre-release. Revision 0001 contains static
initial-schema operations; revisions 0002 through 0006 own later evolution and are immutable from
this point onward.
