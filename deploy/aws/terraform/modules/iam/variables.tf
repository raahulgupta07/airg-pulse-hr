variable "name_prefix" {
  type = string
}

variable "secret_arns" {
  description = "List of Secrets Manager ARNs the task may read"
  type        = list(string)
  default     = []
}

variable "ssm_param_arns" {
  description = "Map of SSM param key -> ARN"
  type        = map(string)
  default     = {}
}

variable "s3_bucket_name" {
  description = "Optional S3 bucket name granted to task role"
  type        = string
  default     = ""
}

variable "log_group_arn" {
  description = "CloudWatch log group ARN the task role can write to"
  type        = string
}
