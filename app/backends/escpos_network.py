"""ESC/POS over TCP :9100.

We render to raw ESC/POS bytes upstream, so this backend just streams them over a socket.
Mid-send detection: a failure during ``sendall`` (after a successful ``connect``) means bytes
may have reached the printer -> ``MidSendError`` (uncertain). A failure to connect is
``PrinterUnreachable`` (retryable).
"""

from __future__ import annotations

import socket

from ..models import Capabilities
from .base import MidSendError, PrinterUnreachable, PrintPayload, SendResult


class EscposNetworkBackend:
    type = "escpos_network"

    def __init__(self, printer_id: int, params: dict) -> None:
        self.printer_id = printer_id
        self.host = params["host"]
        self.port = int(params.get("port", 9100))
        self.timeout = float(params.get("timeout", 10.0))
        self.params = params

    def capabilities(self) -> Capabilities:
        return Capabilities(
            cut=bool(self.params.get("cut", True)),
            qr=True,
            barcode=["CODE128", "EAN13", "CODE39", "UPC-A"],
            raster=True,
            pulse=True,
            pdf=False,
            columns=self.params.get("columns", 48),
            paper_width_dots=self.params.get("paper_width_dots", 576),
        )

    def status(self) -> dict:
        try:
            with socket.create_connection((self.host, self.port), timeout=2.0):
                return {"reachable": True, "state": "idle", "errors": []}
        except OSError as e:
            return {"reachable": False, "state": "offline", "errors": [str(e)]}

    def send(self, payload: PrintPayload) -> SendResult:
        if payload.kind != "escpos":
            raise MidSendError("network ESC/POS backend received non-escpos payload")
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as e:
            raise PrinterUnreachable(f"{self.host}:{self.port} unreachable: {e}") from e
        try:
            sock.sendall(payload.data)
        except OSError as e:
            # Bytes may have partially streamed -> uncertain.
            raise MidSendError(f"send failed mid-stream to {self.host}: {e}") from e
        finally:
            try:
                sock.close()
            except OSError:
                pass
        # ESC/POS is fire-and-forget: "sent", not confirmed printed.
        return SendResult(bytes_sent=len(payload.data), completed=False)

    def close(self) -> None:
        return
