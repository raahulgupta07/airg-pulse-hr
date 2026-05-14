variable "name_prefix" {
  type = string
}

variable "region" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "task_security_group_id" {
  description = "Pre-created task SG (created at root to avoid module cycle)"
  type        = string
}

variable "ecr_repository_url" {
  type = string
}

variable "image_tag" {
  type    = string
  default = "latest"
}

variable "container_cpu" {
  type    = number
  default = 512
}

variable "container_memory" {
  type    = number
  default = 1024
}

variable "container_port" {
  type    = number
  default = 8000
}

variable "desired_count" {
  type    = number
  default = 1
}

variable "log_group_name" {
  type = string
}

variable "task_execution_role_arn" {
  type = string
}

variable "task_role_arn" {
  type = string
}

variable "alb_security_group_id" {
  type = string
}

variable "target_group_arn" {
  type = string
}

variable "alb_listener_https" {
  description = "HTTPS listener ARN — used to enforce dependency ordering"
  type        = string
}

variable "efs_id" {
  type = string
}

variable "efs_access_point_id" {
  type = string
}

variable "secret_arns" {
  description = "Map of env-key -> secret ARN"
  type        = map(string)
}

variable "ssm_param_arns" {
  description = "Map of env-key -> SSM ARN"
  type        = map(string)
  default     = {}
}

variable "ssm_param_names" {
  description = "Map of env-key -> SSM param name"
  type        = map(string)
  default     = {}
}

variable "db_endpoint" {
  type = string
}

variable "db_name" {
  type = string
}

variable "db_user" {
  type = string
}

variable "db_password_secret_arn" {
  type = string
}
