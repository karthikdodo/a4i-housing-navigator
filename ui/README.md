# ui/ — Case workspace (React + A2UI)

**Owner:** Selvan · **Branch:** `ui` · **Reference:** [`docs/UI_API.md`](../docs/UI_API.md) · **Design:** the UI design canvas (Spec, Main, Brief artboards)

The paralegal's screen, built on Google's **A2UI** protocol (v1.0) with the official React renderer (`@a2ui/react`, `@a2ui/web_core`):

- **Zone A** intake queue · **Zone B** case header, chat with tool traces and citation chips, suggested questions · **Zone C** Evidence / Statutes / Funds / Tract / Memo tabs · **Brief** overlay (print to PDF) · **New intake** form.
- Every panel except the chat is an A2UI surface the API sends. Buttons inside them send A2UI `action` messages back.
- `src/a2ui/catalog.tsx` is the navigator catalog: the A2UI basic catalog plus domain components (RecordCard, ExcludedCard, FundCard, StatTile, …) that carry the design's trust rules (excluded records show the failing field, modeled numbers get the violet tag, status is never color alone).

## Run

```bash
npm install
npm run dev            # http://localhost:5173 (API on :8080: `A4I_AGENT_MODE=mock uvicorn api.main:app --port 8080`)
npm run build          # ui/dist, served by the API at /
npm run validate:a2ui  # after `python -m pytest api/tests`: validates the API's A2UI messages
npm run catalog:export # after changing catalog.tsx: rewrites api/a2ui/navigator_catalog.json
```

## Layout

```
src/
  App.tsx                 three-zone shell, chat, overlays
  api/client.ts           WebSocket client (reconnect, session id)
  a2ui/useNavigator.ts    MessageProcessor <-> WebSocket; local vs server actions
  a2ui/catalog.tsx        navigator A2UI catalog (basic v1.0 + 20 components)
  a2ui/markdown.ts        markdown-it + DOMPurify; record ids -> citation chips
  styles.css              design tokens (IBM Plex, blue/orange/red/green/violet tones)
scripts/
  validate-a2ui.ts        API messages -> real A2UI renderer core
  export-catalog.ts       catalog.tsx -> api/a2ui/navigator_catalog.json
```
