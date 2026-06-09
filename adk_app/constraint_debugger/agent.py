"""ADK app entrypoint for `adk web` / `adk deploy cloud_run` discovery.

Re-exports the constraint-debugger agent (defined in ``agent/adk_agent.py``) so
ADK's folder-discovery finds ``root_agent`` under an agents-dir (``adk_app/``). Kept
thin and SEPARATE from the ``agent/`` package: the MCP server subprocess imports the
``agent`` package, so the agent definition must not live there (else constructing the
agent would recurse into spawning itself). The McpToolset uses cwd=repo-root, so the
``python -m agent.mcp_server`` subprocess resolves regardless of how ADK launches us.
"""
import os
import sys

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from agent.adk_agent import root_agent  # noqa: E402

__all__ = ["root_agent"]
