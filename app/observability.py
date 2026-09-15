import logging
import time
from uuid import uuid4

import sentry_sdk
from fastapi import FastAPI, Request
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import Counter, Histogram, make_asgi_app

from app.config import settings


logger = logging.getLogger("mission_control")
REQUEST_COUNT = Counter(
    "mission_control_http_requests_total", "HTTP requests", ["method", "path", "status"]
)
REQUEST_LATENCY = Histogram(
    "mission_control_http_request_duration_seconds", "HTTP request latency", ["method", "path"]
)
AI_LOGICAL_REQUESTS = Counter("ai_logical_requests_total", "Completed logical AI requests", ["run_type", "outcome"])
AI_PROVIDER_ATTEMPTS = Counter("ai_provider_attempts_total", "Actual provider attempts", ["run_type", "provider", "status"])
TEACHING_REQUESTS = Counter("teaching_requests_total", "Completed teaching logical requests", ["outcome"])
TEACHING_FALLBACK = Counter("teaching_fallback_total", "Teaching fallback responses")
TEACHING_SCHEMA_FAILURES = Counter("teaching_schema_failures_total", "Invalid teaching model outputs")
WORKFLOW_RESUME = Counter("workflow_resume_total", "Persisted workflow resumes", ["workflow"])
WORKFLOW_FAILURES = Counter("workflow_failures_total", "Workflow failures", ["workflow"])
QUIZ_ATTEMPTS = Counter("quiz_attempts_total", "Quiz attempts")
QUIZ_PASS = Counter("quiz_pass_total", "Passing quiz attempts")
PLAN_GENERATION = Counter(
    "plan_ai_operations_total", "Completed plan AI logical operations", ["outcome"]
)
DEADLINE_RISK = Counter("deadline_risk_total", "Plans reporting deadline risk")
AI_REQUEST_DURATION = Histogram(
    "ai_request_duration_seconds", "AI request duration", ["run_type", "provider"]
)
AI_TOKENS = Counter("ai_tokens_total", "AI tokens", ["run_type", "provider", "direction"])
ESTIMATED_AI_COST = Counter(
    "estimated_ai_cost_total", "Estimated AI cost in USD", ["run_type", "provider"]
)
TELEMETRY_WRITE_FAILURES = Counter("telemetry_write_failures_total", "Best-effort telemetry persistence failures", ["operation"])


def _safe_type(run_type: str) -> str:
    safe_type = run_type if run_type in {
        "TEACHING", "PLAN_GENERATION", "ASSESSMENT", "QUIZ_GENERATION",
        "QUIZ_EVALUATION", "MODULE_GENERATION",
    } else "OTHER"
    return safe_type

def record_provider_attempt(run_type: str, provider: str, status: str, duration_seconds: float,
                            input_tokens: int | None = None, output_tokens: int | None = None,
                            estimated_cost: float | None = None) -> None:
    safe_type=_safe_type(run_type)
    safe_provider = provider if provider in {"openai", "local"} else "other"
    safe_status = status if status in {"SUCCEEDED", "FAILED", "SCHEMA_FAILURE"} else "UNKNOWN"
    AI_PROVIDER_ATTEMPTS.labels(safe_type,safe_provider,safe_status).inc()
    AI_REQUEST_DURATION.labels(safe_type, safe_provider).observe(max(0.0, duration_seconds))
    if input_tokens is not None: AI_TOKENS.labels(safe_type, safe_provider, "input").inc(max(0,input_tokens))
    if output_tokens is not None: AI_TOKENS.labels(safe_type, safe_provider, "output").inc(max(0,output_tokens))
    if estimated_cost is not None: ESTIMATED_AI_COST.labels(safe_type, safe_provider).inc(max(0.0,estimated_cost))

def record_logical_outcome(run_type: str, outcome: str, schema_failure: bool = False) -> None:
    safe_type=_safe_type(run_type)
    safe_outcome=outcome if outcome in {"MODEL_SUCCESS","FALLBACK_SUCCESS","TOTAL_FAILURE"} else "TOTAL_FAILURE"
    AI_LOGICAL_REQUESTS.labels(safe_type,safe_outcome).inc()
    if safe_type == "TEACHING":
        TEACHING_REQUESTS.labels(safe_outcome).inc()
        if safe_outcome == "FALLBACK_SUCCESS":
            TEACHING_FALLBACK.inc()
        if schema_failure: TEACHING_SCHEMA_FAILURES.inc()
    if safe_type == "PLAN_GENERATION":
        PLAN_GENERATION.labels(safe_outcome).inc()

def record_telemetry_failure(operation: str, exc: Exception) -> None:
    try:
        safe_operation=operation if operation in {"start_request","provider_attempt","finalize_request","schema_failure"} else "other"
        TELEMETRY_WRITE_FAILURES.labels(safe_operation).inc()
        logger.error("telemetry_write_failed operation=%s exception_type=%s",safe_operation,type(exc).__name__)
    except Exception:
        # Failure reporting is the final best-effort boundary and must never affect business output.
        return

# Compatibility for callers/tests outside the lifecycle implementation.
def record_ai_request(run_type: str, provider: str, status: str, duration_seconds: float,
                      input_tokens: int | None = None, output_tokens: int | None = None,
                      estimated_cost: float | None = None) -> None:
    record_provider_attempt(run_type,provider,status,duration_seconds,input_tokens,output_tokens,estimated_cost)


def configure_observability(app: FastAPI) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if settings.sentry_dsn:
        sentry_sdk.init(
            dsn=settings.sentry_dsn, environment=settings.environment,
            traces_sample_rate=.1, send_default_pii=False,
        )
    if settings.otel_exporter_endpoint:
        provider = TracerProvider(resource=Resource.create({"service.name": "mission-control-api"}))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(
            endpoint=settings.otel_exporter_endpoint
        )))
        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument_app(app)
    app.mount("/metrics", make_asgi_app())

    @app.middleware("http")
    async def request_metrics(request: Request, call_next):
        request_id = request.headers.get("x-request-id", str(uuid4()))
        started = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("request_failed request_id=%s path=%s", request_id, request.url.path)
            raise
        latency_ms = round((time.monotonic() - started) * 1000)
        route = request.scope.get("route")
        path_template = getattr(route, "path", request.url.path)
        REQUEST_COUNT.labels(request.method, path_template, response.status_code).inc()
        REQUEST_LATENCY.labels(request.method, path_template).observe(latency_ms / 1000)
        response.headers["x-request-id"] = request_id
        response.headers["server-timing"] = f"app;dur={latency_ms}"
        logger.info(
            "request request_id=%s method=%s path=%s status=%s latency_ms=%s",
            request_id, request.method, request.url.path, response.status_code, latency_ms,
        )
        return response
