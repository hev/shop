"""Test-time loader for the search service.

Puts the hevlayer SDK + the hev_shop_common package + the flat service
modules (app.py, models.py) on sys.path so pytest can resolve
`from app import app`, `from hevlayer import ...`, and
`from hev_shop_common.* import ...` without needing pip installs.

In deployed environments `requirements.txt` pulls both sibling packages
via `-e ../../layer/clients/python` and `-e ../common`.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parent
_REPO_ROOT = _SERVICE_ROOT.parent

# `from app import app` works when search/ is on sys.path, matching how the
# modules run in the container with WORKDIR /app.
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))

_SDK_SRC = _REPO_ROOT.parent / "layer" / "clients" / "python" / "src"
if _SDK_SRC.is_dir() and str(_SDK_SRC) not in sys.path:
    sys.path.insert(0, str(_SDK_SRC))

_COMMON_SRC = _REPO_ROOT / "common"
if _COMMON_SRC.is_dir() and str(_COMMON_SRC) not in sys.path:
    sys.path.insert(0, str(_COMMON_SRC))
