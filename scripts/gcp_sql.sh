#!/usr/bin/env bash
# Apply BigQuery DDL and views. Requires bq CLI and an authenticated project.
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-us-central1}"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "set PROJECT_ID or run: gcloud config set project <PROJECT_ID>" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

render() {
  local src="$1"
  local dest="$2"
  sed "s/\${PROJECT_ID}/${PROJECT_ID}/g" "${src}" > "${dest}"
}

for file in "${ROOT}"/sql/migrations/*.sql; do
  out="${TMP}/$(basename "${file}")"
  render "${file}" "${out}"
  echo "==> applying ${file}"
  bq query --project_id="${PROJECT_ID}" --location="${REGION}" --use_legacy_sql=false < "${out}"
done

for file in "${ROOT}"/sql/views/*.sql; do
  out="${TMP}/$(basename "${file}")"
  render "${file}" "${out}"
  echo "==> applying ${file}"
  bq query --project_id="${PROJECT_ID}" --location="${REGION}" --use_legacy_sql=false < "${out}"
done
