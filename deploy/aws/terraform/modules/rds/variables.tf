variable "name_prefix" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "ecs_security_group" {
  description = "Security group of ECS tasks allowed to reach Aurora on 5432"
  type        = string
}

variable "master_username" {
  type = string
}

variable "master_password" {
  type      = string
  sensitive = true
}

variable "password_secret_id" {
  description = "Secrets Manager secret holding the DB master password"
  type        = string
}

variable "min_acu" {
  type    = number
  default = 0.5
}

variable "max_acu" {
  type    = number
  default = 2
}

variable "database_name" {
  type    = string
  default = "pulse"
}

variable "engine_version" {
  description = "Aurora PostgreSQL engine version supporting Serverless v2 + pgvector"
  type        = string
  default     = "15.5"
}
