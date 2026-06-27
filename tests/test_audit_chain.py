"""Tamper-evident hash-chained audit (deferred plan item, now built)."""

from __future__ import annotations


def test_config_audit_chain_valid(client):
    for i in range(3):
        client.post("/v1/admin/printers", json={"name": f"P{i}", "params": {"type": "virtual"}})
    v = client.get("/v1/admin/audit/verify").json()
    assert v["config_audit"]["valid"] is True
    assert v["config_audit"]["count"] >= 3


def test_tampering_breaks_chain(client):
    client.post("/v1/admin/printers", json={"name": "P", "params": {"type": "virtual"}})
    client.post("/v1/admin/printers", json={"name": "Q", "params": {"type": "virtual"}})
    # Tamper directly with a row in the middle of the chain.
    db = client.app.state.ctx.db
    row = db.query_one("SELECT id FROM config_audit ORDER BY id ASC LIMIT 1")
    db.execute("UPDATE config_audit SET action='HACKED' WHERE id=?", (row["id"],))
    v = client.get("/v1/admin/audit/verify").json()
    assert v["config_audit"]["valid"] is False
    assert v["config_audit"]["broken_at_id"] == row["id"]


def test_print_audit_chain_valid_after_jobs(client):
    fmt = client.post(
        "/v1/admin/formats",
        json={"name": "F", "elements": {"elements": [{"type": "text", "value": "x"}]}},
    ).json()
    pid = client.post(
        "/v1/admin/printers",
        json={"name": "V", "params": {"type": "virtual"}, "default_format_id": fmt["id"]},
    ).json()["id"]
    from conftest import wait_for_job

    r = client.post("/v1/print", json={"printer": pid, "data": {}})
    wait_for_job(client, r.json()["job_id"])
    v = client.get("/v1/admin/audit/verify").json()
    assert v["print_audit"]["valid"] is True
