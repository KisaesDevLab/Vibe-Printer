"""QR options on the ESC/POS element (a) + the qr_data_uri Jinja filter for PDF/HTML (c)."""

from __future__ import annotations

import base64

from app.models import Capabilities
from app.render import render_escpos
from app.templating import _render_str, qr_data_uri

NATIVE_QR_CMD = b"\x1d\x28\x6b"  # GS ( k — the printer's native QR command


def _caps():
    return Capabilities(qr=True, raster=True, cut=True)


# --- (a) ESC/POS qr options ---
def test_qr_default_is_raster_image(tmp_path):
    out = render_escpos([{"type": "qr", "value": "https://x"}], {}, _caps(), tmp_path)
    assert NATIVE_QR_CMD not in out  # rendered as a raster image
    assert len(out) > 100


def test_qr_native_emits_printer_command(tmp_path):
    out = render_escpos(
        [{"type": "qr", "value": "https://x", "native": True}], {}, _caps(), tmp_path
    )
    assert NATIVE_QR_CMD in out


def test_qr_ec_and_model_accepted(tmp_path):
    out = render_escpos(
        [{"type": "qr", "value": "u", "native": True, "ec": "H", "model": 1, "size": 8}],
        {}, _caps(), tmp_path,
    )
    assert NATIVE_QR_CMD in out


def test_qr_size_is_clamped(tmp_path):
    # size 99 would raise in python-escpos; we clamp to 1-16.
    out = render_escpos([{"type": "qr", "value": "u", "size": 99}], {}, _caps(), tmp_path)
    assert len(out) > 0


# --- (c) qr_data_uri filter ---
def test_qr_data_uri_returns_png_data_uri():
    uri = qr_data_uri("https://example.com/r/123")
    assert uri.startswith("data:image/png;base64,")
    raw = base64.b64decode(uri.split(",", 1)[1])
    assert raw.startswith(b"\x89PNG\r\n\x1a\n")  # PNG magic


def test_qr_data_uri_available_in_html_templates():
    tpl = '<img src="{{ data.url | qr_data_uri }}">'
    html = _render_str(tpl, {"data": {"url": "u"}}, html=True)
    assert 'src="data:image/png;base64,' in html
