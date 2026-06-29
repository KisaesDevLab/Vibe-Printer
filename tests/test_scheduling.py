"""Job priority, not-before scheduling, and per-printer daily quotas."""

from __future__ import annotations

from conftest import wait_for_job


def _printer(client):
    return client.post(
        "/v1/admin/printers", json={"name": "V", "params": {"type": "virtual"}}
    ).json()["id"]


def test_ready_orders_by_priority(client):
    jobs = client.app.state.ctx.jobs
    pid = _printer(client)
    # Schedule far in the future so the background worker doesn't claim them before we read
    # ready() — then query with an even-later "now" to include both, ordered by priority.
    far = "2999-01-01T00:00:00.000Z"
    common = dict(global_max=1000, per_printer_max=1000, scheduled_at=far)
    lo = jobs.enqueue(printer_id=pid, payload={"raw": "QUFB", "copies": 1}, priority=0, **common)
    hi = jobs.enqueue(printer_id=pid, payload={"raw": "QUFB", "copies": 1}, priority=50, **common)
    ready = jobs.ready("9999-01-01T00:00:00.000Z")
    ids = [r["id"] for r in ready]
    assert ids.index(hi["id"]) < ids.index(lo["id"])


def test_scheduled_job_not_ready_until_time(client):
    jobs = client.app.state.ctx.jobs
    pid = _printer(client)
    future = jobs.enqueue(
        printer_id=pid,
        payload={"raw": "QUFB", "copies": 1},
        scheduled_at="2999-01-01T00:00:00.000Z",
        global_max=1000,
        per_printer_max=1000,
    )
    ready_now = {r["id"] for r in jobs.ready("2026-06-27T00:00:00.000Z")}
    assert future["id"] not in ready_now
    ready_later = {r["id"] for r in jobs.ready("2999-06-27T00:00:00.000Z")}
    assert future["id"] in ready_later


def test_daily_quota_enforced(client):
    pid = _printer(client)
    dev = client.get("/v1/admin/device").json()
    dev_config = {**dev["config"], "quotas": {str(pid): 1}}
    client.put(
        "/v1/admin/device",
        json={
            "name": dev["name"],
            "timezone": dev["timezone"],
            "config": dev_config,
            "version": dev["version"],
        },
    )
    body = {"printer": pid, "document": {"elements": [{"type": "text", "value": "x"}]}}
    r1 = client.post("/v1/print", json=body)
    assert r1.status_code == 200
    wait_for_job(client, r1.json()["job_id"])
    r2 = client.post("/v1/print", json=body)
    assert r2.status_code == 429
    assert r2.json()["error"]["code"] == "quota_exceeded"


def test_priority_field_accepted_via_api(client):
    pid = _printer(client)
    r = client.post(
        "/v1/print",
        json={"printer": pid, "document": {"elements": [{"type": "cut"}]}, "priority": 10},
    )
    assert r.status_code == 200
    assert wait_for_job(client, r.json()["job_id"])["status"] == "done"
