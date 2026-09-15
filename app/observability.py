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
