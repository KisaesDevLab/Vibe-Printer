"""Admin API (P13): full config management under /v1/admin, every mutation audited."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Body, Depends, File, Form, UploadFile
from fastapi.responses import Response

from .backends.factory import make_backend
from .context import Context
from .deps import AuthInfo, get_ctx, require_access, require_auth
from .errors import ApiError
from .models import (
    DeviceUpdate,
    FormatCreate,
    FormatUpdate,
    PreviewRequest,
    PrinterCreate,
    PrinterUpdate,
    TemplateCreate,
    TemplateUpdate,
)

# Access is verified first (sets identity), then the shared-secret + rate-limit guard.
router = APIRouter(
    prefix="/v1/admin", dependencies=[Depends(require_access), Depends(require_auth)]
)


# --------------------------------------------------------------------------- device
@router.get("/device")
def get_device(ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    return ctx.registry.get_device()


@router.put("/device")
def update_device(
    data: DeviceUpdate, ctx: Context = Depends(get_ctx), auth: AuthInfo = Depends(require_auth)
) -> dict[str, Any]:
    result = ctx.registry.update_device(data)
    ctx.audit.config_change(entity="device", action="update", real_ip=auth.real_ip)
    return result


# --------------------------------------------------------------------------- printers
@router.get("/printers")
def list_printers(ctx: Context = Depends(get_ctx)) -> list[dict[str, Any]]:
    return [p.model_dump() for p in ctx.registry.list_printers()]


@router.post("/printers", status_code=201)
def create_printer(
    data: PrinterCreate, ctx: Context = Depends(get_ctx), auth: AuthInfo = Depends(require_auth)
) -> dict[str, Any]:
    p = ctx.registry.create_printer(data)
    ctx.audit.config_change(
        entity="printer", entity_id=str(p.id), action="create", real_ip=auth.real_ip
    )
    return p.model_dump()


@router.get("/printers/{printer_id}")
def get_printer(printer_id: int, ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    return ctx.registry.get_printer(printer_id).model_dump()


@router.put("/printers/{printer_id}")
def update_printer(
    printer_id: int,
    data: PrinterUpdate,
    ctx: Context = Depends(get_ctx),
    auth: AuthInfo = Depends(require_auth),
) -> dict[str, Any]:
    p = ctx.registry.update_printer(printer_id, data)
    ctx.audit.config_change(
        entity="printer", entity_id=str(printer_id), action="update", real_ip=auth.real_ip
    )
    return p.model_dump()


@router.delete("/printers/{printer_id}", status_code=204)
def delete_printer(
    printer_id: int, ctx: Context = Depends(get_ctx), auth: AuthInfo = Depends(require_auth)
) -> Response:
    ctx.registry.delete_printer(printer_id)
    ctx.audit.config_change(
        entity="printer", entity_id=str(printer_id), action="delete", real_ip=auth.real_ip
    )
    return Response(status_code=204)


@router.post("/printers/{printer_id}/provision-queue")
def provision_queue(
    printer_id: int,
    body: dict[str, Any] = Body(...),
    ctx: Context = Depends(get_ctx),
    auth: AuthInfo = Depends(require_auth),
) -> dict[str, Any]:
    """Create/configure a CUPS queue from the registry (P6.1)."""
    from .backends.base import BackendError

    printer = ctx.registry.get_printer(printer_id)
    if printer.type != "cups":
        raise ApiError("unsupported_for_printer", "only CUPS printers have queues")
    device_uri = body.get("device_uri")
    if not device_uri:
        raise ApiError("validation_error", "device_uri is required (e.g. ipp://printer.local/ipp/print)")
    backend = make_backend(printer, data_dir=ctx.settings.data_dir)
    try:
        backend.provision_queue(device_uri, make_model=body.get("make_model", "everywhere"))  # type: ignore[attr-defined]
    except BackendError as e:
        raise ApiError("printer_unreachable", str(e)) from e
    ctx.audit.config_change(
        entity="printer", entity_id=str(printer_id), action="provision_queue", real_ip=auth.real_ip
    )
    return {"provisioned": printer.params.get("queue")}


@router.post("/printers/{printer_id}/test")
def test_print(printer_id: int, ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    printer = ctx.registry.get_printer(printer_id)
    if printer.type == "cups":
        raise ApiError("unsupported_for_printer", "use a template-based test for CUPS")
    doc = {
        "elements": [
            {"type": "text", "value": "vibe-print test", "align": "center", "bold": True},
            {"type": "text", "value": "{{ data.ts }}", "align": "center"},
            {"type": "feed", "lines": 1},
            {"type": "cut"},
        ]
    }
    from .db import utcnow_iso

    job = ctx.jobs.enqueue(
        printer_id=printer_id,
        payload={"document": doc, "data": {"ts": utcnow_iso()}, "copies": 1},
        global_max=ctx.settings.queue_max_depth,
        per_printer_max=ctx.settings.per_printer_max_depth,
    )
    return {"job_id": job["id"], "status": job["status"]}


@router.get("/printers/{printer_id}/status")
async def printer_status(printer_id: int, ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    printer = ctx.registry.get_printer(printer_id)
    if printer.type == "pool":
        from .pools import pool_status

        return await pool_status(ctx, printer)
    backend = make_backend(printer, data_dir=ctx.settings.data_dir)
    return await asyncio.to_thread(backend.status)


# --------------------------------------------------------------------------- provisioning (P27)
@router.get("/provision/status")
def provision_status(ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    dev = ctx.registry.get_device()
    return {
        "provisioned": bool(dev["config"].get("provisioned")),
        "printers": len(ctx.registry.list_printers()),
    }


@router.post("/provision")
def provision(
    body: dict[str, Any] = Body(default={}),
    ctx: Context = Depends(get_ctx),
    auth: AuthInfo = Depends(require_auth),
) -> dict[str, Any]:
    dev = ctx.registry.get_device()
    config = dict(dev["config"])
    config["provisioned"] = True
    ctx.registry.update_device(
        DeviceUpdate(
            name=body.get("name", dev["name"]),
            timezone=body.get("timezone", dev["timezone"]),
            config=config,
            version=dev["version"],
        )
    )
    if body.get("yaml"):
        ctx.registry.import_yaml(body["yaml"], dry_run=False)
    ctx.audit.config_change(entity="device", action="provision", real_ip=auth.real_ip)
    return ctx.registry.get_device()


@router.post("/discover")
async def discover(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    from .discovery import scan

    subnet = body.get("subnet")
    if not subnet:
        raise ApiError("validation_error", "provide a subnet, e.g. 192.168.1.0/24")
    timeout = float(body.get("timeout", 0.5))
    candidates = await scan(subnet, timeout=timeout)
    return {"candidates": candidates}


# --------------------------------------------------------------------------- formats
@router.get("/formats")
def list_formats(ctx: Context = Depends(get_ctx)) -> list[dict[str, Any]]:
    return ctx.registry.list_formats()


@router.post("/formats", status_code=201)
def create_format(
    data: FormatCreate, ctx: Context = Depends(get_ctx), auth: AuthInfo = Depends(require_auth)
) -> dict[str, Any]:
    f = ctx.registry.create_format(data)
    ctx.audit.config_change(
        entity="format", entity_id=str(f["id"]), action="create", real_ip=auth.real_ip
    )
    return f


@router.get("/formats/{fid}")
def get_format(fid: int, ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    return ctx.registry.get_format(fid)


@router.put("/formats/{fid}")
def update_format(
    fid: int, data: FormatUpdate, ctx: Context = Depends(get_ctx),
    auth: AuthInfo = Depends(require_auth),
) -> dict[str, Any]:
    f = ctx.registry.update_format(fid, data)
    ctx.audit.config_change(
        entity="format", entity_id=str(fid), action="update", real_ip=auth.real_ip
    )
    return f


@router.delete("/formats/{fid}", status_code=204)
def delete_format(
    fid: int, ctx: Context = Depends(get_ctx), auth: AuthInfo = Depends(require_auth)
) -> Response:
    ctx.registry.delete_format(fid)
    ctx.audit.config_change(
        entity="format", entity_id=str(fid), action="delete", real_ip=auth.real_ip
    )
    return Response(status_code=204)


@router.post("/formats/{fid}/preview")
def preview_format(
    fid: int, body: dict[str, Any] = Body(default={}), ctx: Context = Depends(get_ctx)
) -> Response:
    from .api.print import _render_preview

    fmt = ctx.registry.get_format(fid)
    # Prefer inline elements from the editor (unsaved); fall back to the stored format.
    elements = body.get("elements") or fmt["elements"]
    req = PreviewRequest(document=elements, data=body.get("data") or fmt["sample_data"])
    return _render_preview(ctx, req)


# --------------------------------------------------------------------------- templates
@router.get("/templates")
def list_templates(ctx: Context = Depends(get_ctx)) -> list[dict[str, Any]]:
    return ctx.registry.list_templates()


@router.post("/templates", status_code=201)
def create_template(
    data: TemplateCreate, ctx: Context = Depends(get_ctx), auth: AuthInfo = Depends(require_auth)
) -> dict[str, Any]:
    t = ctx.registry.create_template(data)
    ctx.audit.config_change(
        entity="template", entity_id=str(t["id"]), action="create", real_ip=auth.real_ip
    )
    return t


@router.get("/templates/{tid}")
def get_template(tid: int, ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    return ctx.registry.get_template(tid)


@router.put("/templates/{tid}")
def update_template(
    tid: int, data: TemplateUpdate, ctx: Context = Depends(get_ctx),
    auth: AuthInfo = Depends(require_auth),
) -> dict[str, Any]:
    t = ctx.registry.update_template(tid, data)
    ctx.audit.config_change(
        entity="template", entity_id=str(tid), action="update", real_ip=auth.real_ip
    )
    return t


@router.delete("/templates/{tid}", status_code=204)
def delete_template(
    tid: int, ctx: Context = Depends(get_ctx), auth: AuthInfo = Depends(require_auth)
) -> Response:
    ctx.registry.delete_template(tid)
    ctx.audit.config_change(
        entity="template", entity_id=str(tid), action="delete", real_ip=auth.real_ip
    )
    return Response(status_code=204)


@router.post("/templates/{tid}/preview")
def preview_template(
    tid: int, body: dict[str, Any] = Body(default={}), ctx: Context = Depends(get_ctx)
) -> Response:
    from .api.print import _render_preview

    tpl = ctx.registry.get_template(tid)
    # Inline html/css/page_setup from the editor (unsaved); fall back to stored.
    req = PreviewRequest(
        html=body.get("html", tpl["html"]),
        css=body.get("css", tpl["css"]),
        page_setup=body.get("page_setup", tpl["page_setup"]),
        data=body.get("data") or tpl["sample_data"],
    )
    return _render_preview(ctx, req)


# --------------------------------------------------------------------------- assets
@router.get("/assets")
def list_assets(ctx: Context = Depends(get_ctx)) -> list[dict[str, Any]]:
    return ctx.assets.list()


@router.post("/assets", status_code=201)
async def upload_asset(
    file: UploadFile = File(...),
    name: str = Form(default=""),
    ctx: Context = Depends(get_ctx),
    auth: AuthInfo = Depends(require_auth),
) -> dict[str, Any]:
    content = await file.read()
    asset = ctx.assets.save(
        name or file.filename or "asset",
        file.content_type or "application/octet-stream",
        content,
    )
    ctx.audit.config_change(
        entity="asset", entity_id=str(asset["id"]), action="create", real_ip=auth.real_ip
    )
    return asset


@router.delete("/assets/{asset_id}", status_code=204)
def delete_asset(
    asset_id: int, ctx: Context = Depends(get_ctx), auth: AuthInfo = Depends(require_auth)
) -> Response:
    ctx.assets.delete(asset_id)
    ctx.audit.config_change(
        entity="asset", entity_id=str(asset_id), action="delete", real_ip=auth.real_ip
    )
    return Response(status_code=204)


# --------------------------------------------------------------------------- config import/export
@router.post("/config/export")
def export_config(ctx: Context = Depends(get_ctx)) -> Response:
    return Response(ctx.registry.export_yaml(), media_type="application/x-yaml")


@router.post("/config/import")
def import_config(
    body: dict[str, Any] = Body(...),
    ctx: Context = Depends(get_ctx),
    auth: AuthInfo = Depends(require_auth),
) -> dict[str, Any]:
    yaml_text = body.get("yaml", "")
    dry_run = bool(body.get("dry_run", True))
    plan = ctx.registry.import_yaml(yaml_text, dry_run=dry_run)
    if not dry_run:
        ctx.audit.config_change(entity="config", action="import", real_ip=auth.real_ip, diff=plan)
    return plan


# --------------------------------------------------------------------------- jobs admin
@router.get("/jobs")
def list_jobs(
    status: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
    ctx: Context = Depends(get_ctx),
) -> dict[str, Any]:
    jobs = ctx.jobs.list_jobs(status=status, limit=limit, before_id=cursor)
    return {
        "jobs": jobs,
        "counts": ctx.jobs.counts_by_status(),
        "depth": ctx.jobs.depth(),
        "next_cursor": jobs[-1]["id"] if len(jobs) == limit else None,
    }


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    return ctx.jobs.cancel(job_id)


@router.post("/jobs/{job_id}/requeue")
def requeue_job(job_id: str, ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    return ctx.jobs.requeue(job_id)


@router.post("/jobs/{job_id}/resolve")
def resolve_job(
    job_id: str, body: dict[str, Any] = Body(default={}), ctx: Context = Depends(get_ctx)
) -> dict[str, Any]:
    return ctx.jobs.resolve(job_id, body.get("outcome", "done"))


@router.delete("/jobs/{job_id}/payload")
def erase_payload(
    job_id: str, ctx: Context = Depends(get_ctx), auth: AuthInfo = Depends(require_auth)
) -> dict[str, Any]:
    """On-demand erasure of a single job's payload (Phase 29.4)."""
    ctx.jobs.redact_payload(job_id)
    ctx.audit.config_change(
        entity="job", entity_id=job_id, action="erase_payload", real_ip=auth.real_ip
    )
    return {"erased": job_id}


