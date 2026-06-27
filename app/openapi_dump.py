"""Dump the OpenAPI schema to stdout for TS codegen (P26.4).

    python -m app.openapi_dump > web/openapi.json

CI regenerates this and the TS types, then fails on any git diff (schema drift gate).
"""

from __future__ import annotations

import json
import os


def main() -> None:
    os.environ.setdefault("VIBE_PRINT_SECRET", "openapi-dump")
    from .main import create_app
    from .settings import get_settings

    get_settings.cache_clear()
    app = create_app()
    print(json.dumps(app.openapi(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
