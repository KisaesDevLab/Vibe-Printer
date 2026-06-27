"""Finished-document passthrough: PDF / PostScript / PCL via /v1/print/file."""

from __future__ import annotations

import base64
from pathlib import Path

from conftest import wait_for_job

PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
PS_BYTES = b"%!PS-Adobe-3.0\nshowpage\n"
PCL_BYTES = b"\x1bE\x1b&l0O hello \x1bE"


def _virtual(client):
    return client.post(
        "/v1/admin/printers", json={"name": "office", "params": {"type": "virtual"}}
    ).json()["id"]


def _out(client, pid, ext):
    return Path(client.app.state.ctx.settings.data_dir) / "virtual" / f"printer-{pid}.{ext}"


def test_print_pdf_passthrough(client):
    pid = _virtual(client)
    r = client.post("/v1/print/file", json={
        "printer": pid, "content": base64.b64encode(PDF_BYTES).decode(), "content_type": "pdf",
    })
    assert r.status_code == 200
    assert wait_for_job(client, r.json()["job_id"])["status"] == "done"
    out = _out(client, pid, "pdf")
    assert out.exists() and out.read_bytes() == PDF_BYTES


def test_print_postscript_passthrough(client):
    pid = _virtual(client)
    r = client.post("/v1/print/file", json={
        "printer": pid,
        "content": base64.b64encode(PS_BYTES).decode(),
        "content_type": "postscript",
    })
    assert wait_for_job(client, r.json()["job_id"])["status"] == "done"
    assert _out(client, pid, "ps").read_bytes() == PS_BYTES


def test_print_pcl_passthrough(client):
    pid = _virtual(client)
    r = client.post("/v1/print/file", json={
        "printer": pid, "content": base64.b64encode(PCL_BYTES).decode(), "content_type": "pcl",
    })
    assert wait_for_job(client, r.json()["job_id"])["status"] == "done"
    assert _out(client, pid, "pcl").read_bytes() == PCL_BYTES


def test_print_file_rejected_for_thermal_printer(client):
    pid = client.post(
        "/v1/admin/printers",
        json={"name": "thermal", "params": {"type": "escpos_network", "host": "127.0.0.1"}},
    ).json()["id"]
    r = client.post("/v1/print/file", json={
        "printer": pid, "content": base64.b64encode(PDF_BYTES).decode(), "content_type": "pdf",
    })
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "unsupported_for_printer"


def test_print_file_invalid_base64(client):
    pid = _virtual(client)
    r = client.post("/v1/print/file", json={"printer": pid, "content": "!!notb64!!"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


def test_print_file_unknown_content_type_422(client):
    pid = _virtual(client)
    r = client.post("/v1/print/file", json={
        "printer": pid, "content": base64.b64encode(PDF_BYTES).decode(), "content_type": "docx",
    })
    assert r.status_code == 422  # pydantic Literal rejects it


def test_print_file_idempotent_replay(client):
    pid = _virtual(client)
    body = {"printer": pid, "content": base64.b64encode(PDF_BYTES).decode(), "content_type": "pdf"}
    h = {"Idempotency-Key": "file-1"}
    j1 = client.post("/v1/print/file", json=body, headers=h).json()
    j2 = client.post("/v1/print/file", json=body, headers=h).json()
    assert j1["job_id"] == j2["job_id"]
    assert j2.get("idempotent_replay") is True


def test_printers_advertise_document_formats(client):
    pid = _virtual(client)
    printers = {p["id"]: p for p in client.get("/v1/printers").json()}
    assert "pdf" in printers[pid]["capabilities"]["document_formats"]
