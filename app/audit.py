"""Audit writers (P13.5 / P14.2) with a tamper-evident hash chain.

Each row stores ``prev_hash`` (the previous row's ``entry_hash`` in that table) and ``entry_hash``
= sha256(prev_hash + canonical(row fields)). Any insertion/edit/deletion in the middle breaks the
chain, which ``verify_chain`` detects. Never stores payload bodies or merged ``data`` (Phase 29.3).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .db import Database, utcnow_iso

GENESIS = "0" * 64


def _hash(prev: str, fields: dict[str, Any]) -> str:
    blob = prev + "|" + json.dumps(fields, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


class Audit:
    def __init__(self, db: Database) -> None:
        self.db = db

    def _last_hash(self, table: str) -> str:
        row = self.db.query_one(f"SELECT entry_hash FROM {table} ORDER BY id DESC LIMIT 1")
        return row["entry_hash"] if row and row["entry_hash"] else GENESIS

    def config_change(
        self,
        *,
        entity: str,
        action: str,
        entity_id: str | None = None,
        actor: str | None = None,
        real_ip: str | None = None,
        diff: Any | None = None,
    ) -> None:
        ts = utcnow_iso()
        prev = self._last_hash("config_audit")
        fields = {
            "actor": actor, "real_ip": real_ip, "entity": entity,
            "entity_id": entity_id, "action": action, "ts": ts,
            "diff": json.dumps(diff) if diff else None,
        }
        entry = _hash(prev, fields)
        self.db.execute(
            "INSERT INTO config_audit(actor,real_ip,entity,entity_id,action,diff_json,ts,"
            "prev_hash,entry_hash) VALUES (?,?,?,?,?,?,?,?,?)",
            (actor, real_ip, entity, entity_id, action, fields["diff"], ts, prev, entry),
        )

    def print_job(
        self,
        job_id: str,
        printer_id: int,
        *,
        outcome: str,
        bytes_: int = 0,
        actor: str | None = None,
        real_ip: str | None = None,
    ) -> None:
        ts = utcnow_iso()
        prev = self._last_hash("print_audit")
        fields = {
            "job_id": job_id, "printer_id": printer_id, "actor": actor,
            "real_ip": real_ip, "bytes": bytes_, "outcome": outcome, "ts": ts,
        }
        entry = _hash(prev, fields)
        self.db.execute(
            "INSERT INTO print_audit(job_id,printer_id,actor,real_ip,bytes,outcome,ts,"
            "prev_hash,entry_hash) VALUES (?,?,?,?,?,?,?,?,?)",
            (job_id, printer_id, actor, real_ip, bytes_, outcome, ts, prev, entry),
        )

    def list_config(self, limit: int = 100) -> list[dict]:
        return [dict(r) for r in self.db.query(
            "SELECT * FROM config_audit ORDER BY ts DESC LIMIT ?", (limit,))]

    def list_print(self, limit: int = 100) -> list[dict]:
        return [dict(r) for r in self.db.query(
            "SELECT * FROM print_audit ORDER BY ts DESC LIMIT ?", (limit,))]

    def verify_chain(self, table: str) -> dict[str, Any]:
        """Recompute the chain in insertion order; report the first broken row (if any)."""
        if table not in ("config_audit", "print_audit"):
            raise ValueError("unknown audit table")
        rows = self.db.query(f"SELECT * FROM {table} ORDER BY id ASC")
        if not rows:
            return {"valid": True, "count": 0}
        # Seed from the first surviving row's anchor so head-side pruning doesn't read as tampering;
        # internal continuity + per-row hashes still catch any middle insert/edit/delete.
        prev = rows[0]["prev_hash"] or GENESIS
        for r in rows:
            row = dict(r)
            if table == "config_audit":
                fields = {
                    "actor": row["actor"], "real_ip": row["real_ip"], "entity": row["entity"],
                    "entity_id": row["entity_id"], "action": row["action"], "ts": row["ts"],
                    "diff": row["diff_json"],
                }
            else:
                fields = {
                    "job_id": row["job_id"], "printer_id": row["printer_id"],
                    "actor": row["actor"], "real_ip": row["real_ip"], "bytes": row["bytes"],
                    "outcome": row["outcome"], "ts": row["ts"],
                }
            expected = _hash(prev, fields)
            if row["prev_hash"] != prev or row["entry_hash"] != expected:
                return {"valid": False, "broken_at_id": row["id"], "count": len(rows)}
            prev = row["entry_hash"]
        return {"valid": True, "count": len(rows)}

    def prune(self, days: int) -> None:
        # Note: pruning truncates the chain head-side; verify_chain still validates the
        # remaining contiguous tail from its first surviving row.
        from datetime import UTC, datetime, timedelta

        cut = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%fZ")
        self.db.execute("DELETE FROM config_audit WHERE ts < ?", (cut,))
        self.db.execute("DELETE FROM print_audit WHERE ts < ?", (cut,))
