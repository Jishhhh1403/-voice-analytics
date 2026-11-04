locals {
  services = toset([
    "run.googleapis.com",
    "workflows.googleapis.com",
    "workflows.googleapis.com",
    "artifactregistry.googleapis.com",
    "bigquery.googleapis.com",
    "storage.googleapis.com",
    "secretmanager.googleapis.com",
    "cloudbuild.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "iam.googleapis.com",
    "aiplatform.googleapis.com",
  ])

  datasets = {
    ops         = "Pipeline runs, stages, ingestion manifests and audit events"
    staging     = "Raw object metadata and row-level validation status"
    curated     = "Validated, deduplicated and redacted feedback"
    intelligence = "Insights, canonical problems, evidence, clusters and mappings"
    taxonomy    = "Versioned banking journey taxonomy and proposals"
    backlog     = "Backlog uploads and normalised backlog items"
    validation  = "Backlog validation runs, reports and findings"
  }
}

resource "google_project_service" "services" {
  for_each = local.services

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_storage_bucket" "feedback" {
  name                        = var.feedback_bucket_name
  location                    = var.region
  uniform_bucket_level_access = true
  labels                      = var.labels

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      age            = 365
      num_newer_versions = 5
    }
    action {
      type = "Delete"
    }
  }

  depends_on = [google_project_service.services]
}

resource "google_bigquery_dataset" "datasets" {
  for_each = local.datasets

  project                    = var.project_id
  dataset_id                 = each.key
  friendly_name              = "BCI ${each.key}"
  description                = each.value
  location                   = var.bigquery_location
  delete_contents_on_destroy = false
  labels                     = var.labels

  depends_on = [google_project_service.services]
}

resource "google_artifact_registry_repository" "images" {
  project       = var.project_id
  location      = var.region
  repository_id = var.artifact_repository
  format        = "DOCKER"
  description   = "Container images for the banking customer intelligence platform"
  labels        = var.labels

  depends_on = [google_project_service.services]
}

resource "google_service_account" "backend" {
  project      = var.project_id
  account_id   = "${var.name_prefix}-backend"
  display_name = "BCI backend Cloud Run service"
}

resource "google_service_account" "worker" {
  project      = var.project_id
  account_id   = "${var.name_prefix}-worker"
  display_name = "BCI batch worker Cloud Run job"
}

resource "google_service_account" "workflows" {
  project      = var.project_id
  account_id   = "${var.name_prefix}-workflows"
  display_name = "BCI Cloud Workflows orchestrator"
}

locals {
  backend_roles = toset([
    "roles/storage.objectViewer",
    "roles/bigquery.dataEditor",
    "roles/bigquery.jobUser",
    "roles/secretmanager.secretAccessor",
    "roles/workflows.invoker",
    "roles/logging.logWriter",
  ])

  worker_roles = toset([
    "roles/storage.objectAdmin",
    "roles/bigquery.dataEditor",
    "roles/bigquery.jobUser",
    "roles/aiplatform.user",
    "roles/secretmanager.secretAccessor",
    "roles/logging.logWriter",
  ])

  workflows_roles = toset([
    "roles/run.developer",
    "roles/logging.logWriter",
  ])
}

resource "google_project_iam_member" "backend" {
  for_each = local.backend_roles

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.backend.email}"
}

resource "google_project_iam_member" "worker" {
  for_each = local.worker_roles

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.worker.email}"
}

resource "google_project_iam_member" "workflows" {
  for_each = local.workflows_roles

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.workflows.email}"
}

resource "google_service_account_iam_member" "workflows_act_as_worker" {
  service_account_id = google_service_account.worker.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.workflows.email}"
}

resource "google_secret_manager_secret" "gemini" {
  project   = var.project_id
  secret_id = var.gemini_secret_name
  labels    = var.labels

  replication {
    auto {}
  }

  depends_on = [google_project_service.services]
}

resource "google_cloud_run_v2_service" "backend" {
  count = var.backend_image == "" ? 0 : 1

  project  = var.project_id
  name     = "${var.name_prefix}-backend"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"
  labels   = var.labels

  template {
    service_account = google_service_account.backend.email

    scaling {
      min_instance_count = 0
      max_instance_count = 4
    }

    containers {
      image = var.backend_image

      ports {
        container_port = 8000
      }

      env {
        name  = "ENVIRONMENT"
        value = "gcp"
      }
      env {
        name  = "OBJECT_STORE"
        value = "gcs"
      }
      env {
        name  = "GCS_BUCKET"
        value = google_storage_bucket.feedback.name
      }
      env {
        name  = "AUTO_SEED_SOURCE"
        value = "false"
      }
      env {
        name  = "AUTO_RUN_SAMPLE"
        value = "false"
      }
      env {
        name  = "EXTRACTION_PROVIDER"
        value = "rules"
      }
      env {
        name  = "EMBEDDING_PROVIDER"
        value = "local"
      }
      env {
        name  = "CORS_ORIGINS"
        value = "https://${var.name_prefix}-frontend-${var.project_id}.${var.region}.run.app"
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
      }
    }
  }

  depends_on = [
    google_project_service.services,
    google_bigquery_dataset.datasets,
    google_storage_bucket.feedback,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "backend_public" {
  count = var.backend_image == "" ? 0 : 1

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.backend[0].name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service" "frontend" {
  count = var.frontend_image == "" ? 0 : 1

  project  = var.project_id
  name     = "${var.name_prefix}-frontend"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"
  labels   = var.labels

  template {
    service_account = google_service_account.backend.email

    containers {
      image = var.frontend_image

      ports {
        container_port = 80
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
    }
  }

  depends_on = [google_project_service.services]
}

resource "google_cloud_run_v2_service_iam_member" "frontend_public" {
  count = var.frontend_image == "" ? 0 : 1

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.frontend[0].name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_job" "worker" {
  count = var.worker_image == "" ? 0 : 1

  project  = var.project_id
  name     = "${var.name_prefix}-worker"
  location = var.region
  labels   = var.labels

  template {
    template {
      service_account = google_service_account.worker.email
      timeout         = "3600s"

      containers {
        image = var.worker_image

        env {
          name  = "ENVIRONMENT"
          value = "gcp"
        }
        env {
          name  = "OBJECT_STORE"
          value = "gcs"
        }
        env {
          name  = "GCS_BUCKET"
          value = google_storage_bucket.feedback.name
        }
        env {
          name  = "EXTRACTION_PROVIDER"
          value = "rules"
        }
        env {
          name  = "EMBEDDING_PROVIDER"
          value = "local"
        }

        resources {
          limits = {
            cpu    = "2"
            memory = "2Gi"
          }
        }
      }
    }
  }

  depends_on = [
    google_project_service.services,
    google_bigquery_dataset.datasets,
    google_storage_bucket.feedback,
  ]
}

resource "google_workflows_workflow" "feedback" {
  project         = var.project_id
  name            = "${var.name_prefix}-feedback-pipeline"
  region          = var.region
  service_account = google_service_account.workflows.email
  source_contents = file("${path.module}/../../workflows/feedback_pipeline.yaml")
  labels          = var.labels

  depends_on = [google_project_service.services]
}

resource "google_workflows_workflow" "backlog" {
  project         = var.project_id
  name            = "${var.name_prefix}-backlog-validation"
  region          = var.region
  service_account = google_service_account.workflows.email
  source_contents = file("${path.module}/../../workflows/backlog_validation.yaml")
  labels          = var.labels

  depends_on = [google_project_service.services]
}
