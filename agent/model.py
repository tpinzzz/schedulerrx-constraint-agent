"""Toy CP-SAT scheduling model for the constraint debugger.

This is a deliberately small EM-residency block (6 residents, 14 days, 3 shifts)
that reproduces the "Block 12" infeasibility: a day whose night shift cannot be
staffed because every eligible resident is blocked for a different reason.

The model is a *proxy*. The contribution is the architecture around it — in
particular the variable-naming convention, which carries semantic meaning so the
LLM has natural-language context to reason about instead of opaque indices:

    user_{resident}_works_{shift}_on_day_{day}

Because the variable name self-documents, the diagnostic layer can look up a
solver literal by index and get a human-readable string for free — no
constraint-name-to-English dictionary required.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field, replace
from typing import Any

from ortools.sat.python import cp_model

# ---------------------------------------------------------------------------
# Domain
# ---------------------------------------------------------------------------

DEFAULT_HORIZON = 14
DEFAULT_SHIFT_TYPES = ("day", "swing", "night")

# Block-reason tags attached to forced-false work variables. These are produced
# symbolically by the model builder (not by the LLM) and feed both the diagnostic
# report and the relaxation-candidate generator.
REASON_PGY1_NIGHT = "pgy1_ineligible_solo_night"


def preassign_reason(ptype: str) -> str:
    return f"{ptype}_preassigned"


# Human-readable gloss for each block reason, used in the structured report.
REASON_GLOSS = {
    REASON_PGY1_NIGHT: "PGY-1 resident, ineligible to solo the night shift per program policy",
    "vacation_preassigned": "on vacation (pre-assigned, day blocked)",
    "conference_preassigned": "at a conference (pre-assigned, day blocked)",
    "admin_preassigned": "on administrative duty (pre-assigned, day blocked)",
}


def work_var_name(resident: str, shift: str, day: int) -> str:
    """The semantic variable-naming convention. Single source of truth."""
    return f"user_{resident}_works_{shift}_on_day_{day}"


# ---------------------------------------------------------------------------
# Problem specification (the thing relaxations mutate)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Resident:
    name: str
    level: str  # "PGY-1" | "PGY-2" | "PGY-3" | "Chief"


@dataclass(frozen=True)
class Preassignment:
    resident: str
    ptype: str  # "vacation" | "conference" | "admin"
    day: int


@dataclass
class SchedulingProblem:
    """A complete, immutable-by-convention scenario definition.

    Relaxations are expressed as *new* SchedulingProblem instances (see
    ``apply_relaxation``), never as in-place proto mutation. That keeps verify
    deterministic and makes "we only re-solve real models" literally true.
    """

    name: str
    description: str
    residents: list[Resident]
    preassignments: list[Preassignment]
    horizon: int = DEFAULT_HORIZON
    shift_types: tuple[str, ...] = DEFAULT_SHIFT_TYPES
    pgy1_can_solo_night: bool = False

    # ---- serialization (so the problem can cross the MCP boundary as JSON) ----
    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "residents": [{"name": r.name, "level": r.level} for r in self.residents],
            "preassignments": [
                {"resident": p.resident, "ptype": p.ptype, "day": p.day}
                for p in self.preassignments
            ],
            "horizon": self.horizon,
            "shift_types": list(self.shift_types),
            "pgy1_can_solo_night": self.pgy1_can_solo_night,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SchedulingProblem":
        return cls(
            name=d["name"],
            description=d.get("description", ""),
            residents=[Resident(**r) for r in d["residents"]],
            preassignments=[Preassignment(**p) for p in d["preassignments"]],
            horizon=d.get("horizon", DEFAULT_HORIZON),
            shift_types=tuple(d.get("shift_types", DEFAULT_SHIFT_TYPES)),
            pgy1_can_solo_night=d.get("pgy1_can_solo_night", False),
        )


# ---------------------------------------------------------------------------
# Built model (vars + symbolic metadata the diagnostic layer consumes)
# ---------------------------------------------------------------------------


@dataclass
class BuiltModel:
    model: cp_model.CpModel
    work: dict[tuple[str, str, int], cp_model.IntVar]
    name_to_info: dict[str, dict[str, Any]]  # var name -> {resident, shift, day, level}
    block_reasons: dict[str, str]  # var name -> reason tag (only forced-false vars)
    problem: SchedulingProblem


def build_model(problem: SchedulingProblem) -> BuiltModel:
    """Construct the CP-SAT model and the symbolic metadata around it.

    Hard constraints:
      C1  each shift each day staffed by exactly one resident
            -> modelled as bool_or(>=1) + at_most_one(<=1) so the failure
               surfaces as a bool_or ("at least one must be true") primitive
      C2  no resident works two shifts in one day
      C3  PGY-1 cannot solo the night shift (with exactly-1 coverage this means
            a PGY-1 can never take night) -> forced false
      C4  vacation/conference/admin pre-assignments are hard (block the whole day)
    C5 (weekly 60h cap) is informational for the Block 12 analog and omitted.
    """
    model = cp_model.CpModel()
    work: dict[tuple[str, str, int], cp_model.IntVar] = {}
    name_to_info: dict[str, dict[str, Any]] = {}
    block_reasons: dict[str, str] = {}

    days = range(1, problem.horizon + 1)

    for r in problem.residents:
        for s in problem.shift_types:
            for d in days:
                name = work_var_name(r.name, s, d)
                v = model.new_bool_var(name)
                work[(r.name, s, d)] = v
                name_to_info[name] = {
                    "resident": r.name,
                    "shift": s,
                    "day": d,
                    "level": r.level,
                }

    # C4 — pre-assignments block every shift that day (most specific reason wins).
    for pa in problem.preassignments:
        for s in problem.shift_types:
            key = (pa.resident, s, pa.day)
            if key not in work:
                continue
            model.add(work[key] == 0)
            block_reasons[work_var_name(pa.resident, s, pa.day)] = preassign_reason(pa.ptype)

    # C3 — PGY-1 cannot solo night.
    if not problem.pgy1_can_solo_night:
        for r in problem.residents:
            if r.level == "PGY-1":
                for d in days:
                    name = work_var_name(r.name, "night", d)
                    model.add(work[(r.name, "night", d)] == 0)
                    block_reasons.setdefault(name, REASON_PGY1_NIGHT)

    # C2 — no resident works two shifts in one day.
    for r in problem.residents:
        for d in days:
            model.add_at_most_one([work[(r.name, s, d)] for s in problem.shift_types])

    # C1 — exactly-one coverage per shift per day = bool_or + at_most_one.
    for s in problem.shift_types:
        for d in days:
            lits = [work[(r.name, s, d)] for r in problem.residents]
            model.add_bool_or(lits)
            model.add_at_most_one(lits)

    return BuiltModel(
        model=model,
        work=work,
        name_to_info=name_to_info,
        block_reasons=block_reasons,
        problem=problem,
    )


# ---------------------------------------------------------------------------
# Relaxations — expressed as problem mutations, applied *by ID* (never by parsing
# free text). The set of legal actions is bounded symbolically; see
# verify.generate_candidates.
# ---------------------------------------------------------------------------


def apply_relaxation(problem: SchedulingProblem, action: dict[str, Any]) -> SchedulingProblem:
    """Return a NEW problem with the relaxation applied. Pure; does not mutate input."""
    atype = action["type"]

    if atype == "remove_preassignment":
        keep = [
            p
            for p in problem.preassignments
            if not (
                p.resident == action["resident"]
                and p.ptype == action["ptype"]
                and p.day == action["day"]
            )
        ]
        return replace(problem, preassignments=copy.deepcopy(keep))

    if atype == "relax_pgy1_night_rule":
        return replace(problem, pgy1_can_solo_night=True)

    raise ValueError(f"Unknown relaxation action type: {atype!r}")


# ---------------------------------------------------------------------------
# Scenario registry — named problems the CLI / web / MCP tools can load by name.
# ---------------------------------------------------------------------------

# All names are fictional and illustrative — this is a toy model, not a real roster.
_BLOCK_12_RESIDENTS = [
    Resident("alice", "PGY-1"),
    Resident("bob", "PGY-1"),
    Resident("carol", "PGY-2"),
    Resident("dave", "PGY-2"),
    Resident("erin", "PGY-3"),
    Resident("dr_frank", "Chief"),
]


def _block_12() -> SchedulingProblem:
    return SchedulingProblem(
        name="block_12",
        description=(
            "Block 12 analog (a real EM-residency block, anonymized). Day 7 night shift "
            "cannot be staffed: two residents on vacation, one at a conference, one on "
            "admin duty, and the two remaining residents are PGY-1s who cannot solo night."
        ),
        residents=list(_BLOCK_12_RESIDENTS),
        preassignments=[
            Preassignment("carol", "vacation", 7),
            Preassignment("dave", "vacation", 7),
            Preassignment("erin", "conference", 7),
            Preassignment("dr_frank", "admin", 7),
        ],
    )


def _eval_pigeonhole() -> SchedulingProblem:
    """Edge variant (honest-limitation case): day 3 is over-constrained, but the
    infeasibility is a *coverage pigeonhole* (only two residents left for three
    shifts), NOT a single all-false bool_or. The agent should recognize this is
    outside its current bool_or translation scope and decline rather than
    hallucinate an explanation. Three seniors + one PGY-1 blocked on day 3 leaves
    only bob (PGY-1) and dr_frank, and bob cannot take night."""
    return SchedulingProblem(
        name="eval_pigeonhole",
        description="Day 3 over-constrained via a coverage pigeonhole (out of bool_or scope).",
        residents=list(_BLOCK_12_RESIDENTS),
        preassignments=[
            Preassignment("carol", "vacation", 3),
            Preassignment("dave", "conference", 3),
            Preassignment("erin", "admin", 3),
            Preassignment("alice", "vacation", 3),
        ],
    )


def _eval_single_senior() -> SchedulingProblem:
    """Variant: only ONE senior is the linchpin. Three seniors blocked on day 10
    leaving exactly one eligible senior — but that senior is ALSO blocked, so the
    night bool_or is all-false. Removing any single senior's block is sufficient."""
    return SchedulingProblem(
        name="eval_single_senior",
        description="Day 10 night trap with all four seniors blocked by mixed reasons.",
        residents=list(_BLOCK_12_RESIDENTS),
        preassignments=[
            Preassignment("carol", "admin", 10),
            Preassignment("dave", "vacation", 10),
            Preassignment("erin", "vacation", 10),
            Preassignment("dr_frank", "conference", 10),
        ],
    )


_SCENARIOS = {
    "block_12": _block_12,
    "eval_single_senior": _eval_single_senior,
    "eval_pigeonhole": _eval_pigeonhole,
}


def list_scenarios() -> list[str]:
    return list(_SCENARIOS)


def load_problem(scenario: Any) -> SchedulingProblem:
    """Accept a scenario *name* (str, looked up in the registry) or a full problem
    dict (as it would arrive over MCP) and return a SchedulingProblem."""
    if isinstance(scenario, SchedulingProblem):
        return scenario
    if isinstance(scenario, str):
        if scenario not in _SCENARIOS:
            raise KeyError(f"Unknown scenario {scenario!r}; known: {list_scenarios()}")
        return _SCENARIOS[scenario]()
    if isinstance(scenario, dict):
        return SchedulingProblem.from_dict(scenario)
    raise TypeError(f"Cannot load problem from {type(scenario)!r}")
