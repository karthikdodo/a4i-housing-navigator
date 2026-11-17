"""Google-managed BigQuery MCP server (organizer requirement: consume one managed MCP server).

Owner: Karthik. Read-only tools only. Auth uses Application Default Credentials, refreshed
per request so long sessions don't hit an expired token.
"""

import google.auth
from google.auth.transport.requests import Request
from google.adk.tools.mcp_tool import McpToolset, StreamableHTTPConnectionParams

from . import config

READ_ONLY_TOOLS = [
    "list_table_ids",
    "get_table_info",
    "execute_sql_readonly",
]

_creds = None


def _auth_headers(_ctx) -> dict[str, str]:
    global _creds
    if _creds is None:
        _creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
    if not _creds.valid:
        _creds.refresh(Request())
    return {
        "Authorization": f"Bearer {_creds.token}",
        "x-goog-user-project": config.PROJECT,
    }


def bigquery_mcp_toolset() -> McpToolset:
    return McpToolset(
        connection_params=StreamableHTTPConnectionParams(url=config.BQ_MCP_URL, timeout=60),
        tool_filter=READ_ONLY_TOOLS,
        header_provider=_auth_headers,
    )


def block_audit_columns_before_brief(tool, args: dict, tool_context):
    """before_tool_callback: audit_* columns may be queried only after the brief exists."""
    if tool.name == "execute_sql_readonly" and "audit_" in str(args).lower():
        if not tool_context.state.get("brief"):
            return {"error": "audit_* columns are for the post-brief equity audit only. "
                             "Submit the brief first."}
    return None
