# One Cloud Run service: the FastAPI API + agent, serving the built UI at /.
# Build from the repo root:
#   docker build -f infra/Dockerfile -t navigator .
#   gcloud run deploy navigator --source . ...   (or push the image and deploy it)
# Deploy with --min-instances=1 --max-instances=1 --timeout=3600 (in-memory sessions).

FROM node:22-slim AS ui
WORKDIR /src/ui
COPY ui/package.json ui/package-lock.json* ./
RUN npm ci || npm install
COPY ui/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PORT=8080
COPY agent/requirements.txt agent/requirements.txt
COPY api/requirements.txt api/requirements.txt
RUN pip install --no-cache-dir -r agent/requirements.txt fastapi "uvicorn[standard]" pydantic python-multipart
COPY agent/ agent/
COPY api/ api/
COPY --from=ui /src/ui/dist ui/dist
# Optional: GOOGLE_MAPS_API_KEY (interactive map with pins; without it the keyless Google Maps embed is used)
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT}"]
