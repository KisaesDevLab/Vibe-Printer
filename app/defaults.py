"""Ship default formats + templates with the build.

On startup we create any bundled default (from app/defaults.yaml) that doesn't already exist,
matched by name. This is **create-if-missing** — it never overwrites an operator's edits, and a
newly-added default appears on the next boot. Disable via VIBE_PRINT_LOAD_DEFAULTS=0.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from .models import FormatCreate, TemplateCreate

if TYPE_CHECKING:
    from .context import Context

DEFAULTS_PATH = Path(__file__).parent / "defaults.yaml"


def load_defaults(ctx: Context) -> dict[str, int]:
    if not DEFAULTS_PATH.exists():
        return {"formats": 0, "templates": 0}
    doc = yaml.safe_load(DEFAULTS_PATH.read_text(encoding="utf-8")) or {}
    created = {"formats": 0, "templates": 0}
    for f in doc.get("formats", []):
        if ctx.registry._format_id_by_name(f["name"]) is None:
            ctx.registry.create_format(FormatCreate(**f))
            created["formats"] += 1
    for t in doc.get("templates", []):
        if ctx.registry._template_id_by_name(t["name"]) is None:
            ctx.registry.create_template(TemplateCreate(**t))
            created["templates"] += 1
    return created
