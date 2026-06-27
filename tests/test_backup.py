"""Consistent DB snapshot for backup (P22.7)."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def test_snapshot_creates_consistent_copy(client):
    # Seed something so the snapshot has content.
    client.post("/v1/admin/printers", json={"name": "V", "params": {"type": "virtual"}})
    resp = client.post("/v1/admin/backup/snapshot").json()
    snap = Path(resp["path"])
    assert snap.exists() and resp["size"] > 0

    # The snapshot is a valid, queryable SQLite DB with our row.
    conn = sqlite3.connect(str(snap))
    try:
        count = conn.execute("SELECT COUNT(*) FROM printers").fetchone()[0]
        assert count >= 1
    finally:
        conn.close()
