"""ZPL label printer over TCP :9100 (Zebra-style). Streams pre-rendered ZPL bytes."""

from __future__ import annotations

import socket

from ..models import Capabilities
from .base import MidSendError, PrinterUnreachable, PrintPayload, SendResult


class ZplNetworkBackend:
    type = "zpl_network"

    def __init__(self, printer_id: int, params: dict) -> None:
        self.printer_id = printer_id
        self.host = params["host"]
        self.port = int(params.get("port", 9100))
        self.timeout = float(params.get("timeout", 10.0))
        self.params = params

    def capabilities(self) -> Capabilities:
        raster = bool(self.params.get("raster", False))
        return Capabilities(
            cut=False, qr=True, barcode=["CODE128", "CODE39", "EAN13"], raster=raster,
            pulse=False, pdf=False, columns=self.params.get("columns", 64),
            paper_width_dots=self.params.get("label_width_dots", 812),
        )

    def status(self) -> dict:
        try:
            with socket.create_connection((self.host, self.port), timeout=2.0):
                return {"reachable": True, "state": "idle", "errors": []}
        except OSError as e:
            return {"reachable": False, "state": "offline", "errors": [str(e)]}

    def send(self, payload: PrintPayload) -> SendResult:
        if payload.kind != "zpl":
            raise MidSendError("ZPL backend received non-zpl payload")
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as e:
            raise PrinterUnreachable(f"{self.host}:{self.port} unreachable: {e}") from e
        try:
            sock.sendall(payload.data)
        except OSError as e:
            raise MidSendError(f"ZPL send failed mid-stream: {e}") from e
        finally:
            try:
                sock.close()
            except OSError:
                pass
        return SendResult(bytes_sent=len(payload.data), completed=False)

    def close(self) -> None:
        return
