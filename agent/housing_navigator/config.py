"""Runtime configuration, all overridable through environment variables."""

import os

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
DATASET = os.environ.get("A4I_DATASET", "a4i_housing")
BQ_LOCATION = os.environ.get("A4I_LOCATION", "US")
METRO = os.environ.get("A4I_METRO", "San Francisco")
STATE_CODE = os.environ.get("A4I_STATE_CODE", "CA")

# AI.EMBED settings. Must match the model used to build the embedded tables.
# Leave the connection empty to embed with the caller's own credentials
# (how the team's complaint_embeddings table was built).
EMBED_CONNECTION = os.environ.get("A4I_EMBED_CONNECTION", "")
EMBED_ENDPOINT = os.environ.get("A4I_EMBED_ENDPOINT", "text-embedding-005")
COMPLAINTS_EMBEDDED_TABLE = os.environ.get("A4I_COMPLAINTS_EMBEDDED", "complaint_embeddings")

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

# Google-managed BigQuery MCP server (remote, streamable HTTP).
ENABLE_BQ_MCP = os.environ.get("ENABLE_BQ_MCP", "true").lower() in ("1", "true", "yes")
BQ_MCP_URL = os.environ.get("BQ_MCP_URL", "https://bigquery.googleapis.com/mcp")


def table(name: str) -> str:
    """Fully-qualified, backtick-quoted table reference."""
    if not PROJECT:
        raise RuntimeError("GOOGLE_CLOUD_PROJECT is not set.")
    return f"`{PROJECT}.{DATASET}.{name}`"
