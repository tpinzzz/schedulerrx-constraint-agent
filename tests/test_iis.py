"""Relaxation/IIS search for EMERGENT infeasibilities (no single empty cell). Hermetic.

This is the capability that diagnosed the real production Block 12 failure: the proto-scan
finds nothing, so diagnose() falls through to the IIS, which finds the minimal binding set
and discriminates the true cause (availability) from a red herring (shift minimums)."""
from agent import realsolver


def test_emergent_scenario_falls_through_to_iis_with_a_verified_minimal_fix():
    rep = realsolver.diagnose("em_block_capacity")["report"]
    assert rep["infeasible"] is True
    assert rep.get("emergent") is True, "emergent case must not be handled by the proto-scan fast path"
    assert rep.get("minimal_fix"), "the IIS must return a minimal relaxation set"
    assert rep.get("minimal_fix_verified") is True


def test_category_sweep_discriminates_binding_cause_from_red_herring():
    rep = realsolver.diagnose("em_block_capacity")["report"]
    sweep = rep.get("category_sweep", {})
    assert sweep.get("relax_all_availability") is True   # availability IS binding
    assert sweep.get("relax_all_min_shifts") is False    # shift-minimums are NOT (the red herring)


def test_minimal_fix_reverifies_feasible():
    out = realsolver.diagnose("em_block_capacity")
    ids = [f["id"] for f in out["report"]["minimal_fix"]]
    assert realsolver.verify("em_block_capacity", ids)["feasible"] is True


def test_minimality_certificate_proves_irreducibility():
    rep = realsolver.diagnose("em_block_capacity")["report"]
    cert = rep.get("certificate")
    assert cert and cert["sufficient"] is True
    assert cert["proven_minimal"] is True
    # removing ANY element of the fix must break feasibility (that's what makes it minimal)
    assert all(n["removing_it_stays_feasible"] is False for n in cert["necessity"])
    assert cert["resolves"] >= 2
