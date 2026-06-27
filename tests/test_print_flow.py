"""End-to-end print flow against the virtual backend + idempotency (P24.2)."""

from __future__ import annotations

from pathlib import Path

from conftest import wait_for_job


def _setup(client):
    fmt = client.post(
        "/v1/admin/formats",
        json={
            "name": "R",
            "elements": {
                "elements": [
                    {"type": "text", "value": "{{ data.company }}", "align": "center"},
                    {"type": "rule"},
                    {"type": "cut"},
                ]
            },
        },
    ).json()
    printer = client.post(
        "/v1/admin/printers",
        json={
            "name": "V",
            "params": {"type": "virtual", "columns": 48},
            "default_format_id": fmt["id"],
        },
    ).json()
    return printer["id"], fmt["id"]


def test_print_document_completes(client, tmp_path):
    pid, _ = _setup(client)
    r = client.post(
        "/v1/print",
        json={
            "printer": pid,
            "document": {"elements": [{"type": "text", "value": "hello"}, {"type": "cut"}]},
            "data": {},
        },
    )
    assert r.status_code == 200
    job = wait_for_job(client, r.json()["job_id"])
    assert job["status"] == "done"
    assert job["delivery"] == "completed"

    # Virtual backend wrote the bytes to disk.
    out = Path(client.app.state.ctx.settings.data_dir) / "virtual" / f"printer-{pid}.bin"
    assert out.exists() and out.stat().st_size > 0


def test_print_with_default_format(client):
    pid, _ = _setup(client)
    r = client.post("/v1/print", json={"printer": pid, "data": {"company": "Acme"}})
    job = wait_for_job(client, r.json()["job_id"])
    assert job["status"] == "done"


def test_idempotency_replay_and_conflict(client):
    pid, _ = _setup(client)
    headers = {"Idempotency-Key": "key-1"}
    body = {"printer": pid, "data": {"company": "A"}}
    j1 = client.post("/v1/print", json=body, headers=headers).json()
    j2 = client.post("/v1/print", json=body, headers=headers).json()
    assert j1["job_id"] == j2["job_id"]
    assert j2.get("idempotent_replay") is True

    # Same key, different payload -> conflict
    r = client.post(
        "/v1/print", json={"printer": pid, "data": {"company": "B"}}, headers=headers
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "idempotency_conflict"


def test_raw_disabled_by_default(client):
    pid, _ = _setup(client)
    r = client.post("/v1/print/raw", json={"printer": pid, "data": "AAAA"})
    assert r.status_code == 403


def test_cups_rejects_document(client):
    p = client.post(
        "/v1/admin/printers",
        json={"name": "C", "params": {"type": "cups", "queue": "q"}},
    ).json()
    r = client.post(
        "/v1/print",
        json={"printer": p["id"], "document": {"elements": []}},
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "unsupported_for_printer"
