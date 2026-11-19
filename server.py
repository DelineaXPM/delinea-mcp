"""Backwards-compatible entry point: ``python server.py`` / ``uv run server.py``.

The implementation lives in :mod:`delinea_mcp.server` (so it ships in the
PyPI wheel behind the ``delinea-mcp`` console script). This shim aliases
that module under the historical ``server`` name so ``import server`` and
``monkeypatch.setattr(server, ...)`` keep addressing the real module.
"""

import sys

from delinea_mcp import server as _server

if __name__ == "__main__":
    _server.run_server()
else:
    sys.modules[__name__] = _server
