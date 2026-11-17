# ui/ — Intake chat + Stabilization Brief

**Owner:** Selvan · **Branch:** `ui` · **Contract:** [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md#websocket-contract)

The screen a paralegal uses: chat on the left, the Tenant Stabilization Brief card on the right.

## What the screen shows

- **Chat panel:** user messages, agent replies (`message` events), and a live status line (`status` events, e.g. "Searching 311 records…").
- **Brief card** (from the `brief` event):
  - Case summary: block, hazards, hearing date
  - Corroborating 311 records with similarity scores
  - **Excluded records and why.** Keep this visible: it's the decoy-catching moment for judges.
  - Statute citations
  - Funds: eligible or not, with the reason and intake link
  - Tract context + equity note
  - "What this record can't prove"
  - Intake memo, with a copy or download button

## How the UI is served

The UI ships **inside April's API service**: FastAPI serves these files at `/`, and the WebSocket is at `/ws` on the same host. So connect to the page's own host and never hard-code a URL:

```js
const ws = new WebSocket(
  (location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws");
```

That one line works locally (`http://localhost:8080`) and on Cloud Run (`https://….run.app`).

- **Plain HTML/JS/CSS:** put the files in `ui/` with `index.html` at the top. No build step.
- **React/Vite or similar:** the API serves `ui/dist/`. Run `npm run build` and tell April and Sid, so the Dockerfile either builds it or copies a committed `dist/`.

Streaming note: `message` events with `"final": false` are chunks to append. The one with `"final": true` is the **whole** reply again, so replace the chunks with it instead of appending.

## Start now, without the backend

Build against a mock of the brief JSON in [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md#brief-json-draft--sid-owns-the-final-version). Then run April's server locally (`http://localhost:8080`) and finally the Cloud Run URL at T+2:30.

Fallback if time runs short: `adk web` (it works out of the box, but looks like a developer tool). Be ready to say why we chose the UI we did.
