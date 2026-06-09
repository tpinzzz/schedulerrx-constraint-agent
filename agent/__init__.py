"""SchedulerRX Constraint Debugger Agent.

A neuro-symbolic agent that turns a CP-SAT ``INFEASIBLE`` into a plain-English diagnosis
and solver-VERIFIED relaxation fixes. The production OR-Tools CP-SAT solver is ground truth
(``realsolver.py``, over a vendored snapshot); a Gemini LlmAgent (Google ADK) drives the
symbolic MCP tools (``mcp_server.py`` — ``diagnose_schedule`` + ``verify_relaxation``), and
every fix is re-solved before it is shown. For *emergent* infeasibilities (no single empty
cell) a relaxation/IIS search (``iis.py``) finds the minimal binding set.

The symbolic layers structurally bound the LLM: it can only rank relaxation candidates the
solver authored, and every surfaced recommendation has been re-solved to feasibility first.
Deployed on Cloud Run with Gemini on Vertex AI (``server.py`` / ``adk_app/``).
"""

__version__ = "0.2.0"
