"""Fleet observability (P28): heartbeat phone-home, diagnostics bundle, offline detection.

Everything here is PII-free — versions, counts, reachability, and config metadata only. Never
job payloads (P28.1).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from . import __version__
from .backends.factory import make_backend

if TYPE_CHECKING:
    from .context import Context


async def _probe_printers(ctx: Context) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in ctx.registry.list_printers():
        backend = make_backend(p, data_dir=ctx.settings.data_dir)
        try:
            status = await asyncio.wait_for(asyncio.to_thread(backend.status), 3.0)
            reachable = bool(status.get("reachable"))
        except Exception:
            reachable = False
        out.append({"id": p.id, "name": p.name, "type": p.type, "reachable": reachable})
    return out


async def build_heartbeat(ctx: Context, uptime_s: float) -> dict[str, Any]:
    device = ctx.registry.get_device()
    printers = await _probe_printers(ctx)
    return {
        "device": device["name"],
        "app_version": __version__,
        "image_digest": ctx.settings.image_digest,
        "uptime_s": round(uptime_s),
        "queue_depth": ctx.jobs.depth(),
        "job_counts": ctx.jobs.counts_by_status(),
        "printers": printers,
    }


async def build_diagnostics(ctx: Context, uptime_s: float) -> dict[str, Any]:
    """PII-free support bundle (P28.2): config snapshot + status + recent audit (no payloads)."""
    printers = await _probe_printers(ctx)
    s = ctx.settings
    return {
        "version": {"app": __version__, "image_digest": s.image_digest},
        "uptime_s": round(uptime_s),
        "device": ctx.registry.get_device(),
        "printers": printers,
        "formats": [{"id": f["id"], "name": f["name"], "version": f["version"]}
                    for f in ctx.registry.list_formats()],
        "templates": [{"id": t["id"], "name": t["name"], "version": t["version"]}
                      for t in ctx.registry.list_templates()],
        "queue": {"depth": ctx.jobs.depth(), "counts": ctx.jobs.counts_by_status()},
        "recent_print_audit": ctx.audit.list_print(25),
        "config": {
            "remote_access_mode": s.remote_access_mode,
            "store_payloads": s.store_payloads,
            "encrypt_at_rest": s.encrypt_at_rest,
            "rate_limit_per_minute": s.rate_limit_per_minute,
            "max_attempts": s.max_attempts,
            "job_retention_days": s.job_retention_days,
        },
    }
