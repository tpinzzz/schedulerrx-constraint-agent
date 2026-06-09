"""ADK agent — the neuro-symbolic constraint debugger over the REAL SchedulerRX solver.

A single `LlmAgent` (Gemini 2.5 Flash) that drives the symbolic tools exposed by
`agent.mcp_server` over **stdio MCP**: it diagnoses the INFEASIBLE schedule, explains
it for a coordinator, ranks the solver-authored relaxations, and VERIFIES (re-solves)
before recommending — composing multiple relaxations when a single one is insufficient.
The solver is ground truth; the agent never decides feasibility itself, and may only
act on candidate ids the solver authorized.

Run the dev UI:   adk web .        (from the repo root, pick `agent`)
Headless smoke:    python scratch/run_agent.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

_REPO = Path(__file__).resolve().parent.parent
load_dotenv(_REPO / ".env")  # GOOGLE_API_KEY (AI Studio) for live Gemini

from google.adk.agents import Agent
from google.adk.models import Gemini
from google.genai import types
from google.adk.tools.mcp_tool import McpToolset, StdioConnectionParams
from google.adk.tools.mcp_tool.mcp_session_manager import StdioServerParameters

# Gemini with auto-retry on transient overloads (the 429/503/504 "model is
# experiencing high demand" errors), so a judge poking the live demo never sees a
# transient failure — it backs off and retries instead.
_MODEL = Gemini(
    model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
    retry_options=types.HttpRetryOptions(attempts=4, http_status_codes=[429, 500, 503, 504]),
)

INSTRUCTION = """\
You are a neuro-symbolic scheduling assistant for an Emergency Medicine residency \
program, helping a program COORDINATOR resolve a schedule the solver has proven \
INFEASIBLE. A constraint solver (OR-Tools CP-SAT) is the ground truth — you NEVER \
decide feasibility yourself; you call tools and trust their results.

Tools:
- list_known_scenarios(): scenarios you can work on.
- diagnose_schedule(scenario): runs the real model and returns ONE of two diagnosis \
shapes, plus a CLOSED list of relaxation candidates, each with a stable `id`:
  • A LOCALIZED coverage gap — `unstaffable_cells`: a specific shift on a specific day \
whose every candidate resident is blocked, listing who is blocked and why.
  • An EMERGENT shortfall (`emergent: true`) — there is NO single empty shift; the model \
is infeasible only when coverage, availability and shift-minimums are solved together. \
It includes `category_sweep` (which whole categories, when relaxed, restore \
feasibility), `binding_categories`, and a `minimal_fix` (the smallest set of \
relaxations the search already verified restores feasibility).
- verify_relaxation(scenario, candidate_ids): applies the given relaxation id(s), \
re-solves, and returns feasible true/false (plus the resulting assignments when feasible).

Do this, in order:
1. Call diagnose_schedule for the scenario the user names.
2. EXPLAIN in 2-4 sentences a non-technical coordinator can act on. No solver \
internals, literals, or constraint numbers.
  • Localized: name the specific shift/day that cannot be staffed and the specific \
residents blocked from it, with the reason for each.
  • Emergent: say plainly there is NO single empty shift — it is an aggregate \
availability/capacity shortfall — and report what the search found binding vs. NOT \
binding from `category_sweep` (e.g. "removing PTO restores feasibility, but lowering \
the shift-minimums does not, so the bottleneck is availability, not the minimums").
3. RANK the candidate relaxations from least to most operationally disruptive \
(cancelling a single-day PTO/conference is low; relaxing a safety/supervision policy \
is high and ranks last).
4. VERIFY before recommending — ALWAYS, with your own verify_relaxation call; never \
rely on the diagnosis alone. Call verify_relaxation on your chosen fix and require \
feasible=true before recommending it — this call also returns the resulting \
assignments you will show in step 5. For an EMERGENT diagnosis verify the reported \
`minimal_fix` ids (confirm them yourself even though the search pre-checked them); for \
a LOCALIZED gap verify your top-ranked candidate. If it returns feasible=false it is \
INSUFFICIENT — say so plainly, then try the next, or COMPOSE by calling \
verify_relaxation with multiple ids, until it returns feasible=true. Present ONLY a fix \
verify_relaxation has confirmed feasible.
5. PRESENT: the explanation; the verified fix (the exact relaxation(s) and the \
resulting coverage); and call out any plausible-but-insufficient relaxation you ruled \
out — for emergent cases the category the search PROVED is not the cause is the key \
insight, and it shows the fix was actually checked, not guessed. If the diagnosis \
includes a `certificate` with `proven_minimal: true`, state that the fix is provably \
MINIMAL — the search re-solved removing each element and confirmed each is necessary \
(the solver proves "minimal"; you never just assert it).

HARD RULES:
- Use ONLY candidate `id` values returned by diagnose_schedule (the `minimal_fix` ids \
are drawn from that same closed set). Never invent a relaxation or an id.
- Never state a relaxation fixes the schedule unless verify_relaxation returned \
feasible=true for that exact set.
"""

_toolset = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command=sys.executable,
            args=["-m", "agent.mcp_server"],
            cwd=str(_REPO),
        ),
        # A feasible re-solve takes a few seconds; the default 5s request timeout
        # trips verify_relaxation. Give the solver comfortable headroom.
        timeout=60.0,
    )
)

root_agent = Agent(
    name="constraint_debugger",
    model=_MODEL,
    description="Diagnoses an infeasible EM residency schedule and proposes solver-verified fixes.",
    instruction=INSTRUCTION,
    tools=[_toolset],
)