@router.post("/backup/snapshot")
def backup_snapshot(
    ctx: Context = Depends(get_ctx), auth: AuthInfo = Depends(require_auth)
) -> dict[str, Any]:
    """Create a consistent on-disk DB snapshot for the backup job to ship to B2 (P22.7)."""
    from .db import utcnow_iso

    backups = ctx.settings.data_dir / "backups"
    stamp = utcnow_iso().replace(":", "").replace(".", "").replace("-", "")
    dest = backups / f"vibe-print-{stamp}.sqlite"
    ctx.db.snapshot(dest)
    ctx.audit.config_change(entity="backup", action="snapshot", real_ip=auth.real_ip)
    return {
        "path": str(dest),
        "size": dest.stat().st_size,
        "assets_dir": str(ctx.settings.assets_dir),
        "encrypted": ctx.db.encrypted,
    }


@router.post("/retention/prune")
def prune_now(
    ctx: Context = Depends(get_ctx), auth: AuthInfo = Depends(require_auth)
) -> dict[str, Any]:
    """Run retention pruning immediately (jobs + audit + idempotency)."""
    ctx.jobs.prune(
        job_days=ctx.settings.job_retention_days,
        idem_hours=ctx.settings.idempotency_ttl_hours,
    )
    ctx.audit.prune(ctx.settings.audit_retention_days)
    ctx.audit.config_change(entity="retention", action="prune", real_ip=auth.real_ip)
    return {"pruned": True}


