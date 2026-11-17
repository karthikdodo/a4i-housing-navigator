# infra/ — Connection, container, deploy

**Owner:** Sid · **Branch:** `infra` · **Contract:** [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md#deploy-sid)

## 1. Vertex AI connection (needed by T+0:30)

The connection doesn't exist yet. Run this in Cloud Shell or any machine authed to the lab project:

```bash
PROJECT_ID="$(gcloud config get-value project)"
bq mk --connection --location=US --project_id="${PROJECT_ID}" \
  --connection_type=CLOUD_RESOURCE a4i-vertex

SA="$(bq show --format=json --connection "${PROJECT_ID}.us.a4i-vertex" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["cloudResource"]["serviceAccountId"])')"

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA}" --role="roles/aiplatform.user"
```

Wait about 60 seconds for permissions to spread, then tell Prachi.

## 2. Cloud Run deploy (needed by T+2:30)

Planned files: `Dockerfile` (runs `uvicorn api.main:app --port 8080`) and `deploy.sh`.

Required flags:

```
--region=us-central1 --min-instances=1 --max-instances=1 --timeout=3600
```

- `min-instances=1`: no cold start during the recorded demo.
- `max-instances=1`: ADK sessions are in memory, so all conversations must hit one instance.
- `timeout=3600`: WebSockets stay open for the whole conversation.

Runtime service account roles: `roles/bigquery.user`, `roles/bigquery.dataViewer`, `roles/aiplatform.user`.

## 3. MCP decision

Pick one and note it here: **BigQuery built-in MCP server** (fastest) or **MCP Toolbox for Databases** (custom parameterized SQL tools; deploy with `--min-instances=1`).
