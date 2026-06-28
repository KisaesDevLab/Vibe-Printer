"""Star (StarPRNT / Star Line Mode) printer over TCP :9100. Streams pre-rendered Star bytes."""

from __future__ import annotations

import socket

from ..models import Capabilities
from .base import MidSendError, PrinterUnreachable, PrintPayload, SendResult


class StarNetworkBackend:
    type = "star_network"

    def __init__(self, printer_id: int, params: dict) -> None:
        self.printer_id = printer_id
        self.host = params["host"]
        self.port = int(params.get("port", 9100))
        self.timeout = float(params.get("timeout", 10.0))
        self.params = params

    def capabilities(self) -> Capabilities:
        return Capabilities(
            cut=True, qr=False, barcode=[], raster=False, pulse=True, pdf=False,
            columns=self.params.get("columns", 48),
        )

    def status(self) -> dict:
        try:
            with socket.create_connection((self.host, self.port), timeout=2.0):
                return {"reachable": True, "state": "idle", "errors": []}
        except OSError as e:
            return {"reachable": False, "state": "offline", "errors": [str(e)]}

    def send(self, payload: PrintPayload) -> SendResult:
        if payload.kind != "star":
            raise MidSendError("Star backend received non-star payload")
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as e:
            raise PrinterUnreachable(f"{self.host}:{self.port} unreachable: {e}") from e
        try:
            sock.sendall(payload.data)
        except OSError as e:
            raise MidSendError(f"Star send failed mid-stream: {e}") from e
        finally:
            try:
                sock.close()
            except OSError:
                pass
        return SendResult(bytes_sent=len(payload.data), completed=False)

    def close(self) -> None:
        return
