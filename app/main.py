"""FastAPI application: lifespan wiring, routers, static admin UI, health, security headers.

Fail-fast: the service refuses to start when VIBE_PRINT_SECRET is unset/empty (Decision 6).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from .admin import router as admin_router
from .api import jobs_router, print_router, printers_router
from .context import build_context
from .errors import install_error_handlers
from .obs import RequestContextMiddleware, configure_logging, get_logger, install_metrics
from .queue import Worker
from .settings import get_settings

log = get_logger("main")
STATIC_DIR = Path(__file__).parent / "static"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """CSP + hardening headers, especially for the /admin UI (P30.1)."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        resp = await call_next(request)
        if request.url.path.startswith("/admin"):
            resp.headers["Content-Security-Policy"] = (
                "default-src 'self'; img-src 'self' data: blob:; "
                "style-src 'self' 'unsafe-inline'; "
                # allow the in-browser PDF preview (<embed>/<iframe> of a blob: PDF)
                "object-src 'self' blob:; frame-src 'self' blob:; frame-ancestors 'none'"
            )
            resp.headers["X-Frame-Options"] = "DENY"
            resp.headers["Referrer-Policy"] = "no-referrer"
            resp.headers["X-Content-Type-Options"] = "nosniff"
        return resp


def _reprovision_cups(ctx: Any) -> None:
    """Re-create CUPS queues from the DB on startup so they survive container rebuilds
    (CUPS state in /etc/cups is ephemeral; the DB is the source of truth)."""
    from .backends.base import BackendError
    from .backends.factory import make_backend

    for p in ctx.registry.list_printers():
        if p.type != "cups" or not p.params.get("device_uri"):
            continue
        try:
            backend = make_backend(p, data_dir=ctx.settings.data_dir)
            backend.provision_queue(  # type: ignore[attr-defined]
                p.params["device_uri"], make_model=p.params.get("make_model", "everywhere")
            )
            log.info("cups_reprovisioned", printer=p.id, queue=p.params.get("queue"))
        except (BackendError, Exception) as e:  # best-effort
            log.warning("cups_reprovision_failed", printer=p.id, error=str(e))


async def _autostart_tunnel(ctx: Any) -> None:
    """Re-start the managed tunnel on boot if it was enabled (durable across restarts)."""
    from .remote import resolve_remote, tunnel_token

    r = resolve_remote(ctx)
    if not r["tunnel_enabled"]:
        return
    try:
        if r["tunnel_mode"] == "quick":
            await ctx.tunnel.start(metrics="127.0.0.1:2000")
        elif tunnel_token(ctx):
            await ctx.tunnel.start(token=tunnel_token(ctx), metrics="127.0.0.1:2000")
        log.info("tunnel_autostarted", mode=r["tunnel_mode"])
    except Exception as e:  # best-effort
        log.warning("tunnel_autostart_failed", error=str(e))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    if not settings.secret.strip():
        raise RuntimeError(
            "VIBE_PRINT_SECRET is unset/empty — refusing to start (the service never runs open)."
        )
    import time

    ctx = build_context(settings)
    ctx.started_at = time.monotonic()
    worker = Worker(ctx)
    ctx.worker = worker
    app.state.ctx = ctx
    worker.start()
    _reprovision_cups(ctx)
    await _autostart_tunnel(ctx)
    log.info("startup", data_dir=str(settings.data_dir))
    try:
        yield
    finally:
        log.info("shutdown_begin")
        await ctx.tunnel.stop()
        await worker.stop()
        ctx.db.close()
        log.info("shutdown_complete")


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="Vibe Print", version="0.1.0", lifespan=lifespan)

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestContextMiddleware)

    install_error_handlers(app)
    install_metrics(app)

    app.include_router(print_router)
    app.include_router(printers_router)
    app.include_router(jobs_router)
    app.include_router(admin_router)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    async def readyz(request: Request) -> JSONResponse:
        ctx = getattr(request.app.state, "ctx", None)
        checks = {
            "db": False,
            "worker": False,
        }
        if ctx is not None:
            try:
                ctx.db.query_one("SELECT 1")
                checks["db"] = True
            except Exception:
                checks["db"] = False
            checks["worker"] = ctx.worker is not None and ctx.worker._task is not None
        ready = all(checks.values())
        return JSONResponse(
            status_code=200 if ready else 503, content={"ready": ready, "checks": checks}
        )

    if STATIC_DIR.exists():
        app.mount("/admin", StaticFiles(directory=str(STATIC_DIR), html=True), name="admin")

    return app


app = create_app()
