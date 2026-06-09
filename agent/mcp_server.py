"""MCP server exposing the symbolic tools — backed by the REAL SchedulerRX solver.

The two deterministic capabilities — running the real CP-SAT model + diagnosing an
INFEASIBLE coverage gap, and applying relaxation(s) then re-solving — are exposed as
Model Context Protocol tools. The ADK agent consumes them via `McpToolset` over
stdio (`python -m agent.mcp_server`), so every diagnosis and every verification
actually traverses the protocol. This is also the seam where a future A2A / external
agent could call the same tools.

Tool bodies delegate to `agent.realsolver`, which builds the production `ShiftSolver`
in-process on a pinned, vendored snapshot (no DB).

    python -m agent.mcp_server   # run standalone over stdio
"""
from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from . import realsolver

mcp = FastMCP(name="schedulerrx-constraint-debugger")


@mcp.tool
def diagnose_schedule(scenario: str) -> dict[str, Any]:
    """Run the real SchedulerRX CP-SAT model on a scenario. If INFEASIBLE, return a
    structured diagnosis — the unstaffable coverage cell(s), which residents are
    blocked from them and why — plus the CLOSED set of relaxation candidates the
    solver authorizes (each with a stable id). `scenario` is a registered scenario
    id from `list_known_scenarios`. The candidate ids are the ONLY actions a caller
    may propose; never invent one."""
    return realsolver.anonymize_pods(realsolver.diagnose(scenario))


@mcp.tool
def verify_relaxation(scenario: str, candidate_ids: list[str]) -> dict[str, Any]:
    """Apply one or more relaxation candidates (by id) to the scenario, re-solve the
    real model, and report whether the schedule becomes feasible — and if so, the
    resulting assignments for the previously-unstaffable date(s). This is the
    verification that gates which fixes may reach a human: an insufficient set of
    relaxations comes back feasible=False and must NOT be presented as a fix."""
    return realsolver.anonymize_pods(realsolver.verify(scenario, candidate_ids))


@mcp.tool
def list_known_scenarios() -> dict[str, Any]:
    """List the scenario ids this server can diagnose, with a short description each."""
    return {"scenarios": realsolver.list_scenarios()}


if __name__ == "__main__":  # pragma: no cover - manual/stdio entry point
    mcp.run()
