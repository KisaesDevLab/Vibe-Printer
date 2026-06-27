"""Delivery semantics: mid-send -> uncertain (no auto-retry), then resolve (Decision 16)."""

from __future__ import annotations

from conftest import wait_for_job

from app.backends.base import MidSendError, PrinterUnreachable, SendResult


class _MidSend:
    type = "virtual"

    def capabilities(self):
        from app.models import Capabilities

        return Capabilities(cut=True, qr=True, raster=True)

    def status(self):
        return {"reachable": True}

    def send(self, payload):
        raise MidSendError("link died mid stream")

    def close(self):
        pass


class _Flaky:
    """Fails to connect twice, then succeeds — exercises retry/backoff."""

    calls = 0
    type = "virtual"

    def capabilities(self):
        from app.models import Capabilities

        return Capabilities(cut=True)

    def status(self):
        return {"reachable": True}

    def send(self, payload):
        type(self).calls += 1
        if type(self).calls < 2:
            raise PrinterUnreachable("offline")
        return SendResult(bytes_sent=len(payload.data), completed=False)

    def close(self):
        pass


def _printer(client):
    return client.post(
        "/v1/admin/printers", json={"name": "V", "params": {"type": "virtual"}}
    ).json()["id"]


def test_mid_send_marks_uncertain_then_resolves(client, monkeypatch):
    pid = _printer(client)
    monkeypatch.setattr("app.queue.make_backend", lambda printer, data_dir: _MidSend())
    r = client.post(
        "/v1/print",
        json={"printer": pid, "document": {"elements": [{"type": "text", "value": "x"}]}},
    )
    job = wait_for_job(client, r.json()["job_id"])
    assert job["status"] == "uncertain"
    assert job["attempts"] == 0  # never auto-retried

    resolved = client.post(f"/v1/admin/jobs/{job['id']}/resolve", json={"outcome": "done"}).json()
    assert resolved["status"] == "done"


def test_retry_then_succeed(client, monkeypatch):
    pid = _printer(client)
    _Flaky.calls = 0
    # short backoff so the test is fast
    client.app.state.ctx.settings.retry_base_seconds = 0.05
    monkeypatch.setattr("app.queue.make_backend", lambda printer, data_dir: _Flaky())
    r = client.post(
        "/v1/print",
        json={"printer": pid, "document": {"elements": [{"type": "text", "value": "x"}]}},
    )
    job = wait_for_job(client, r.json()["job_id"], timeout=8.0)
    assert job["status"] == "done"
    assert job["attempts"] >= 1
