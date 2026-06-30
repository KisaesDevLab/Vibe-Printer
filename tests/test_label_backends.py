"""ZPL + StarPRNT renderers and network streaming (deferred plan items, now built)."""

from __future__ import annotations

import socket
import threading
from pathlib import Path

from conftest import wait_for_job

from app.models import Capabilities
from app.render import render_star, render_zpl, render_zpl_raster

DOC = [
    {"type": "text", "value": "Acme", "align": "center", "bold": True},
    {"type": "rule"},
    {"type": "text", "value": "SKU-123"},
    {"type": "cut"},
]


def test_render_zpl_structure():
    caps = Capabilities(qr=True, barcode=["CODE128"])
    out = render_zpl(DOC + [{"type": "barcode", "value": "123"}], {"label_width_dots": 812}, caps)
    text = out.decode()
    assert text.startswith("^XA") and text.rstrip().endswith("^XZ")
    assert "Acme" in text and "^BCN" in text


def test_render_zpl_raster_emits_gfa():
    caps = Capabilities(qr=True, raster=True)
    els = DOC + [{"type": "qr", "value": "https://example.com"}]
    params = {"label_width_dots": 400, "label_height_dots": 600}
    out = render_zpl_raster(els, params, caps, Path("."))
    text = out.decode("ascii")
    assert text.startswith("^XA") and text.rstrip().endswith("^XZ")
    assert "^GFA," in text  # raster graphic field instead of native font/QR commands


def test_zpl_raster_printer_streams_gfa(client):
    port, box, th = _capture_server()
    params = {"type": "zpl_network", "host": "127.0.0.1", "port": port, "raster": True}
    pid = client.post("/v1/admin/printers", json={"name": "zebra-r", "params": params}).json()["id"]
    r = client.post("/v1/print", json={"printer": pid, "document": {"elements": DOC}})
    job = wait_for_job(client, r.json()["job_id"])
    assert job["status"] == "done"
    th.join(timeout=3)
    assert b"^GFA," in box["data"]


def test_render_star_structure():
    caps = Capabilities(cut=True)
    out = render_star(DOC, {"columns": 48}, caps)
    assert out.startswith(b"\x1b@")  # ESC @ init
    assert b"Acme" in out
    assert out.rstrip().endswith(b"\x1bd\x03") or b"\x1bd\x03" in out  # partial cut


def _capture_server():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    box: dict = {}

    def run():
        conn, _ = srv.accept()
        data = b""
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                break
            data += chunk
        box["data"] = data
        conn.close()
        srv.close()

    th = threading.Thread(target=run, daemon=True)
    th.start()
    return port, box, th


def test_zpl_network_streams_label(client):
    port, box, th = _capture_server()
    params = {"type": "zpl_network", "host": "127.0.0.1", "port": port}
    pid = client.post("/v1/admin/printers", json={"name": "zebra", "params": params}).json()["id"]
    r = client.post("/v1/print", json={"printer": pid, "document": {"elements": DOC}})
    job = wait_for_job(client, r.json()["job_id"])
    assert job["status"] == "done"
    th.join(timeout=3)
    assert b"^XA" in box["data"] and b"Acme" in box["data"]


def test_star_network_streams_bytes(client):
    port, box, th = _capture_server()
    params = {"type": "star_network", "host": "127.0.0.1", "port": port}
    pid = client.post("/v1/admin/printers", json={"name": "star", "params": params}).json()["id"]
    r = client.post("/v1/print", json={"printer": pid, "document": {"elements": DOC}})
    job = wait_for_job(client, r.json()["job_id"])
    assert job["status"] == "done"
    th.join(timeout=3)
    assert box["data"].startswith(b"\x1b@")
