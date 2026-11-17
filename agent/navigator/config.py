"""Settings for the navigator agent. Every value can be overridden with an env var.

Defaults point at the team lab project, so `adk web agent/` works with no .env file
as long as `gcloud auth application-default login` has been run.
"""

import os

# Gemini through Vertex AI (no API key; uses Application Default Credentials).
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "TRUE")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "qwiklabs-gcp-04-3b4b41069fc3")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-central1")

PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]
DATASET = os.getenv("A4I_DATASET", "a4i_housing")
BQ_LOCATION = os.getenv("A4I_LOCATION", "US")
METRO = os.getenv("A4I_METRO", "San Francisco")

MODEL = os.getenv("A4I_MODEL", "gemini-2.5-flash")

# Must be the same model that built the *_embedded tables: gemini-embedding-2 (3072 dims)
# through the us.a4i-vertex CLOUD_RESOURCE connection, see sql/0*_embed_*.sql.
# A different model gives vectors of a different size or space, and search breaks.
EMBED_ENDPOINT = os.getenv("A4I_EMBED_ENDPOINT", "gemini-embedding-2")
# Empty string = embed with the caller's credentials instead of the connection.
EMBED_CONNECTION = os.getenv("A4I_EMBED_CONNECTION", "us.a4i-vertex")

# Embedding tables built by the vector lane (sql/).
COMPLAINTS_TABLE = os.getenv("A4I_COMPLAINTS_TABLE", "complaints_embedded")
STATUTES_TABLE = os.getenv("A4I_STATUTES_TABLE", "statutes_embedded")
BULLETINS_TABLE = os.getenv("A4I_BULLETINS_TABLE", "bulletins_embedded")

# Multi-agent mode: a coordinator delegates to specialist agents (specialists.py).
# Set to "false" to fall back to the original single navigator agent.
MULTI_AGENT = os.getenv("A4I_MULTI_AGENT", "true").lower() == "true"

# Google-managed BigQuery MCP server (organizer requirement). Set to "false" to run without it.
ENABLE_BQ_MCP = os.getenv("A4I_ENABLE_BQ_MCP", "true").lower() == "true"
BQ_MCP_URL = os.getenv("A4I_BQ_MCP_URL", "https://bigquery.googleapis.com/mcp")


def table(name: str) -> str:
    return f"`{PROJECT}.{DATASET}.{name}`"
