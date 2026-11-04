#!/usr/bin/env bash
# Thin wrapper around Terraform and Cloud Build. All identifiers are arguments;
# no project id, bucket or region is hardcoded.
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-}"
REGION="${REGION:-us-central1}"
PREFIX="${PREFIX:-bci}"
FEEDBACK_BUCKET="${FEEDBACK_BUCKET:-}"

if [[ -z "${PROJECT_ID}" || -z "${FEEDBACK_BUCKET}" ]]; then
  echo "usage: PROJECT_ID=<id> FEEDBACK_BUCKET=<globally-unique-bucket> $0" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

echo "==> terraform init/apply"
pushd infra/terraform >/dev/null
terraform init
terraform apply -auto-approve \
  -var "project_id=${PROJECT_ID}" \
  -var "region=${REGION}" \
  -var "name_prefix=${PREFIX}" \
  -var "feedback_bucket_name=${FEEDBACK_BUCKET}"
popd >/dev/null

echo "==> cloud build: test, build, push, deploy"
gcloud builds submit \
  --project "${PROJECT_ID}" \
  --config cloudbuild.yaml \
  --substitutions="_REGION=${REGION},_AR_REPO=${PREFIX},_PREFIX=${PREFIX},_FEEDBACK_BUCKET=${FEEDBACK_BUCKET}"

echo "==> deploying BigQuery DDL"
PROJECT_ID="${PROJECT_ID}" REGION="${REGION}" ./scripts/gcp_sql.sh

echo "==> done"
echo "Frontend: gcloud run services describe ${PREFIX}-frontend --region ${REGION} --format='value(status.url)'"
