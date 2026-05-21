"""Test-time loader for the common package.

`hev_shop_common` is meant to be installed via `pip install -e ../common`
from the search/ and indexer/ services. Local pytest runs put the source
on sys.path so `from hev_shop_common.* import ...` works without needing
an editable install.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PKG_ROOT = Path(__file__).resolve().parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

