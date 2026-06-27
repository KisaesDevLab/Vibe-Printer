"""Durable SQLite job store + async worker (P10).

Delivery guarantees:
- Per-printer serialization for ESC/POS (network/usb/virtual) via async locks; CUPS runs parallel.
- At-most-once for the in-flight job: a mid-send failure -> ``uncertain`` (never auto-retried).
- All other delivery failures retry with exponential backoff up to ``max_attempts`` -> ``dead``.
- Idempotency keys dedupe within a TTL; same key + different payload -> ``idempotency_conflict``.
- Backpressure: global + per-printer depth caps -> ``queue_full``.
- Graceful drain on shutdown.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from .backends import MidSendError, PrinterUnreachable, PrintPayload
from .backends.base import BackendError
from .backends.factory import is_serialized, make_backend
from .db import Database, utcnow_iso
from .errors import ApiError
from .notify import post_signed
from .obs import JOBS_BY_PRINTER, JOBS_TOTAL, QUEUE_DEPTH, get_logger
from .render import render_escpos
from .templating import merge_format, render_pdf

if TYPE_CHECKING:
    from .context import Context

log = get_logger("queue")

ACTIVE_STATES = ("queued", "rendering", "printing")


def _canonical_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


class JobStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------------ enqueue
    def enqueue(
        self,
        *,
        printer_id: int,
        payload: dict[str, Any],
        format_id: int | None = None,
        template_id: int | None = None,
        resolved_version: int | None = None,
        idempotency_key: str | None = None,
        priority: int = 0,
        scheduled_at: str | None = None,
        global_max: int,
        per_printer_max: int,
    ) -> dict[str, Any]:
        # Backpressure (P10.5)
        depth = self.depth()
        if depth >= global_max:
            raise ApiError("queue_full", "global queue is full", status=429)
        pdepth = self.printer_depth(printer_id)
        if pdepth >= per_printer_max:
            raise ApiError("queue_full", f"printer {printer_id} queue is full", status=429)

        job_id = uuid.uuid4().hex
        self.db.execute(
            "INSERT INTO jobs(id,idempotency_key,printer_id,format_id,template_id,"
            "resolved_version,payload_json,status,attempts,priority,scheduled_at,"
            "created_at,updated_at) VALUES (?,?,?,?,?,?,?, 'queued', 0, ?, ?, ?, ?)",
            (
                job_id,
                idempotency_key,
                printer_id,
                format_id,
                template_id,
                resolved_version,
                json.dumps(payload),
                priority,
                scheduled_at,
                utcnow_iso(),
                utcnow_iso(),
            ),
        )
        QUEUE_DEPTH.set(self.depth())
        return self.get(job_id)

    def count_printer_jobs_since(self, printer_id: int, since_iso: str) -> int:
        row = self.db.query_one(
            "SELECT COUNT(*) c FROM jobs WHERE printer_id=? AND created_at >= ? "
            "AND status != 'canceled'",
            (printer_id, since_iso),
        )
        return int(row["c"]) if row else 0

    # -------------------------------------------------------------------- reads
    def get(self, job_id: str) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM jobs WHERE id=?", (job_id,))
        if row is None:
            raise ApiError("not_found", f"no job {job_id}")
        return dict(row)

    def list_jobs(
        self, *, status: str | None = None, limit: int = 50, before_id: str | None = None
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM jobs"
        params: list[Any] = []
        clauses = []
        if status:
            clauses.append("status=?")
            params.append(status)
        if before_id:
            # Cursor pagination: rows older than the cursor job (amendment B11).
            clauses.append("created_at < (SELECT created_at FROM jobs WHERE id=?)")
            params.append(before_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self.db.query(sql, params)]

    def depth(self) -> int:
        row = self.db.query_one(
            f"SELECT COUNT(*) c FROM jobs WHERE status IN ({','.join('?'*len(ACTIVE_STATES))})",
            ACTIVE_STATES,
        )
        return int(row["c"]) if row else 0

    def printer_depth(self, printer_id: int) -> int:
        row = self.db.query_one(
            f"SELECT COUNT(*) c FROM jobs WHERE printer_id=? AND "
            f"status IN ({','.join('?'*len(ACTIVE_STATES))})",
            (printer_id, *ACTIVE_STATES),
        )
        return int(row["c"]) if row else 0

    def counts_by_status(self) -> dict[str, int]:
        rows = self.db.query("SELECT status, COUNT(*) c FROM jobs GROUP BY status")
        return {r["status"]: r["c"] for r in rows}

    # ------------------------------------------------------------------ claim/mark
    def ready(self, now_iso: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM jobs WHERE status='queued' "
            "AND (next_attempt_at IS NULL OR next_attempt_at <= ?) "
            "AND (scheduled_at IS NULL OR scheduled_at <= ?) "
            "ORDER BY priority DESC, created_at ASC LIMIT 50",
            (now_iso, now_iso),
        )
        return [dict(r) for r in rows]

    def claim(self, job_id: str) -> bool:
        cur = self.db.execute(
            "UPDATE jobs SET status='rendering', updated_at=? WHERE id=? AND status='queued'",
            (utcnow_iso(), job_id),
        )
        return cur.rowcount == 1

    def mark(self, job_id: str, status: str, **fields: Any) -> None:
        cols = ["status=?", "updated_at=?"]
        params: list[Any] = [status, utcnow_iso()]
        for k, v in fields.items():
            cols.append(f"{k}=?")
            params.append(v)
        params.append(job_id)
        self.db.execute(f"UPDATE jobs SET {','.join(cols)} WHERE id=?", params)
        QUEUE_DEPTH.set(self.depth())

    # --------------------------------------------------------------- admin ops
    def cancel(self, job_id: str) -> dict[str, Any]:
        job = self.get(job_id)
        if job["status"] not in ("queued", "failed"):
            raise ApiError("conflict", f"cannot cancel job in state {job['status']}")
        self.mark(job_id, "canceled")
        return self.get(job_id)

    def requeue(self, job_id: str) -> dict[str, Any]:
        job = self.get(job_id)
        if job["status"] not in ("failed", "dead", "uncertain", "canceled"):
            raise ApiError("conflict", f"cannot requeue job in state {job['status']}")
        self.mark(job_id, "queued", attempts=0, next_attempt_at=None, last_error=None)
        return self.get(job_id)

    def resolve(self, job_id: str, outcome: str = "done") -> dict[str, Any]:
        job = self.get(job_id)
        if job["status"] != "uncertain":
            raise ApiError("conflict", "only uncertain jobs can be resolved")
        self.mark(job_id, "done" if outcome == "done" else "failed")
        return self.get(job_id)

    # --------------------------------------------------------------- idempotency
    def idempotency_lookup(self, key: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM idempotency WHERE key=?", (key,))
        return dict(row) if row else None

    def idempotency_store(self, key: str, request_hash: str, job_id: str) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO idempotency(key,request_hash,job_id,created_at) "
            "VALUES (?,?,?,?)",
            (key, request_hash, job_id, utcnow_iso()),
        )

    def redact_payload(self, job_id: str) -> None:
        """Replace a stored payload with a content hash + metadata (Phase 29.1)."""
        job = self.get(job_id)
        raw = job["payload_json"]
        digest = hashlib.sha256(raw.encode()).hexdigest()
        meta = {"_redacted": True, "sha256": digest, "bytes": len(raw)}
        self.db.execute(
            "UPDATE jobs SET payload_json=? WHERE id=?", (json.dumps(meta), job_id)
        )

    # ----------------------------------------------------------------- retention
    def prune(self, *, job_days: int, idem_hours: int) -> None:
        job_cut = (datetime.now(UTC) - timedelta(days=job_days)).strftime("%Y-%m-%dT%H:%M:%fZ")
        self.db.execute(
            "DELETE FROM jobs WHERE created_at < ? AND status IN "
            "('done','failed','dead','canceled')",
            (job_cut,),
        )
        idem_cut = (datetime.now(UTC) - timedelta(hours=idem_hours)).strftime(
            "%Y-%m-%dT%H:%M:%fZ"
        )
        self.db.execute("DELETE FROM idempotency WHERE created_at < ?", (idem_cut,))


class Worker:
    """Async worker driving jobs to delivery, honoring per-printer serialization."""

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self.jobs = ctx.jobs
        self._stop = asyncio.Event()
        self._inflight: dict[str, asyncio.Task] = {}
        self._sema = asyncio.Semaphore(8)
        self._task: asyncio.Task | None = None
        self._last_sweep = 0.0
        self._last_heartbeat = 0.0
        self._offline_since: dict[int, float] = {}
        self._offline_alerted: set[int] = set()
        self._rr_state: dict[int, int] = {}  # pool round-robin cursors

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="vibe-print-worker")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await self._task
        if self._inflight:
            await asyncio.wait(
                self._inflight.values(), timeout=self.ctx.settings.shutdown_drain_seconds
            )

    async def _run(self) -> None:
        import time

        poll = self.ctx.settings.worker_poll_seconds
        while not self._stop.is_set():
            try:
                for job in self.jobs.ready(utcnow_iso()):
                    jid = job["id"]
                    if jid in self._inflight:
                        continue
                    if not self.jobs.claim(jid):
                        continue
                    task = asyncio.create_task(self._guarded(jid))
                    self._inflight[jid] = task
                # Periodic retention sweep (P10.7 / P29.4).
                now = time.monotonic()
                if now - self._last_sweep > self.ctx.settings.retention_sweep_minutes * 60:
                    self._last_sweep = now
                    self._sweep()
                # Periodic fleet heartbeat (P28.1).
                hb = self.ctx.settings.heartbeat_url
                if hb and now - self._last_heartbeat > self.ctx.settings.heartbeat_minutes * 60:
                    self._last_heartbeat = now
                    asyncio.create_task(self._heartbeat())
            except Exception as e:  # pragma: no cover - loop must survive
                log.error("worker_loop_error", error=str(e))
            await asyncio.sleep(poll)

    def _sweep(self) -> None:
        try:
            self.jobs.prune(
                job_days=self.ctx.settings.job_retention_days,
                idem_hours=self.ctx.settings.idempotency_ttl_hours,
            )
            self.ctx.audit.prune(self.ctx.settings.audit_retention_days)
        except Exception as e:  # pragma: no cover
            log.error("retention_sweep_error", error=str(e))

    async def _alert(self, event: str, *, job_id: str, printer_id: int, status: str,
                     error: str | None = None) -> None:
        """Fire a signed failure webhook for dead/uncertain jobs (P14.4). Best-effort."""
        s = self.ctx.settings
        if not s.webhook_url:
            return
        await post_signed(
            s.webhook_url,
            s.webhook_secret,
            {"event": event, "job_id": job_id, "printer_id": printer_id,
             "status": status, "error": error, "device": s.image_digest},
        )

    async def _heartbeat(self) -> None:
        import time as _t

        from .fleet import build_heartbeat

        s = self.ctx.settings
        try:
            uptime = _t.monotonic() - (self.ctx.started_at or _t.monotonic())
            payload = await build_heartbeat(self.ctx, uptime)
            await post_signed(s.heartbeat_url, s.heartbeat_secret, payload)
            await self._check_offline(payload["printers"])
        except Exception as e:  # pragma: no cover
            log.warning("heartbeat_error", error=str(e))

    async def _check_offline(self, printers: list[dict]) -> None:
        """Alert (once) when a printer has been unreachable past the threshold (P28.3)."""
        import time as _t

        now = _t.monotonic()
        threshold = self.ctx.settings.printer_offline_alert_minutes * 60
        for p in printers:
            pid = p["id"]
            if p["reachable"]:
                self._offline_since.pop(pid, None)
                self._offline_alerted.discard(pid)
                continue
            since = self._offline_since.setdefault(pid, now)
            if now - since >= threshold and pid not in self._offline_alerted:
                self._offline_alerted.add(pid)
                await post_signed(
                    self.ctx.settings.webhook_url,
                    self.ctx.settings.webhook_secret,
                    {"event": "printer_offline", "printer_id": pid, "name": p["name"]},
                )

    async def _guarded(self, job_id: str) -> None:
        async with self._sema:
            try:
                await self._process(job_id)
            except Exception as e:  # pragma: no cover
                log.error("job_crash", job_id=job_id, error=str(e))
                self.jobs.mark(job_id, "failed", last_error=str(e))
            finally:
                self._inflight.pop(job_id, None)

    async def _process(self, job_id: str) -> None:
        from .pools import resolve_target

        job = self.jobs.get(job_id)
        requested = self.ctx.registry.get_printer(job["printer_id"])

        # Resolve pool -> concrete member (retryable if none reachable).
        try:
            printer = await resolve_target(self.ctx, requested, self._rr_state)
        except PrinterUnreachable as e:
            await self._retry_or_dead(job, requested.id, str(e))
            return

        backend = make_backend(printer, data_dir=self.ctx.settings.data_dir)

        # --- render (deterministic; render errors are terminal, not retried) ---
        try:
            payload = self._render(job, printer)
        except ApiError as e:
            self.jobs.mark(job_id, "failed", last_error=f"{e.code}: {e.message}")
            self.jobs.mark(job_id, "dead", last_error=f"{e.code}: {e.message}")
            JOBS_TOTAL.labels(status="dead").inc()
            await self._alert(
                "job_dead", job_id=job_id, printer_id=printer.id, status="dead",
                error=f"{e.code}: {e.message}",
            )
            return

        self.jobs.mark(job_id, "printing")

        # --- send (serialized for ESC/POS; uncertain on mid-send) ---
        lock = self.ctx.locks.get(printer.id) if is_serialized(printer.type) else None
        try:
            if lock is not None:
                async with lock:
                    result = await self._send(backend, payload)
            else:
                result = await self._send(backend, payload)
        except MidSendError as e:
            self.jobs.mark(job_id, "uncertain", last_error=str(e))
            JOBS_TOTAL.labels(status="uncertain").inc()
            self.ctx.audit.print_job(job_id, printer.id, outcome="uncertain", bytes_=0)
            log.warning("job_uncertain", job_id=job_id, error=str(e))
            await self._alert(
                "job_uncertain", job_id=job_id, printer_id=printer.id, status="uncertain",
                error=str(e),
            )
            return
        except (PrinterUnreachable, BackendError) as e:
            await self._retry_or_dead(job, printer.id, str(e))
            return

        delivery = "completed" if result.completed else "sent"
        self.jobs.mark(job_id, "done", delivery=delivery)
        JOBS_TOTAL.labels(status="done").inc()
        JOBS_BY_PRINTER.labels(printer_id=str(printer.id)).inc()
        self.ctx.audit.print_job(
            job_id, printer.id, outcome=delivery, bytes_=result.bytes_sent
        )
        # PII minimization: drop the payload once printed if configured (Phase 29.1).
        if not self.ctx.settings.store_payloads:
            self.jobs.redact_payload(job_id)

    async def _send(self, backend: Any, payload: PrintPayload) -> Any:
        timeout = self.ctx.settings.render_timeout_seconds + 30
        try:
            return await asyncio.wait_for(asyncio.to_thread(backend.send, payload), timeout)
        except TimeoutError as e:
            # Hang after streaming began -> treat as uncertain (at-most-once).
            raise MidSendError("send timed out") from e

    async def _retry_or_dead(self, job: dict[str, Any], printer_id: int, err: str) -> None:
        attempts = job["attempts"] + 1
        if attempts >= self.ctx.settings.max_attempts:
            self.jobs.mark(job["id"], "dead", attempts=attempts, last_error=err)
            JOBS_TOTAL.labels(status="dead").inc()
            log.warning("job_dead", job_id=job["id"], error=err)
            await self._alert(
                "job_dead", job_id=job["id"], printer_id=printer_id, status="dead", error=err
            )
            return
        delay = min(
            self.ctx.settings.retry_base_seconds * (2 ** (attempts - 1)),
            self.ctx.settings.retry_max_seconds,
        )
        next_at = (datetime.now(UTC) + timedelta(seconds=delay)).strftime("%Y-%m-%dT%H:%M:%fZ")
        self.jobs.mark(
            job["id"], "queued", attempts=attempts, last_error=err, next_attempt_at=next_at
        )

    # ---------------------------------------------------------------- rendering
    def _render(self, job: dict[str, Any], printer: Any) -> PrintPayload:
        payload = json.loads(job["payload_json"])
        copies = int(payload.get("copies", 1))

        if payload.get("raw"):
            data = base64.b64decode(payload["raw"])
            if printer.type == "zpl_network":
                return PrintPayload(kind="zpl", data=data * copies)
            if printer.type == "star_network":
                return PrintPayload(kind="star", data=data * copies)
            return PrintPayload(kind="escpos", data=data * copies)

        data = payload.get("data", {})
        caps = self.ctx.backend_capabilities(printer)

        if printer.type == "cups":
            template = self._template(job, payload)
            pdf = render_pdf(
                template["html"],
                template["css"],
                template["page_setup"],
                data,
                self.ctx.settings.assets_dir,
            )
            return PrintPayload(kind="pdf", data=pdf, options={"copies": copies})

        # Element-based families (ESC/POS, ZPL, Star) share document/format resolution.
        if payload.get("document"):
            elements = merge_format(payload["document"], data)
        else:
            fmt = self.ctx.registry.get_format(payload["format"])
            elements = merge_format(fmt["elements"], data)

        if printer.type == "zpl_network":
            from .render import render_zpl

            zpl = render_zpl(elements, printer.params, caps)
            return PrintPayload(kind="zpl", data=zpl * copies)
        if printer.type == "star_network":
            from .render import render_star

            return PrintPayload(
                kind="star", data=render_star(elements, printer.params, caps) * copies
            )

        escpos_bytes = render_escpos(elements, printer.params, caps, self.ctx.settings.assets_dir)
        return PrintPayload(kind="escpos", data=escpos_bytes * copies)

    def _template(self, job: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        tid = payload.get("template") or job.get("template_id")
        if not tid:
            raise ApiError("validation_error", "CUPS print requires a template")
        return self.ctx.registry.get_template(tid)
