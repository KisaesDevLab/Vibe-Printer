"""Print API (P11): /v1/print, /v1/print/raw, /v1/print/preview."""

from __future__ import annotations

import base64
from typing import Any

from fastapi import APIRouter, Depends, Header
from fastapi.responses import Response

from ..context import Context
from ..deps import AuthInfo, get_ctx, require_auth
from ..errors import ApiError
from ..models import PreviewRequest, PrintRequest, RawPrintRequest
from ..queue import _canonical_hash
from ..render import render_preview_png
from ..templating import merge_format, render_pdf

router = APIRouter(prefix="/v1")


def _enforce_quota(ctx: Context, printer_id: int) -> None:
    """Per-printer daily quota from device config: {"quotas": {"<printer_id>": max_per_day}}."""
    quotas = ctx.registry.get_device()["config"].get("quotas", {})
    limit = quotas.get(str(printer_id)) or quotas.get("default")
    if not limit:
        return
    from datetime import UTC, datetime

    midnight = datetime.now(UTC).strftime("%Y-%m-%dT00:00:00.000Z")
    used = ctx.jobs.count_printer_jobs_since(printer_id, midnight)
    if used >= int(limit):
        raise ApiError(
            "quota_exceeded",
            f"daily quota of {limit} reached for printer {printer_id}",
            status=429,
            details={"used": used, "limit": int(limit)},
        )


def _resolve_targets(ctx: Context, req: PrintRequest) -> dict[str, Any]:
    printer = ctx.registry.get_printer(req.printer)
    payload: dict[str, Any] = {"data": req.data, "copies": req.copies}
    format_id = req.format
    template_id = req.template
    resolved_version = None

    if printer.type == "cups":
        if req.document or req.format:
            raise ApiError("unsupported_for_printer", "CUPS printers use a PDF template")
        template_id = template_id or printer.default_template_id
        if not template_id:
            raise ApiError("validation_error", "no template and printer has no default template")
        tpl = ctx.registry.get_template(template_id)
        resolved_version = tpl["version"]
        payload["template"] = template_id
    else:
        if req.document:
            payload["document"] = req.document
        else:
            format_id = format_id or printer.default_format_id
            if not format_id:
                raise ApiError("validation_error", "no document/format and no default format")
            fmt = ctx.registry.get_format(format_id)
            resolved_version = fmt["version"]
            payload["format"] = format_id

    return {
        "printer": printer,
        "payload": payload,
        "format_id": format_id if "format" in payload else None,
        "template_id": template_id if "template" in payload else None,
        "resolved_version": resolved_version,
    }


@router.post("/print")
def print_job(
    req: PrintRequest,
    ctx: Context = Depends(get_ctx),
    auth: AuthInfo = Depends(require_auth),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    resolved = _resolve_targets(ctx, req)
    payload = resolved["payload"]

    _enforce_quota(ctx, req.printer)

    if idempotency_key:
        request_hash = _canonical_hash({"printer": req.printer, **payload})
        existing = ctx.jobs.idempotency_lookup(idempotency_key)
        if existing:
            if existing["request_hash"] != request_hash:
                raise ApiError("idempotency_conflict", "key reused with a different payload")
            job = ctx.jobs.get(existing["job_id"])
            return {"job_id": job["id"], "status": job["status"], "idempotent_replay": True}

    job = ctx.jobs.enqueue(
        printer_id=req.printer,
        payload=payload,
        format_id=resolved["format_id"],
        template_id=resolved["template_id"],
        resolved_version=resolved["resolved_version"],
        idempotency_key=idempotency_key,
        priority=req.priority,
        scheduled_at=req.scheduled_at,
        global_max=ctx.settings.queue_max_depth,
        per_printer_max=ctx.settings.per_printer_max_depth,
    )
    if idempotency_key:
        ctx.jobs.idempotency_store(
            idempotency_key, _canonical_hash({"printer": req.printer, **payload}), job["id"]
        )
    return {"job_id": job["id"], "status": job["status"]}


@router.post("/print/raw")
def print_raw(
    req: RawPrintRequest,
    ctx: Context = Depends(get_ctx),
    auth: AuthInfo = Depends(require_auth),
) -> dict[str, Any]:
    printer = ctx.registry.get_printer(req.printer)
    if printer.type == "cups":
        raise ApiError("unsupported_for_printer", "print/raw is ESC/POS only")
    if not printer.allow_raw:
        raise ApiError("forbidden", "print/raw disabled for this printer (enable allow_raw)")
    try:
        base64.b64decode(req.data, validate=True)
    except Exception as e:
        raise ApiError("validation_error", "data is not valid base64") from e
    job = ctx.jobs.enqueue(
        printer_id=req.printer,
        payload={"raw": req.data, "copies": 1},
        global_max=ctx.settings.queue_max_depth,
        per_printer_max=ctx.settings.per_printer_max_depth,
    )
    return {"job_id": job["id"], "status": job["status"]}


@router.post("/print/preview")
def print_preview(
    req: PreviewRequest,
    ctx: Context = Depends(get_ctx),
    auth: AuthInfo = Depends(require_auth),
) -> Response:
    return _render_preview(ctx, req)


def _render_preview(ctx: Context, req: PreviewRequest) -> Response:
    data = req.data
    # PDF path: inline html, an explicit template, or a CUPS printer target.
    is_pdf = (
        req.html is not None
        or req.template is not None
        or (req.printer is not None and ctx.registry.get_printer(req.printer).type == "cups")
    )
    if is_pdf:
        if req.html is not None:
            # Inline: render the editor's current (unsaved) content directly.
            html, css = req.html, req.css or ""
            page_setup = req.page_setup or {}
        elif req.template is not None:
            tpl = ctx.registry.get_template(req.template)
            html, css, page_setup = tpl["html"], tpl["css"], tpl["page_setup"]
        else:
            raise ApiError("validation_error", "PDF preview needs html or a template")
        pdf = render_pdf(html, css, page_setup, data, ctx.settings.assets_dir)
        return Response(pdf, media_type="application/pdf")

    # PNG (thermal) path
    if req.document:
        elements = merge_format(req.document, data)
        params = {"columns": 48}
    elif req.format is not None:
        fmt = ctx.registry.get_format(req.format)
        elements = merge_format(fmt["elements"], data or fmt["sample_data"])
        params = {"columns": 48}
    else:
        raise ApiError("validation_error", "provide document, format, or template")
    if req.printer is not None:
        params = ctx.registry.get_printer(req.printer).params
    png = render_preview_png(elements, params)
    return Response(png, media_type="image/png")
