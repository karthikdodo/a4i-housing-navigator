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

## Start now, without the backend

Build against a mock of the brief JSON in [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md#brief-json-draft--sid-owns-the-final-version). Swap in `ws://localhost:8080/ws`, then the Cloud Run URL at T+2:30.

Fallback if time runs short: `adk web` (it works out of the box, but looks like a developer tool). Be ready to say why we chose the UI we did.
