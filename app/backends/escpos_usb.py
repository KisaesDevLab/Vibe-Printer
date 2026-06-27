"""ESC/POS over USB via python-escpos (libusb). Lazy import so the app runs without pyusb."""

from __future__ import annotations

from typing import Any

from ..models import Capabilities
from .base import BackendError, MidSendError, PrinterUnreachable, PrintPayload, SendResult


class EscposUsbBackend:
    type = "escpos_usb"

    def __init__(self, printer_id: int, params: dict) -> None:
        self.printer_id = printer_id
        self.vendor_id = int(params["vendor_id"])
        self.product_id = int(params["product_id"])
        self.serial = params.get("serial")
        self.params = params

    def _open(self) -> Any:
        try:
            from escpos.printer import Usb
        except Exception as e:  # pragma: no cover - import guard
            raise BackendError(
                "USB support unavailable: install the 'usb' extra (pyusb + libusb)."
            ) from e
        try:
            kwargs = {}
            if self.serial:
                kwargs["serial_number"] = self.serial
            return Usb(self.vendor_id, self.product_id, **kwargs)
        except Exception as e:
            raise PrinterUnreachable(
                f"USB device {self.vendor_id:#06x}:{self.product_id:#06x} not found: {e}"
            ) from e

    def capabilities(self) -> Capabilities:
        return Capabilities(
            cut=bool(self.params.get("cut", True)),
            qr=True,
            barcode=["CODE128", "EAN13", "CODE39"],
            raster=True,
            pulse=True,
            pdf=False,
            columns=self.params.get("columns", 48),
            paper_width_dots=self.params.get("paper_width_dots", 576),
        )

    def status(self) -> dict:
        try:
            dev = self._open()
            dev.close()
            return {"reachable": True, "state": "idle", "errors": []}
        except PrinterUnreachable as e:
            return {"reachable": False, "state": "offline", "errors": [str(e)]}
        except BackendError as e:
            return {"reachable": False, "state": "unknown", "errors": [str(e)]}

    def send(self, payload: PrintPayload) -> SendResult:
        if payload.kind != "escpos":
            raise MidSendError("USB ESC/POS backend received non-escpos payload")
        dev = self._open()
        try:
            dev._raw(payload.data)
        except Exception as e:
            raise MidSendError(f"USB send failed mid-stream: {e}") from e
        finally:
            try:
                dev.close()
            except Exception:
                pass
        return SendResult(bytes_sent=len(payload.data), completed=False)

    def close(self) -> None:
        return
