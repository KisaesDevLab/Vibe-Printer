"""Read-only printer endpoints (P11.4)."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends

from .. import __version__
from ..backends.factory import make_backend
from ..context import Context
from ..deps import AuthInfo, get_ctx, require_auth

router = APIRouter(prefix="/v1")


@router.get("/version")
def version(
    ctx: Context = Depends(get_ctx), auth: AuthInfo = Depends(require_auth)
) -> dict[str, Any]:
    mig = ctx.db.query_one("SELECT name FROM schema_migrations ORDER BY name DESC LIMIT 1")
    return {
        "app": __version__,
        "schema": mig["name"] if mig else None,
        "image_digest": ctx.settings.image_digest,
    }


@router.get("/printers")
def list_printers(
    ctx: Context = Depends(get_ctx), auth: AuthInfo = Depends(require_auth)
) -> list[dict[str, Any]]:
    out = []
    for p in ctx.registry.list_printers():
        caps = ctx.backend_capabilities(p)
        out.append(
            {
                "id": p.id,
                "name": p.name,
                "type": p.type,
                "capabilities": caps.model_dump(),
                "default_format_id": p.default_format_id,
                "default_template_id": p.default_template_id,
                "allow_raw": p.allow_raw,
                "version": p.version,
            }
        )
    return out


@router.get("/printers/{printer_id}/status")
async def printer_status(
    printer_id: int, ctx: Context = Depends(get_ctx), auth: AuthInfo = Depends(require_auth)
) -> dict[str, Any]:
    printer = ctx.registry.get_printer(printer_id)
    if printer.type == "pool":
        from ..pools import pool_status

        return {"id": printer_id, **(await pool_status(ctx, printer))}
    backend = make_backend(printer, data_dir=ctx.settings.data_dir)
    status = await asyncio.to_thread(backend.status)
    return {"id": printer_id, **status}
