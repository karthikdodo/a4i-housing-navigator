# infra/: Connection, container, deploy

**Owners:** Sid (Vertex connection, embeddings) · April (container + Cloud Run deploy) · **Contract:** [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md)

## 1. Vertex AI connection: done ✅

`us.a4i-vertex` (CLOUD_RESOURCE) exists, and the embedding tables are built with `gemini-embedding-2` through it. SQL: [`sql/`](../sql/). Settings: [`agent/navigator/config.py`](../agent/navigator/config.py).

## 2. Cloud Run: one service for UI + API + agent

`Dockerfile` at the **repo root** (so `gcloud run deploy --source .` finds it):

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY agent/requirements.txt agent/requirements.txt
COPY api/requirements.txt api/requirements.txt
RUN pip install --no-cache-dir -r agent/requirements.txt -r api/requirements.txt
COPY agent/ agent/
COPY api/ api/
COPY ui/ ui/
# If the UI needs a build step (React/Vite), add a node stage that runs `npm run build` into ui/dist.
ENV PYTHONPATH=/app/agent
CMD exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8080}
```

Deploy:

```bash
gcloud run deploy navigator --source . --region=us-central1 \
  --allow-unauthenticated \
  --min-instances=1 --max-instances=1 --timeout=3600
```

| Flag | Why |
|---|---|
| `--allow-unauthenticated` | Public URL, no login. The judges and anyone with the link can open it. |
| `--min-instances=1` | No cold start during the recorded demo. |
| `--max-instances=1` | ADK sessions live in memory, so every message must reach the same instance. |
| `--timeout=3600` | WebSockets stay open for the whole conversation. |

Runtime service account roles: `roles/bigquery.jobUser`, `roles/bigquery.dataViewer`, `roles/aiplatform.user`. Grant them explicitly if the deploy uses a dedicated service account. No env vars are needed: `config.py` defaults to the lab project.

**After deploying, check:**
1. `https://<url>/health` returns `{"ok": true}`.
2. The UI at `https://<url>/` runs the Turk St case end to end (about 40 s, with a brief card).
3. Ask an ad-hoc data question ("how many open residential complaints?"). It uses the BigQuery MCP tools under the service account, the part most likely to need an extra permission.

## 3. Know before demo day

- **The lab project is temporary.** Qwiklabs projects are usually deleted after the event, and judges score later. Record the video as a live end-to-end run, and ask the Table Captain how long the project stays up.
- **The URL is public**, so every conversation spends lab credits. The data is public records and the agent's BigQuery tools are read-only, so nothing private is exposed.

## 4. MCP decision: done ✅

Google-managed **BigQuery MCP server** (`https://bigquery.googleapis.com/mcp`), read-only tools. See [`agent/navigator/bq_mcp.py`](../agent/navigator/bq_mcp.py).
