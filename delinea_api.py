"""Backwards-compatible alias for :mod:`delinea_mcp.api`.

Kept so existing scripts doing ``import delinea_api`` keep working; the
module object is shared, so patching attributes here patches the real one.
"""

import sys

from delinea_mcp import api as _api

sys.modules[__name__] = _api
