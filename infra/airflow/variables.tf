variable "region" {
  description = "Región de AWS del pipeline."
  type        = string
  default     = "eu-west-3"
}

variable "instance_type" {
  description = "Tipo de instancia de Airflow (plan B: t4g.small con una AMI arm64)."
  type        = string
  default     = "t3.small"
}

variable "volume_size_gb" {
  description = "Tamaño del volumen raíz gp3 en GB."
  type        = number
  default     = 20
}

variable "bucket_name" {
  description = "Bucket S3 del data lake (raw/, processed/, athena-results/)."
  type        = string
}

variable "lambda_function_name" {
  description = "Función Lambda de ingesta que invoca el DAG."
  type        = string
  default     = "birds-inaturalist-ingestion"
}

variable "alerts_topic_name" {
  description = "Topic SNS de alertas creado en la feature 001."
  type        = string
  default     = "birds-pipeline-alerts"
}

variable "repo_url" {
  description = "Repositorio que se clona en la instancia (debe ser accesible sin credenciales)."
  type        = string
  default     = "https://github.com/javiladino/oiseaux_nantes.git"
}

variable "repo_branch" {
  description = "Rama desplegada en la instancia."
  type        = string
  default     = "main"
}
