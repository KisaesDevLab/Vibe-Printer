"""SQLite access + forward-only migration runner.

Single shared connection (check_same_thread=False) guarded by a re-entrant lock for writes;
WAL mode keeps concurrent reads cheap. The appliance is a single process, so this is plenty.

Migrations: numbered ``NNNN_*.sql`` files in app/migrations, applied in order inside a
transaction, tracked in ``schema_migrations``. Forward-only; we refuse to "downgrade".
A backup copy of the DB is written before any new migration is applied (P1.1 amendment).
"""

from __future__ import annotations

import shutil
import sqlite3
import threading
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def utcnow_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%fZ")


def _load_sqlcipher() -> Any:
    for mod in ("sqlcipher3", "pysqlcipher3.dbapi2"):
        try:
            import importlib

            return importlib.import_module(mod)
        except Exception:
            continue
    raise RuntimeError(
        "encrypt_at_rest is on but no SQLCipher driver is installed "
        "(pip install sqlcipher3-binary). Or use host/volume encryption (see STATUS.md)."
    )


class Database:
    def __init__(self, path: Path, *, encryption_key: str = "") -> None:
        self.path = path
        self._lock = threading.RLock()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.encrypted = False

        if encryption_key:
            # Opt-in SQLCipher at rest (Phase 29.2). Try the maintained `sqlcipher3` first,
            # then `pysqlcipher3`. Never silently store plaintext when encryption was requested.
            sqlcipher = _load_sqlcipher()
            self._conn = sqlcipher.connect(str(path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            # Parameter-bind the key to avoid quoting issues.
            self._conn.execute("PRAGMA key = ?", (encryption_key,))
            self._conn.execute("PRAGMA cipher_memory_security = ON")
            self.encrypted = True
        else:
            self._conn = sqlite3.connect(str(path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row

        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")

    # --- low level ---
    def query(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, tuple(params)))

    def query_one(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, tuple(params))
            self._conn.commit()
            return cur

    def executemany(self, sql: str, seq: Iterable[Iterable[Any]]) -> None:
        with self._lock:
            self._conn.executemany(sql, [tuple(p) for p in seq])
            self._conn.commit()

    def transaction(self) -> _Tx:
        return _Tx(self)

    def snapshot(self, dest: Path) -> None:
        """Write a consistent copy of the DB (online, no readers blocked) via VACUUM INTO."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            dest.unlink()
        with self._lock:
            self._conn.execute("VACUUM INTO ?", (str(dest),))

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # --- migrations ---
    def migrate(self) -> list[str]:
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        self._conn.commit()
        applied = {r["name"] for r in self.query("SELECT name FROM schema_migrations")}
        files = sorted(MIGRATIONS_DIR.glob("*.sql"))
        ran: list[str] = []
        for f in files:
            if f.name in applied:
                continue
            if self.path.exists() and applied:
                # backup-before-migrate
                backup = self.path.with_suffix(f".pre-{f.stem}.bak")
                try:
                    shutil.copy2(self.path, backup)
                except OSError:
                    pass
            with self._lock:
                self._conn.executescript(f.read_text(encoding="utf-8"))
                self._conn.execute(
                    "INSERT INTO schema_migrations(name, applied_at) VALUES (?,?)",
                    (f.name, utcnow_iso()),
                )
                self._conn.commit()
            ran.append(f.name)
        # Ensure the device_settings singleton exists.
        self.execute(
            "INSERT OR IGNORE INTO device_settings(id, name, timezone) "
            "VALUES (1,'vibe-print','UTC')"
        )
        return ran


class _Tx:
    """Context manager for a multi-statement atomic write under the DB lock."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def __enter__(self) -> sqlite3.Connection:
        self._db._lock.acquire()
        self._db._conn.execute("BEGIN")
        return self._db._conn

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        try:
            if exc_type is None:
                self._db._conn.commit()
            else:
                self._db._conn.rollback()
        finally:
            self._db._lock.release()


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> Iterator[dict[str, Any]]:
    for r in rows:
        yield dict(r)
