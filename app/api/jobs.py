"""Job status + reprint (P11.5 / amendment B10)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends

from ..context import Context
from ..deps import AuthInfo, get_ctx, require_auth
from ..errors import ApiError

router = APIRouter(prefix="/v1")


def _public(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": job["id"],
        "printer_id": job["printer_id"],
        "status": job["status"],
        "delivery": job["delivery"],
        "attempts": job["attempts"],
        "last_error": job["last_error"],
        "format_id": job["format_id"],
        "template_id": job["template_id"],
        "resolved_version": job["resolved_version"],
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
    }


@router.get("/jobs/{job_id}")
def get_job(
    job_id: str, ctx: Context = Depends(get_ctx), auth: AuthInfo = Depends(require_auth)
) -> dict[str, Any]:
    return _public(ctx.jobs.get(job_id))


@router.post("/jobs/{job_id}/reprint")
def reprint(
    job_id: str, ctx: Context = Depends(get_ctx), auth: AuthInfo = Depends(require_auth)
) -> dict[str, Any]:
    """Re-render and re-enqueue from the stored payload + recorded version (amendment B10)."""
    job = ctx.jobs.get(job_id)
    payload = json.loads(job["payload_json"])
    if payload.get("_redacted"):
        raise ApiError("conflict", "payload was erased/redacted; cannot reprint", status=409)
    new_job = ctx.jobs.enqueue(
        printer_id=job["printer_id"],
        payload=payload,
        format_id=job["format_id"],
        template_id=job["template_id"],
        resolved_version=job["resolved_version"],
        global_max=ctx.settings.queue_max_depth,
        per_printer_max=ctx.settings.per_printer_max_depth,
    )
    ctx.audit.config_change(
        entity="job", entity_id=new_job["id"], action="reprint", real_ip=auth.real_ip,
        diff={"from": job_id},
    )
    return {"job_id": new_job["id"], "status": new_job["status"], "reprint_of": job_id}
