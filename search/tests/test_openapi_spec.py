"""Spec-drift gate for the search service.

If you change a route or a Pydantic model, regenerate the spec:

    make openapi   # or: python3 scripts/dump_openapi.py

This test fails on drift so committed `search/openapi.json` is always
the spec the FastAPI app actually serves.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.main import app  # noqa: E402
from scripts.dump_openapi import _normalize_for_3_0, _serialize  # noqa: E402

SPEC_PATH = Path(__file__).resolve().parent.parent / "openapi.json"


def test_committed_openapi_matches_app():
    committed = SPEC_PATH.read_text()
    current = _serialize(_normalize_for_3_0(app.openapi()))
    assert current == committed, (
        "search/openapi.json is out of sync with FastAPI app.\n"
        "Run `make openapi` (or `python3 scripts/dump_openapi.py`) and commit."
    )
