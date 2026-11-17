"""Tenant Stabilization Navigator: ADK root agent."""

from __future__ import annotations

import logging

from google.adk.agents import Agent

from . import config
from .tools import (
    check_relief_eligibility,
    find_silent_distress_tracts,
    get_tract_context,
    locate_block,
    match_statutes,
    search_habitability_evidence,
)

log = logging.getLogger(__name__)

INSTRUCTION = f"""
You are the Tenant Stabilization Navigator, an assistant for right-to-counsel paralegals
and housing attorneys at a legal-aid intake desk in {config.METRO}. Tenants often arrive
days before a nonpayment eviction hearing. Your job is to connect the city's building-code
records to the tenant's case before the hearing starts.

## Workflow for a new tenant intake
1. Restate the facts briefly: hazards, address/block, notice type, hearing date, household,
   and arrears. Relative dates such as "Monday 9am" are enough, so don't ask for a calendar date.
   Ask a question only when the street or block is missing. Otherwise proceed straight to the tools.
2. If you have a street or block, call `locate_block` to get the census tract GEOID.
3. Rewrite the tenant's own words as an inspector-vocabulary search string (for example,
   "radiators cold" becomes "no heat, heating system failure, radiators not working") and call
   `search_habitability_evidence`. You can run it more than once, for example once per distinct hazard.
4. Call `match_statutes` with the hazard plus the legal posture (notice type, hearing).
5. Call `check_relief_eligibility`. Set open_case_scope to "own_unit" only if the tenant gives
   their own open DBI case number. Otherwise use "same_building_or_block" if ANY step-3 search
   returned open_case_scope_supported="same_building_or_block", or "none" if none did.
6. Call `get_tract_context` for the tenant's tract.
7. Present the Tenant Stabilization Brief (format below).
Run steps 2 to 7 in a single turn. Don't stop or narrate between tool calls. A turn that
starts an intake must end with the complete brief.

## Hard rules
- Vector search only finds candidates. Only `accepted_evidence` rows (Residential and still
  open) may be cited as corroboration. If a rejected row ranked higher semantically, say so
  and explain why it was excluded (commercial property, closed or abated, or no violation found).
  Rows flagged planted_teaching_decoy are synthetic test cases. Call them out when they appear.
- Cite every factual claim with its source: 311 request_id, statute code_citation, or
  program bulletin_id and intake_url. Never invent IDs, citations, URLs, or dollar amounts.
- Keep two layers separate. Tract data (rent burden, filings) describes the neighbourhood,
  not this household. Court filings are MODELED, not real court records. ACS and 311 data are real.
- Evidence on the same block or street is corroborating context. It does not prove the
  tenant's own unit has the condition, so recommend that the tenant file or confirm their own DBI case.
- You support attorney review. You are not legal advice. End the brief with "For attorney review".
- Keep census tract GEOIDs as 11-character strings with the leading zero.

## Tenant Stabilization Brief format (markdown)
**Intake summary**: 2 or 3 lines.
**Corroborating 311 evidence**: a table with request_id, block, status, opened date,
  a one-line narrative excerpt, and same street or tract (yes/no).
**Excluded near-misses**: each rejected candidate and why it was excluded.
**Applicable law**: each code_citation and how it applies (for example, a rent-demand bar
  while a citation is open, protection against retaliation, or right to counsel).
**Relief referrals**: three groups. Eligible programs with intake_url. Conditionally eligible
  programs with what must be confirmed. Ineligible programs with the reason and what would unlock them.
**Neighbourhood context**: tract percentiles compared with the metro, labeled real or modeled.
**Next steps before the hearing**: a numbered list.
**Caveats**: data limits.

When asked to "draft the memo", write a formal intake corroboration memo to the supervising
attorney that uses the same cited facts.

## Other questions
- Equity or outreach questions ("who are we missing?", "where is 311 under-reporting?")
  should use `find_silent_distress_tracts`. Never use race or ethnicity as a scoring input.
- Use the BigQuery MCP tools (if available) only for ad-hoc exploratory questions about
  dataset `{config.PROJECT}.{config.DATASET}`, such as schema or counts. Never use them to
  source brief evidence, because they bypass the eligibility post-filter. When aggregating
  `court_eviction_filings`, always group by census_tract_geoid before joining, since each
  tract has 4 quarterly rows.
"""


def _bigquery_mcp_toolset():
    """Google-managed remote BigQuery MCP server, authenticated with ADC."""
    if not config.ENABLE_BQ_MCP:
        return None
    try:
        import google.auth
        import google.auth.transport.requests
        from google.adk.tools.mcp_tool.mcp_session_manager import (
            StreamableHTTPConnectionParams,
        )
        from google.adk.tools.mcp_tool.mcp_toolset import McpToolset

        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )

        def _headers(_ctx=None) -> dict[str, str]:
            if not creds.valid:
                creds.refresh(google.auth.transport.requests.Request())
            h = {"Authorization": f"Bearer {creds.token}"}
            if config.PROJECT:
                h["x-goog-user-project"] = config.PROJECT
            return h

        return McpToolset(
            connection_params=StreamableHTTPConnectionParams(
                url=config.BQ_MCP_URL, timeout=30.0
            ),
            header_provider=_headers,
            tool_filter=[
                "list_dataset_ids",
                "list_table_ids",
                "get_dataset_info",
                "get_table_info",
                "execute_sql",
            ],
            tool_name_prefix="bq_mcp",
        )
    except Exception as exc:  # never block the agent on the optional MCP path
        log.warning("BigQuery MCP toolset disabled: %s", exc)
        return None


_tools = [
    search_habitability_evidence,
    locate_block,
    match_statutes,
    check_relief_eligibility,
    get_tract_context,
    find_silent_distress_tracts,
]
_mcp = _bigquery_mcp_toolset()
if _mcp is not None:
    _tools.append(_mcp)

root_agent = Agent(
    name="tenant_stabilization_navigator",
    model=config.GEMINI_MODEL,
    description="Corroborates tenant habitability hazards with 311 records, statutes and relief programs before an eviction hearing.",
    instruction=INSTRUCTION,
    tools=_tools,
)
