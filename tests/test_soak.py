"""Soak: mixed load across printers asserts per-printer serialization (P24.6).

A recording backend tracks concurrent sends per printer. If the per-printer async lock works,
no printer ever has two sends in flight at once (no interleaved/corrupted output), while different
printers run in parallel.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict

from conftest import wait_for_job

from app.backends.base import SendResult
from app.models import Capabilities


class _Recorder:
    active: dict[int, int] = defaultdict(int)
    max_overlap: dict[int, int] = defaultdict(int)
    lock = threading.Lock()

    def __init__(self, printer_id: int) -> None:
        self.printer_id = printer_id

    @classmethod
    def reset(cls) -> None:
        cls.active = defaultdict(int)
        cls.max_overlap = defaultdict(int)

    def capabilities(self):
        return Capabilities(cut=True)

    def status(self):
        return {"reachable": True}

    def send(self, payload):
        pid = self.printer_id
        with _Recorder.lock:
            _Recorder.active[pid] += 1
            _Recorder.max_overlap[pid] = max(_Recorder.max_overlap[pid], _Recorder.active[pid])
        time.sleep(0.01)  # widen the window for any interleaving to show up
        with _Recorder.lock:
            _Recorder.active[pid] -= 1
        return SendResult(bytes_sent=len(payload.data), completed=True)

    def close(self):
        pass


def test_no_interleaving_under_load(client, monkeypatch):
    _Recorder.reset()
    monkeypatch.setattr("app.queue.make_backend", lambda printer, data_dir: _Recorder(printer.id))

    def _new_printer(i: int) -> int:
        resp = client.post(
            "/v1/admin/printers", json={"name": f"V{i}", "params": {"type": "virtual"}}
        )
        return resp.json()["id"]

    printer_ids = [_new_printer(i) for i in range(3)]

    job_ids = []
    for pid in printer_ids:
        for _ in range(6):
            r = client.post(
                "/v1/print",
                json={"printer": pid, "document": {"elements": [{"type": "text", "value": "x"}]}},
            )
            job_ids.append(r.json()["job_id"])

    for jid in job_ids:
        job = wait_for_job(client, jid, timeout=15.0)
        assert job["status"] == "done"

    # The invariant: at most one concurrent send per printer (serialized byte stream).
    for pid in printer_ids:
        assert _Recorder.max_overlap[pid] == 1, f"printer {pid} interleaved sends"
