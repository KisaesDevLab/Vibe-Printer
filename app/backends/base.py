"""PrinterBackend protocol + shared types.

Backends are SYNC (sockets / libusb / cups are blocking); the async worker runs ``send`` in a
thread. Error taxonomy drives delivery semantics:

- ``PrinterUnreachable``  -> retryable (could not even start: connect/open failed).
- ``MidSendError``        -> NOT auto-retried: bytes began streaming then the link died.
                             The worker marks the job ``uncertain`` (Decision 16 / P10.4).
- ``BackendError``        -> generic retryable failure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

from ..models import Capabilities


class PrinterUnreachable(Exception):
    """Could not connect/open the device — safe to retry."""


class MidSendError(Exception):
    """Connection died after bytes began streaming — mark uncertain, do not auto-retry."""


class BackendError(Exception):
    """Other delivery failure — retryable."""


@dataclass
class PrintPayload:
    kind: Literal["escpos", "pdf", "zpl", "star", "postscript", "pcl"]
    data: bytes
    options: dict = field(default_factory=dict)  # e.g. media, copies for CUPS


@dataclass
class SendResult:
    bytes_sent: int
    completed: bool  # True only when we have positive confirmation (CUPS job-state)


@runtime_checkable
class PrinterBackend(Protocol):
    type: str

    def capabilities(self) -> Capabilities: ...

    def status(self) -> dict: ...

    def send(self, payload: PrintPayload) -> SendResult: ...

    def close(self) -> None: ...
