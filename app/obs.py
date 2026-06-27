"""Observability: structlog JSON logging, request-id middleware, Prometheus metrics, audit.

Redaction rule (Phase 29.3): never log payload bodies or merged `data` — ids + metadata only.
Audit writers live here too; they persist to the DB (see app.db schema).
"""

from __future__ import annotations

import logging
import sys
import uuid
from collections.abc import MutableMapping
from contextvars import ContextVar
from typing import Any

import structlog
from fastapi import FastAPI, Request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

# --- Metrics ---
JOBS_TOTAL = Counter("vibe_print_jobs_total", "Jobs by terminal status", ["status"])
JOBS_BY_PRINTER = Counter("vibe_print_jobs_by_printer_total", "Jobs per printer", ["printer_id"])
QUEUE_DEPTH = Gauge("vibe_print_queue_depth", "Current queued+active jobs")
RENDER_SECONDS = Histogram("vibe_print_render_seconds", "Render duration", ["kind"])


# Keys that must never reach the logs (Phase 29.3): payload bodies / merged data / rendered content.
_SENSITIVE_KEYS = frozenset(
    {"payload", "payload_json", "data", "document", "html", "css", "value", "sample_data", "merged"}
)


def _redact(_: Any, __: str, event_dict: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    for key in list(event_dict.keys()):
        if key in _SENSITIVE_KEYS:
            event_dict[key] = "<redacted>"
    return event_dict


def configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            _redact,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "vibe_print") -> Any:
    return structlog.get_logger(name)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a request id and bind it to the log context."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request_id_ctx.set(rid)
        structlog.contextvars.bind_contextvars(request_id=rid, path=request.url.path)
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()
        response.headers["X-Request-ID"] = rid
        return response


def install_metrics(app: FastAPI) -> None:
    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
