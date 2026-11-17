#!/usr/bin/env bash
# Deploy the navigator (with the ADK web UI) to Cloud Run.
# Run from the repo root, in Cloud Shell or anywhere gcloud is logged in to the team project.
set -euo pipefail
PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project)}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-housing-navigator}"

# The default compute service account needs: bigquery.jobUser, bigquery.dataViewer,
# aiplatform.user, mcp.toolUser (plus storage.objectViewer, artifactregistry.writer and
# logging.logWriter for the Cloud Build step). See agent/README.md "Team setup".
adk deploy cloud_run \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --service_name "${SERVICE}" \
  --with_ui \
  --env "GOOGLE_GENAI_USE_VERTEXAI=TRUE" \
  --env "GOOGLE_CLOUD_PROJECT=${PROJECT_ID}" \
  --env "GOOGLE_CLOUD_LOCATION=${REGION}" \
  --env "A4I_DATASET=a4i_housing" \
  --env "A4I_METRO=San Francisco" \
  --env "A4I_STATE_CODE=CA" \
  --env "A4I_EMBED_ENDPOINT=text-embedding-005" \
  --env "A4I_COMPLAINTS_EMBEDDED=complaint_embeddings" \
  --env "GEMINI_MODEL=gemini-2.5-flash" \
  --env "ENABLE_BQ_MCP=true" \
  agent/housing_navigator \
  -- --min-instances=1 --allow-unauthenticated
