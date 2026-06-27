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

OP_PRINT_JOB = 0x0002
OP_GET_PRINTER_ATTRS = 0x000B


def _attr(tag: int, name: str, value: str | bytes) -> bytes:
    nb = name.encode("utf-8")
    vb = value.encode("utf-8") if isinstance(value, str) else value
    return bytes([tag]) + len(nb).to_bytes(2, "big") + nb + len(vb).to_bytes(2, "big") + vb


def _build(operation: int, printer_uri: str, extra: bytes = b"", request_id: int = 1) -> bytes:
    out = bytearray()
    out += b"\x02\x00"  # IPP version 2.0
    out += operation.to_bytes(2, "big")
    out += request_id.to_bytes(4, "big")
    out += b"\x01"  # operation-attributes-tag
    out += _attr(_TAG_CHARSET, "attributes-charset", "utf-8")
    out += _attr(_TAG_NATURAL_LANG, "attributes-natural-language", "en")
    out += _attr(_TAG_URI, "printer-uri", printer_uri)
    out += _attr(_TAG_NAME, "requesting-user-name", "vibe-print")
    out += extra
    out += b"\x03"  # end-of-attributes-tag
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


def print_pdf(printer_uri: str, pdf: bytes, job_name: str = "vibe-print",
              timeout: float = 30.0) -> int:
    """Submit a PDF via IPP Print-Job. Returns bytes sent; raises on IPP error."""
    extra = _attr(_TAG_NAME, "job-name", job_name) + _attr(
        _TAG_MIME, "document-format", "application/pdf"
    )
    body = _build(OP_PRINT_JOB, printer_uri, extra) + pdf
    r = httpx.post(
        http_url(printer_uri), content=body,
        headers={"Content-Type": "application/ipp"}, timeout=timeout,
    )
    r.raise_for_status()
    status = _ipp_status(r.content)
    if status >= 0x0100:
        raise RuntimeError(f"IPP error status {status:#06x}")
    return len(pdf)
