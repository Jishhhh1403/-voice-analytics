#!/usr/bin/env bash
# Remove deployed resources. Destructive: requires FORCE=1.
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-us-central1}"
PREFIX="${PREFIX:-bci}"
FEEDBACK_BUCKET="${FEEDBACK_BUCKET:-}"

if [[ "${FORCE:-0}" != "1" ]]; then
  echo "Refusing to delete resources. Re-run with FORCE=1 after reviewing docs/gcp-migration.md." >&2
  exit 2
fi

if [[ -z "${PROJECT_ID}" ]]; then
  echo "set PROJECT_ID or run: gcloud config set project <PROJECT_ID>" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

delete_run() {
  local kind="$1" name="$2"
  if gcloud run "${kind}" describe "${name}" --project "${PROJECT_ID}" --region "${REGION}" >/dev/null 2>&1; then
    echo "==> deleting Cloud Run ${kind} ${name}"
    gcloud run "${kind}" delete "${name}" --project "${PROJECT_ID}" --region "${REGION}" --quiet
  fi
}

delete_run services "${PREFIX}-frontend"
delete_run services "${PREFIX}-backend"
delete_run jobs "${PREFIX}-worker"

for wf in "${PREFIX}-feedback-pipeline" "${PREFIX}-backlog-validation"; do
  if gcloud workflows describe "${wf}" --project "${PROJECT_ID}" --location "${REGION}" >/dev/null 2>&1; then
    echo "==> deleting workflow ${wf}"
    gcloud workflows delete "${wf}" --project "${PROJECT_ID}" --location "${REGION}" --quiet
  fi
done

for dataset in ops staging curated intelligence taxonomy backlog validation; do
  if bq show --project_id="${PROJECT_ID}" "${PROJECT_ID}:${dataset}" >/dev/null 2>&1; then
    echo "==> deleting BigQuery dataset ${dataset}"
    bq rm -r -f --project_id="${PROJECT_ID}" "${PROJECT_ID}:${dataset}"
  fi
done

if [[ -n "${FEEDBACK_BUCKET}" ]] && gcloud storage buckets describe "gs://${FEEDBACK_BUCKET}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
  echo "==> deleting bucket gs://${FEEDBACK_BUCKET}"
  gcloud storage rm -r "gs://${FEEDBACK_BUCKET}"
fi

if gcloud artifacts repositories describe "${PREFIX}" --project "${PROJECT_ID}" --location "${REGION}" >/dev/null 2>&1; then
  echo "==> deleting Artifact Registry repository ${PREFIX}"
  gcloud artifacts repositories delete "${PREFIX}" --project "${PROJECT_ID}" --location "${REGION}" --quiet
fi

for sa in backend worker workflows; do
  email="${PREFIX}-${sa}@${PROJECT_ID}.iam.gserviceaccount.com"
  if gcloud iam service-accounts describe "${email}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
    echo "==> deleting service account ${email}"
    gcloud iam service-accounts delete "${email}" --project "${PROJECT_ID}" --quiet
  fi
done

echo "Teardown complete. Verify in the console that no billable resources remain."
