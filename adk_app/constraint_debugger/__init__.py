from .agent import root_agent

# Export the agent so it can be discovered by ADK (`adk web` / `adk deploy`).
__all__ = ["root_agent"]
