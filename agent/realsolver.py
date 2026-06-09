"""Real-model integration — the seam where the production SchedulerRX solver
replaces the toy ``model.py``.

Builds the real ``ShiftSolver`` in-process on a static scenario (no DB), diagnoses
``INFEASIBLE`` with the symbolic proto-scan (``diagnostic._forced_values`` +
``_unsatisfiable_coverage_linears``), generates a CLOSED set of relaxation
candidates, and verifies each by re-solving.

The solver is a pinned, gitignored snapshot under ``../vendor`` (see
``planning/SPIKE_RESULTS.md``); ``app.database`` there is a ``Base``-only stub, so
no DATABASE_URL / DB connection is needed.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

# --- Vendored proprietary solver snapshot (Base-only db stub → no DB) ---
_VENDOR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "vendor"))
if _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)
os.environ.setdefault("ENVIRONMENT", "test")

from app.config.programs.em_norms import EM_NORMS
from app.scripts.seed_programs import build_em_program_config
from app.solvers import create_single_solver
from app.solvers.context_window import FutureShift, ResidentContextWindow
from app.solvers.factories import resolve_extra_factories_for_norms

from .diagnostic import _forced_values, _unsatisfiable_coverage_linears

# EM program config (2 pods, 6 shift instances: day/night/swing × purple/orange).
# Built once at import — pure literals, no DB.
_CONFIG = build_em_program_config()


# ---------------------------------------------------------------------------
# Scenario definition (static fixtures — the demo inputs)
# ---------------------------------------------------------------------------


@dataclass
class ResidentSpec:
    name: str
    level: str  # "pgy1" | "pgy2" | "pgy3"
    pto: list[str] = field(default_factory=list)  # ISO dates fully off (vacation/conference)
    night_restricted: list[str] = field(default_factory=list)  # ISO dates: no night (didactics)
    min_shifts: int = 0  # per-resident minimum shifts over the block (0 = no floor)


@dataclass
class Scenario:
    id: str
    description: str
    block_start: str  # ISO date (a Monday)
    ndays: int
    residents: list[ResidentSpec]
    # How a full-day-off / night block reads in the diagnosis. Defaults are residency
    # phrasing; a faculty scenario relabels them (sabbatical / protected time / FTE cap)
    # so the SAME engine explains faculty infeasibility in faculty terms.
    pto_label: str = "PTO (vacation/conference)"
    night_label: str = "night restriction (didactics)"
    role_label: str = ""  # display-role override (e.g. "attending"); empty = use each spec's level


_THU = "2026-07-09"  # Thursday — weekday 3, within the night day_of_week_mask

SCENARIOS: dict[str, Scenario] = {
    "em_block_gap": Scenario(
        id="em_block_gap",
        description=(
            "An Emergency Medicine residency block. On Thursday 2026-07-09 the night shift is "
            "unstaffable: 4 residents are on PTO (vacation/conference) and the other 4 "
            "are restricted from nights (didactics) — so no one can cover either night pod."
        ),
        block_start="2026-07-06",  # Monday
        ndays=7,
        residents=[
            ResidentSpec("Dr. Alice Okafor", "pgy3", pto=[_THU]),
            ResidentSpec("Dr. Ben Reyes", "pgy3", pto=[_THU]),
            ResidentSpec("Dr. Carmen Liu", "pgy2", pto=[_THU]),
            ResidentSpec("Dr. Dev Patel", "pgy2", pto=[_THU]),
            ResidentSpec("Dr. Elena Sorkin", "pgy2", night_restricted=[_THU]),
            ResidentSpec("Dr. Frank Mwangi", "pgy2", night_restricted=[_THU]),
            ResidentSpec("Dr. Gina Holt", "pgy1", night_restricted=[_THU]),
            ResidentSpec("Dr. Hassan Ali", "pgy1", night_restricted=[_THU]),
        ],
    ),
    "em_block_capacity": Scenario(
        id="em_block_capacity",
        description=(
            "A 7-day Emergency Medicine block the scheduler flags INFEASIBLE — but with "
            "no single empty shift, so the coordinator can't see why: every shift still "
            "has eligible residents. The cause is an aggregate capacity shortfall that "
            "only surfaces when coverage, availability and shift-minimums are solved "
            "together. Diagnose it and propose a verified fix."
        ),
        block_start="2026-07-06",  # Monday; Thursday 2026-07-09 is night-active
        ndays=7,
        residents=[
            ResidentSpec("Dr. Maya Iqbal", "pgy3", pto=[_THU], min_shifts=4),
            ResidentSpec("Dr. Noah Brenner", "pgy3", pto=[_THU], min_shifts=4),
            ResidentSpec("Dr. Priya Raman", "pgy2", pto=[_THU], min_shifts=4),
            ResidentSpec("Dr. Quentin Ade", "pgy2", pto=[_THU], min_shifts=4),
            ResidentSpec("Dr. Rosa Linden", "pgy2", pto=[_THU], min_shifts=4),
            ResidentSpec("Dr. Sam Okonkwo", "pgy1", min_shifts=4),
            ResidentSpec("Dr. Tara Voss", "pgy1", min_shifts=4),
            ResidentSpec("Dr. Umar Sheikh", "pgy1", min_shifts=4),
        ],
    ),
    # Faculty/attending block — the SAME engine, relabeled. Demonstrates the diagnosis
    # generalizes beyond residency to the faculty factors generic schedulers miss.
    "faculty_block": Scenario(
        id="faculty_block",
        description=(
            "A 7-day Emergency Medicine FACULTY (attending) block — the same engine applied to "
            "faculty constraints. On Thursday 2026-07-09 neither night pod can be covered: 4 "
            "attendings are on sabbatical / protected academic time and the other 4 are at their "
            "clinical-FTE cap / on protected research, so none can take a night. Shows the "
            "diagnosis generalizes beyond residency to the faculty factors generic schedulers miss."
        ),
        block_start="2026-07-06",  # Monday; Thursday 2026-07-09 is night-active
        ndays=7,
        pto_label="sabbatical / protected academic time",
        night_label="protected research / clinical-FTE cap",
        role_label="attending",
        residents=[
            ResidentSpec("Dr. Morgan Vale", "pgy3", pto=[_THU]),
            ResidentSpec("Dr. Priya Anand", "pgy3", pto=[_THU]),
            ResidentSpec("Dr. Theo Brandt", "pgy3", pto=[_THU]),
            ResidentSpec("Dr. Lena Ortiz", "pgy3", pto=[_THU]),
            ResidentSpec("Dr. Sam Devereux", "pgy3", night_restricted=[_THU]),
            ResidentSpec("Dr. Nia Coleman", "pgy3", night_restricted=[_THU]),
            ResidentSpec("Dr. Raj Bhatt", "pgy3", night_restricted=[_THU]),
            ResidentSpec("Dr. Owen Frost", "pgy3", night_restricted=[_THU]),
        ],
    ),
}

_PTO_REASON = "PTO — vacation/conference"
_NIGHT_REASON = "night-restricted — didactics"


def list_scenarios() -> list[dict[str, str]]:
    return [{"id": s.id, "description": s.description} for s in SCENARIOS.values()]


# ---------------------------------------------------------------------------
# Build + solve the real model from a scenario
# ---------------------------------------------------------------------------


def _block_dates(sc: Scenario) -> list[date]:
    bs = date.fromisoformat(sc.block_start)
    return [bs + timedelta(days=i) for i in range(sc.ndays)]


def _context_window(dts: list[date]) -> ResidentContextWindow:
    bs, be = dts[0], dts[-1]
    nd = be + timedelta(days=1)
    # A nominal future placeholder makes the border-night constraint skip the
    # resident, isolating the in-block coverage logic (mirrors the test harness).
    return ResidentContextWindow(
        pre_window_start=bs - timedelta(days=8), block_start=bs, block_end=be,
        post_window_end=be + timedelta(days=2),
        future_shifts=[FutureShift(
            date=nd, shift_instance_id="__future__", is_night=False, is_day=False,
            shift_category=None, start_datetime=datetime.combine(nd, time(0, 0)),
            duration_minutes=0)],
    )


def _resident_data(sc: Scenario, relax: dict[str, Any] | None = None) -> dict[int, dict[str, Any]]:
    """The solver's resident_data dict. ``relax`` applies relaxation knobs:

      relax["free"]: {resident_idx: {iso_dates}} — lift that resident's PTO AND
        night-restriction on those dates (adds availability/capacity).
      relax["min0"]: {resident_idx} — drop that resident's min_shifts floor to 0
        (lowers demand).

    Parse candidate ids into this shape with ``_parse_candidates`` — never hand-split."""
    relax = relax or {}
    free = relax.get("free", {})
    min0 = relax.get("min0", set())
    cw = _context_window(_block_dates(sc))
    out: dict[int, dict[str, Any]] = {}
    for i, r in enumerate(sc.residents):
        lifted = free.get(i, set())
        pto = [d for d in r.pto if d not in lifted]
        nights = [d for d in r.night_restricted if d not in lifted]
        min_shifts = 0 if i in min0 else r.min_shifts
        out[i] = {
            "name": r.name, "level": r.level, "program_type": "EM",
            "constraints": {"min_shifts": min_shifts, "max_shifts": sc.ndays},
            "pto_dates": pto, "rto_dates": [],
            "shift_restrictions": [{"date": d, "forbidden_shifts": ["night"]} for d in nights],
            "buffer_start_days": 0, "buffer_end_days": 0, "pinned_shifts": [],
            "preferences": {}, "continues_into_next": True,
            "context_window": cw, "blocked_night_weekdays": [], "didactics_weekdays": [],
        }
    return out


def _solve(sc: Scenario, resident_data: dict, time_limit_s: int = 10, first_solution: bool = False):
    """Build + solve the real model. ``first_solution`` stops at the first feasible
    assignment (no optimization) — the IIS/verify feasibility checks only need
    'does a feasible schedule exist?', so this keeps the many re-solves fast."""
    s = create_single_solver(_CONFIG, extra_factories=resolve_extra_factories_for_norms(EM_NORMS))
    dts = _block_dates(sc)
    s.block_metadata = {"block_number": 1, "start_date": dts[0].isoformat(),
                        "end_date": dts[-1].isoformat(), "program": "EM"}
    s.resident_data = resident_data
    s.build_model()
    s.solver.parameters.max_time_in_seconds = time_limit_s
    s.solver.parameters.num_workers = 1
    s.solver.parameters.log_search_progress = False
    s.solver.parameters.log_to_stdout = False  # keep MCP stdio clean (logs → stderr)
    if first_solution:
        s.solver.parameters.stop_after_first_solution = True
    return s, s.solve()


def _parse_var(name: str) -> tuple[int, str, str]:
    """``x_r{idx}_si{shift_instance_id}_d{iso}`` → (resident_idx, shift_instance_id, iso)."""
    p = name.split("_")
    return int(p[1][1:]), p[2][2:], p[3][1:]


def _reason_for(sc: Scenario, r: ResidentSpec, d_iso: str) -> str:
    if d_iso in r.pto:
        return sc.pto_label
    if d_iso in r.night_restricted:
        return sc.night_label
    return "blocked"


def _parse_candidates(candidate_ids: list[str]) -> dict[str, Any]:
    """Map relaxation candidate ids to the ``relax`` spec ``_resident_data`` expects.
    Ids: ``free:{idx}:{iso}`` (cancel that resident's PTO/night on the date) and
    ``minshift:{idx}`` (drop that resident's min_shifts floor). Centralized so verify,
    demo_payload and the IIS never hand-split ids (the no-date form breaks a 3-way split)."""
    relax: dict[str, Any] = {"free": {}, "min0": set()}
    for cid in candidate_ids:
        parts = cid.split(":")
        kind = parts[0]
        if kind == "free":
            relax["free"].setdefault(int(parts[1]), set()).add(parts[2])
        elif kind == "minshift":
            relax["min0"].add(int(parts[1]))
        else:
            raise ValueError(f"unknown relaxation candidate id: {cid!r}")
    return relax


def _candidate_label(sc: Scenario, cid: str) -> str:
    parts = cid.split(":")
    if parts[0] == "free":
        r = sc.residents[int(parts[1])]
        d = parts[2]
        if d in r.pto:
            return f"Cancel {r.name}'s {sc.pto_label} on {d}"
        if d in r.night_restricted:
            return f"Lift {r.name}'s {sc.night_label} on {d}"
        return f"Free {r.name} on {d}"
    if parts[0] == "minshift":
        return f"Lower {sc.residents[int(parts[1])].name}'s minimum-shifts requirement"
    return cid


# ---------------------------------------------------------------------------
# Diagnose / candidates / verify  (the MCP tool bodies call these)
# ---------------------------------------------------------------------------


def diagnose(scenario_id: str) -> dict[str, Any]:
    """Build + solve the real model. On INFEASIBLE, localize the unstaffable
    coverage cell(s) and return a structured report + a CLOSED candidate set.

    Always returns ``{"report": {...}, "candidates": [...]}``."""
    sc = SCENARIOS[scenario_id]
    s, result = _solve(sc, _resident_data(sc))

    if result.feasible:
        return {"report": {"scenario": scenario_id, "infeasible": False, "localized": False,
                           "status": result.status,
                           "message": "Schedule is feasible — nothing to diagnose."},
                "candidates": []}

    proto = s.model.proto
    forced = _forced_values(proto)
    names = [v.name for v in proto.variables]
    cov_idx = _unsatisfiable_coverage_linears(proto, forced)

    if not cov_idx:
        # Emergent / aggregate infeasibility — no single forced-empty cell. Hand off to
        # the relaxation/IIS search, which localizes the minimal binding set by
        # re-solving under candidate relaxations. Lazy import breaks the import cycle.
        from .iis import search_infeasibility

        return search_infeasibility(scenario_id)

    cells: list[dict[str, Any]] = []
    blocked_pairs: set[tuple[int, str]] = set()
    for ci in cov_idx:
        c = proto.constraints[ci]
        need = list(c.linear.domain)[0]
        si_id = d_iso = None
        blocked = []
        for v in c.linear.vars:
            r_idx, si_id, d_iso = _parse_var(names[v])
            r = sc.residents[r_idx]
            blocked.append({"resident": r.name, "level": (sc.role_label or r.level),
                            "reason": _reason_for(sc, r, d_iso)})
            blocked_pairs.add((r_idx, d_iso))
        cells.append({"shift_instance": si_id, "date": d_iso, "needs": need, "blocked": blocked})

    report = {
        "scenario": scenario_id,
        "description": sc.description,
        "infeasible": True,
        "localized": True,
        "status": result.status,
        "primitive": "linear_coverage",
        "constraint_rule": "At least N residents must staff this shift (coverage floor)",
        "unstaffable_cells": cells,
    }
    return {"report": report, "candidates": _generate_candidates(sc, blocked_pairs)}


def _generate_candidates(sc: Scenario, blocked_pairs: set[tuple[int, str]]) -> list[dict[str, Any]]:
    """One relaxation per (blocked resident, date): free them for night on that date.
    Stable IDs (``free:{idx}:{iso}``) — the LLM only ever ranks these; never invents one.
    Labels go through ``_candidate_label`` so they respect the scenario's vocabulary
    (residency PTO/didactics vs. faculty sabbatical/protected-time)."""
    cands = []
    for r_idx, d_iso in sorted(blocked_pairs):
        r = sc.residents[r_idx]
        cid = f"free:{r_idx}:{d_iso}"
        cands.append({"id": cid, "label": _candidate_label(sc, cid),
                      "resident": r.name, "level": (sc.role_label or r.level), "date": d_iso})
    return cands


def verify(scenario_id: str, candidate_ids: list[str]) -> dict[str, Any]:
    """Apply candidate relaxation(s) by ID, re-solve the real model, report
    feasibility. On feasible, include the resulting schedule for the relaxed date(s) —
    or the full block when the relaxation carries no date (e.g. a min-shift drop)."""
    sc = SCENARIOS[scenario_id]
    relax = _parse_candidates(candidate_ids)
    trap_dates = {d for dates in relax["free"].values() for d in dates}

    s, result = _solve(sc, _resident_data(sc, relax=relax), first_solution=True)
    out: dict[str, Any] = {"applied": list(candidate_ids), "feasible": result.feasible,
                           "status": result.status}
    if result.feasible:
        entries = s._get_schedule_entries()
        out["schedule"] = [e for e in entries if e["date"] in trap_dates] if trap_dates else entries
    return out


# ---------------------------------------------------------------------------
# Demo packaging — one call for the before/after calendar UI (/demo route)
# ---------------------------------------------------------------------------


def _full_schedule(scenario_id: str, candidate_ids: list[str]) -> list[dict] | None:
    """Solve with the given relaxation candidate(s) applied and return the FULL block
    schedule (all dates), or None if still infeasible. Solves to OPTIMAL (not
    first-feasible): this feeds the /demo 'after' calendar a prospect sees, so the
    wellbeing/balance/preference tiers must run for a balanced grid. Called once and
    cached, so the extra solve time is paid only on the first /demo hit."""
    sc = SCENARIOS[scenario_id]
    s, result = _solve(sc, _resident_data(sc, relax=_parse_candidates(candidate_ids)))
    return s._get_schedule_entries() if result.feasible else None


def _minimal_verified_fix(scenario_id: str, candidates: list[dict]) -> list[str]:
    """Greedily add candidates (in solver-authorized order) until verify is feasible —
    the deterministic analogue of the agent's compose-until-feasible loop, so the UI
    never depends on an LLM call."""
    chosen: list[str] = []
    for c in candidates:
        chosen.append(c["id"])
        if verify(scenario_id, chosen)["feasible"]:
            break
    return chosen


def certify_minimal(scenario_id: str, fix_ids: list[str]) -> dict[str, Any]:
    """Certificate of irreducibility — PROVE the fix is both sufficient and minimal by
    re-solving. ``sufficient`` = applying the whole fix is feasible. For each element we
    re-solve the fix WITHOUT it: if that's infeasible, the element is necessary. The fix is
    ``proven_minimal`` iff it's sufficient and every element is necessary. These are the
    re-solves the deletion-filter implies, captured so a human/judge sees the proof, not an
    LLM's word. ``resolves`` = number of CP-SAT solves the certificate cost."""
    sc = SCENARIOS[scenario_id]
    fix_ids = list(fix_ids)
    sufficient = bool(fix_ids) and verify(scenario_id, fix_ids)["feasible"]
    necessity = []
    for c in fix_ids:
        without = [x for x in fix_ids if x != c]
        stays_feasible = verify(scenario_id, without)["feasible"]
        necessity.append({"id": c, "label": _candidate_label(sc, c),
                          "removing_it_stays_feasible": stays_feasible})
    proven_minimal = sufficient and all(not n["removing_it_stays_feasible"] for n in necessity)
    return {
        "fix": [{"id": c, "label": _candidate_label(sc, c)} for c in fix_ids],
        "sufficient": sufficient,
        "necessity": necessity,
        "proven_minimal": proven_minimal,
        "resolves": 1 + len(fix_ids),
    }


def demo_payload(scenario_id: str) -> dict[str, Any]:
    """Everything the before/after calendar needs, in one deterministic call: the
    grid shape, the unstaffable gap (BEFORE), a minimal VERIFIED fix, and the
    resulting full-block schedule (AFTER)."""
    sc = SCENARIOS[scenario_id]
    diag = diagnose(scenario_id)
    rep, candidates = diag["report"], diag["candidates"]
    base = {
        "scenario": scenario_id,
        "description": sc.description,
        "block_start": sc.block_start,
        "ndays": sc.ndays,
        "dates": [d.isoformat() for d in _block_dates(sc)],
        "shifts": [{"id": si.id, "code": si.code, "location": si.location_id,
                    "is_night": si.is_night} for si in _CONFIG.shift_instances],
        "residents": [{"idx": i, "name": r.name, "level": (sc.role_label or r.level)}
                      for i, r in enumerate(sc.residents)],
    }
    if not rep.get("localized"):
        return {**base, "localized": False, "message": rep.get("message", "Not localized.")}

    if rep.get("emergent"):
        # No single empty cell — the gap-cell calendar doesn't apply. Degrade to the
        # narrative + the verified minimal fix (the emergent case is shown via the agent
        # dev-ui; this keeps /demo/data safe and informative if pointed at the scenario).
        em_fix_ids = [f["id"] for f in rep.get("minimal_fix", [])]
        return {
            **base, "localized": False, "emergent": True,
            "message": rep.get("message", ""),
            "binding_categories": rep.get("binding_categories", []),
            "category_sweep": rep.get("category_sweep", {}),
            "fix_labels": [f["label"] for f in rep.get("minimal_fix", [])],
            "after_schedule": _full_schedule(scenario_id, em_fix_ids) or [],
        }

    fix_ids = _minimal_verified_fix(scenario_id, candidates)
    chosen = set(fix_ids)
    return {
        **base,
        "localized": True,
        "gap_cells": rep["unstaffable_cells"],          # BEFORE: unstaffable (shift_instance, date, blocked[])
        "fix_ids": fix_ids,
        "fix_labels": [c["label"] for c in candidates if c["id"] in chosen],
        "certificate": certify_minimal(scenario_id, fix_ids),  # proof the fix is minimal
        "after_schedule": _full_schedule(scenario_id, fix_ids) or [],  # AFTER: full feasible block
    }

