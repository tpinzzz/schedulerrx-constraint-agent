"""Test collection guard for the open repo.

The hermetic solver tests import SchedulerRX's production CP-SAT engine from the
pinned snapshot under ``vendor/`` (proprietary; gitignored, not published). When
that snapshot is absent — i.e. in the open repository — importing those modules
would raise at collection time. We skip collecting them instead, so ``pytest -q``
exits cleanly and explains why (see ``test_open_repo.py``). With the snapshot
present (maintainer + CI), all 11 tests run.
"""

import os

_VENDOR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "vendor"))
VENDOR_PRESENT = os.path.isdir(_VENDOR)

if not VENDOR_PRESENT:
    collect_ignore = ["test_realsolver.py", "test_iis.py", "test_mcp.py"]
