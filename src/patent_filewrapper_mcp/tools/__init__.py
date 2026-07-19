"""MCP tool registration package (audit F2: main.py God File split).

Each module exposes register(mcp) and holds the tools for one concern.
Registration order matches the historical main.py order so tools/list is
unchanged.
"""


def register_all(mcp, auth_provider=None) -> None:
    """Register every PFW tool on the FastMCP server."""
    from . import admin_tools, document_tools, guidance_tools, oa_tools, search_tools

    admin_tools.register(mcp, auth_provider)
    search_tools.register(mcp)
    document_tools.register(mcp)
    guidance_tools.register(mcp)
    oa_tools.register(mcp)
