# agent/ — ADK root agent and tools

**Owner:** Karthik · **Branch:** `agent` · **Contract:** [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md)

One ADK root agent (`navigator`) on Gemini, plus our custom tools. The WebSocket server in [`api/`](../api/) imports and runs it.

## Planned layout

```
agent/
  navigator/
    __init__.py
    agent.py          # root_agent: model, system prompt, tool list (incl. BigQuery MCP)
    prompts.py        # system prompt: caveats, brief format, when to refuse
    tools/
      semantic_search.py   # AI.EMBED + VECTOR_SEARCH + decoy labeling
      match_fund.py        # deterministic eligibility rules
      tract_context.py     # 4-quarter-safe tract summary
      equity_audit.py      # post-output only, audit_* columns
  requirements.txt
```

Run locally with `adk web agent/` while the API and UI are being built.

## Rules the system prompt must enforce

- A 311 match corroborates **block** conditions (`block_address`), never a specific apartment.
- Eviction filing counts are **modeled** neighborhood baselines, not this tenant's court record.
- Never cite an excluded (decoy) record as evidence. Say why it was excluded if asked.
- Fund eligibility comes from `match_fund`, not the model's own judgment.
- `audit_*` columns never appear in reasoning before the brief is written.

---

## Organizer requirements (from the original template)

- **An ADK agent**, in Python.
- **At least one tool you built yourself.** A Python function tool or a custom MCP Toolbox tool. Consuming only prebuilt generic tools does not count.
- **At least one Google-managed MCP server, consumed.** BigQuery's built-in MCP server or [MCP Toolbox for Databases](https://github.com/googleapis/mcp-toolbox). Don't author your own.
- **Deployed to Google Cloud**, on Agent Runtime or Cloud Run.
- **Required differentiator: BigQuery Vector Search.** The agent must genuinely call `AI.EMBED` + `VECTOR_SEARCH`. Filtering on categories or `LIKE '%no heat%'` doesn't count.

> Vector search is a **candidate generator, not an answer**. Every metro has nine planted near-miss decoys (`DECOY-*`). What you do *after* the search (enforcing `property_type = 'Residential'`, checking `closed_date IS NULL`, matching program rules, avoiding the 4x quarterly join inflation) is what makes the agent useful.

See Section 13 of [`notebooks/c_housing_01_load_explore.ipynb`](../notebooks/c_housing_01_load_explore.ipynb) for the connection setup and query syntax.
