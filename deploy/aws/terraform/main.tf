locals {
  name_prefix = "pulse-${var.env_name}"

  common_tags = {
    Project     = "pulse"
    Environment = var.env_name
  }
}

data "aws_availability_zones" "available" {
  state = "available"
}

# CloudWatch log group for ECS task logs
resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/pulse-api"
  retention_in_days = 30

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-logs"
  })
}

module "vpc" {
  source = "./modules/vpc"

  name_prefix        = local.name_prefix
  vpc_cidr           = var.vpc_cidr
  availability_zones = slice(data.aws_availability_zones.available.names, 0, 2)
}

module "ecr" {
  source = "./modules/ecr"

  name_prefix = local.name_prefix
  repo_name   = "pulse-api"
}

# Task security group lives at root to break a module-level cycle
# (efs/rds need the task SG; ecs needs efs/rds resources).
resource "aws_security_group" "task" {
  name        = "${local.name_prefix}-task-sg"
  description = "ECS task SG"
  vpc_id      = module.vpc.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${local.name_prefix}-task-sg"
  }
}

module "secrets" {
  source = "./modules/secrets"

  name_prefix = local.name_prefix

  ssm_params = {
    APP_VERSION       = var.app_version
    ALLOWED_ORIGINS   = var.allowed_origins
    LLM_DAILY_CAP_USD = var.llm_daily_cap_usd
    STORAGE_BACKEND   = var.storage_backend
    AWS_REGION        = var.region
  }
}

module "iam" {
  source = "./modules/iam"

  name_prefix    = local.name_prefix
  secret_arns    = values(module.secrets.secret_arns)
  ssm_param_arns = module.secrets.ssm_param_arns
  s3_bucket_name = var.s3_bucket_name
  log_group_arn  = aws_cloudwatch_log_group.ecs.arn
}

module "efs" {
  source = "./modules/efs"

  name_prefix        = local.name_prefix
  vpc_id             = module.vpc.vpc_id
  private_subnet_ids = module.vpc.private_subnet_ids
  ecs_security_group = aws_security_group.task.id
}

module "rds" {
  source = "./modules/rds"

  name_prefix        = local.name_prefix
  vpc_id             = module.vpc.vpc_id
  private_subnet_ids = module.vpc.private_subnet_ids
  ecs_security_group = aws_security_group.task.id
  master_username    = var.db_master_user
  master_password    = module.secrets.db_master_password
  password_secret_id = module.secrets.db_password_secret_id
  min_acu            = var.aurora_min_acu
  max_acu            = var.aurora_max_acu
}

module "alb" {
  source = "./modules/alb"

  name_prefix       = local.name_prefix
  vpc_id            = module.vpc.vpc_id
  public_subnet_ids = module.vpc.public_subnet_ids
  certificate_arn   = var.certificate_arn
  container_port    = var.container_port
}

module "ecs" {
  source = "./modules/ecs"

  name_prefix              = local.name_prefix
  region                   = var.region
  vpc_id                   = module.vpc.vpc_id
  private_subnet_ids       = module.vpc.private_subnet_ids
  task_security_group_id   = aws_security_group.task.id
  ecr_repository_url       = module.ecr.repository_url
  image_tag                = var.image_tag
  container_cpu            = var.container_cpu
  container_memory         = var.container_memory
  container_port           = var.container_port
  desired_count            = var.instance_count
  log_group_name           = aws_cloudwatch_log_group.ecs.name
  task_execution_role_arn  = module.iam.task_execution_role_arn
  task_role_arn            = module.iam.task_role_arn
  alb_security_group_id    = module.alb.alb_security_group_id
  target_group_arn         = module.alb.target_group_arn
  alb_listener_https       = module.alb.https_listener_arn
  efs_id                   = module.efs.efs_id
  efs_access_point_id      = module.efs.access_point_id
  secret_arns              = module.secrets.secret_arns
  ssm_param_arns           = module.secrets.ssm_param_arns
  ssm_param_names          = module.secrets.ssm_param_names
  db_endpoint              = module.rds.cluster_endpoint
  db_name                  = module.rds.database_name
  db_user                  = var.db_master_user
  db_password_secret_arn   = module.secrets.secret_arns["DB_MASTER_PASS"]
}

# Optional Route53 alias
resource "aws_route53_record" "alias" {
  count   = var.route53_zone_id != "" && var.domain_name != "" ? 1 : 0
  zone_id = var.route53_zone_id
  name    = var.domain_name
  type    = "A"

  alias {
    name                   = module.alb.alb_dns_name
    zone_id                = module.alb.alb_zone_id
    evaluate_target_health = true
  }
}
