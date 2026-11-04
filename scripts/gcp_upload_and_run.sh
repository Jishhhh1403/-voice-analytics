#!/usr/bin/env bash
# Upload the bundled synthetic CSV to GCS and start the feedback Workflow.
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-us-central1}"
PREFIX="${PREFIX:-bci}"
FEEDBACK_BUCKET="${FEEDBACK_BUCKET:-}"
SOURCE="${SOURCE:-synthetic_banking_app_feedback_1800.csv}"
RUN_ID="${RUN_ID:-RUN-$(date -u +%Y%m%d%H%M%S)}"

if [[ -z "${PROJECT_ID}" || -z "${FEEDBACK_BUCKET}" ]]; then
  echo "usage: PROJECT_ID=<id> FEEDBACK_BUCKET=<bucket> $0" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

OBJECT="feedback/source/$(basename "${SOURCE}")"
echo "==> uploading ${SOURCE} to gs://${FEEDBACK_BUCKET}/${OBJECT}"
gcloud storage cp "${SOURCE}" "gs://${FEEDBACK_BUCKET}/${OBJECT}" --project "${PROJECT_ID}"

GENERATION="$(gcloud storage objects describe "gs://${FEEDBACK_BUCKET}/${OBJECT}" \
  --project "${PROJECT_ID}" --format='value(generation)')"

DATA="$(printf '{"region":"%s","worker_job":"%s-worker","run_id":"%s","input_uri":"gs://%s/%s","generation":"%s"}' \
  "${REGION}" "${PREFIX}" "${RUN_ID}" "${FEEDBACK_BUCKET}" "${OBJECT}" "${GENERATION}")"

echo "==> starting workflow ${PREFIX}-feedback-pipeline (generation ${GENERATION})"
gcloud workflows run "${PREFIX}-feedback-pipeline" \
  --project "${PROJECT_ID}" \
  --location "${REGION}" \
  --data "${DATA}"
