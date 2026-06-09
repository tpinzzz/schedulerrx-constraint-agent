"""The symbolic capabilities are exposed as real MCP tools the ADK agent consumes over
stdio. This confirms the server module loads and registers its tools."""
import agent.mcp_server as mcp_server


def test_mcp_server_module_loads_with_tools():
    assert mcp_server.mcp is not None
    # the three symbolic tools the agent drives
    for fn in ("diagnose_schedule", "verify_relaxation", "list_known_scenarios"):
        assert hasattr(mcp_server, fn)
