"""Jinja2 templating: sandboxed env, element-JSON merge (formats), HTML/CSS -> PDF (WeasyPrint).

Security:
- SandboxedEnvironment blocks attribute/`__` access escapes (P7.1, P22.5).
- HTML rendering is autoescaped (injection via `data` is neutralised).
- WeasyPrint is locked to local asset files only — no remote URL fetch (SSRF, P7.4/P22.2).
- A render timeout is enforced by the caller (worker / preview) via a thread budget.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from jinja2 import ChainableUndefined, StrictUndefined
from jinja2.exceptions import TemplateError, UndefinedError
from jinja2.sandbox import SandboxedEnvironment

from .errors import ApiError


class _LenientUndefined(ChainableUndefined):
    """Optional-field-friendly undefined for HTML/PDF templates: missing names render empty,
    are falsy in `{% if %}`, and iterate to nothing in `{% for %}` (so `{% if logo %}` and
    `{% for x in surcharges %}` work without every optional key being supplied)."""

    __slots__ = ()

    def __iter__(self) -> Any:
        return iter(())

    def __bool__(self) -> bool:
        return False

    def __len__(self) -> int:
        return 0


# Thermal/overlay element rendering stays strict (controlled schema → catch typos).
_env = SandboxedEnvironment(autoescape=False, undefined=StrictUndefined)
# PDF/HTML templates are lenient so optional variables can be omitted.
_html_env = SandboxedEnvironment(autoescape=True, undefined=_LenientUndefined)


def qr_data_uri(value: str, box_size: int = 4, border: int = 2, ec: str = "M") -> str:
    """Jinja filter: turn a string/URL into a PNG QR ``data:`` URI for use in HTML/PDF templates.

    Usage in a PDF template:  ``<img src="{{ data.url | qr_data_uri }}">``
    """
    import base64
    import io

    import qrcode
    from qrcode.constants import (
        ERROR_CORRECT_H,
        ERROR_CORRECT_L,
        ERROR_CORRECT_M,
        ERROR_CORRECT_Q,
    )

    levels = {
        "L": ERROR_CORRECT_L, "M": ERROR_CORRECT_M, "Q": ERROR_CORRECT_Q, "H": ERROR_CORRECT_H,
    }
    qr = qrcode.QRCode(
        error_correction=levels.get(str(ec).upper(), ERROR_CORRECT_M),
        box_size=max(1, int(box_size)),
        border=max(0, int(border)),
    )
    qr.add_data(str(value))
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


# Filters are safe (pure, no I/O beyond in-memory encoding); register on both envs.
for _e in (_env, _html_env):
    _e.filters["qr_data_uri"] = qr_data_uri

# Bound WeasyPrint concurrency so previews can't exhaust a Pi (P30.4).
_weasy_sema = threading.Semaphore(2)


def _render_str(template: str, context: dict[str, Any], *, html: bool = False) -> str:
    env = _html_env if html else _env
    try:
        return env.from_string(template).render(**context)
    except UndefinedError as e:
        raise ApiError("render_error", f"Missing template variable: {e.message}") from e
    except TemplateError as e:
        raise ApiError("render_error", f"Template error: {e}") from e


def _resolve_path(data: dict[str, Any], path: str) -> Any:
    """Resolve a dotted path like 'data.lines' against {'data': data}."""
    cur: Any = {"data": data}
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return []
    return cur


def merge_format(elements_doc: dict[str, Any], data: dict[str, Any]) -> list[dict[str, Any]]:
    """Merge a format's element list with request `data` -> render-ready elements (P7.2)."""
    out: list[dict[str, Any]] = []
    ctx = {"data": data}
    for el in elements_doc.get("elements", []):
        etype = el.get("type")
        if etype == "table":
            out.append(_merge_table(el, data, ctx))
            continue
        merged = dict(el)
        for key in ("value", "asset"):
            if isinstance(merged.get(key), str):
                merged[key] = _render_str(merged[key], ctx)
        out.append(merged)
    return out


def _merge_table(el: dict[str, Any], data: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    merged = dict(el)
    rows_from = el.get("rows_from")
    if rows_from:
        items = _resolve_path(data, rows_from)
        row_tpl = el.get("row", [])
        rendered_rows = []
        for item in items:
            row_ctx = {**ctx, "item": item}
            rendered_rows.append([_render_str(str(cell), row_ctx) for cell in row_tpl])
        merged["rows"] = rendered_rows
        merged.pop("rows_from", None)
        merged.pop("row", None)
    else:
        merged["rows"] = [
            [_render_str(str(cell), ctx) for cell in row] for row in el.get("rows", [])
        ]
    return merged


def _pdf_context(data: dict[str, Any]) -> dict[str, Any]:
    """Expose request fields both under `data.*` and at the top level, so templates can use
    either `{{ data.client.name }}` or `{{ client.name }}`."""
    if isinstance(data, dict):
        return {**data, "data": data}
    return {"data": data}


def render_pdf(html: str, css: str, page_setup: dict[str, Any], data: dict[str, Any],
               assets_dir: Path) -> bytes:
    """Render an HTML/CSS template to PDF bytes via WeasyPrint, sandboxed to local assets."""
    try:
        from weasyprint import CSS, HTML  # lazy: native libs only in the appliance image
        from weasyprint.urls import URLFetchingError
    except Exception as e:  # pragma: no cover
        raise ApiError(
            "render_error", "PDF rendering unavailable: install the 'pdf' extra (WeasyPrint)."
        ) from e

    body = _render_str(html, _pdf_context(data), html=True)
    page_css = _page_css(page_setup)
    assets_root = assets_dir.resolve()

    def url_fetcher(url: str, **kwargs: Any) -> dict[str, Any]:
        # Allow only files under the assets dir — block http(s), file:// escapes (SSRF lockdown).
        from urllib.parse import unquote, urlparse

        parsed = urlparse(url)
        if parsed.scheme in ("http", "https"):
            raise URLFetchingError(f"remote fetch blocked: {url}")
        if parsed.scheme in ("file", ""):
            target = Path(unquote(parsed.path)).resolve()
            if assets_root in target.parents or target.parent == assets_root:
                return {"file_obj": open(target, "rb"), "mime_type": None}
        raise URLFetchingError(f"resource not allowed: {url}")

    with _weasy_sema:
        doc = HTML(string=body, base_url=str(assets_root), url_fetcher=url_fetcher)
        stylesheets = [CSS(string=page_css)]
        if css:
            stylesheets.append(CSS(string=css))
        return doc.write_pdf(stylesheets=stylesheets)


def _page_css(page_setup: dict[str, Any]) -> str:
    size = page_setup.get("size", "A4")
    margins = page_setup.get("margins", "1cm")
    return f"@page {{ size: {size}; margin: {margins}; }}"
