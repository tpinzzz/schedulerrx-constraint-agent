# Evaluation

Three hand-constructed infeasibility variants of the toy model. For each we check:

1. **Localization** — does the agent identify the correct failing constraint?
2. **Explanation** — does the English name the blocked variables and their reasons?
3. **Suggestions** — are the proposed relaxations actually viable?
4. **Verification** — does re-solving confirm feasibility for the surfaced fixes, and
   reject the ones that don't actually work?

All results below are **derived from real** agent output (`python main.py --run <scenario>`,
which prints the full JSON result — rendered into tables here). Run in offline-template
mode; the live Gemini explanation reads more naturally, but the symbolic results —
localization, candidates, verification — are identical because they are deterministic.

Reproduce: `python main.py --run block_12` · `--run eval_single_senior` · `--run eval_pigeonhole`.

---

## Variant 1 — `block_12` (primary demo, "obvious")

The Block 12 analog. Day 7 night shift: four seniors pre-assigned away, two PGY-1s
ineligible to solo night.

| Check | Result |
|---|---|
| Localization | ✅ `bool_or` at proto index **192**; solver-reported `#192` cross-validated (proven during initial copy) |
| Explanation | ✅ Names all six residents and the four distinct reasons (2× vacation, conference, admin, 2× PGY-1 policy) |
| Suggestions | ✅ 5 candidates generated symbolically (4 pre-assignment cancellations + 1 policy relaxation) |
| Verification | ✅ 4 cancellations re-solve **feasible**; the PGY-1 relaxation re-solves **INFEASIBLE** and is correctly badged ✗ |

Verified fix (auto-applied, highest-ranked feasible): **cancel carol's vacation, day 7** →
resulting day-7 schedule `{day: bob, swing: alice, night: carol}`.

**Why the PGY-1 relaxation is caught:** allowing a PGY-1 to solo night frees alice and
bob for the night slot, but day 7 still has only **two** available residents
(alice, bob) for **three** shifts — a coverage pigeonhole. The re-solve returns
INFEASIBLE, so the suggestion never reaches the user as a "fix." This is the
neuro-symbolic guardrail working on a real, plausible-but-insufficient suggestion.

---

## Variant 2 — `eval_single_senior` ("obvious")

Same trap structure on **day 10**, with a different mix of block reasons (admin,
vacation, vacation, conference) to confirm the diagnosis isn't hard-coded to Block 12.

| Check | Result |
|---|---|
| Localization | ✅ `bool_or` at proto index **198**; reported `#198` cross-validated |
| Explanation | ✅ Names all six residents; reasons map correctly to each |
| Suggestions | ✅ 5 candidates |
| Verification | ✅ 4 cancellations feasible; PGY-1 relaxation correctly caught INFEASIBLE |

Verified fix: **cancel dave's vacation, day 10** → `{day: bob, swing: alice, night: dave}`.

---

## Variant 3 — `eval_pigeonhole` ("ambiguous" / honest-limit case)

Day 3 is over-constrained, but the infeasibility is a **coverage pigeonhole** (only
two residents left for three shifts), *not* a single all-false `bool_or`.

| Check | Result |
|---|---|
| Localization | ✅ (correct behavior) Agent reports infeasible but **declines to localize** — the failure is not a single bool_or |
| Explanation | ✅ States the honest scope limit instead of inventing a bool_or explanation |
| Suggestions | ✅ None offered (correct — no bool_or to relax) |
| Verification | n/a |

This is the most important *negative* result: when the infeasibility has a structure
the prototype doesn't translate (only `bool_or` is wired end-to-end; the other four
CP-SAT Boolean primitives each need a detection branch + candidate generator), the agent
**does not hallucinate**.
It says so. The solver-reported number here (`#15`) does *not* point at a bool_or, and
the proto scan finds no all-false bool_or — so the agent abstains. An LLM-only system
would happily fabricate a confident, wrong explanation.

---

## Summary

| Scenario | Localize | Explain | Suggest | Verify | Overall |
|---|---|---|---|---|---|
| `block_12` | ✅ #192 | ✅ | ✅ 5 | ✅ 4✓ / 1✗ | **Pass** |
| `eval_single_senior` | ✅ #198 | ✅ | ✅ 5 | ✅ 4✓ / 1✗ | **Pass** |
| `eval_pigeonhole` | ✅ declines | ✅ | ✅ none | n/a | **Pass (abstains correctly)** |

Two findings worth highlighting in the writeup:

- **The verification step earns its keep.** In both localized variants, a confidently
  plausible relaxation (relax the PGY-1 supervision rule) is *insufficient* and is
  caught by re-solving. Surfacing only re-verified fixes is not decoration — it
  changes what the user is shown.
- **The agent knows the edge of its competence.** The pigeonhole variant proves the
  symbolic layer prevents the LLM from being asked to explain something it can't
  ground, rather than letting it improvise.
