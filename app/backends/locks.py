"""Per-printer async mutex.

Applies to ESC/POS network + USB only: a single byte stream must not interleave (gap #2).
CUPS has its own spooler — the worker submits to CUPS concurrently and does NOT take this lock.
"""

from __future__ import annotations

import asyncio


class PrinterLocks:
    def __init__(self) -> None:
        self._locks: dict[int, asyncio.Lock] = {}

    def get(self, printer_id: int) -> asyncio.Lock:
        lock = self._locks.get(printer_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[printer_id] = lock
        return lock
