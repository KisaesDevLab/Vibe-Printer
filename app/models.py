"""Pydantic v2 models: printers (discriminated union on `type`), formats, templates,
device settings, jobs, and the print request/document schema.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Printer params — discriminated on `type`
# ---------------------------------------------------------------------------


class EscposNetworkParams(BaseModel):
    type: Literal["escpos_network"] = "escpos_network"
    host: str
    port: int = 9100
    profile: str | None = None
    columns: int = 48
    paper_width_dots: int = 576
    encoding: str = "cp437"
    codepage: str | None = None
    cut: bool = True
    timeout: float = 10.0


class EscposUsbParams(BaseModel):
    type: Literal["escpos_usb"] = "escpos_usb"
    vendor_id: int
    product_id: int
    serial: str | None = None
    profile: str | None = None
    columns: int = 48
    paper_width_dots: int = 576
    encoding: str = "cp437"
    cut: bool = True


class CupsParams(BaseModel):
    type: Literal["cups"] = "cups"
    queue: str
    media: str | None = None
    output_bin: str = ""  # IPP output-bin (e.g. face-up, face-down, tray-1, stacker-1, mailbox-1)
    input_tray: str = ""  # IPP media-source (e.g. tray-1, tray-2, manual, auto)
    # Stored so the queue can be auto-(re)provisioned on startup (durable across rebuilds).
    device_uri: str | None = None
    make_model: str = "everywhere"


class IppNetworkParams(BaseModel):
    """Direct IPP (no CUPS) — point at a network printer's IPP endpoint and send PDF."""

    type: Literal["ipp_network"] = "ipp_network"
    host: str
    port: int = 631
    uri_path: str = "/ipp/print"
    tls: bool = False
    media: str | None = None
    output_bin: str = ""  # IPP output-bin keyword
    input_tray: str = ""  # IPP media-source (sent as media-col{media-source})
    uri: str | None = None  # full override; otherwise built from host/port/uri_path


class VirtualParams(BaseModel):
    type: Literal["virtual"] = "virtual"
    columns: int = 48
    paper_width_dots: int = 576


class ZplNetworkParams(BaseModel):
    type: Literal["zpl_network"] = "zpl_network"
    host: str
    port: int = 9100
    dpmm: int = 8  # dots per mm (203dpi=8, 300dpi=12)
    label_width_dots: int = 812
    label_height_dots: int = 1218  # max raster canvas height (cropped to content)
    raster: bool = False  # render the whole label to a ^GFA bitmap (graphics/QR/images/fonts)
    timeout: float = 10.0


class StarNetworkParams(BaseModel):
    type: Literal["star_network"] = "star_network"
    host: str
    port: int = 9100
    columns: int = 48
    encoding: str = "ascii"
    timeout: float = 10.0


class PoolParams(BaseModel):
    type: Literal["pool"] = "pool"
    members: list[int] = Field(default_factory=list)  # member printer ids (ESC/POS-family)
    strategy: Literal["failover", "round_robin"] = "failover"


PrinterParams = Annotated[
    EscposNetworkParams
    | EscposUsbParams
    | CupsParams
    | IppNetworkParams
    | VirtualParams
    | ZplNetworkParams
    | StarNetworkParams
    | PoolParams,
    Field(discriminator="type"),
]


class PrinterCreate(BaseModel):
    name: str
    params: PrinterParams
    default_format_id: int | None = None
    default_template_id: int | None = None
    allow_raw: bool = False


class PrinterUpdate(PrinterCreate):
    version: int  # optimistic concurrency token


class Capabilities(BaseModel):
    cut: bool = False
    qr: bool = False
    barcode: list[str] = Field(default_factory=list)
    raster: bool = False
    columns: int | None = None
    paper_width_dots: int | None = None
    pulse: bool = False
    pdf: bool = False
    # Finished-document formats this printer accepts via /v1/print/file (CUPS/office).
    document_formats: list[str] = Field(default_factory=list)


