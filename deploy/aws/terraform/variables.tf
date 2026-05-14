variable "region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "us-east-1"
}

variable "env_name" {
  description = "Environment name (e.g. prod, staging, dev). Used for resource prefixing."
  type        = string
  default     = "prod"
}

variable "image_tag" {
  description = "Container image tag in the pulse-api ECR repo"
  type        = string
  default     = "latest"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.40.0.0/16"
}

variable "db_master_user" {
  description = "Master username for Aurora PostgreSQL"
  type        = string
  default     = "pulseadmin"
}

variable "instance_count" {
  description = "Desired count of ECS tasks for pulse-api service"
  type        = number
  default     = 1
}

variable "container_cpu" {
  description = "Fargate task CPU units"
  type        = number
  default     = 512
}

variable "container_memory" {
  description = "Fargate task memory (MiB)"
  type        = number
  default     = 1024
}

variable "container_port" {
  description = "Container listening port"
  type        = number
  default     = 8000
}

variable "certificate_arn" {
  description = "ACM certificate ARN for the ALB HTTPS listener"
  type        = string
}

variable "route53_zone_id" {
  description = "Optional Route53 hosted zone id for alias record"
  type        = string
  default     = ""
}

variable "domain_name" {
  description = "Optional domain name for Route53 alias (e.g. api.example.com)"
  type        = string
  default     = ""
}

variable "allowed_origins" {
  description = "ALLOWED_ORIGINS env value passed via SSM"
  type        = string
  default     = "*"
}

variable "app_version" {
  description = "APP_VERSION env value"
  type        = string
  default     = "1.0.0"
}

variable "llm_daily_cap_usd" {
  description = "LLM_DAILY_CAP_USD env value"
  type        = string
  default     = "10"
}

variable "storage_backend" {
  description = "STORAGE_BACKEND env (efs|s3)"
  type        = string
  default     = "efs"
}

variable "s3_bucket_name" {
  description = "Optional S3 bucket name granted to task role when STORAGE_BACKEND=s3"
  type        = string
  default     = ""
}

variable "aurora_min_acu" {
  description = "Aurora Serverless v2 minimum capacity"
  type        = number
  default     = 0.5
}

variable "aurora_max_acu" {
  description = "Aurora Serverless v2 maximum capacity"
  type        = number
  default     = 2
}
