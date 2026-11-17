# api/ — FastAPI server: agent runner + A2UI surfaces

**Owner:** Karthik (with Sid) · **Branch:** `agent` · **Reference:** [`docs/UI_API.md`](../docs/UI_API.md) · **Agent contract:** [`docs/AGENT_REQUIREMENTS.md`](../docs/AGENT_REQUIREMENTS.md)

Runs the ADK `navigator` agent from [`agent/`](../agent/) and drives the UI with Google's **A2UI** protocol (v1.0). The agent never writes UI: this server folds each tool result into a case state and sends fixed A2UI component trees with new data models, so only records a tool returned can reach the screen.

## Run

```bash
pip install -r api/requirements.txt -r agent/requirements.txt
uvicorn api.main:app --reload --port 8080                      # live agent (Gemini + BigQuery)
A4I_AGENT_MODE=mock uvicorn api.main:app --reload --port 8080  # demo replay of INT-1142, no GCP
```

Then run the UI (`cd ui && npm run dev`) or open http://localhost:8080 after `npm run build`.

## Layout

```
api/
  main.py              routes: /health, /api/*, WS /ws, SSE fallbacks, serves ui/dist
  workspace.py         one workspace per UI session: queue, open case, chat turns, A2UI actions
  cases.py             CaseState: folds tool results + brief; demo intake queue
  runners.py           LiveRunner (ADK InMemoryRunner, SSE) and MockRunner (scripted replay)
  a2ui/
    surfaces.py        the six A2UI surfaces (component trees) + message builders
    view.py            CaseState -> data model per surface (formatting, tones, fit labels)
    navigator_catalog.json   catalog definition, exported from ui/src/a2ui/catalog.tsx
  fixtures/
    build_demo_fixture.py    rebuilds demo_int_1142.json from data/*.parquet
    demo_int_1142.json
  tests/test_api.py    demo flow over WS + SSE; dumps A2UI messages for `npm run validate:a2ui`
```

## Test

```bash
python -m pytest api/tests -q
cd ui && npm run validate:a2ui      # every A2UI message through the real renderer core
```
