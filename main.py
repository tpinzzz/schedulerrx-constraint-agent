#!/usr/bin/env python3
"""Local CLI for the SchedulerRX Constraint Debugger — drives the REAL CP-SAT solver.

  python main.py --list                              # known scenarios
  python main.py --diagnose em_block_capacity        # diagnose (proto-scan + IIS fallback) -> JSON
  python main.py --diagnose em_block_gap             # the clean single-gap case
  python main.py --verify em_block_capacity free:4:2026-07-09   # apply relaxation id(s), re-solve

The FULL agent (Gemini-on-Vertex reasoning over the MCP tools) and the before/after demo
calendar run via the deployed Cloud Run service, or locally with `uvicorn server:app`
(then /dev-ui and /demo). Diagnosis/verify here are pure symbolic CP-SAT — no LLM, no network.

Note: requires the vendored production solver snapshot under ./vendor (proprietary; present
in the full build, excluded from the open repo — see README).
"""
from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="SchedulerRX Constraint Debugger (real solver)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--list", action="store_true", help="list known scenarios")
    mode.add_argument("--diagnose", action="store_true", help="diagnose a scenario (default)")
    mode.add_argument("--verify", action="store_true", help="apply relaxation candidate id(s) + re-solve")
    ap.add_argument("scenario", nargs="?", default="em_block_capacity")
    ap.add_argument("candidates", nargs="*", help="relaxation candidate ids (for --verify)")
    args = ap.parse_args(argv)

    from agent import realsolver

    if args.list:
        print(json.dumps(realsolver.list_scenarios(), indent=2))
        return 0
    if args.verify:
        print(json.dumps(realsolver.verify(args.scenario, args.candidates), indent=2, default=str))
        return 0
    print(json.dumps(realsolver.diagnose(args.scenario), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
