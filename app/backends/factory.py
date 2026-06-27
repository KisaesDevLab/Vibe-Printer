"""Factory: registry printer row -> concrete backend (P3.2)."""

from __future__ import annotations

from pathlib import Path

from ..errors import ApiError
from ..models import PrinterRead
from .base import PrinterBackend
from .cups import CupsBackend
from .escpos_network import EscposNetworkBackend
from .escpos_usb import EscposUsbBackend
from .star_network import StarNetworkBackend
from .virtual import VirtualBackend
from .zpl_network import ZplNetworkBackend


def make_backend(printer: PrinterRead, *, data_dir: Path) -> PrinterBackend:
    params = printer.params
    if printer.type == "virtual":
        return VirtualBackend(printer.id, params, data_dir / "virtual")
    if printer.type == "escpos_network":
        return EscposNetworkBackend(printer.id, params)
    if printer.type == "escpos_usb":
        return EscposUsbBackend(printer.id, params)
    if printer.type == "cups":
        return CupsBackend(printer.id, params)
    if printer.type == "zpl_network":
        return ZplNetworkBackend(printer.id, params)
    if printer.type == "star_network":
        return StarNetworkBackend(printer.id, params)
    raise ApiError("validation_error", f"Unknown printer type: {printer.type}")


def is_serialized(printer_type: str) -> bool:
    """Single byte-stream devices serialize per printer. CUPS has its own spooler -> don't."""
    return printer_type in (
        "escpos_network", "escpos_usb", "virtual", "zpl_network", "star_network"
    )
