from mcp_servers.servers.canvas import server as canvas_server
from mcp_servers.servers.discord import server as discord_server


def test_placeholder_servers_import_cleanly_and_remain_explicitly_empty():
    assert "PLACEHOLDER" in (canvas_server.__doc__ or "")
    assert "PLACEHOLDER" in (discord_server.__doc__ or "")
    assert canvas_server.mcp is not None
    assert discord_server.mcp is not None
