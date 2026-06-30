"""ESC/POS rendering (elements -> bytes) and server-side previews (PNG for thermal, PDF for office).

The same merged element list drives both the real ESC/POS byte stream and the PNG preview, so
the preview faithfully reflects what will print. Capability-aware: elements the target printer
can't do raise ``unsupported_for_printer`` (P8.2).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .errors import ApiError
from .models import Capabilities

_QR_EC = {"L": 0, "M": 1, "Q": 2, "H": 3}  # error-correction levels (escpos constants)
_QR_MODEL = {1: 1, 2: 2, "1": 1, "2": 2}


def _qr_kwargs(el: dict[str, Any]) -> dict[str, Any]:
    """Map a `qr` element's options onto python-escpos qr() kwargs.

    Options: size (1-16), native (printer command vs raster image), ec (L/M/Q/H),
    model (1/2), center (bool).
    """
    kwargs: dict[str, Any] = {
        "size": max(1, min(16, int(el.get("size", 6)))),
        "native": bool(el.get("native", False)),
        "center": bool(el.get("center", False)),
    }
    ec = str(el.get("ec", "")).upper()
    if ec in _QR_EC:
        kwargs["ec"] = _QR_EC[ec]
    model = el.get("model")
    if model in _QR_MODEL:
        kwargs["model"] = _QR_MODEL[model]
    return kwargs


def _drawer_kick(el: dict[str, Any]) -> bytes:
    """ESC/POS cash-drawer pulse: ESC p m t1 t2 (m=0→pin2, m=1→pin5; times in 2ms units)."""
    pin = int(el.get("pin", 2))
    m = 0 if pin == 2 else 1
    on = max(1, min(255, int(el.get("on_ms", 100)) // 2))
    off = max(1, min(255, int(el.get("off_ms", 200)) // 2))
    return b"\x1bp" + bytes([m, on, off])


# --------------------------------------------------------------------------- text layout helpers
def _fit(text: str, width: int, align: str) -> str:
    text = text[:width]
    pad = width - len(text)
    if align == "right":
        return " " * pad + text
    if align == "center":
        left = pad // 2
        return " " * left + text + " " * (pad - left)
    return text + " " * pad


def _table_lines(el: dict[str, Any], columns: int) -> list[str]:
    cols = el.get("cols", [])
    aligns = el.get("align", ["left"] * len(cols))
    lines: list[str] = []
    for row in el.get("rows", []):
        cells = []
        for i in range(len(cols)):
            val = str(row[i]) if i < len(row) else ""
            align = aligns[i] if i < len(aligns) else "left"
            cells.append(_fit(val, cols[i], align))
        lines.append(" ".join(cells)[:columns])
    return lines


def _as_text_lines(elements: list[dict[str, Any]], columns: int) -> list[str]:
    """A plain-text rendering used for the PNG preview."""
    out: list[str] = []
    for el in elements:
        t = el.get("type")
        if t == "text":
            val = str(el.get("value", ""))
            align = el.get("align", "left")
            for line in val.split("\n"):
                out.append(_fit(line, columns, align))
        elif t == "rule":
            out.append("-" * columns)
        elif t == "table":
            out.extend(_table_lines(el, columns))
        elif t == "qr":
            out.append(_fit(f"[QR: {el.get('value','')}]", columns, "center"))
        elif t == "barcode":
            label = f"[{el.get('format', 'CODE128')}: {el.get('value', '')}]"
            out.append(_fit(label, columns, "center"))
        elif t == "image":
            out.append(_fit(f"[image: {el.get('asset','')}]", columns, "center"))
        elif t == "feed":
            out.extend([""] * int(el.get("lines", 1)))
        elif t == "cut":
            out.append("-" * columns)
        elif t == "pulse":
            out.append("[cash drawer]")
    return out


# --------------------------------------------------------------------------- ESC/POS byte render
def render_escpos(
    elements: list[dict[str, Any]],
    params: dict[str, Any],
    caps: Capabilities,
    assets_dir: Path,
) -> bytes:
    from escpos.printer import Dummy

    d = Dummy(encoding=params.get("encoding", "cp437"))
    columns = params.get("columns", 48)
    paper_width_dots = params.get("paper_width_dots", 576)

    for el in elements:
        t = el.get("type")
        if t == "text":
            size = el.get("size", [1, 1])
            d.set(
                align=el.get("align", "left"),
                bold=bool(el.get("bold", False)),
                width=int(size[0]) if isinstance(size, list) else 1,
                height=int(size[1]) if isinstance(size, list) and len(size) > 1 else 1,
            )
            d.textln(str(el.get("value", "")))
            d.set()  # reset
        elif t == "rule":
            d.textln("-" * columns)
        elif t == "table":
            for line in _table_lines(el, columns):
                d.textln(line)
        elif t == "qr":
            if not caps.qr:
                raise ApiError("unsupported_for_printer", "printer has no QR support")
            d.qr(str(el.get("value", "")), **_qr_kwargs(el))
        elif t == "barcode":
            fmt = el.get("format", "CODE128")
            if fmt not in caps.barcode:
                raise ApiError("unsupported_for_printer", f"printer lacks barcode {fmt}")
            code = str(el.get("value", ""))
            # python-escpos CODE128 requires a code-set selector prefix ({A/{B/{C).
            if fmt == "CODE128" and not code.startswith("{"):
                code = "{B" + code
            d.barcode(code, fmt, function_type="B")
        elif t == "image":
            if not caps.raster:
                raise ApiError("unsupported_for_printer", "printer has no raster/image support")
            img = _load_asset_image(el.get("asset", ""), assets_dir, paper_width_dots)
            d.image(img)
        elif t == "pulse":
            if caps.pulse:
                d._raw(_drawer_kick(el))
        elif t == "feed":
            d.ln(int(el.get("lines", 1)))
        elif t == "cut":
            if caps.cut:
                d.cut()
        else:
            raise ApiError("validation_error", f"unknown element type: {t}")
    return bytes(d.output)


def _zpl_escape(s: str) -> str:
    return s.replace("^", " ").replace("~", " ")


def render_zpl(elements: list[dict[str, Any]], params: dict[str, Any], caps: Capabilities) -> bytes:
    """Render elements to ZPL II for Zebra-style label printers (deferred plan item, now built)."""
    width = params.get("label_width_dots", 812)
    columns = params.get("columns", 64)
    out: list[str] = ["^XA", "^CI28"]  # UTF-8
    y = 20
    for el in elements:
        t = el.get("type")
        if t == "text":
            size = el.get("size", [1, 1])
            h = 24 * (int(size[1]) if isinstance(size, list) and len(size) > 1 else 1)
            out.append(f"^FO20,{y}^A0N,{h},{h}^FD{_zpl_escape(str(el.get('value','')))}^FS")
            y += h + 8
        elif t == "rule":
            out.append(f"^FO20,{y}^GB{width - 40},2,2^FS")
            y += 14
        elif t == "table":
            for line in _table_lines(el, columns):
                out.append(f"^FO20,{y}^A0N,24,24^FD{_zpl_escape(line)}^FS")
                y += 28
        elif t == "qr":
            if not caps.qr:
                raise ApiError("unsupported_for_printer", "printer has no QR support")
            out.append(f"^FO20,{y}^BQN,2,{int(el.get('size',6))}^FDLA,{_zpl_escape(str(el.get('value','')))}^FS")
            y += 140
        elif t == "barcode":
            fmt = el.get("format", "CODE128")
            if fmt not in caps.barcode:
                raise ApiError("unsupported_for_printer", f"printer lacks barcode {fmt}")
            out.append(f"^FO20,{y}^BCN,90,Y,N,N^FD{_zpl_escape(str(el.get('value','')))}^FS")
            y += 130
        elif t == "feed":
            y += 24 * int(el.get("lines", 1))
        elif t in ("cut", "pulse", "image"):
            pass  # labels auto-separate; raster/drawer not modeled here
        else:
            raise ApiError("validation_error", f"unknown element type: {t}")
    out.append("^XZ")
    return ("\n".join(out) + "\n").encode("utf-8", "replace")


def _ttf(size: int, *, mono: bool = False) -> Any:
    name = "DejaVuSansMono.ttf" if mono else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(name, size)
    except OSError:
        return ImageFont.load_default()


def _qr_image(value: str, box: int) -> Image.Image:
    import qrcode

    qr = qrcode.QRCode(box_size=max(2, int(box)), border=2)
    qr.add_data(value)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").convert("1")


def _zpl_gfa(img: Image.Image) -> str:
    """Pack a 1-bit PIL image into a ZPL ``^GFA`` graphic field (ASCII-hex, uncompressed).
    In PIL mode "1", a pixel value of 0 is black; ZPL wants a 1-bit set for black dots."""
    img = img.convert("1")
    w, h = img.size
    bytes_per_row = (w + 7) // 8
    px = img.load()
    assert px is not None
    data = bytearray()
    for y in range(h):
        for bx in range(bytes_per_row):
            b = 0
            for bit in range(8):
                x = bx * 8 + bit
                if x < w and px[x, y] == 0:
                    b |= 0x80 >> bit
            data.append(b)
    total = len(data)
    return f"^FO0,0^GFA,{total},{total},{bytes_per_row},{data.hex().upper()}^FS"


def render_zpl_raster(
    elements: list[dict[str, Any]], params: dict[str, Any], caps: Capabilities,
    assets_dir: Path,
) -> bytes:
    """Render an element list to a single monochrome bitmap sent as ZPL ``^GFA`` — so text, QR,
    images, rules and tables print as graphics on any Zebra printer regardless of resident fonts."""
    width = int(params.get("label_width_dots", 812))
    max_h = int(params.get("label_height_dots", 1218))
    columns = int(params.get("columns", 48))
    margin = 12

    canvas = Image.new("1", (width, max_h), 1)  # white background
    draw = ImageDraw.Draw(canvas)
    y = margin
    for el in elements:
        t = el.get("type")
        if t == "text":
            size = el.get("size", [1, 1])
            scale = int(size[1]) if isinstance(size, list) and len(size) > 1 else 1
            fsize = 22 * max(1, scale)
            draw.text((margin, y), str(el.get("value", "")), fill=0, font=_ttf(fsize))
            y += fsize + 8
        elif t == "rule":
            draw.line([(margin, y), (width - margin, y)], fill=0, width=2)
            y += 14
        elif t == "table":
            for line in _table_lines(el, columns):
                draw.text((margin, y), line, fill=0, font=_ttf(20, mono=True))
                y += 24
        elif t == "qr":
            if not caps.qr:
                raise ApiError("unsupported_for_printer", "printer has no QR support")
            qimg = _qr_image(str(el.get("value", "")), int(el.get("size", 6)))
            canvas.paste(qimg, (margin, min(y, max_h - qimg.height)))
            y += qimg.height + 8
        elif t == "image":
            asset = el.get("asset")
            if asset:
                im = _load_asset_image(str(asset), assets_dir, width - 2 * margin)
                canvas.paste(im, (margin, min(y, max_h - im.height)))
                y += im.height + 8
        elif t == "barcode":
            raise ApiError(
                "unsupported_for_printer",
                "linear barcodes need native ZPL — turn raster off for this printer",
            )
        elif t == "feed":
            y += 24 * int(el.get("lines", 1))
        elif t in ("cut", "pulse"):
            pass  # labels auto-separate; no drawer on Zebra
        else:
            raise ApiError("validation_error", f"unknown element type: {t}")

    used = min(max_h, y + margin)
    label = canvas.crop((0, 0, width, used))
    return ("^XA\n" + _zpl_gfa(label) + "\n^XZ\n").encode("ascii")


def render_star(
    elements: list[dict[str, Any]], params: dict[str, Any], caps: Capabilities
) -> bytes:
    """Render elements to Star Line Mode commands (text/align/cut). Deferred item, now built."""
    esc = b"\x1b"
    enc = params.get("encoding", "ascii")
    columns = params.get("columns", 48)
    out = bytearray(esc + b"@")  # initialize
    align_map = {"left": 0, "center": 1, "right": 2}
    for el in elements:
        t = el.get("type")
        if t == "text":
            out += esc + b"\x1d\x61" + bytes([align_map.get(el.get("align", "left"), 0)])
            bold = bool(el.get("bold", False))
            if bold:
                out += esc + b"E"
            out += str(el.get("value", "")).encode(enc, "replace") + b"\n"
            if bold:
                out += esc + b"F"
        elif t == "rule":
            out += ("-" * columns).encode(enc, "replace") + b"\n"
        elif t == "table":
            for line in _table_lines(el, columns):
                out += line.encode(enc, "replace") + b"\n"
        elif t == "feed":
            out += b"\n" * int(el.get("lines", 1))
        elif t == "cut":
            if caps.cut:
                out += esc + b"d\x03"  # partial cut
        elif t == "pulse":
            # Star Line Mode drawer kick: BEL (07h) = drawer 1, SUB (1Ah) = drawer 2.
            if caps.pulse:
                out += b"\x07" if int(el.get("pin", 2)) == 2 else b"\x1a"
        elif t in ("qr", "barcode", "image"):
            pass  # not modeled in Star Line Mode minimal renderer
        else:
            raise ApiError("validation_error", f"unknown element type: {t}")
    return bytes(out)


def _load_asset_image(asset_name: str, assets_dir: Path, paper_width_dots: int) -> Image.Image:
    path = assets_dir / asset_name
    if not path.exists():
        raise ApiError("render_error", f"asset not found: {asset_name}")
    img = Image.open(path).convert("L")
    if img.width > paper_width_dots:
        ratio = paper_width_dots / img.width
        img = img.resize((paper_width_dots, int(img.height * ratio)))
    return img.convert("1")  # 1-bit dither for thermal


# --------------------------------------------------------------------------- PNG preview
def render_preview_png(
    elements: list[dict[str, Any]], params: dict[str, Any]
) -> bytes:
    import io

    columns = params.get("columns", 48)
    lines = _as_text_lines(elements, columns)
    if not lines:
        lines = ["(empty)"]
    font: Any
    try:
        font = ImageFont.truetype("DejaVuSansMono.ttf", 16)
    except OSError:
        font = ImageFont.load_default()

    char_w, line_h = 9, 20
    width = max(columns * char_w + 16, 200)
    height = len(lines) * line_h + 16
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((8, 8 + i * line_h), line, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
