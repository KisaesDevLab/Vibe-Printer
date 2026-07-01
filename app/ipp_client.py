"""Minimal IPP client (RFC 8010/8011) over httpx — enough to query status and print a PDF.

IPP is HTTP POST with an ``application/ipp`` binary body. We implement two operations:
Get-Printer-Attributes (0x000B) for reachability/state, and Print-Job (0x0002) to submit a PDF.
This avoids CUPS entirely for modern IPP-Everywhere printers.
"""

from __future__ import annotations

import httpx

# IPP value tags
_TAG_CHARSET = 0x47
_TAG_NATURAL_LANG = 0x48
_TAG_URI = 0x45
_TAG_KEYWORD = 0x44
_TAG_NAME = 0x42
_TAG_MIME = 0x49
_TAG_BEG_COLLECTION = 0x34
_TAG_END_COLLECTION = 0x37
_TAG_MEMBER_NAME = 0x4A

# IPP delimiter tags
_TAG_OPERATION_ATTRS = 0x01
_TAG_JOB_ATTRS = 0x02
_TAG_END_ATTRS = 0x03

OP_PRINT_JOB = 0x0002
OP_GET_PRINTER_ATTRS = 0x000B


def _attr(tag: int, name: str, value: str | bytes) -> bytes:
    nb = name.encode("utf-8")
    vb = value.encode("utf-8") if isinstance(value, str) else value
    return bytes([tag]) + len(nb).to_bytes(2, "big") + nb + len(vb).to_bytes(2, "big") + vb


def _member(tag: int, value: bytes) -> bytes:
    # A collection member: zero-length name, then the value (name goes in a memberAttrName attr).
    return bytes([tag]) + (0).to_bytes(2, "big") + len(value).to_bytes(2, "big") + value


def _media_col_source(tray: str) -> bytes:
    """Encode ``media-col = { media-source = <tray> }`` (an IPP collection) for input-tray."""
    out = bytearray()
    out += _attr(_TAG_BEG_COLLECTION, "media-col", b"")
    out += _member(_TAG_MEMBER_NAME, b"media-source")
    out += _member(_TAG_KEYWORD, tray.encode("utf-8"))
    out += _attr(_TAG_END_COLLECTION, "", b"")
    return bytes(out)


def _job_attributes(output_bin: str = "", input_tray: str = "") -> bytes:
    """Job-template attributes (output-bin keyword, media-col input source)."""
    out = bytearray()
    if output_bin:
        out += _attr(_TAG_KEYWORD, "output-bin", output_bin)
    if input_tray:
        out += _media_col_source(input_tray)
    return bytes(out)


def _build(operation: int, printer_uri: str, extra: bytes = b"", job_attrs: bytes = b"",
           request_id: int = 1) -> bytes:
    out = bytearray()
    out += b"\x02\x00"  # IPP version 2.0
    out += operation.to_bytes(2, "big")
    out += request_id.to_bytes(4, "big")
    out += bytes([_TAG_OPERATION_ATTRS])
    out += _attr(_TAG_CHARSET, "attributes-charset", "utf-8")
    out += _attr(_TAG_NATURAL_LANG, "attributes-natural-language", "en")
    out += _attr(_TAG_URI, "printer-uri", printer_uri)
    out += _attr(_TAG_NAME, "requesting-user-name", "vibe-print")
    out += extra
    if job_attrs:
        out += bytes([_TAG_JOB_ATTRS]) + job_attrs
    out += bytes([_TAG_END_ATTRS])
    return bytes(out)


def http_url(printer_uri: str) -> str:
    if printer_uri.startswith("ipps://"):
        return "https://" + printer_uri[len("ipps://") :]
    if printer_uri.startswith("ipp://"):
        return "http://" + printer_uri[len("ipp://") :]
    return printer_uri


