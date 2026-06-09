"""Real-solver diagnosis + verify. Hermetic: vendored production CP-SAT snapshot, no DB,
no network, no LLM. These exercise the actual ground-truth layer the agent depends on."""
import pytest

from agent import realsolver


def test_list_scenarios_includes_both():
    ids = {s["id"] for s in realsolver.list_scenarios()}
    assert {"em_block_gap", "em_block_capacity"} <= ids


def test_clean_scenario_localizes_to_a_forced_empty_cell():
    rep = realsolver.diagnose("em_block_gap")["report"]
    assert rep["infeasible"] is True
    assert rep["localized"] is True
    assert rep["unstaffable_cells"], "expected at least one forced-empty coverage cell"


def test_clean_scenario_offers_a_closed_candidate_set():
    out = realsolver.diagnose("em_block_gap")
    assert out["candidates"], "diagnosis must offer solver-authored relaxation candidates"
    for c in out["candidates"]:
        assert c["id"].startswith(("free:", "minshift:"))


def test_full_relaxation_is_verified_feasible():
    out = realsolver.diagnose("em_block_gap")
    ids = [c["id"] for c in out["candidates"]]
    assert realsolver.verify("em_block_gap", ids)["feasible"] is True


def test_unknown_candidate_id_is_rejected():
    # The agent may only act on ids the solver authored; a bogus id must not silently apply.
    with pytest.raises(Exception):
        realsolver.verify("em_block_gap", ["bogus:99:2026-01-01"])


def test_faculty_scenario_speaks_faculty_not_residency():
    # The same engine, relabeled: faculty vocabulary in reasons + fix labels, role "attending".
    out = realsolver.diagnose("faculty_block")
    rep = out["report"]
    assert rep["localized"] is True
    reasons = " ".join(b["reason"] for c in rep["unstaffable_cells"] for b in c["blocked"]).lower()
    assert "sabbatical" in reasons and "vacation" not in reasons
    labels = " ".join(c["label"] for c in out["candidates"]).lower()
    assert "sabbatical" in labels
    assert all(c["level"] == "attending" for c in out["candidates"])
    assert realsolver.verify("faculty_block", [c["id"] for c in out["candidates"]])["feasible"] is True
