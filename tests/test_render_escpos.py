"""Exercise the ESC/POS renderer across element types + capability gating (P8)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from app.errors import ApiError
from app.models import Capabilities
from app.render import render_escpos


def _caps(**kw):
    base = dict(cut=True, qr=True, barcode=["CODE128", "EAN13"], raster=True, pulse=True,
               columns=48, paper_width_dots=576)
    base.update(kw)
    return Capabilities(**base)


def test_render_all_element_types(tmp_path):
    els = [
        {"type": "text", "value": "Title", "align": "center", "bold": True, "size": [2, 2]},
        {"type": "rule"},
        {"type": "table", "cols": [20, 10], "align": ["left", "right"],
         "rows": [["Item", "Qty"], ["Widget", "2"]]},
        {"type": "qr", "value": "https://x", "size": 6},
        {"type": "barcode", "format": "CODE128", "value": "12345"},
        {"type": "feed", "lines": 2},
        {"type": "pulse"},
        {"type": "cut"},
    ]
    out = render_escpos(els, {"columns": 48, "encoding": "cp437"}, _caps(), tmp_path)
    assert isinstance(out, bytes) and len(out) > 0


def test_qr_unsupported_raises(tmp_path):
    with pytest.raises(ApiError) as e:
        render_escpos([{"type": "qr", "value": "x"}], {}, _caps(qr=False), tmp_path)
    assert e.value.code == "unsupported_for_printer"


def test_barcode_unsupported_format_raises(tmp_path):
    with pytest.raises(ApiError) as e:
        render_escpos([{"type": "barcode", "format": "UPC-A", "value": "1"}], {},
                      _caps(barcode=["CODE128"]), tmp_path)
    assert e.value.code == "unsupported_for_printer"


def test_unknown_element_raises(tmp_path):
    with pytest.raises(ApiError) as e:
        render_escpos([{"type": "nope"}], {}, _caps(), tmp_path)
    assert e.value.code == "validation_error"


def test_image_element_renders(tmp_path):
    img = Image.new("L", (200, 50), 255)
    asset = Path(tmp_path) / "logo.png"
    img.save(asset)
    out = render_escpos(
        [{"type": "image", "asset": "logo.png"}],
        {"paper_width_dots": 384}, _caps(), tmp_path,
    )
    assert len(out) > 0


def test_missing_image_asset_raises(tmp_path):
    with pytest.raises(ApiError) as e:
        render_escpos([{"type": "image", "asset": "nope.png"}], {}, _caps(), tmp_path)
    assert e.value.code == "render_error"
