# Case study — diagnosing an "unsolvable" residency schedule with a neuro-symbolic agent

*(Anonymized. Real specifics are kept in the team's private notes.)*

> **This is a retrospective analysis.** The block was originally resolved by hand at the
> time. Pointed at the same block afterward, the agent reproduced the diagnosis and a
> solver-verified fix in seconds — entirely read-only. Nothing here was applied to a
> production schedule; the value shown is turning an after-the-fact "why was that
> unsolvable?" into a verified answer in seconds instead of engineer-hours.

## The problem

An Emergency Medicine residency program runs a constraint solver to build each ~4-week
schedule "block." For one block — **14 residents, 28 days** — the solver returned a flat
**`INFEASIBLE`**. No schedule could be produced, and the tool gave no actionable reason:
no "this shift is empty," no "this rule failed." Just: it can't be solved.

This is the worst kind of failure for a chief resident or associate program director. The
block *looks* fine — every shift has eligible residents, everyone's time-off looks
reasonable — yet nothing tried by hand resolves it, because the real cause isn't visible to
the eye.

## Why it's genuinely hard

The infeasibility is **emergent**: there is no single empty shift or single broken rule to
point at. It exists only as an *interaction* of three things across all 14 residents and 28
days at once:

1. **Exact shift targets** — each resident has a fixed number of shifts to work this block
   (not a soft minimum). All 14 targets must be hit.
2. **Coverage floors** — every required shift-cell (day/night, each pod) must be staffed.
3. **Availability** — residents can only work days they're free (not on approved or
   requested time off), one shift per day, with mandatory rest after nights.

No assignment satisfies all three at once — but you cannot see that by inspection, and a
static "find the empty cell" check finds nothing. A tempting wrong answer was available,
too: one resident had a suspicious data value. But **fixing that alone does not make the
block solvable** — it's a red herring.

## The approach — neuro-symbolic, solver-verified

The agent pairs an LLM (translation + ranking) with the **OR-Tools CP-SAT solver as ground
truth**. It never *guesses* a fix. To explain an emergent infeasibility it runs a
**relaxation / IIS search** (irreducible-infeasible-subset style): relax candidate groups of
constraints, **re-solve**, and keep only the relaxations whose removal restores
infeasibility — deletion-filtering down to the *minimal* set that matters. Every step is a
real solve, so every claim is verified, not asserted.

## The result — 47 re-solves, 25 seconds

The agent isolated the bottleneck from *all* of the block's time-off and targets down to
**just 2 of the 14 residents**, and produced **two minimal, solver-verified fixes** — each
exactly two changes (remove any single one and it's infeasible again):

- **Option A — decline two time-off *requests*** (two specific resident-days). These were
  *requested*, not approved — the least operationally disruptive fix.
- **Option B — relax two residents' shift targets** (let them work slightly fewer this block).

It also correctly **ruled out the red herring**: the suspicious data value, fixed on its own,
leaves the block infeasible — a second resident is independently implicated.

### What was actually going on

A **coupled over-constraint**, not one isolated cause:
- One resident's target was *razor-tight* against their available days; their time-off pushed
  it over the edge (the classic "can't hit the target and take the day off" bind).
- The other was individually loose on shifts but pivotal to **coverage on a single day** —
  with everyone else locked to their exact targets, only they could fill a particular cell.

Both fixes work because each injects a little **slack** into a globally tight system — one
adds an available day, the other relaxes a rigid target.

## Why it matters

This turns *"INFEASIBLE — good luck"* into *"here are the two smallest changes that make it
solvable, and we re-solved to prove each one works."* For a chief resident or associate
program director that's the difference between hours of trial-and-error (or silently
over-riding the solver) and a two-line, defensible decision.

- **Verified, not hallucinated** — the solver confirms every proposed fix.
- **Minimal & ranked** — smallest changes first, ordered by real-world disruption.
- **Read-only & safe** — the agent *diagnoses*; a human applies the fix. It never edits the
  production schedule.
- **Generalizes** — the same engine handles clean single-shift gaps and these emergent,
  many-cause infeasibilities alike, and applies to any regulated scheduling domain.

## How it was validated

Run **retrospectively** against the data from the real failing block (anonymized, read-only),
on the same solver build that produced the failure. The baseline infeasibility was reproduced,
the fixes were verified by re-solving, and minimality was confirmed by the deletion filter
(removing any single element of a fix restores infeasibility). Nothing was written back to a
production schedule.
