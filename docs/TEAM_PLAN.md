# Team Plan

We build a San Francisco intake navigator (Track 1, with fund matching). A paralegal chats with an ADK agent that finds open residential 311 hazards on the tenant's block, matches the statute and an eligible fund, and drafts the Tenant Stabilization Brief. Five owners, one live deploy by **T+2:30**.

A styled version of this page is in [`team-plan.html`](team-plan.html).

## Who owns what

Each person works on their own branch and merges to `main` only when someone else needs the work.

| Person | Role | Owns | Done when | Branch |
|---|---|---|---|---|
| Sid | Architect | Architecture diagram; brief JSON contract (final); Vertex connection + IAM; MCP choice; Cloud Run deploy | Live URL serving the agent | `infra` |
| Karthik | Chatbot | WebSocket API; ADK agent; tools; system prompt caveats; brief + intake memo | Multi-turn chat returns a full brief from real BigQuery data | `agent` |
| Prachi | Analyst | Embedding tables; vector search SQL; decoy check; 4-quarter tract summary; demo block; equity audit numbers | 9 of 9 decoys filtered; SQL and numbers handed over | `data` |
| Selvan | UI | Chat panel + Stabilization Brief card + excluded-decoys panel; built on mock JSON first | Works end to end against the live URL | `ui` |
| April | TPM | Timeline and scope cuts; repo access; integration checks; deck; 3-minute video; submission | All four items submitted on the portal | `story` |

## Hand-offs

A late hand-off blocks someone else. Flag it in team chat right away.

| By | Hand-off | From | To |
|---|---|---|---|
| T+0:20 | Brief JSON contract (draft in [`ARCHITECTURE.md`](ARCHITECTURE.md#brief-json-draft--sid-owns-the-final-version)) | Sid | Karthik, Selvan |
| T+0:30 | Vertex connection `us.a4i-vertex` working | Sid | Prachi |
| T+1:30 | Vector search SQL with the decoy filter, tested | Prachi | Karthik |
| T+1:30 | Demo scenario on a real SF block | Prachi | April, Karthik |
| T+2:30 | Live Cloud Run URL | Sid, Karthik | Selvan, April |
| T+3:00 | Equity audit numbers + silent-distress tracts | Prachi | April |
| T+3:30 | Feature freeze | April | Everyone |

## Checkpoints

The whole run is 4.5 hours. The deploy at T+2:30 is the one that cannot slip.

1. **T+0:00–0:20, everyone:** agree on the scenario sentence and the brief JSON; create branches; add collaborators.
2. **T+0:20–1:30, in parallel:** Prachi embeds and tests the decoy filter; Karthik builds the API + agent on stub tools; Selvan builds the UI on mock JSON; Sid sets up the connection and deploy; April drafts the deck outline.
3. **T+1:30:** the agent swaps stub tools for Prachi's real SQL.
4. **T+2:30:** first deploy to Cloud Run, even if rough. The UI switches to the live URL.
5. **T+2:30–3:30:** decoy demo, equity audit numbers, bug fixes.
6. **T+3:30:** feature freeze; record the video on the live app.
7. **T+4:00–4:30:** submit the repo, Skills project link, deck, and video.

## Open decisions

- [ ] Sid: BigQuery built-in MCP server or MCP Toolbox?
- [ ] Selvan: custom web UI, or `adk web` as a fallback if time runs short?
- [ ] Prachi: which SF block is the demo scenario?
- [ ] April: if time allows, which bonus to add (no-open-case fallback that drafts a 311 request)?
