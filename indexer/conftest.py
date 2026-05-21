"""Test-time loader for the hevlayer SDK + the local hev_shop_common pkg.

The SDK lives at `../../layer/clients/python` and isn't published yet, so
`requirements.txt` pulls it via `-e ../../layer/clients/python` in deployed
environments.

`hev_shop_common` lives in the sibling `common/` directory; pinned in
`requirements.txt` via `-e ../common` in deployed environments.

For local pytest runs we put both source trees on sys.path so the tests
can `from hevlayer import ...` and `from hev_shop_common.* import ...`
without needing pip installs.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

_SDK_SRC = _REPO_ROOT.parent / "layer" / "clients" / "python" / "src"
if _SDK_SRC.is_dir() and str(_SDK_SRC) not in sys.path:
    sys.path.insert(0, str(_SDK_SRC))

_COMMON_SRC = _REPO_ROOT / "common"
if _COMMON_SRC.is_dir() and str(_COMMON_SRC) not in sys.path:
    sys.path.insert(0, str(_COMMON_SRC))
