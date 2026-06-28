"""Per-printer test print: element-based for thermal, PDF for CUPS/office."""

from __future__ import annotations

import json

from conftest import wait_for_job


def test_test_print_virtual_completes(client):
    pid = client.post(
        "/v1/admin/printers", json={"name": "V", "params": {"type": "virtual"}}
    ).json()["id"]
    r = client.post(f"/v1/admin/printers/{pid}/test")
    assert r.status_code == 200
    assert wait_for_job(client, r.json()["job_id"])["status"] == "done"


def test_test_print_available_for_all_types(client):
    member = client.post(
        "/v1/admin/printers", json={"name": "m", "params": {"type": "virtual"}}
    ).json()["id"]
    cases = [
        {"type": "virtual"},
        {"type": "escpos_network", "host": "127.0.0.1", "port": 9},
        {"type": "escpos_usb", "vendor_id": 1208, "product_id": 3624},
        {"type": "cups", "queue": "q"},
        {"type": "ipp_network", "host": "127.0.0.1"},
        {"type": "zpl_network", "host": "127.0.0.1", "port": 9},
        {"type": "star_network", "host": "127.0.0.1", "port": 9},
        {"type": "pool", "members": [member], "strategy": "failover"},
    ]
    for i, params in enumerate(cases):
        pid = client.post(
            "/v1/admin/printers", json={"name": f"t{i}", "params": params}
        ).json()["id"]
        r = client.post(f"/v1/admin/printers/{pid}/test")
        assert r.status_code == 200, f"{params['type']}: {r.text}"
        assert r.json()["job_id"], params["type"]


def test_test_print_cups_renders_pdf(client):
    cid = client.post(
        "/v1/admin/printers", json={"name": "C", "params": {"type": "cups", "queue": "q"}}
    ).json()["id"]
    r = client.post(f"/v1/admin/printers/{cid}/test")
    assert r.status_code == 200
    # The enqueued payload is a finished PDF (no template required).
    payload = json.loads(client.app.state.ctx.jobs.get(r.json()["job_id"])["payload_json"])
    assert payload["content_type"] == "pdf"
    import base64

    assert base64.b64decode(payload["file_content"]).startswith(b"%PDF")
