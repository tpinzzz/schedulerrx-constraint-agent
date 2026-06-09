"""Open-repo marker test.

In the published repository the proprietary CP-SAT snapshot under ``vendor/`` is
not included, so the 11 hermetic solver tests cannot import. This test documents
that clearly (a single, explained skip) so ``pytest -q`` is green rather than a
wall of import errors. The same tests run in the maintainer's environment and CI,
and the live deployment exercises the identical code paths.
"""

import os

import pytest

_VENDOR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "vendor"))


@pytest.mark.skipif(
    os.path.isdir(_VENDOR),
    reason="vendored solver snapshot present — the full 11-test solver suite runs",
)
def test_open_repo_uses_proprietary_solver_snapshot():
    pytest.skip(
        "The 11 hermetic solver tests require SchedulerRX's proprietary OR-Tools "
        "CP-SAT snapshot (vendor/), which is not published in this open repo. "
        "They pass in the maintainer's environment and CI; the live deployment "
        "(/dev-ui, /demo) exercises the same diagnose/verify paths. See README."
    )