class PrinterRead(BaseModel):
    id: int
    name: str
    type: str
    params: dict[str, Any]
    capabilities: Capabilities | None = None
    reachable: bool | None = None
    default_format_id: int | None = None
    default_template_id: int | None = None
    allow_raw: bool = False
    version: int


# ---------------------------------------------------------------------------
# Formats / templates / device
# ---------------------------------------------------------------------------


class FormatCreate(BaseModel):
    name: str
    elements: dict[str, Any] = Field(default_factory=lambda: {"elements": []})
    sample_data: dict[str, Any] = Field(default_factory=dict)


class FormatUpdate(FormatCreate):
    version: int


class TemplateCreate(BaseModel):
    name: str
    html: str = ""
    css: str = ""
    page_setup: dict[str, Any] = Field(default_factory=dict)
    sample_data: dict[str, Any] = Field(default_factory=dict)


class TemplateUpdate(TemplateCreate):
    version: int


class OverlayField(BaseModel):
    """A field stamped onto a base PDF. Coordinates are PDF points, origin TOP-LEFT."""

    type: Literal["text", "qr", "image"] = "text"
    page: int = 0
    x: float = 0
    y: float = 0
    value: str = ""  # text/qr: Jinja template merged with `data`
    asset: str | None = None  # image: stored asset name
    size: float = 12  # text: font size; qr/image: box size in points
    width: float | None = None  # image override
    height: float | None = None
    font: str = "Helvetica"
    align: Literal["left", "center", "right"] = "left"
    color: str = "#000000"


class OverlayCreate(BaseModel):
    name: str
    base_asset: str  # stored asset filename of the uploaded base PDF
    fields: list[OverlayField] = Field(default_factory=list)
    sample_data: dict[str, Any] = Field(default_factory=dict)


class OverlayUpdate(OverlayCreate):
    version: int


class DeviceSettings(BaseModel):
    name: str = "vibe-print"
    timezone: str = "UTC"
    config: dict[str, Any] = Field(default_factory=dict)


class DeviceUpdate(DeviceSettings):
    version: int


# ---------------------------------------------------------------------------
# Print request / document schema
# ---------------------------------------------------------------------------


class Element(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: str


class Document(BaseModel):
    elements: list[dict[str, Any]] = Field(default_factory=list)


class PrintRequest(BaseModel):
    printer: int
    document: dict[str, Any] | None = None
    format: int | None = None
    template: int | None = None
    overlay: int | None = None  # stamp data onto an uploaded base PDF
    data: dict[str, Any] = Field(default_factory=dict)
    copies: int = Field(default=1, ge=1, le=50)
    priority: int = Field(default=0, ge=-100, le=100)  # higher runs first
    scheduled_at: str | None = None  # ISO8601 not-before; null = run now


class RawPrintRequest(BaseModel):
    printer: int
    data: str  # base64 ESC/POS


class FilePrintRequest(BaseModel):
    """Print a finished document (PDF / PostScript / PCL) to an office/CUPS printer."""

    printer: int
    content: str  # base64-encoded document bytes
    content_type: Literal["pdf", "postscript", "pcl"] = "pdf"
    copies: int = Field(default=1, ge=1, le=50)
    media: str | None = None
    priority: int = Field(default=0, ge=-100, le=100)
    scheduled_at: str | None = None


class PreviewRequest(BaseModel):
    printer: int | None = None
    document: dict[str, Any] | None = None
    format: int | None = None
    template: int | None = None
    overlay: int | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    # Inline content lets the UI preview UNSAVED edits (no stored-version churn).
    html: str | None = None
    css: str | None = None
    page_setup: dict[str, Any] | None = None


JobStatus = Literal[
    "queued", "rendering", "printing", "done", "failed", "dead", "canceled", "uncertain"
]


class JobRead(BaseModel):
    id: str
    printer_id: int
    status: str
    delivery: str | None = None
    attempts: int
    last_error: str | None = None
    format_id: int | None = None
    template_id: int | None = None
    resolved_version: int | None = None
    created_at: str
    updated_at: str
