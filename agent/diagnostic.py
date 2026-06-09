"""Layer 1 — symbolic diagnostic extraction.

Runs the CP-SAT solver on a scheduling problem. On INFEASIBLE it:

  1. Parses the solver log for the reported failing-constraint number (text parse).
  2. Independently scans the model proto for the bool_or whose literals are *all*
     pinned false — the ground-truth failing constraint (proto API).
  3. Cross-checks (1) against (2). The log number is reliable when infeasibility is
     proven "during initial copy" (numbering matches the original model), but
     presolve can transform it in general; the proto scan makes us robust either way.
  4. Maps each literal index to its semantic variable name and the symbolic reason
     it is pinned false, producing a structured report for the Gemini layer.

Nothing here calls an LLM. This layer is deterministic ground truth.
"""

from __future__ import annotations

import re
from typing import Any

from ortools.sat.python import cp_model

from .model import (
    REASON_GLOSS,
    BuiltModel,
    SchedulingProblem,
    build_model,
    load_problem,
)

# CP-SAT Boolean primitives -> the hand-coded "constraint rule" templates.
# All five rule strings exist, but only bool_or is wired end-to-end (detection in
# _all_false_bool_ors + candidate generation in verify.py). Extending to the others is
# bounded, mechanical work — a detection branch + a candidate generator each (see README
# "Scope"), not a one-liner.
RULE_TEMPLATES = {
    "bool_or": "At least one must be true",
    "bool_and": "All must be true",
    "at_most_one": "At most one can be true",
    "exactly_one": "Exactly one must be true",
    "bool_xor": "An odd number must be true",
}

_REPORTED_NUM_RE = re.compile(r"constraint #(\d+)")


# ---------------------------------------------------------------------------
# Low-level solve (shared with verify.py)
# ---------------------------------------------------------------------------


def solve_built(built: BuiltModel, capture_log: bool = True):
    """Solve a BuiltModel. Returns (status, solver, log_text)."""
    solver = cp_model.CpSolver()
    logs: list[str] = []
    if capture_log:
        solver.parameters.log_search_progress = True
        # Keep the (verbose) solver chatter out of stdout; we read it via callback.
        try:
            solver.parameters.log_to_stdout = False
        except AttributeError:  # pragma: no cover - older ortools
            pass
        solver.log_callback = lambda line: logs.append(line)
    status = solver.solve(built.model)
    return status, solver, "\n".join(logs)


def solve_problem(problem: SchedulingProblem, capture_log: bool = False):
    """Convenience: build + solve a problem. Returns (status, solver, built, log)."""
    built = build_model(problem)
    status, solver, log = solve_built(built, capture_log=capture_log)
    return status, solver, built, log


# ---------------------------------------------------------------------------
# Proto helpers — rigorous, proto-only ground truth
# ---------------------------------------------------------------------------


def _in_domain(value: int, flat_domain: list[int]) -> bool:
    """flat_domain is [lo0, hi0, lo1, hi1, ...]."""
    for i in range(0, len(flat_domain), 2):
        if flat_domain[i] <= value <= flat_domain[i + 1]:
            return True
    return False


def _forced_values(proto) -> dict[int, int]:
    """Return {var_index: fixed_value} for every Boolean variable the model pins to
    a single value, reading ONLY the proto: the variable's own domain plus any
    single-variable (linear1) equality constraint. This is how we know a literal is
    'forced false' without trusting any Python-side bookkeeping."""
    forced: dict[int, int] = {}

    for i, v in enumerate(proto.variables):
        dom = list(v.domain)
        if dom == [0, 0]:
            forced[i] = 0
        elif dom == [1, 1]:
            forced[i] = 1

    for c in proto.constraints:
        if not c.has_linear():
            continue
        if len(getattr(c, "enforcement_literal", [])) > 0:
            continue  # a reified/conditional pin is not an unconditional fixing
        lin = c.linear
        if len(lin.vars) != 1 or len(lin.coeffs) != 1:
            continue
        idx = lin.vars[0]
        coeff = lin.coeffs[0]
        dom = list(lin.domain)
        feasible = [x for x in (0, 1) if _in_domain(coeff * x, dom)]
        if len(feasible) == 1:
            forced[idx] = feasible[0]

    return forced


