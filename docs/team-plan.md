# A4I Housing Navigator: Team Plan

*Agents for Impact 2026 · Nov 17, 2026*

> We build a San Francisco intake navigator (Track 1, with fund matching): a paralegal chats with an ADK agent that finds open residential 311 hazards on the tenant's block, matches the statute and an eligible fund, and drafts the Tenant Stabilization Brief. Five owners, one live deploy by **T+2:30**.

## Decisions locked

| Decision | Choice |
|---|---|
| **Metro** | San Francisco (42 tracts, 140 open residential 311s, 9 decoys) |
| **Track** | 1, Today at intake, with Track 2 fund matching built in |
| **User** | Right-to-counsel paralegal with a tenant facing a Monday hearing |
| **Agent** | ADK in Python on Gemini |
| **Search** | BigQuery `AI.EMBED` (gemini-embedding-2) + `VECTOR_SEARCH`, then the Residential + open filter |
| **MCP** | BigQuery built-in MCP server (Sid to confirm vs. MCP Toolbox) |
| **Deploy** | Cloud Run, min-instances 1 |
| **GCP project** | qwiklabs-gcp-04-3b4b41069fc3, dataset `a4i_housing` (already loaded) |
| **Repo** | [karthikdodo/a4i-housing-navigator](https://github.com/karthikdodo/a4i-housing-navigator) (public) |

## Who owns what

Each person works on their own branch and merges to `main` only when someone else needs the work.

| Person | Owns | Done when | Branch |
|---|---|---|---|
| **Sid** (Architect) | Architecture diagram; brief JSON contract; Vertex connection + IAM; MCP choice; Cloud Run deploy | Live URL serving the agent, min-instances 1 | `infra` |
| **Karthik** (Chatbot) | ADK agent; custom tools (block evidence search, statute match, fund match, tract context, equity audit); system prompt caveats; brief + intake memo | Multi-turn chat returns a full brief from real BigQuery data | `agent` |
| **Prachi** (Analyst) | Embedding tables (complaints, statutes, funds); vector search SQL; decoy check; 4-quarter tract summary; demo block pick; equity audit numbers | 9 of 9 decoys filtered; SQL and numbers handed over | `data` |
| **Selvan** (UI) | Web UI: chat panel + Stabilization Brief card + excluded-decoys panel; built on mock JSON first | Works end to end against the live URL | `ui` |
| **April** (TPM) | Timeline and scope cuts; repo access; integration checks; deck; 3-minute video; submission | All four artifacts submitted on the portal | `story` |

## Hand-offs

These seven hand-offs are what let people work in parallel. A late one blocks someone else, so flag it in chat right away.

| By | Hand-off | From | To |
|---|---|---|---|
| **T+0:20** | Brief JSON contract (fields of the brief card) | Sid | Karthik, Selvan |
| **T+0:30** | Vertex connection `us.a4i-vertex` working | Sid | Prachi |
| **T+1:30** | Vector search SQL with the decoy filter, tested | Prachi | Karthik |
| **T+1:30** | Demo scenario on a real SF block | Prachi | April, Karthik |
| **T+2:30** | Live Cloud Run URL | Sid, Karthik | Selvan, April |
| **T+3:00** | Equity audit numbers + silent-distress tracts | Prachi | April |
| **T+3:30** | Feature freeze | April | Everyone |

## Checkpoints

The whole run is 4.5 hours. The deploy at T+2:30 is the one that cannot slip.

- **T+0:00 to 0:20, everyone:** agree on the scenario sentence and the brief JSON; create branches; add collaborators to the repo.
- **T+0:20 to 1:30, in parallel:** Prachi embeds the data and tests the decoy filter; Karthik builds the agent on stub tools; Selvan builds the UI on mock JSON; Sid sets up the connection and deploy pipeline; April drafts the deck outline.
- **T+1:30:** the agent swaps its stub tools for Prachi's real SQL.
- ⭐ **T+2:30:** first deploy to Cloud Run, even if rough; the UI switches to the live URL.
- **T+2:30 to 3:30:** run the decoy demo, add equity audit numbers, fix bugs.
- ⭐ **T+3:30:** feature freeze; record the video on the live app.
- **T+4:00 to 4:30:** submit the repo, the Skills project link, the deck and the video.

## Rules and open decisions

- One shared GCP project: never rename or drop a table in `a4i_housing` without saying so in chat.
- Keep the `audit_*` columns out of search, scoring and prompts; use them only in the equity audit.
- Add up the 4 quarters of eviction filings per tract before joining, or every count is 4x too high.
- Say it plainly in the app and deck: 311 records prove block conditions, not the tenant's unit; eviction filings are modeled.
- April may cut scope at T+2:30 if there is no deploy.

**Open decisions**

- [ ] Sid: BigQuery built-in MCP server or MCP Toolbox?
- [ ] Selvan: custom web UI, or `adk web` as a fallback if time runs short?
- [ ] Prachi: which SF block is the demo scenario?
- [ ] April: if time allows, which bonus to add (no-open-case fallback that drafts a 311 request)?

---

*A4I 2026 · Affordable Housing Stability & Eviction Prevention Navigator*
