"""Direct IPP network backend (no CUPS). Sends PDF straight to a printer's IPP endpoint.

Reachability is a real IPP Get-Printer-Attributes call, so the status badge reflects the
network, not a provisioned queue. Best for modern IPP-Everywhere printers.
"""

from __future__ import annotations

import httpx

from ..models import Capabilities
from .base import BackendError, MidSendError, PrinterUnreachable, PrintPayload, SendResult


class IppNetworkBackend:
    type = "ipp_network"

    def __init__(self, printer_id: int, params: dict) -> None:
        self.printer_id = printer_id
        from ..ipp_client import build_uri

        self.uri = params.get("uri") or build_uri(
            params["host"],
            int(params.get("port", 631)),
            params.get("uri_path", "/ipp/print"),
            bool(params.get("tls", False)),
        )
        self.params = params

    def capabilities(self) -> Capabilities:
        # IPP Everywhere printers accept PDF natively; raster too.
        return Capabilities(pdf=True, raster=True, document_formats=["pdf"])

    def status(self) -> dict:
        from ..ipp_client import get_printer_attributes

        try:
            ok = get_printer_attributes(self.uri)
            return {"reachable": ok, "state": "idle" if ok else "unknown", "errors": []}
        except httpx.HTTPError as e:
            return {"reachable": False, "state": "offline", "errors": [str(e)]}
        except Exception as e:  # pragma: no cover
            return {"reachable": False, "state": "unknown", "errors": [str(e)]}

    def send(self, payload: PrintPayload) -> SendResult:
        if payload.kind != "pdf":
            raise BackendError("IPP backend requires a PDF payload")
        from ..ipp_client import print_pdf

        try:
            sent = print_pdf(self.uri, payload.data)
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise PrinterUnreachable(f"{self.uri} unreachable: {e}") from e
        except httpx.HTTPError as e:
            # Connected, but the request didn't complete cleanly -> can't be sure.
            raise MidSendError(f"IPP send failed mid-request: {e}") from e
        except RuntimeError as e:
            # Printer answered with an IPP error (cleanly rejected) -> retryable.
            raise BackendError(str(e)) from e
        return SendResult(bytes_sent=sent, completed=False)

    def close(self) -> None:
        return
