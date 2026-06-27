"""PDF overlay rendering: stamp data-bound fields onto an uploaded base PDF.

Fields carry coordinates in PDF points with a TOP-LEFT origin (matches the UI). We build a
transparent overlay page per source page with reportlab, then merge it onto the base with pypdf.
Text/QR values are Jinja templates merged with the request `data` (sandboxed env).
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from .errors import ApiError
from .templating import _render_str


def _hex_color(value: str) -> Any:
    from reportlab.lib.colors import HexColor

    try:
        return HexColor(value)
    except Exception:
        return HexColor("#000000")


def _draw_text(c: Any, f: dict[str, Any], data: dict[str, Any], page_h: float) -> None:
    text = _render_str(str(f.get("value", "")), {"data": data})
    size = float(f.get("size", 12))
    c.setFont(f.get("font", "Helvetica"), size)
    c.setFillColor(_hex_color(str(f.get("color", "#000000"))))
    x = float(f.get("x", 0))
    # Convert top-left y to a baseline in PDF's bottom-left space.
    baseline = page_h - float(f.get("y", 0)) - size
    align = f.get("align", "left")
    if align == "right":
        c.drawRightString(x, baseline, text)
    elif align == "center":
        c.drawCentredString(x, baseline, text)
    else:
        c.drawString(x, baseline, text)


def _draw_qr(c: Any, f: dict[str, Any], data: dict[str, Any], page_h: float) -> None:
    import qrcode
    from reportlab.lib.utils import ImageReader

    value = _render_str(str(f.get("value", "")), {"data": data})
    img = qrcode.make(value)  # PIL image
    box = float(f.get("size", 72))
    x = float(f.get("x", 0))
    bottom = page_h - float(f.get("y", 0)) - box
    c.drawImage(ImageReader(img.get_image() if hasattr(img, "get_image") else img),
                x, bottom, width=box, height=box)


def _draw_image(c: Any, f: dict[str, Any], assets_dir: Path, page_h: float) -> None:
    from reportlab.lib.utils import ImageReader

    name = f.get("asset")
    if not name:
        return
    path = assets_dir / name
    if not path.exists():
        raise ApiError("render_error", f"overlay asset not found: {name}")
    w = float(f.get("width") or f.get("size", 72))
    h = float(f.get("height") or w)
    x = float(f.get("x", 0))
    bottom = page_h - float(f.get("y", 0)) - h
    c.drawImage(ImageReader(str(path)), x, bottom, width=w, height=h, mask="auto")


def render_overlay(
    base_pdf: bytes, fields: list[dict[str, Any]], data: dict[str, Any], assets_dir: Path
) -> bytes:
    from pypdf import PdfReader, PdfWriter
    from reportlab.pdfgen import canvas

    try:
        # Clone the base into the writer so merged pages are writer-attached (pypdf >=7 safe).
        writer = PdfWriter(clone_from=io.BytesIO(base_pdf))
    except Exception as e:
        raise ApiError("render_error", f"base PDF is invalid: {e}") from e

    for i, page in enumerate(writer.pages):
        page_w = float(page.mediabox.width)
        page_h = float(page.mediabox.height)
        page_fields = [f for f in fields if int(f.get("page", 0)) == i]
        if not page_fields:
            continue
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(page_w, page_h))
        for f in page_fields:
            t = f.get("type", "text")
            if t == "text":
                _draw_text(c, f, data, page_h)
            elif t == "qr":
                _draw_qr(c, f, data, page_h)
            elif t == "image":
                _draw_image(c, f, assets_dir, page_h)
            else:
                raise ApiError("validation_error", f"unknown overlay field type: {t}")
        c.save()
        buf.seek(0)
        page.merge_page(PdfReader(buf).pages[0])

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def page_sizes(base_pdf: bytes) -> list[dict[str, float]]:
    """Return per-page dimensions (points) so the UI can scale its drag canvas."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(base_pdf))
    return [
        {"width": float(p.mediabox.width), "height": float(p.mediabox.height)}
        for p in reader.pages
    ]
