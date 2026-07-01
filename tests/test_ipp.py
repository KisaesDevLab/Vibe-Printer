"""Direct IPP backend + client + print routing, and CUPS device_uri persistence."""

from __future__ import annotations

from conftest import wait_for_job

from app.backends.base import PrintPayload, SendResult
from app.backends.ipp_network import IppNetworkBackend
from app.ipp_client import (
    OP_GET_PRINTER_ATTRS,
    _build,
    _ipp_status,
    build_print_job,
    build_uri,
)
from app.models import Capabilities


# --- IPP wire format ---
def test_build_request_structure():
    body = _build(OP_GET_PRINTER_ATTRS, "ipp://x:631/ipp/print")
    assert body[:2] == b"\x02\x00"  # version 2.0
    assert body[2:4] == (0x000B).to_bytes(2, "big")  # operation id
    assert b"printer-uri" in body and b"ipp://x:631/ipp/print" in body
    assert body[-1:] == b"\x03"  # end-of-attributes


def test_ipp_status_parse():
    assert _ipp_status(b"\x02\x00\x00\x00rest") == 0  # successful-ok
    assert _ipp_status(b"\x02\x00\x04\x01rest") == 0x0401  # an error


def test_build_uri():
    assert build_uri("h") == "ipp://h:631/ipp/print"
    assert build_uri("h", 443, "/x", True) == "ipps://h:443/x"


def test_print_job_carries_output_bin_and_input_tray():
    body = build_print_job("ipp://x/ipp/print", b"%PDF-1.4", output_bin="stacker-1",
                           input_tray="tray-2")
    assert b"\x02" in body  # job-attributes-tag group present
    assert b"output-bin" in body and b"stacker-1" in body
    assert b"media-col" in body and b"media-source" in body and b"tray-2" in body
    assert body[-8:] == b"%PDF-1.4"  # document follows the attributes


def test_print_job_omits_trays_when_unset():
    body = build_print_job("ipp://x/ipp/print", b"%PDF")
    assert b"output-bin" not in body and b"media-col" not in body


def test_ipp_backend_passes_trays(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        "app.ipp_client.print_pdf",
        lambda uri, pdf, **k: seen.update(k) or len(pdf),
    )
    IppNetworkBackend(1, {"host": "h", "output_bin": "face-up", "input_tray": "tray-3"}).send(
        PrintPayload(kind="pdf", data=b"%PDF")
    )
    assert seen["output_bin"] == "face-up" and seen["input_tray"] == "tray-3"


# --- backend (client monkeypatched) ---
def test_backend_status_reachable(monkeypatch):
    monkeypatch.setattr("app.ipp_client.get_printer_attributes", lambda uri, timeout=5.0: True)
    assert IppNetworkBackend(1, {"host": "h"}).status()["reachable"] is True


def test_backend_send_pdf(monkeypatch):
    monkeypatch.setattr("app.ipp_client.print_pdf", lambda uri, pdf, **k: len(pdf))
    res = IppNetworkBackend(1, {"host": "h"}).send(PrintPayload(kind="pdf", data=b"%PDF-1.4"))
    assert res.bytes_sent == 8 and res.completed is False


# --- print routing ---
def test_ipp_rejects_thermal_document(client):
    pid = client.post(
        "/v1/admin/printers", json={"name": "L", "params": {"type": "ipp_network", "host": "h"}}
    ).json()["id"]
    r = client.post("/v1/print", json={"printer": pid, "document": {"elements": []}})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "unsupported_for_printer"


def test_ipp_prints_overlay_as_pdf(client, monkeypatch):
    import io

    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(612, 792))
    c.drawString(72, 720, "base")
    c.showPage()
    c.save()
    base = client.post(
        "/v1/admin/assets", files={"file": ("f.pdf", buf.getvalue(), "application/pdf")}
    ).json()["name"]
    ov = client.post(
        "/v1/admin/overlays",
        json={"name": "o", "base_asset": base,
              "fields": [{"type": "text", "page": 0, "x": 100, "y": 100, "value": "Hi"}]},
    ).json()
    pid = client.post(
        "/v1/admin/printers", json={"name": "L", "params": {"type": "ipp_network", "host": "h"}}
    ).json()["id"]

    seen = []

    class _Fake:
        type = "ipp_network"

        def capabilities(self):
            return Capabilities(pdf=True, document_formats=["pdf"])

        def status(self):
            return {"reachable": True}

        def send(self, payload):
            seen.append(payload.kind)
            return SendResult(bytes_sent=len(payload.data), completed=False)

        def close(self):
            pass

    monkeypatch.setattr("app.queue.make_backend", lambda printer, data_dir: _Fake())
    r = client.post("/v1/print", json={"printer": pid, "overlay": ov["id"], "data": {}})
    job = wait_for_job(client, r.json()["job_id"])
    assert job["status"] == "done"
    assert seen == ["pdf"]


def test_cups_and_ipp_accept_tray_params(client):
    c = client.post(
        "/v1/admin/printers",
        json={"name": "C2", "params": {"type": "cups", "queue": "q",
                                       "output_bin": "stacker-1", "input_tray": "tray-2"}},
    ).json()
    assert c["params"]["output_bin"] == "stacker-1" and c["params"]["input_tray"] == "tray-2"
    i = client.post(
        "/v1/admin/printers",
        json={"name": "I2",
              "params": {"type": "ipp_network", "host": "h", "output_bin": "face-up"}},
    ).json()
    assert i["params"]["output_bin"] == "face-up"


# --- CUPS device_uri persistence (for startup re-provision) ---
def test_update_printer_params_persists_device_uri(client):
    pid = client.post(
        "/v1/admin/printers", json={"name": "C", "params": {"type": "cups", "queue": "q"}}
    ).json()["id"]
    client.app.state.ctx.registry.update_printer_params(pid, {"device_uri": "ipp://x/ipp/print"})
    p = client.app.state.ctx.registry.get_printer(pid)
    assert p.params["device_uri"] == "ipp://x/ipp/print"
