#!/usr/bin/env python3
"""Dump OpenAPI specs for both hev-shop FastAPI services.

Writes `search/openapi.json` and `indexer/openapi.json` from the live
FastAPI `app.openapi()` payloads. Output is sorted-keys + 2-space indent
+ trailing newline so the files diff cleanly against drift tests.

Run from the repo root (or anywhere — paths resolve from this file):

    python3 scripts/dump_openapi.py
    # or:
    make openapi
"""

from __future__ import annotations

import json
import sys
from importlib import import_module
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SDK_SRC = REPO_ROOT.parent / "layer" / "clients" / "python" / "src"
COMMON_SRC = REPO_ROOT / "common"


# Flat modules each service may define. Dropped between dumps so the second
# service's imports aren't shadowed by the first's.
_SERVICE_MODULES = ("app", "models", "dataset", "extract_chunk", "embed")


def _prepare_sys_path(service_dir: Path) -> None:
    """Mirror the conftest sys.path setup so `from app import app` works
    without `pip install -e`. The service dir goes first so its flat modules
    win over the other service's."""
    for path in (SDK_SRC, COMMON_SRC, service_dir):
        s = str(path)
        if s in sys.path:
            sys.path.remove(s)
        if path.is_dir():
            sys.path.insert(0, s)


def _drop_service_modules() -> None:
    for name in list(sys.modules):
        if name in _SERVICE_MODULES or any(
            name.startswith(f"{mod}.") for mod in _SERVICE_MODULES
        ):
            del sys.modules[name]


def _downconvert_3_1_to_3_0(node):
    """FastAPI/Pydantic emit OpenAPI 3.1; oapi-codegen v2 only handles 3.0.

    The only 3.1-only idiom both services emit is `anyOf: [..., {"type":
    "null"}, ...]` for `T | None`. Collapse it to 3.0's `nullable: true`.
    If anyOf is left with a single branch after dropping null, inline
    that branch's keys into the parent so consumers don't see a useless
    one-element anyOf.
    """
    if isinstance(node, list):
        return [_downconvert_3_1_to_3_0(item) for item in node]
    if not isinstance(node, dict):
        return node
    converted = {k: _downconvert_3_1_to_3_0(v) for k, v in node.items()}

    any_of = converted.get("anyOf")
    if isinstance(any_of, list):
        non_null = [
            b for b in any_of if not (isinstance(b, dict) and b.get("type") == "null")
        ]
        if len(non_null) < len(any_of):
            converted["nullable"] = True
            if len(non_null) == 1 and isinstance(non_null[0], dict):
                # Inline the single remaining branch alongside `nullable`.
                # Existing sibling keys (title, description, ...) win on conflict.
                merged = dict(non_null[0])
                merged.update({k: v for k, v in converted.items() if k != "anyOf"})
                return merged
            converted["anyOf"] = non_null
    return converted


def _normalize_for_3_0(spec: dict) -> dict:
    converted = _downconvert_3_1_to_3_0(spec)
    converted["openapi"] = "3.0.3"
    return converted


def _serialize(spec: dict) -> str:
    return json.dumps(spec, sort_keys=True, indent=2) + "\n"


def dump_one(service_dir: Path) -> Path:
    _drop_service_modules()
    _prepare_sys_path(service_dir)
    module = import_module("app")
    spec = _normalize_for_3_0(module.app.openapi())
    out_path = service_dir / "openapi.json"
    out_path.write_text(_serialize(spec))
    return out_path


def main() -> int:
    paths = [dump_one(REPO_ROOT / svc) for svc in ("search", "indexer")]
    for p in paths:
        print(f"wrote {p.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