def _ipp_status(response_body: bytes) -> int:
    # bytes 2..4 of an IPP response are the status-code; < 0x0100 == successful.
    if len(response_body) < 4:
        raise RuntimeError("short IPP response")
    return int.from_bytes(response_body[2:4], "big")


def build_uri(host: str, port: int = 631, path: str = "/ipp/print", tls: bool = False) -> str:
    scheme = "ipps" if tls else "ipp"
    return f"{scheme}://{host}:{port}{path}"


def get_printer_attributes(printer_uri: str, timeout: float = 5.0) -> bool:
    """Return True if the printer answers IPP successfully (reachable)."""
    body = _build(OP_GET_PRINTER_ATTRS, printer_uri)
    r = httpx.post(
        http_url(printer_uri), content=body,
        headers={"Content-Type": "application/ipp"}, timeout=timeout,
    )
    r.raise_for_status()
    return _ipp_status(r.content) < 0x0100


def build_print_job(printer_uri: str, pdf: bytes, job_name: str = "vibe-print",
                    output_bin: str = "", input_tray: str = "") -> bytes:
    """Assemble the full IPP Print-Job request body (attributes + document)."""
    extra = _attr(_TAG_NAME, "job-name", job_name) + _attr(
        _TAG_MIME, "document-format", "application/pdf"
    )
    job_attrs = _job_attributes(output_bin, input_tray)
    return _build(OP_PRINT_JOB, printer_uri, extra, job_attrs) + pdf


def _parse_attributes(body: bytes) -> dict[str, list[str]]:
    """Parse an IPP response into {attribute-name: [string values]} (keyword/name/text values).
    Handles 1setOf: additional values carry a zero-length name and belong to the prior attribute."""
    attrs: dict[str, list[str]] = {}
    i = 8  # skip version(2) + status(2) + request-id(4)
    n = len(body)
    last: str | None = None
    while i < n:
        tag = body[i]
        i += 1
        if tag < 0x10:  # delimiter tag (0x03 = end-of-attributes)
            if tag == 0x03:
                break
            last = None
            continue
        if i + 2 > n:
            break
        name_len = int.from_bytes(body[i:i + 2], "big")
        i += 2
        name = body[i:i + name_len].decode("utf-8", "replace")
        i += name_len
        val_len = int.from_bytes(body[i:i + 2], "big")
        i += 2
        val = body[i:i + val_len]
        i += val_len
        key = name if name_len > 0 else last
        if name_len > 0:
            last = name
        if key is None or tag in (0x21, 0x22, 0x23):  # skip integer/boolean/enum values
            continue
        attrs.setdefault(key, []).append(val.decode("utf-8", "replace"))
    return attrs


def list_trays(printer_uri: str, timeout: float = 5.0) -> dict[str, list[str]]:
    """Query the printer for its supported output bins and input trays (media sources)."""
    body = _build(OP_GET_PRINTER_ATTRS, printer_uri)
    r = httpx.post(
        http_url(printer_uri), content=body,
        headers={"Content-Type": "application/ipp"}, timeout=timeout,
    )
    r.raise_for_status()
    attrs = _parse_attributes(r.content)
    return {
        "output_bins": attrs.get("output-bin-supported", []),
        "input_trays": attrs.get("media-source-supported", []),
    }


def print_pdf(printer_uri: str, pdf: bytes, job_name: str = "vibe-print",
              timeout: float = 30.0, output_bin: str = "", input_tray: str = "") -> int:
    """Submit a PDF via IPP Print-Job. Returns bytes sent; raises on IPP error."""
    body = build_print_job(printer_uri, pdf, job_name, output_bin, input_tray)
    r = httpx.post(
        http_url(printer_uri), content=body,
        headers={"Content-Type": "application/ipp"}, timeout=timeout,
    )
    r.raise_for_status()
    status = _ipp_status(r.content)
    if status >= 0x0100:
        raise RuntimeError(f"IPP error status {status:#06x}")
    return len(pdf)
