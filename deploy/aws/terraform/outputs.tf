output "alb_dns_name" {
  description = "DNS name of the ALB"
  value       = module.alb.alb_dns_name
}

output "ecr_repo_url" {
  description = "URL of the pulse-api ECR repository"
  value       = module.ecr.repository_url
}

output "rds_cluster_endpoint" {
  description = "Aurora cluster writer endpoint"
  value       = module.rds.cluster_endpoint
}

output "rds_cluster_reader_endpoint" {
  description = "Aurora cluster reader endpoint"
  value       = module.rds.cluster_reader_endpoint
}

output "efs_id" {
  description = "EFS file system id"
  value       = module.efs.efs_id
}

output "log_group" {
  description = "CloudWatch log group for ECS tasks"
  value       = aws_cloudwatch_log_group.ecs.name
}

output "ecs_cluster_name" {
  description = "ECS cluster name"
  value       = module.ecs.cluster_name
}

output "ecs_service_name" {
  description = "ECS service name"
  value       = module.ecs.service_name
}

output "secret_arns" {
  description = "Map of secret name -> ARN"
  value       = module.secrets.secret_arns
}
