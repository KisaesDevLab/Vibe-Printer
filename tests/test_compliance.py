"""Compliance P29: log redaction, payload-hash mode, erasure."""

from __future__ import annotations

from conftest import wait_for_job

from app.obs import _redact


def test_log_redaction_drops_sensitive_keys():
    event = {"event": "x", "data": {"ssn": "123"}, "html": "<b>", "job_id": "abc"}
    out = _redact(None, "info", event)
    assert out["data"] == "<redacted>"
    assert out["html"] == "<redacted>"
    assert out["job_id"] == "abc"  # ids are kept


def _printer_and_format(client):
    fmt = client.post(
        "/v1/admin/formats",
        json={"name": "R", "elements": {"elements": [{"type": "text", "value": "x"}]}},
    ).json()
    pid = client.post(
        "/v1/admin/printers",
        json={"name": "V", "params": {"type": "virtual"}, "default_format_id": fmt["id"]},
    ).json()["id"]
    return pid


def test_payload_hash_mode(client):
    client.app.state.ctx.settings.store_payloads = False
    pid = _printer_and_format(client)
    r = client.post("/v1/print", json={"printer": pid, "data": {"company": "Secret Inc"}})
    job = wait_for_job(client, r.json()["job_id"])
    assert job["status"] == "done"

    # The stored payload must be a hash, not the original data.
    raw = client.app.state.ctx.jobs.get(job["id"])["payload_json"]
    assert "Secret Inc" not in raw
    assert "_redacted" in raw


def test_erase_payload_endpoint(client):
    client.app.state.ctx.settings.store_payloads = True
    pid = _printer_and_format(client)
    r = client.post("/v1/print", json={"printer": pid, "data": {"company": "Acme"}})
    job_id = r.json()["job_id"]
    wait_for_job(client, job_id)
    assert client.delete(f"/v1/admin/jobs/{job_id}/payload").status_code == 200
    raw = client.app.state.ctx.jobs.get(job_id)["payload_json"]
    assert "_redacted" in raw


def test_retention_prune_endpoint(client):
    assert client.post("/v1/admin/retention/prune").json()["pruned"] is True
