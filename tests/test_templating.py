"""Templating merge: table loops, missing-var errors, injection safety (P24.1 / P24.4)."""

from __future__ import annotations

import pytest

from app.errors import ApiError
from app.templating import merge_format


def test_table_loop_merge():
    doc = {
        "elements": [
            {"type": "text", "value": "Hi {{ data.name }}"},
            {
                "type": "table",
                "cols": [10, 6],
                "rows_from": "data.lines",
                "row": ["{{ item.n }}", "{{ item.q }}"],
            },
        ]
    }
    out = merge_format(doc, {"name": "Bob", "lines": [{"n": "a", "q": "1"}, {"n": "b", "q": "2"}]})
    assert out[0]["value"] == "Hi Bob"
    assert out[1]["rows"] == [["a", "1"], ["b", "2"]]


def test_missing_var_raises_render_error():
    with pytest.raises(ApiError) as e:
        merge_format({"elements": [{"type": "text", "value": "{{ data.nope }}"}]}, {})
    assert e.value.code == "render_error"


def test_pdf_context_exposes_top_level_and_data_namespace():
    from app.templating import _pdf_context

    ctx = _pdf_context({"client": {"name": "Acme"}, "note": "hi"})
    assert ctx["client"]["name"] == "Acme"  # {{ client.name }}
    assert ctx["note"] == "hi"  # {{ note }}
    assert ctx["data"]["client"]["name"] == "Acme"  # {{ data.client.name }} still works


def test_sandbox_blocks_dunder_access():
    with pytest.raises(ApiError):
        merge_format(
            {"elements": [{"type": "text", "value": "{{ data.__class__ }}"}]},
            {},
        )
