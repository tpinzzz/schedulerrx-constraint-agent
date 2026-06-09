#!/usr/bin/env bash
# Deploy the ADK constraint-agent to Cloud Run (one command).
#
#   ./deploy_adk.sh                 # deploy, min-instances 0
#   MIN_INSTANCES=1 ./deploy_adk.sh # demo day: kill cold starts
#
# Uses Vertex AI (GOOGLE_GENAI_USE_VERTEXAI=TRUE) via the Cloud Run runtime service
# account's ADC — no API key, no free-tier daily cap. Explicit --project so it can't
# target the wrong project. The toy `constraint-debugger` service is left untouched.
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
PROJECT="${PROJECT:-schedulerrx-constraint-agent}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-constraint-agent}"
MIN_INSTANCES="${MIN_INSTANCES:-0}"
GEMINI_MODEL="${GEMINI_MODEL:-gemini-3.5-flash}"
VERTEX_LOCATION="${VERTEX_LOCATION:-global}"  # Vertex model endpoint (gemini-3.5-flash lives on `global`, not us-central1)
TAG="${TAG:-}"                                # if set: deploy a tagged candidate revision with NO traffic (for smoke-testing)

# Vertex AI authenticates via the runtime service account (ADC) — no GOOGLE_API_KEY.
EXTRA=()
if [ -n "$TAG" ]; then EXTRA+=(--no-traffic --tag "$TAG"); fi
echo ">> Deploying '$SERVICE' to $PROJECT/$REGION (Vertex AI @ $VERTEX_LOCATION, min-instances=$MIN_INSTANCES, model=$GEMINI_MODEL${TAG:+ · tag=$TAG no-traffic})"
gcloud run deploy "$SERVICE" \
  --source "$REPO" \
  --project "$PROJECT" \
  --region "$REGION" \
  --allow-unauthenticated \
  --memory 2Gi --cpu 2 --timeout 300 \
  --min-instances "$MIN_INSTANCES" --max-instances 3 \
  --set-env-vars "GOOGLE_GENAI_USE_VERTEXAI=TRUE,GOOGLE_CLOUD_PROJECT=${PROJECT},GOOGLE_CLOUD_LOCATION=${VERTEX_LOCATION},GEMINI_MODEL=${GEMINI_MODEL}" \
  ${EXTRA[@]+"${EXTRA[@]}"} \
  --quiet

echo ">> Service URL:"
gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" \
  --format='value(status.url)'
