"""Relaxation / IIS search for EMERGENT infeasibilities.

The proto-scan (``realsolver.diagnose``) localizes *clean* coverage gaps — a single
shift cell whose every candidate is forced false. But most real infeasibilities are
*emergent*: the model proves INFEASIBLE only after presolve combines coverage,
availability (PTO), shift-minimums and rest — no single cell is empty, so the scan
finds nothing. (This is exactly what we saw on the real production block: relaxing
PTO restored feasibility, fixing a bad shift-bound alone did not.)

This module finds the minimal binding set the way an Irreducible Infeasible Subset
(IIS) search does: relax candidate constraint groups, re-solve, and keep only the
relaxations whose removal restores infeasibility (deletion filtering). It generalizes
the verify-by-re-solve already in ``realsolver`` — every step is a real CP-SAT solve,
so the result is ground truth, not an LLM guess.

Search (coarse -> fine):
  1. Category sweep — relax ALL availability (PTO/night), then ALL shift-minimums;
     record which restores feasibility. This separates a binding cause from a red herring.
  2. Seed — the smallest category that restores feasibility on its own (else everything).
  3. Deletion filter — drop each relaxation whose removal keeps the seed feasible,
     leaving an irreducible (minimal) feasible-making set.
  4. Rank by operational disruption, then verify the minimal set by re-solving.
"""
from __future__ import annotations

from typing import Any

from . import realsolver as R

# Operational disruption weight — lower is less painful, presented first.
_DISRUPTION = {"free_pto": 1, "free_night": 2, "minshift": 3}


def _atomic_candidates(sc) -> list[str]:
    """Every atomic relaxation the solver authorizes for this scenario (closed set)."""
    cands: list[str] = []
    for i, r in enumerate(sc.residents):
        for d in r.pto:
            cands.append(f"free:{i}:{d}")
        for d in r.night_restricted:
            cands.append(f"free:{i}:{d}")
        if r.min_shifts > 0:
            cands.append(f"minshift:{i}")
    return cands


def _has_min_floor(sc) -> bool:
    return any(r.min_shifts > 0 for r in sc.residents)


def _kind(sc, cid: str) -> str:
    parts = cid.split(":")
    if parts[0] == "minshift":
        return "minshift"
    r = sc.residents[int(parts[1])]
    is_night = parts[2] in r.night_restricted and parts[2] not in r.pto
    return "free_night" if is_night else "free_pto"


def _candidate_dict(sc, cid: str) -> dict[str, Any]:
    parts = cid.split(":")
    r = sc.residents[int(parts[1])]
    d: dict[str, Any] = {"id": cid, "label": R._candidate_label(sc, cid),
                         "resident": r.name, "level": r.level}
    if parts[0] == "free":
        d["date"] = parts[2]
    return d


def _feasible(scenario_id: str, cids: list[str]) -> bool:
    return R.verify(scenario_id, cids)["feasible"]


def _deletion_filter(scenario_id: str, seed: list[str]) -> list[str]:
    """Drop each relaxation whose removal keeps the set feasible — leaving an
    irreducible (minimal) feasible-making subset. ``verify([])`` re-solves the
    baseline (infeasible), so the last necessary relaxation is never dropped."""
    current = list(seed)
    for c in list(seed):
        trial = [x for x in current if x != c]
        if _feasible(scenario_id, trial):
            current = trial
    return current


def _ranked(sc, cids: list[str]) -> list[str]:
    return sorted(cids, key=lambda c: (_DISRUPTION.get(_kind(sc, c), 9), c))


def search_infeasibility(scenario_id: str) -> dict[str, Any]:
    """Diagnose an emergent infeasibility by relaxation/IIS search. Returns the same
    ``{"report": ..., "candidates": [...]}`` contract as ``realsolver.diagnose``."""
    sc = R.SCENARIOS[scenario_id]
    _, res = R._solve(sc, R._resident_data(sc))
    if res.feasible:
        return {"report": {"scenario": scenario_id, "infeasible": False, "localized": False,
                           "status": res.status,
                           "message": "Schedule is feasible — nothing to diagnose."},
                "candidates": []}

    atoms = _atomic_candidates(sc)
    pto_cands = [c for c in atoms if c.startswith("free")]
    min_cands = [c for c in atoms if c.startswith("minshift")]

    # 1. Category sweep — which whole-category relaxation restores feasibility?
    sweep = {
        "relax_all_availability": bool(pto_cands) and _feasible(scenario_id, pto_cands),
        "relax_all_min_shifts": bool(min_cands) and _feasible(scenario_id, min_cands),
    }
    binding: list[str] = []
    if sweep["relax_all_availability"]:
        binding.append("availability (PTO / night limits)")
    if sweep["relax_all_min_shifts"]:
        binding.append("shift minimums")

    # 2. Seed = the smallest category that restores feasibility on its own, else all.
    if sweep["relax_all_availability"]:
        seed = pto_cands
    elif sweep["relax_all_min_shifts"]:
        seed = min_cands
    elif _feasible(scenario_id, atoms):
        seed = atoms
        binding = ["availability + shift minimums (only together)"]
    else:
        return {"report": {"scenario": scenario_id, "infeasible": True, "localized": False,
                           "emergent": True, "status": res.status, "category_sweep": sweep,
                           "message": ("Infeasible even after relaxing all PTO and all "
                                       "shift-minimums — the shortfall is structural: "
                                       "coverage demand exceeds the resident pool.")},
                "candidates": []}

    # 3. Deletion-filter to an irreducible minimal set; 4. rank + verify.
    minimal = _ranked(sc, _deletion_filter(scenario_id, seed))
    vr = R.verify(scenario_id, minimal)

    report = {
        "scenario": scenario_id,
        "description": sc.description,
        "infeasible": True,
        "localized": True,
        "emergent": True,
        "status": res.status,
        "primitive": "aggregate_capacity_shortfall",
        "constraint_rule": ("Aggregate feasibility over the block — coverage floors vs. "
                            "available residents vs. shift minimums. No single shift cell is "
                            "empty; the conflict only appears when they are solved together."),
        "category_sweep": sweep,
        "binding_categories": binding,
        "minimal_fix": [{"id": c, "label": R._candidate_label(sc, c)} for c in minimal],
        "minimal_fix_verified": vr["feasible"],
        "certificate": R.certify_minimal(scenario_id, minimal),
        "message": _message(sc, minimal, sweep),
    }
    candidates = [_candidate_dict(sc, c) for c in _ranked(sc, seed)]
    return {"report": report, "candidates": candidates}


def _message(sc, minimal, sweep) -> str:
    if sweep["relax_all_availability"]:
        head = ("This block is infeasible because of an availability shortfall, not any "
                "single empty shift — every shift still has eligible residents.")
    else:
        head = "This block is infeasible due to an aggregate capacity shortfall."
    ruled_out = ""
    if _has_min_floor(sc) and not sweep["relax_all_min_shifts"]:
        ruled_out = (" The search ruled out a plausible cause: relaxing the shift-minimums "
                     "does NOT restore feasibility, so the bottleneck is availability.")
    fix = ""
    if minimal:
        n = len(minimal)
        fix = (" Minimal verified fix (%d relaxation%s): " % (n, "" if n == 1 else "s")
               + "; ".join(R._candidate_label(sc, c) for c in minimal) + ".")
    return head + ruled_out + fix
