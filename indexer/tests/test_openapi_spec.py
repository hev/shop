"""Spec-drift gate for the indexer service.

If you change a route or a Pydantic model, regenerate the spec:

    make openapi   # or: python3 scripts/dump_openapi.py

This test fails on drift so committed `indexer/openapi.json` is always
the spec the FastAPI app actually serves.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parent.parent
_REPO_ROOT = _SERVICE_ROOT.parent
for _p in (_SERVICE_ROOT, _REPO_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from app.main import app  # noqa: E402
from scripts.dump_openapi import _normalize_for_3_0, _serialize  # noqa: E402

SPEC_PATH = _SERVICE_ROOT / "openapi.json"


def test_committed_openapi_matches_app():
    committed = SPEC_PATH.read_text()
    current = _serialize(_normalize_for_3_0(app.openapi()))
    assert current == committed, (
        "indexer/openapi.json is out of sync with FastAPI app.\n"
        "Run `make openapi` (or `python3 scripts/dump_openapi.py`) and commit."
    )