def _decode_literal(lit: int) -> tuple[int, bool]:
    """CP-SAT literal encoding: l>=0 -> var l (positive); l<0 -> NOT(var -l-1)."""
    if lit >= 0:
        return lit, False
    return -lit - 1, True


def _literal_is_forced_false(lit: int, forced: dict[int, int]) -> bool:
    idx, negated = _decode_literal(lit)
    if idx not in forced:
        return False
    val = forced[idx]
    # NOT(x) is false iff x is true; x is false iff x is forced 0.
    return val == 1 if negated else val == 0


def _all_false_bool_ors(proto, forced: dict[int, int]) -> list[int]:
    """Proto indices of bool_or constraints whose every literal is pinned false."""
    out = []
    for i, c in enumerate(proto.constraints):
        if not c.has_bool_or():
            continue
        if len(getattr(c, "enforcement_literal", [])) > 0:
            continue  # a conditionally-enforced clause is not unconditionally violated
        lits = list(c.bool_or.literals)
        if lits and all(_literal_is_forced_false(l, forced) for l in lits):
            out.append(i)
    return out


def _unsatisfiable_coverage_linears(proto, forced: dict[int, int]) -> list[int]:
    """Proto indices of linear "at least k" coverage constraints whose every
    referenced variable is pinned false — the linear analogue of an all-false
    bool_or.

    SchedulerRX (and most real CP-SAT schedulers) encode shift coverage as
    ``model.Add(sum(cell_vars) >= min_staff)`` — a *linear* constraint, not an
    ``AddBoolOr``. So on the real model the all-false bool_or scan finds nothing;
    this detector localizes the genuine failure: a coverage demand of >= k over a
    set of (resident, shift_instance, date) vars that are ALL forced to 0 (by PTO
    / blackout / shift restriction / pinned-elsewhere). Reuses the same `forced`
    map as `_all_false_bool_ors`. Coverage vars are referenced positively, so a
    direct ``forced[v] == 0`` is the per-var "blocked" test (no literal negation)."""
    out = []
    for i, c in enumerate(proto.constraints):
        if not c.has_linear():
            continue
        if len(getattr(c, "enforcement_literal", [])) > 0:
            continue  # a reified/conditional coverage clause is not unconditionally violated
        lin = c.linear
        vrs = list(lin.vars)
        coeffs = list(lin.coeffs)
        dom = list(lin.domain)
        # unit-coefficient `sum(vars) >= lower`, lower >= 1, every var forced false
        if not vrs or not dom or any(co != 1 for co in coeffs):
            continue
        need = dom[0]
        if need < 1:
            continue
        # Max the sum can reach: a forced var contributes its fixed value, a free
        # var its domain ceiling (1 for a Boolean, higher for an integer count var
        # — so aggregate count constraints aren't mis-flagged). Unsatisfiable when
        # even that maximum can't reach `need`: the "all blocked" case (max 0,
        # need >= 1) and the "understaffed/pigeonhole" case (need 6, only 5
        # Booleans can fill it).
        max_reach = 0
        for v in vrs:
            fv = forced.get(v)
            if fv is not None:
                max_reach += fv
            else:
                dv = list(proto.variables[v].domain)
                max_reach += dv[-1] if dv else 0
        if max_reach < need:
            out.append(i)
    return out


# ---------------------------------------------------------------------------
# The diagnostic
# ---------------------------------------------------------------------------