# --------------------------------------------------------------------------- audit
@router.get("/audit/config")
def audit_config(limit: int = 100, ctx: Context = Depends(get_ctx)) -> list[dict[str, Any]]:
    return ctx.audit.list_config(limit)


@router.get("/audit/print")
def audit_print(limit: int = 100, ctx: Context = Depends(get_ctx)) -> list[dict[str, Any]]:
    return ctx.audit.list_print(limit)


@router.get("/audit/verify")
def audit_verify(ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    """Verify the tamper-evident hash chains for both audit logs."""
    return {
        "config_audit": ctx.audit.verify_chain("config_audit"),
        "print_audit": ctx.audit.verify_chain("print_audit"),
    }


# ----------------------------------------------------------------- fleet / remote (P28 / P16)
@router.get("/diagnostics")
async def diagnostics(ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    import time

    from .fleet import build_diagnostics

    uptime = time.monotonic() - (ctx.started_at or time.monotonic())
    return await build_diagnostics(ctx, uptime)


@router.post("/heartbeat/test")
async def heartbeat_test(ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    import time

    from .fleet import build_heartbeat
    from .notify import post_signed

    uptime = time.monotonic() - (ctx.started_at or time.monotonic())
    payload = await build_heartbeat(ctx, uptime)
    sent = await post_signed(ctx.settings.heartbeat_url, ctx.settings.heartbeat_secret, payload)
    return {"sent": sent, "configured": bool(ctx.settings.heartbeat_url), "payload": payload}


@router.get("/remote/status")
async def remote_status(ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    """Tunnel health (P16.4): poll cloudflared /ready. Hostname is display-only (Decision 12)."""
    import httpx

    s = ctx.settings
    result: dict[str, Any] = {
        "mode": s.remote_access_mode,
        "hostname": s.remote_hostname,
        "access_enabled": bool(s.access_team_domain and s.access_aud),
        "tunnel": "unknown",
    }
    if s.cloudflared_metrics_url:
        try:
            async with httpx.AsyncClient(timeout=3.0) as c:
                r = await c.get(s.cloudflared_metrics_url.rstrip("/") + "/ready")
            result["tunnel"] = "ready" if r.status_code == 200 else "not_ready"
        except Exception:
            result["tunnel"] = "unreachable"
    return result
