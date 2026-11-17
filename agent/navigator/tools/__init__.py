"""Tool registry. Real tools win; stubs fill in until Prachi's files are merged.

==========================================================================================
FOR PRACHI: how to build, test, and run your tools
==========================================================================================

You own three files in this folder (agent/navigator/tools/):
    match_fund.py      tract_context.py      equity_audit.py
They don't exist yet. Until they do, the agent uses the placeholders in _stubs.py.
Once your file exists, this registry picks it up automatically. Don't edit this file,
agent.py, or prompts.py (Karthik's).

------------------------------------------------------------------------------------------
1. Set up (once, from the repo root)
------------------------------------------------------------------------------------------
    git fetch origin
    git switch -c agent-tools origin/agent-core
    python3 -m venv .venv
    .venv/bin/pip install -r agent/requirements.txt
    gcloud auth application-default login     # sign in with the student-…@qwiklabs.net lab account

------------------------------------------------------------------------------------------
2. Write each tool
------------------------------------------------------------------------------------------
Copy the function from _stubs.py into your file: SAME name, SAME arguments. Then replace
the body with real logic. Rules:

  - Keep the docstring with its `Args:` section. Gemini reads it to decide how to call the tool.
  - Return a dict. On failure return {"error": "..."} instead of raising.
  - Don't include "stub": True (that marks placeholder data in the brief).
  - census_tract_geoid is always a STRING of 11 characters ("06075012502"). Never cast to int:
    the leading zero disappears and every join breaks.
  - court_eviction_filings has 4 quarters per tract: SUM by census_tract_geoid before joining.
  - audit_* columns are allowed ONLY in equity_audit. Never in match_fund or tract_context.

Return shapes the brief reads (submit_brief copies these into the brief JSON):

    match_fund    -> {"funds": [{"program_name", "administering_agency", "eligible": bool,
                                 "why", "requires_open_habitability_case": bool, "intake_url"}]}
                     One entry per SF fund (4). Read caps/flags from rental_relief_program_bulletins.
    tract_context -> {"census_tract_geoid", "severe_rent_burden_pct",
                      "metro_severe_rent_burden_pct", "annual_filings_modeled"}
    equity_audit  -> any JSON dict; the agent summarizes it into the brief's equity_note.

BigQuery from your tool (shared client and table names, same project/dataset as the agent):

    from google.cloud import bigquery
    from .. import config
    from .semantic_search import _bq            # shared, already-configured client

    rows = _bq().query(
        f"SELECT ... FROM {config.table('acs_tract_housing_tenure')} WHERE census_tract_geoid = @g",
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("g", "STRING", census_tract_geoid)]),
    ).result()

------------------------------------------------------------------------------------------
3. Test your tool on its own (fast, no LLM)
------------------------------------------------------------------------------------------
    PYTHONPATH=agent .venv/bin/python -c "
    from navigator.tools import match_fund, tract_context, equity_audit
    print(match_fund(income_pct_ami=45, household_size=3, has_open_habitability_case=True))
    print(tract_context('06075012502'))
    print(equity_audit(['06075012502']))"

The line "tools/<name>.py not found, using STUB" means your file isn't being picked up.
If your file has an error, the import fails loudly (on purpose; it won't fall back to the stub).

------------------------------------------------------------------------------------------
4. Test it inside the agent (chat in the browser)
------------------------------------------------------------------------------------------
    .venv/bin/adk web agent/ --reload_agents        # open http://localhost:8000, pick "navigator"

Click "New Session", then try:
    100 block of Turk St, black mold and no heat. Hearing 2026-11-30. 3 people, 45% AMI, residential.
The left panel shows each tool call and its exact input/output. Your tools are working
when the brief's "stub_tools" list no longer names them. --reload_agents picks up your edits
without a restart (start a new session after each change).

------------------------------------------------------------------------------------------
5. Ship
------------------------------------------------------------------------------------------
    git add agent/navigator/tools/match_fund.py agent/navigator/tools/tract_context.py \
            agent/navigator/tools/equity_audit.py
    git commit -m "Prachi: real match_fund, tract_context, equity_audit"
    git push -u origin agent-tools                   # then open a PR into agent-core
"""

import importlib
import logging

from .locate_block import locate_block
from .resolve_date import resolve_date
from .semantic_search import semantic_search

log = logging.getLogger(__name__)


def _load(name: str):
    try:
        module = importlib.import_module(f".{name}", __name__)
    except ModuleNotFoundError as e:
        if e.name != f"{__name__}.{name}":
            raise  # the real file exists but is broken: fail loudly, don't hide it behind a stub
        log.warning("tools/%s.py not found, using STUB", name)
        module = importlib.import_module("._stubs", __name__)
    return getattr(module, name)


match_fund = _load("match_fund")
tract_context = _load("tract_context")
equity_audit = _load("equity_audit")

__all__ = ["resolve_date", "semantic_search", "locate_block", "match_fund", "tract_context", "equity_audit"]
