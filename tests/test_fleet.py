"""Signed webhooks, fleet heartbeat, diagnostics (P28 / P14.4)."""

from __future__ import annotations

from conftest import wait_for_job

from app.backends.base import BackendError
from app.notify import sign, verify


class _AlwaysFail:
    type = "virtual"

    def capabilities(self):
        from app.models import Capabilities

        return Capabilities(cut=True)

    def status(self):
        return {"reachable": False}

    def send(self, payload):
        raise BackendError("nope")

    def close(self):
        pass


def test_sign_verify_roundtrip():
    import time

    body = b'{"a":1}'
    ts = str(int(time.time()))
    s = sign("secret", ts, body)
    assert verify("secret", ts, body, s)
    assert not verify("secret", ts, body, "deadbeef")
    # Stale timestamp is rejected even with a valid MAC.
    old = str(int(time.time()) - 10_000)
    assert not verify("secret", old, body, sign("secret", old, body))


def test_dead_job_fires_signed_webhook(client, monkeypatch):
    ctx = client.app.state.ctx
    ctx.settings.webhook_url = "http://example.test/hook"
    ctx.settings.webhook_secret = "s"
    ctx.settings.max_attempts = 1
    ctx.settings.retry_base_seconds = 0.05

    captured = []

    async def fake_post(url, secret, payload):
        captured.append(payload)
        return True

    monkeypatch.setattr("app.queue.post_signed", fake_post)
    monkeypatch.setattr("app.queue.make_backend", lambda printer, data_dir: _AlwaysFail())

    resp = client.post("/v1/admin/printers", json={"name": "V", "params": {"type": "virtual"}})
    pid = resp.json()["id"]
    r = client.post(
        "/v1/print",
        json={"printer": pid, "document": {"elements": [{"type": "text", "value": "x"}]}},
    )
    job = wait_for_job(client, r.json()["job_id"])
    assert job["status"] == "dead"
    assert any(p["event"] == "job_dead" and p["printer_id"] == pid for p in captured)
    # PII guarantee: webhook carries no document/data.
    assert all("data" not in p and "document" not in p for p in captured)


def test_diagnostics_is_pii_free(client):
    client.post("/v1/admin/printers", json={"name": "V", "params": {"type": "virtual"}})
    d = client.get("/v1/admin/diagnostics").json()
    assert "version" in d and "printers" in d and "queue" in d
    assert "secret" not in str(d).lower()


def test_heartbeat_test_endpoint_unconfigured(client):
    r = client.post("/v1/admin/heartbeat/test").json()
    assert r["configured"] is False and r["sent"] is False


def test_remote_status(client):
    r = client.get("/v1/admin/remote/status").json()
    assert r["mode"] == "lan"
    assert r["tunnel"] == "unknown"
