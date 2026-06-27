"""PDF overlay templating: stamp text/QR/image onto an uploaded base PDF, then print."""

from __future__ import annotations

import base64
import io

import pytest
from pypdf import PdfReader
from reportlab.pdfgen import canvas

from app.overlay import page_sizes, render_overlay


def _base_pdf(pages: int = 1, size=(612, 792)) -> bytes:
    """A minimal multi-page base PDF (Letter)."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=size)
    for n in range(pages):
        c.drawString(20, 20, f"base page {n}")
        c.showPage()
    c.save()
    return buf.getvalue()


def test_render_overlay_stamps_text(tmp_path):
    fields = [{"type": "text", "page": 0, "x": 100, "y": 100, "value": "Hello {{ data.name }}"}]
    out = render_overlay(_base_pdf(), fields, {"name": "Bob"}, tmp_path)
    text = "".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(out)).pages)
    assert "Hello Bob" in text
    assert "base page 0" in text  # base content preserved


def test_render_overlay_qr_and_image(tmp_path):
    # an image asset to overlay
    from PIL import Image

    Image.new("RGB", (32, 32), "white").save(tmp_path / "logo.png")
    fields = [
        {"type": "qr", "page": 0, "x": 50, "y": 50, "value": "{{ data.url }}", "size": 80},
        {"type": "image", "page": 0, "x": 200, "y": 50, "asset": "logo.png", "width": 40},
    ]
    out = render_overlay(_base_pdf(), fields, {"url": "https://x"}, tmp_path)
    assert out.startswith(b"%PDF")
    assert len(PdfReader(io.BytesIO(out)).pages) == 1


def test_render_overlay_multipage_targets_right_page(tmp_path):
    fields = [{"type": "text", "page": 1, "x": 100, "y": 100, "value": "second"}]
    out = render_overlay(_base_pdf(pages=2), fields, {}, tmp_path)
    pages = PdfReader(io.BytesIO(out)).pages
    assert "second" in (pages[1].extract_text() or "")
    assert "second" not in (pages[0].extract_text() or "")


def test_invalid_base_pdf_raises(tmp_path):
    from app.errors import ApiError

    with pytest.raises(ApiError):
        render_overlay(b"not a pdf", [], {}, tmp_path)


def test_page_sizes(tmp_path):
    sizes = page_sizes(_base_pdf(pages=2))
    assert len(sizes) == 2
    assert round(sizes[0]["width"]) == 612 and round(sizes[0]["height"]) == 792


# --- API + print flow ---
def _upload_base(client) -> str:
    files = {"file": ("form.pdf", _base_pdf(), "application/pdf")}
    return client.post("/v1/admin/assets", files=files).json()["name"]


def test_overlay_crud_and_print(client):
    base = _upload_base(client)
    ov = client.post("/v1/admin/overlays", json={
        "name": "W2 form", "base_asset": base,
        "fields": [{"type": "text", "page": 0, "x": 120, "y": 90, "value": "{{ data.name }}"}],
        "sample_data": {"name": "Sample"},
    }).json()
    assert ov["id"] and ov["version"] == 1

    # live preview (inline edits) returns a PDF
    pv = client.post(f"/v1/admin/overlays/{ov['id']}/preview",
                     json={"data": {"name": "Acme LLC"}})
    assert pv.status_code == 200 and pv.headers["content-type"] == "application/pdf"
    assert b"%PDF" in pv.content

    # page dimensions for the drag canvas
    pages = client.get(f"/v1/admin/overlays/{ov['id']}/pages").json()
    assert pages["pages"][0]["width"] > 0

    # print it to a virtual (PDF-capable) printer
    pid = client.post("/v1/admin/printers",
                      json={"name": "office", "params": {"type": "virtual"}}).json()["id"]
    from conftest import wait_for_job

    r = client.post("/v1/print", json={"printer": pid, "overlay": ov["id"], "data": {"name": "Z"}})
    assert r.status_code == 200
    assert wait_for_job(client, r.json()["job_id"])["status"] == "done"


def test_overlay_rejected_on_thermal_printer(client):
    base = _upload_base(client)
    ov = client.post("/v1/admin/overlays", json={"name": "o", "base_asset": base}).json()
    pid = client.post("/v1/admin/printers",
                      json={"name": "t", "params": {"type": "escpos_network", "host": "127.0.0.1"}}
                      ).json()["id"]
    r = client.post("/v1/print", json={"printer": pid, "overlay": ov["id"]})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "unsupported_for_printer"
    _ = base64  # silence unused import in some runners
