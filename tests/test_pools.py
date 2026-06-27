"""Printer pools / failover (deferred plan item, now built)."""

from __future__ import annotations

from pathlib import Path

from conftest import wait_for_job


def _virtual(client, name):
    return client.post(
        "/v1/admin/printers", json={"name": name, "params": {"type": "virtual"}}
    ).json()["id"]


def test_pool_failover_skips_unreachable_member(client):
    # Member 1 is an unreachable TCP printer; member 2 is the virtual backend.
    bad = client.post(
        "/v1/admin/printers",
        json={"name": "bad", "params": {"type": "escpos_network", "host": "127.0.0.1", "port": 9}},
    ).json()["id"]
    good = _virtual(client, "good")
    pool = client.post(
        "/v1/admin/printers",
        json={"name": "pool", "params": {"type": "pool", "members": [bad, good],
                                         "strategy": "failover"}},
    ).json()["id"]

    r = client.post(
        "/v1/print",
        json={"printer": pool, "document": {"elements": [{"type": "text", "value": "hi"},
                                                          {"type": "cut"}]}},
    )
    job = wait_for_job(client, r.json()["job_id"])
    assert job["status"] == "done"
    # The reachable virtual member actually printed.
    out = Path(client.app.state.ctx.settings.data_dir) / "virtual" / f"printer-{good}.bin"
    assert out.exists() and out.stat().st_size > 0


def test_pool_status_aggregates_members(client):
    a, b = _virtual(client, "a"), _virtual(client, "b")
    pool = client.post(
        "/v1/admin/printers",
        json={"name": "p", "params": {"type": "pool", "members": [a, b]}},
    ).json()["id"]
    st = client.get(f"/v1/printers/{pool}/status").json()
    assert st["reachable"] is True
    assert len(st["members"]) == 2


def test_pool_capabilities_are_intersection(client):
    a, b = _virtual(client, "a"), _virtual(client, "b")
    pool = client.post(
        "/v1/admin/printers",
        json={"name": "p", "params": {"type": "pool", "members": [a, b]}},
    ).json()["id"]
    printers = {p["id"]: p for p in client.get("/v1/printers").json()}
    assert printers[pool]["capabilities"]["qr"] is True  # both virtual members support QR