def diagnose(scenario: Any) -> dict[str, Any]:
    """Diagnose a scenario (name, problem dict, or SchedulingProblem).

    Returns a structured report. When the model is feasible, returns a
    feasibility summary instead (so callers can short-circuit)."""
    problem = load_problem(scenario)
    built = build_model(problem)
    status, solver, log = solve_built(built, capture_log=True)
    status_name = solver.status_name(status)

    if status != cp_model.INFEASIBLE:
        return {
            "scenario": problem.name,
            "status": status_name,
            "infeasible": False,
            "message": f"Model is {status_name}; nothing to diagnose.",
        }

    proto = built.model.proto

    # (1) Text parse: the reported failing-constraint number, plus whether the log
    # says it was proven during the "initial copy" phase (which preserves original
    # constraint numbering).
    reported_number: int | None = None
    proven_during_initial_copy = "during initial copy" in log
    m = _REPORTED_NUM_RE.search(log)
    if m:
        reported_number = int(m.group(1))

    # (2) Proto scan: ground-truth all-false bool_or(s).
    forced = _forced_values(proto)
    all_false = _all_false_bool_ors(proto, forced)

    if not all_false:
        # Out of scope for this prototype: infeasibility not localizable to a
        # single all-false bool_or (only bool_or is translated for the hackathon).
        return {
            "scenario": problem.name,
            "status": status_name,
            "infeasible": True,
            "localized": False,
            "constraint_number_reported": reported_number,
            "message": (
                "Infeasible, but the failure does not reduce to a single "
                "'at least one must be true' (bool_or) constraint. Only bool_or "
                "is translated in this prototype; bool_and / at_most_one / "
                "exactly_one / bool_xor are one-line template additions."
            ),
            "raw_log_excerpt": _log_excerpt(log),
        }

    # (3) Cross-check: prefer the reported number iff it points at an all-false
    # bool_or; otherwise fall back to the proto scan and flag the discrepancy.
    if reported_number in all_false:
        failing_index = reported_number
        matches_proto = True
    else:
        failing_index = all_false[0]
        matches_proto = reported_number == failing_index

    failing = proto.constraints[failing_index]
    rule = RULE_TEMPLATES["bool_or"]

    # (4) Map literals -> semantic names + symbolic block reasons.
    variables_involved = []
    for lit in failing.bool_or.literals:
        idx, negated = _decode_literal(lit)
        name = proto.variables[idx].name
        reason = built.block_reasons.get(name, "unknown")
        info = built.name_to_info.get(name, {})
        variables_involved.append(
            {
                "name": name,
                "current_value": "forced_false",
                "literal_negated": negated,
                "block_reason": reason,
                "block_reason_gloss": REASON_GLOSS.get(reason, reason),
                "resident": info.get("resident"),
                "level": info.get("level"),
                "shift": info.get("shift"),
                "day": info.get("day"),
            }
        )

    note = (
        "The reported number was proven during the solver's INITIAL COPY phase, so "
        "it matches the original model's constraint index. In general, presolve can "
        "transform this number; we cross-validate against the model proto, so the "
        "diagnosis is robust either way."
        if proven_during_initial_copy
        else (
            "Reported numbers can be transformed by presolve and may not match the "
            "original model index. We identify the failing constraint by scanning "
            "the model proto for the bool_or whose literals are all pinned false."
        )
    )

    return {
        "scenario": problem.name,
        "scenario_description": problem.description,
        "status": status_name,
        "infeasible": True,
        "localized": True,
        "constraint_rule": rule,
        "constraint_primitive": "bool_or",
        "constraint_number_reported": reported_number,
        "constraint_number_note": note,
        "failing_constraint_proto_index": failing_index,
        "reported_matches_proto": matches_proto,
        "proven_during_initial_copy": proven_during_initial_copy,
        "all_false_bool_or_indices": all_false,
        "variables_involved": variables_involved,
        "raw_log_excerpt": _log_excerpt(log),
    }


def _log_excerpt(log: str, max_chars: int = 900) -> str:
    """The most relevant slice of the solver log for display (the INFEASIBLE block)."""
    idx = log.find("INFEASIBLE")
    if idx == -1:
        return log[:max_chars]
    start = log.rfind("\n", 0, idx)
    return log[max(0, start) : idx + max_chars].strip()
