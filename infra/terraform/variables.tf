variable "project_id" {
  type        = string
  description = "GCP project id. Do not commit a real value."
}

variable "region" {
  type        = string
  default     = "us-central1"
  description = "Region for Cloud Run, Workflows and Artifact Registry."
}

variable "name_prefix" {
  type        = string
  default     = "bci"
  description = "Prefix for resource names."
}

variable "feedback_bucket_name" {
  type        = string
  description = "Globally unique GCS bucket for raw feedback, backlog uploads and reports."
}

variable "bigquery_location" {
  type        = string
  default     = "US"
  description = "BigQuery dataset location."
}

variable "artifact_repository" {
  type        = string
  default     = "bci"
  description = "Artifact Registry repository name."
}

variable "backend_image" {
  type        = string
  default     = ""
  description = "Full backend image reference. Leave empty to skip Cloud Run service creation."
}

variable "frontend_image" {
  type        = string
  default     = ""
  description = "Full frontend image reference. Leave empty to skip Cloud Run service creation."
}

variable "worker_image" {
  type        = string
  default     = ""
  description = "Full worker image reference. Leave empty to skip Cloud Run job creation."
}

variable "gemini_secret_name" {
  type        = string
  default     = "bci-gemini-api-key"
  description = "Secret Manager secret name for the optional Gemini API key."
}

variable "labels" {
  type = map(string)
  default = {
    application = "banking-customer-intelligence"
    managed_by  = "terraform"
  }
}
