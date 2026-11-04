output "feedback_bucket" {
  value = google_storage_bucket.feedback.name
}

output "bigquery_datasets" {
  value = { for key, dataset in google_bigquery_dataset.datasets : key => dataset.dataset_id }
}

output "artifact_registry" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}

output "backend_url" {
  value = try(google_cloud_run_v2_service.backend[0].uri, "")
}

output "frontend_url" {
  value = try(google_cloud_run_v2_service.frontend[0].uri, "")
}

output "worker_job" {
  value = try(google_cloud_run_v2_job.worker[0].name, "")
}

output "feedback_workflow" {
  value = google_workflows_workflow.feedback.name
}

output "backlog_workflow" {
  value = google_workflows_workflow.backlog.name
}

output "service_accounts" {
  value = {
    backend   = google_service_account.backend.email
    worker    = google_service_account.worker.email
    workflows = google_service_account.workflows.email
  }
}
