# /// script
# requires-python = ">=3.11"
# dependencies = ["packaging"]
# ///
"""Print ``true`` if a PEP 440 version is a final release, ``false`` otherwise.

uv run scripts/version_is_stable.py 2.1.0rc1
"""

import sys

from packaging.version import Version

print(str(not Version(sys.argv[1]).is_prerelease).lower())
