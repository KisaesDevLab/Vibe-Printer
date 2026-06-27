"""Seed fixtures for local dev (P26.2): a virtual printer, a receipt format, a PDF template.

Run with ``python -m app.seed`` (the Makefile's ``seed`` target). Idempotent-ish: it just
appends fixtures, so run against a fresh DB.
"""

from __future__ import annotations

from .context import build_context
from .models import (
    EscposNetworkParams,
    FormatCreate,
    PrinterCreate,
    TemplateCreate,
    VirtualParams,
)
from .settings import get_settings

RECEIPT = {
    "elements": [
        {"type": "text", "value": "{{ data.company }}", "align": "center", "bold": True,
         "size": [2, 2]},
        {"type": "text", "value": "Receipt {{ data.date }}", "align": "center"},
        {"type": "rule"},
        {"type": "table", "cols": [24, 10, 12], "align": ["left", "right", "right"],
         "rows_from": "data.lines",
         "row": ["{{ item.name }}", "{{ item.qty }}", "{{ item.amt }}"]},
        {"type": "rule"},
        {"type": "text", "value": "TOTAL: {{ data.total }}", "align": "right", "bold": True},
        {"type": "qr", "value": "{{ data.url }}", "size": 6},
        {"type": "feed", "lines": 2},
        {"type": "cut"},
    ]
}

SAMPLE_DATA = {
    "company": "Acme Co",
    "date": "2026-06-27",
    "lines": [
        {"name": "Widget", "qty": "2", "amt": "9.98"},
        {"name": "Gadget", "qty": "1", "amt": "14.50"},
    ],
    "total": "24.48",
    "url": "https://example.com/r/123",
}

TEMPLATE_HTML = """
<h1>{{ data.title }}</h1>
<p>Generated {{ data.date }}</p>
<table border="1" cellpadding="4">
  <tr><th>Item</th><th>Amount</th></tr>
  {% for line in data.lines %}
  <tr><td>{{ line.name }}</td><td>{{ line.amt }}</td></tr>
  {% endfor %}
</table>
{% if data.url %}<img src="{{ data.url | qr_data_uri }}" alt="QR">{% endif %}
"""


def main() -> None:
    settings = get_settings()
    ctx = build_context(settings)

    fmt = ctx.registry.create_format(
        FormatCreate(name="Receipt", elements=RECEIPT, sample_data=SAMPLE_DATA)
    )
    tpl = ctx.registry.create_template(
        TemplateCreate(
            name="Report",
            html=TEMPLATE_HTML,
            css="body{font-family:sans-serif} h1{color:#333}",
            page_setup={"size": "A4", "margins": "1.5cm"},
            sample_data={"title": "Monthly Report", "date": "2026-06-27",
                         "lines": SAMPLE_DATA["lines"]},
        )
    )
    ctx.registry.create_printer(
        PrinterCreate(
            name="Virtual Thermal",
            params=VirtualParams(columns=48, paper_width_dots=576),
            default_format_id=fmt["id"],
        )
    )
    ctx.registry.create_printer(
        PrinterCreate(
            name="Front Counter (TCP)",
            params=EscposNetworkParams(host="192.168.1.50", port=9100),
            default_format_id=fmt["id"],
        )
    )
    print(f"Seeded format #{fmt['id']}, template #{tpl['id']}, and 2 printers.")
    ctx.db.close()


if __name__ == "__main__":
    main()
